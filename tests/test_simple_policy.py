"""Simplified heating policy (design draft): rules and multi-day simulations.

Offline and deterministic. The simulated heater is a mixed 315 L tank with the
Thermann Manual thermostat (reheats 8 °C below its target), a 3 kW element,
0.2 °C/h standing loss, 30-minute Thermann polls in whole degrees and local
meter samples once a minute. It is a test bench for the policy's rules, not a
claim about the real tank (whose bottom sensor reads lower after draws)."""

from dataclasses import replace
from datetime import datetime, timedelta
import importlib
import math

import pytest

from test_shadow_model import c, m

sp = importlib.import_module(f"{m.__package__}.simple_policy")
SETTINGS, TARIFFS = c.parse_options({})
S = sp.PolicySettings(feed_in_rate=SETTINGS.feed_in_rate, tariff_clock=SETTINGS.tariff_clock)
OFF, BASE, STORE, HOLD = sp.OFF, sp.BASELINE, sp.STORAGE, sp.HOLD
MIN = timedelta(minutes=1)


def at(day, hour, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=m.HOBART).astimezone(m.UTC)


# 2026-11-16 Mon ... 11-13 Fri, 11-14 Sat, 11-15 Sun (AEDT); 2026-07-14 Tue (AEST).
MON, TUE, FRI, SAT, SUN = 16, 17, 13, 14, 15


def feed(policy, start, minutes, grid_kw, element=False):
    for i in range(minutes):
        policy.add_meter(start + i * MIN, grid_kw(i) if callable(grid_kw) else grid_kw, element)
    return start + (minutes - 1) * MIN


def snap(now, state, reading=60.0, **kw):
    return sp.Snapshot(now, state, reading, kw.pop("reading_at", now - 5 * MIN), **kw)


def fc(start, hours, export_kw):
    return tuple(
        m.Forecast(start + timedelta(minutes=30 * i), start + timedelta(minutes=30 * (i + 1)), kw)
        for i in range(hours * 2)
        for kw in [export_kw(i) if callable(export_kw) else export_kw]
    )


# --- settings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"baseline_c": 35},
        {"storage_c": 75},
        {"baseline_c": 65},
        {"peak_start_kw": 2.5},
        {"peak_lead": timedelta(minutes=5)},
    ],
)
def test_unsafe_or_contradictory_settings_are_rejected(change):
    with pytest.raises(ValueError):
        replace(S, **change)


def test_commands_are_the_three_states_only():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(SAT, 23)
    assert p.decide(snap(now, OFF)).command == "Manual:45"
    p60 = sp.SimplePolicy(replace(S, baseline_c=60), TARIFFS)
    assert p60.decide(snap(now, OFF)).command == "Manual:60"


# --- precedence ------------------------------------------------------------------------


def test_manufacturer_heating_beats_everything_even_at_a_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 18)
    d = p.decide(snap(now, STORE, manufacturer_heating=True, holiday=True, override_12h=True))
    assert (d.state, d.reason, d.layer, d.command) == (
        HOLD,
        "manufacturer_protective_heating",
        1,
        None,
    )


def test_owner_layer_then_cloud_gate_then_spacing():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 18)  # evening peak
    assert p.decide(snap(now, STORE, owner_override=True)).state == HOLD
    assert p.decide(snap(now, None)).reason == "heater_state_not_controlled"
    assert p.decide(snap(now, BASE, holiday=True)).command == "off"
    assert p.decide(snap(now, OFF, override_12h=True)).command == "Manual:70"
    blocked = p.decide(snap(now, STORE, cloud_ready=False))
    assert (blocked.state, blocked.layer, blocked.plan["wanted"]) == (HOLD, 3, OFF)
    spaced = p.decide(snap(now, STORE, last_command_at=now - 14 * MIN))
    assert (spaced.reason, spaced.command) == ("command_spacing", None)
    assert p.decide(snap(now, STORE, last_command_at=now - 15 * MIN)).command == "off"


def test_no_command_when_the_desired_state_is_already_active():
    p = sp.SimplePolicy(S, TARIFFS)
    for now, state in ((at(MON, 18), OFF), (at(SAT, 12), BASE), (at(MON, 23), BASE)):
        assert p.decide(snap(now, state)).command is None


# --- weekday peaks: measured solar only --------------------------------------------------


def test_peak_never_heats_from_the_grid_and_forecast_cannot_qualify():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 8, 30), 20, 0.4)
    sunny = fc(now, 4, 6.0)
    for state in (OFF, BASE, STORE):
        d = p.decide(snap(now, state, reading=40, forecast=sunny))
        assert d.state == OFF, (state, d)


def test_peak_start_needs_ten_minutes_of_3_3_kw_excluding_the_element():
    p = sp.SimplePolicy(S, TARIFFS)
    start = at(MON, 9)
    now = feed(p, start, 9, -3.5)
    assert p.decide(snap(now, OFF, reading=50)).state == OFF  # 9 minutes: not yet
    now = feed(p, now + MIN, 2, -3.5)
    d = p.decide(snap(now, OFF, reading=50))
    assert (d.state, d.reason, d.command) == (STORE, "peak_solar_qualified", "Manual:70")
    # 3.2 kW is below element + buffer.
    q = sp.SimplePolicy(S, TARIFFS)
    now = feed(q, start, 15, -3.2)
    assert q.decide(snap(now, OFF, reading=50)).state == OFF


def test_peak_start_tolerates_a_short_kettle_dip():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 9), 11, lambda i: 0.5 if i in (4, 5) else -3.6)
    assert p.decide(snap(now, OFF, reading=50)).state == STORE


def test_peak_start_is_skipped_when_the_thermostat_would_not_heat():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 9), 12, -4.0)
    assert p.decide(snap(now, OFF, reading=64)).state == OFF


def test_element_load_is_not_mistaken_for_lost_solar_and_small_imports_are_ignored():
    p = sp.SimplePolicy(S, TARIFFS)
    # Solar 3.5 kW, house 0.4 kW, element on: export 0.1 kW, then 0.15 kW import.
    now = feed(p, at(MON, 9, 30), 20, lambda i: -0.1 if i < 10 else 0.15, element=True)
    assert p.decide(snap(now, STORE, reading=55)).state == STORE


def test_sustained_import_withdraws_after_five_minutes_not_four():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(MON, 9, 30), 10, -0.3, element=True)
    now = feed(p, t0 + MIN, 4, 1.2, element=True)  # cloud: 1.2 kW import
    assert p.decide(snap(now, STORE)).state == STORE
    now = feed(p, now + MIN, 2, 1.2, element=True)
    d = p.decide(snap(now, STORE))
    assert (d.state, d.reason, d.command) == (OFF, "peak_import_sustained", "off")


def test_appliance_load_during_peak_solar_heating_withdraws():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(MON, 18), 10, -0.4, element=True)
    now = feed(p, t0 + MIN, 6, 1.6, element=True)  # oven on: 2 kW extra
    assert p.decide(snap(now, STORE)).state == OFF


def test_stale_meter_withdraws_and_never_qualifies():
    p = sp.SimplePolicy(S, TARIFFS)
    last = feed(p, at(MON, 9), 12, -4.0)
    later = last + 4 * MIN
    assert p.decide(snap(later, OFF, reading=50)).state == OFF
    d = p.decide(snap(later, STORE))
    assert (d.state, d.reason) == (OFF, "peak_meter_unavailable")


def test_after_a_restart_peak_solar_needs_a_fresh_qualification():
    p = sp.SimplePolicy(S, TARIFFS)  # new instance: no samples yet
    now = feed(p, at(MON, 9), 5, -4.0)
    assert p.decide(snap(now, OFF, reading=50)).state == OFF


@pytest.mark.parametrize(
    ("month", "day", "lead_hour", "lead_minute"),
    [(11, MON, 16, 45), (7, 14, 15, 45)],
)
def test_park_lead_before_evening_peak_in_summer_and_winter(month, day, lead_hour, lead_minute):
    p = sp.SimplePolicy(S, TARIFFS)
    before = at(day, lead_hour, lead_minute, month) - MIN
    p.add_meter(before, 2.5, True)
    assert p.decide(snap(before, STORE, reading=62)).state == STORE
    lead = before + MIN
    p.add_meter(lead, 2.5, True)
    d = p.decide(snap(lead, STORE, reading=62))
    assert (d.state, d.plan["mode"]) == (OFF, "peak")


# --- weekday daytime: storage before the evening peak -------------------------------------


def test_latest_start_finishes_before_the_peak_with_margin():
    p = sp.SimplePolicy(S, TARIFFS)
    sunny = fc(at(MON, 11), 8, 4.0)
    d = p.decide(snap(at(MON, 11, 30), OFF, reading=50, forecast=sunny))
    assert (d.state, d.reason) == (OFF, "storage_waiting")
    hours = (70 - 50) / (S.element_kw / S.kwh_per_c)
    expected = at(MON, 17) - timedelta(minutes=30) - timedelta(hours=hours)
    assert abs((d.plan["latest_start"] - expected).total_seconds()) < 1
    late = p.decide(snap(expected + MIN, OFF, reading=50, forecast=sunny))
    assert (late.state, late.reason, late.command) == (STORE, "storage_latest_start", "Manual:70")


def test_overcast_forecast_starts_storage_on_off_peak_at_once():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 11, 5)
    d = p.decide(snap(now, OFF, reading=55, forecast=fc(now, 8, 0.3)))
    assert (d.state, d.reason, d.layer) == (STORE, "storage_now_no_solar_forecast", 6)


def test_sunny_forecast_waits_and_measured_solar_starts_when_no_worse():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 11), 12, -1.2)
    forecast = fc(now, 8, lambda i: 4.0 if 2 <= i <= 6 else 1.0)
    d = p.decide(snap(now, OFF, reading=55, forecast=forecast))
    assert (d.reason, d.plan["waiting_for"]) == ("storage_waiting", "better_solar_forecast_later")
    q = sp.SimplePolicy(S, TARIFFS)
    now = feed(q, at(MON, 12), 12, -3.4)
    d = q.decide(snap(now, OFF, reading=55, forecast=forecast))
    assert (d.state, d.reason) == (STORE, "storage_now_solar")


def test_low_tank_starts_storage_immediately_and_satisfied_tank_waits():
    p = sp.SimplePolicy(S, TARIFFS)
    assert p.decide(snap(at(MON, 11, 5), OFF, reading=36)).reason == "storage_now_tank_low"
    d = p.decide(snap(at(MON, 13), OFF, reading=65))
    assert (d.state, d.reason, d.command) == (OFF, "storage_satisfied", None)


def test_stale_reading_plans_from_a_cold_assumption_and_says_so():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 11, 30)
    fresh = p.decide(snap(now, OFF, reading=60, forecast=fc(now, 8, 4.0)))
    stale = p.decide(
        snap(now, OFF, reading=60, reading_at=now - timedelta(hours=2), forecast=fc(now, 8, 4.0))
    )
    assert stale.plan["reading_fresh"] is False and stale.plan["reading_c"] == 37
    assert stale.plan["latest_start"] < fresh.plan["latest_start"]


def test_infeasible_target_heats_off_peak_reports_and_still_parks_at_the_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    d = p.decide(snap(at(MON, 15), OFF, reading=30))
    assert (d.state, d.reason) == (STORE, "storage_target_may_be_missed")
    assert d.plan["expected_reading_at_peak"] < 65
    lead = at(MON, 16, 45)
    p.add_meter(lead, 3.4, True)
    assert p.decide(snap(lead, STORE, reading=45)).state == OFF


def test_storage_started_on_a_weekday_continues_until_the_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 13), 12, 2.8, element=True)  # clouds: mostly grid
    assert p.decide(snap(now, STORE, reading=58)).state == STORE


# --- weekends ------------------------------------------------------------------------------


def test_weekend_baseline_without_solar_and_no_forced_storage():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(SAT, 14), 30, 0.3)
    d = p.decide(snap(now, BASE, reading=44, forecast=fc(now, 6, 0.2)))
    assert (d.state, d.reason) == (BASE, "baseline")


def test_weekend_one_kilowatt_qualifies_only_without_a_better_forecast():
    now = at(SAT, 11)
    p = sp.SimplePolicy(S, TARIFFS)
    feed(p, now - 11 * MIN, 12, -1.1)
    flat = fc(now, 14, 1.0)
    d = p.decide(snap(now, BASE, reading=44, forecast=flat))
    assert (d.state, d.reason, d.command) == (STORE, "solar_opportunity", "Manual:70")
    q = sp.SimplePolicy(S, TARIFFS)
    feed(q, now - 11 * MIN, 12, -1.1)
    brighter = fc(now, 14, lambda i: 3.5 if 3 <= i <= 8 else 1.0)
    d = q.decide(snap(now, BASE, reading=44, forecast=brighter))
    assert (d.state, d.plan["waiting_for"]) == (BASE, "better_solar_forecast_later")


def test_weekend_floor_is_economic_not_a_peak_style_prohibition():
    # 0.8 kW is below the floor; 1.0 kW saves about 2.6 c/kWh on 17 c off-peak.
    now = at(SUN, 12)
    p = sp.SimplePolicy(S, TARIFFS)
    feed(p, now - 11 * MIN, 12, -0.8)
    assert p.decide(snap(now, BASE, reading=44)).state == BASE
    cost = sp.SimplePolicy(S, TARIFFS).mixed_cost(1.0, 0.1702)
    assert 0.1702 - cost == pytest.approx(0.0258, abs=0.0005)
    # A dearer margin would make 1 kW not worth it.
    strict = sp.SimplePolicy(replace(S, optional_heat_margin=0.03), TARIFFS)
    feed(strict, now - 11 * MIN, 12, -1.1)
    assert strict.decide(snap(now, BASE, reading=44)).state == BASE


def test_weekend_opportunity_ends_when_solar_fades_not_on_a_short_cloud():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(SAT, 13), 10, -0.5, element=True)  # heating: available 3.5 kW
    now = feed(p, t0 + MIN, 3, 2.7, element=True)  # short cloud
    assert p.decide(snap(now, STORE, reading=55)).state == STORE
    now = feed(p, now + MIN, 6, 2.7, element=True)  # available 0.3 kW for 5+ min
    d = p.decide(snap(now, STORE, reading=55))
    assert (d.state, d.reason, d.command) == (BASE, "solar_opportunity_ended", "Manual:45")


def test_opportunity_never_starts_what_cannot_finish_before_monday_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 6, 30)
    feed(p, now - 11 * MIN, 12, -1.5)
    assert p.decide(snap(now, BASE, reading=44)).state == BASE


# --- simulations ---------------------------------------------------------------------------


class Tank:
    """Manual thermostat plus the manufacturer's antibacterial cycle, which (per
    the guide) runs regardless of the mode: heat above 62 °C, hold 32 minutes."""

    def __init__(self, reading, state, settings=S, antibacterial_at=None):
        self.t, self.state, self.element, self.s = reading, state, False, settings
        self.antibacterial_at, self.cycle, self.cycle_done_at = antibacterial_at, None, None

    def minute(self, now=None):
        if (
            self.cycle is None
            and self.antibacterial_at is not None
            and now == self.antibacterial_at
        ):
            self.cycle = ["heat", None]
        if self.cycle is not None:
            if self.cycle[0] == "heat" and self.t >= 63:
                self.cycle = ["hold", now + timedelta(minutes=32)]
            if self.cycle[0] == "hold" and now >= self.cycle[1]:
                self.cycle, self.cycle_done_at = None, now
        target = {OFF: None, BASE: self.s.baseline_c, STORE: self.s.storage_c}[self.state]
        if self.cycle is not None:
            self.element = self.cycle[0] == "heat" or self.t < 62.5
        elif target is None:
            self.element = False
        elif not self.element and self.t <= target - self.s.hysteresis_c:
            self.element = True
        elif self.element and self.t >= target:
            self.element = False
        if self.element:
            self.t += self.s.element_kw / 60 / self.s.kwh_per_c
        self.t -= 0.2 / 60


def sunny_summer(loc):
    h = loc.hour + loc.minute / 60
    return 6.0 * max(0.0, math.sin(math.pi * (h - 6) / 14))


def cloudy(loc):
    return 0.15 * sunny_summer(loc)


def sunny_winter(loc):
    h = loc.hour + loc.minute / 60
    return 3.5 * max(0.0, math.sin(math.pi * (h - 8) / 8.5))


def simulate(
    start,
    hours,
    reading,
    state,
    pv,
    forecast_pv=None,
    draws=None,
    loads=None,
    settings=S,
    antibacterial_at=None,
):
    policy = sp.SimplePolicy(settings, TARIFFS)
    tank = Tank(reading, state, settings, antibacterial_at)
    forecast_pv = forecast_pv or pv
    draws, loads = draws or {}, loads or {}
    seen, last_cmd, forecast, times = (reading, start), None, (), []
    log = {"commands": [], "peak_grid_kwh": 0.0, "grid_heat_kwh": 0.0, "at": {}, "reasons": set()}
    log.update(protective_peak_kwh=0.0, baseline_peak_minutes=0, holds=[])
    for i in range(hours * 60):
        now = start + i * MIN
        loc = now.astimezone(m.HOBART)
        key = (loc.day, loc.strftime("%H:%M"))
        tank.t -= draws.get(key, 0.0)
        tank.minute(now)
        house = 0.5 + loads.get(key[1], 0.0)
        grid = house + (settings.element_kw if tank.element else 0.0) - pv(loc)
        policy.add_meter(now, grid, tank.element)
        if i % 30 == 0:
            seen = (round(tank.t), now)
            forecast = tuple(
                m.Forecast(
                    now + timedelta(minutes=30 * k),
                    now + timedelta(minutes=30 * (k + 1)),
                    forecast_pv((now + timedelta(minutes=30 * k + 15)).astimezone(m.HOBART)) - 0.5,
                )
                for k in range(36)
            )
        d = policy.decide(sp.Snapshot(now, tank.state, seen[0], seen[1], forecast, last_cmd))
        log["reasons"].add(d.reason)
        if d.command:
            log["commands"].append((loc.strftime("%a %H:%M"), d.state, d.reason))
            tank.state, last_cmd = d.state, now
            times.append(now)
        if d.layer == 1:
            log["holds"].append(loc.strftime("%a %H:%M"))
        heat_grid = min(settings.element_kw, max(0.0, grid)) if tank.element else 0.0
        log["grid_heat_kwh"] += heat_grid / 60
        if m.tariff_at(now, TARIFFS, settings.tariff_clock).kind == "peak":
            if tank.cycle is not None:
                log["protective_peak_kwh"] += heat_grid / 60  # the manufacturer's heat
            else:
                log["peak_grid_kwh"] += heat_grid / 60
            if tank.state == BASE and d.layer != 1:
                log["baseline_peak_minutes"] += 1
        log["at"][key] = tank.t
    log["exposure"], log["cycle_done_at"] = policy.last_exposure_at, tank.cycle_done_at
    # Agreed design: Manual 45 only in off-peak baseline periods, never in a peak
    # (except while the manufacturer's own cycle is being left alone).
    assert log["baseline_peak_minutes"] == 0, log["commands"]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert all(gap >= settings.command_spacing for gap in gaps), log["commands"]
    return log, tank


def test_sim_summer_weekday_sunny_heats_on_solar_without_peak_grid():
    log, tank = simulate(at(MON, 0), 24, 60, BASE, sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:44")] >= 62
    assert len(log["commands"]) <= 4, log["commands"]
    assert [c[1] for c in log["commands"]] == [OFF, STORE, OFF, BASE], log["commands"]
    assert log["grid_heat_kwh"] < 1.0  # stored almost entirely from solar


def test_sim_summer_weekday_overcast_uses_off_peak_and_meets_target():
    log, _ = simulate(at(MON, 0), 24, 60, BASE, cloudy)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:44")] >= 62
    storage = [c for c in log["commands"] if c[1] == STORE]
    assert storage and storage[0][2] == "storage_now_no_solar_forecast"
    assert len(log["commands"]) == 4


def test_sim_forecast_error_sunny_forecast_cloudy_day_still_meets_target():
    log, _ = simulate(at(MON, 0), 24, 55, BASE, cloudy, forecast_pv=sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:44")] >= 62
    assert "storage_latest_start" in {c[2] for c in log["commands"]}


def test_sim_winter_weekday_target_before_16_00():
    start = datetime(2026, 7, 14, 0, 0, tzinfo=m.HOBART).astimezone(m.UTC)
    log, _ = simulate(start, 24, 58, BASE, sunny_winter)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(14, "15:44")] >= 62
    assert len(log["commands"]) <= 4


def test_sim_big_evening_shower_recovers_on_baseline_overnight_not_in_the_peak():
    # Monday 18:30: reading 68 -> 25 after showers.
    log, tank = simulate(at(MON, 12), 20, 66, STORE, sunny_summer, draws={(MON, "18:30"): 43.0})
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "21:59")] < 37  # no reheat in the evening peak
    assert log["at"][(TUE, "06:00")] >= 37  # native Manual 45 recovered it overnight
    overnight = [
        cmd
        for cmd in log["commands"]
        if (cmd[0].startswith("Mon") and cmd[0] >= "Mon 22:00")
        or (cmd[0].startswith("Tue") and cmd[0] < "Tue 07:00")
    ]
    assert [c[1] for c in overnight] == [BASE]  # never STORAGE overnight
    assert "solar_opportunity" not in log["reasons"]


def test_sim_manual_45_hysteresis_leaves_a_warm_tank_alone_overnight():
    log, tank = simulate(at(MON, 22), 9, 64, OFF, sunny_summer)
    assert [c[1] for c in log["commands"]] == [BASE]
    assert log["grid_heat_kwh"] == 0  # 64 -> about 62 by morning: no reheat at all


def test_sim_friday_to_monday_weekend_then_weekday():
    log, _ = simulate(at(FRI, 12), 24 * 3 + 18, 60, OFF, sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(FRI, "16:44")] >= 62 and log["at"][(MON, "16:44")] >= 62
    weekend = [c for c in log["commands"] if c[0][:3] in ("Sat", "Sun")]
    assert len(weekend) <= 4, weekend
    monday = [c for c in log["commands"] if c[0].startswith("Mon")]
    assert monday[0][1] == OFF and monday[0][0] <= "Mon 07:50"  # parked for the 08:00 peak


def test_sim_cloudy_weekend_stays_on_baseline():
    log, _ = simulate(at(SAT, 0), 48, 50, BASE, cloudy)
    assert log["commands"] == []
    assert log["at"][(SUN, "20:00")] >= 37


def test_sim_no_command_pairs_closer_than_the_spacing_and_no_flapping():
    def patchy(loc):
        base = sunny_summer(loc)
        return base * (0.3 if (loc.minute // 7) % 2 else 1.0)  # clouds every 7 minutes

    log, _ = simulate(at(SAT, 6), 14, 44, BASE, patchy)
    assert len(log["commands"]) <= 4, log["commands"]


# --- the agreed 45 °C baseline -------------------------------------------------------------


def test_agreed_baseline_is_45_and_storage_70():
    assert (S.baseline_c, S.storage_c) == (45, 70)
    assert sp.PolicySettings().baseline_c == 45


def test_tonights_state_manual_45_heating_in_the_peak_is_parked():
    # 12 Nov 21:09 (Thursday, evening peak): Manual 45, reading 35, heating
    # from the grid. The thermostat explains it (35 <= 45 - 8): not protective.
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(12, 20, 58), 12, 4.5, element=True)
    d = p.decide(snap(now, BASE, reading=35))
    assert (d.state, d.reason, d.command) == (OFF, "peak_no_grid_heating", "off")


def test_baseline_is_commanded_only_off_peak_on_aurora_93():
    """Every BASELINE command in a summer week, a cloudy working week and two
    winter weekdays falls in an off-peak baseline period: a weekday night after
    the evening peak, or a weekend."""
    winter = datetime(2026, 7, 13, tzinfo=m.HOBART).astimezone(m.UTC)
    runs = [
        simulate(at(MON, 0), 24 * 7, 60, BASE, sunny_summer)[0],
        simulate(at(MON, 0), 24 * 5, 60, BASE, cloudy)[0],
        simulate(winter, 48, 58, BASE, sunny_winter)[0],
    ]
    for log in runs:
        for label, state, reason in log["commands"]:
            if state == BASE:
                day, hhmm = label.split()
                weekend = day in ("Sat", "Sun")
                assert weekend or hhmm >= "21:00" or hhmm < "07:00", (label, reason)


# --- the manufacturer's antibacterial cycle --------------------------------------------------


def test_heating_while_off_is_protective_and_held_even_in_a_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 18), 4, 3.4, element=True)
    d = p.decide(snap(now, OFF, reading=50, holiday=True))
    assert (d.state, d.reason, d.layer, d.command) == (
        HOLD,
        "manufacturer_protective_heating",
        1,
        None,
    )


def test_heating_above_the_baseline_target_is_protective_but_thermostat_heating_is_not():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 18), 4, 3.4, element=True)
    assert p.decide(snap(now, BASE, reading=50)).layer == 1  # 50 > 45: not the thermostat
    q = sp.SimplePolicy(S, TARIFFS)
    now = feed(q, at(MON, 18), 4, 3.4, element=True)
    assert q.decide(snap(now, BASE, reading=40)).state == OFF  # 37-45 band: thermostat


def test_exposure_evidence_needs_32_minutes_at_62_from_ordinary_polls():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = at(MON, 14)
    p.observe_poll(t0, 63)
    p.observe_poll(t0 + 30 * MIN, 64)
    assert p.last_exposure_at is None  # 30 minutes is not 32
    p.observe_poll(t0 + 60 * MIN, 61)  # a draw breaks the run
    p.observe_poll(t0 + 90 * MIN, 66)
    p.observe_poll(t0 + 120 * MIN, 66)
    assert p.last_exposure_at is None
    p.observe_poll(t0 + 150 * MIN, 65)
    assert p.last_exposure_at == t0 + 150 * MIN
    assert p.hygiene(t0 + timedelta(days=6))["exposure_overdue"] is False
    assert p.hygiene(t0 + timedelta(days=8))["exposure_overdue"] is True


def test_hygiene_status_never_changes_the_decision():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(SAT, 12)
    d = p.decide(snap(now, BASE, reading=44))
    assert d.plan["hygiene"]["exposure_overdue"] is True
    assert (d.state, d.command) == (BASE, None)


def test_sim_weekday_storage_evidences_exposure_every_weekday():
    log, _ = simulate(at(MON, 0), 17, 60, BASE, cloudy)  # to the evening peak
    assert log["exposure"] is not None


def test_sim_antibacterial_cycle_on_a_45_weekend_completes_untouched():
    log, tank = simulate(at(SAT, 0), 24, 44, BASE, cloudy, antibacterial_at=at(SAT, 3))
    assert tank.cycle_done_at is not None
    assert log["commands"] == []  # no command before, during or after it
    assert log["holds"] and log["exposure"] is not None


def test_sim_antibacterial_cycle_across_the_morning_peak_is_not_interrupted():
    # Starts in Manual 45 at 07:20. The 07:45 park may still be sent before the
    # cycle is recognised (OFF keeps the cycle running, guide p10); once it is
    # recognised, nothing more is sent until it has finished.
    log, tank = simulate(at(MON, 4), 8, 44, BASE, cloudy, antibacterial_at=at(MON, 7, 20))
    assert tank.cycle_done_at is not None
    assert log["holds"]
    during = [c for c in log["commands"] if "Mon 07:50" <= c[0] <= "Mon 09:59"]
    assert during == []
    assert log["peak_grid_kwh"] == 0  # all peak heating there was the manufacturer's
