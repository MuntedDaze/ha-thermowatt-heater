"""Simplified heating policy (design draft): rules and multi-day simulations.

Offline and deterministic. The simulated heater is a mixed 315 L tank with the
Thermann Manual thermostat (reheats 8 °C below its target), a 3 kW element,
0.2 °C/h standing loss, 30-minute Thermann polls in whole degrees, local meter
samples once a minute and an EMHASS-style forecast refreshed every 30 minutes.
It is a test bench for the policy's rules, not a claim about the real tank
(whose bottom sensor reads lower after draws)."""

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
RATE = S.element_kw / S.kwh_per_c  # about 8.2 °C/h


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
    """Half-hour forecast slots from ``start``; ``export_kw(i)`` for slot i."""
    return tuple(
        m.Forecast(start + timedelta(minutes=30 * i), start + timedelta(minutes=30 * (i + 1)), kw)
        for i in range(hours * 2)
        for kw in [export_kw(i) if callable(export_kw) else export_kw]
    )


def from_hour(start, sunny_from, kw=4.0, before=0.1):
    """Forecast from ``start``: ``before`` kW until local hour ``sunny_from``, then ``kw``."""
    return fc(
        start,
        12,
        lambda i: kw
        if (start + timedelta(minutes=30 * i)).astimezone(m.HOBART).hour >= sunny_from
        else before,
    )


# --- settings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"baseline_c": 35},
        {"storage_c": 75},
        {"baseline_c": 65},
        {"peak_start_kw": 2.5},
        {"peak_lead": timedelta(0)},
        {"peak_lead": timedelta(minutes=20)},
        {"soft_target_margin": timedelta(minutes=1)},
    ],
)
def test_unsafe_or_contradictory_settings_are_rejected(change):
    with pytest.raises(ValueError):
        replace(S, **change)


def test_agreed_design_values():
    assert (S.baseline_c, S.storage_c) == (45, 70)
    assert sp.PolicySettings().baseline_c == 45
    assert S.peak_lead == 2 * MIN and S.soft_target_margin == 30 * MIN
    assert (S.qualify, S.withdraw, S.command_spacing) == (10 * MIN, 5 * MIN, 15 * MIN)


def test_commands_are_the_three_states_only():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(SAT, 23)
    assert p.decide(snap(now, OFF)).command == "Manual:45"
    p60 = sp.SimplePolicy(replace(S, baseline_c=60), TARIFFS)
    assert p60.decide(snap(now, OFF)).command == "Manual:60"


def test_no_antibacterial_or_exposure_subsystem():
    p = sp.SimplePolicy(S, TARIFFS)
    for name in ("observe_poll", "hygiene", "protective_heating_suspected", "last_exposure_at"):
        assert not hasattr(p, name)
    assert "manufacturer_heating" not in sp.Snapshot.__dataclass_fields__


# --- precedence ------------------------------------------------------------------------


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


# --- peaks: measured solar only, one rule for morning and evening ------------------------


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
    assert (d.state, d.reason, d.command) == (OFF, "peak_solar_withdrawn", "off")


def test_lost_solar_withdraws_even_while_the_thermostat_has_the_element_off():
    # Tank at 70: the element is off, so there is no import to see. The surplus
    # falls from 3.5 to 1.0 kW, which would not cover the element.
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(MON, 18), 10, -3.5)
    now = feed(p, t0 + MIN, 4, -1.0)
    assert p.decide(snap(now, STORE, reading=70)).state == STORE
    now = feed(p, now + MIN, 2, -1.0)
    d = p.decide(snap(now, STORE, reading=70))
    assert (d.state, d.reason) == (OFF, "peak_solar_withdrawn")
    q = sp.SimplePolicy(S, TARIFFS)
    now = feed(q, at(MON, 18), 20, -3.0)  # 3.0 kW still covers the element
    assert q.decide(snap(now, STORE, reading=70)).state == STORE


def test_appliance_load_during_peak_solar_heating_withdraws():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(MON, 18), 10, -0.4, element=True)
    now = feed(p, t0 + MIN, 6, 1.6, element=True)  # oven on: 2 kW extra
    assert p.decide(snap(now, STORE)).state == OFF


def test_after_withdrawal_peak_solar_must_requalify():
    p = sp.SimplePolicy(S, TARIFFS)
    withdrawn = at(MON, 18)
    now = feed(p, withdrawn + MIN, 16, lambda i: 1.0 if i < 8 else -3.6)  # 8 min back
    assert p.decide(snap(now, OFF, reading=55, last_command_at=withdrawn)).state == OFF
    now = feed(p, now + MIN, 3, -3.6)  # 11 minutes qualified
    d = p.decide(snap(now, OFF, reading=55, last_command_at=withdrawn))
    assert (d.state, d.command) == (STORE, "Manual:70")


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
    ("month", "day", "hour", "state"),
    [
        (11, MON, 17, STORE),  # summer evening peak 17:00
        (7, 14, 16, STORE),  # winter evening peak 16:00
        (11, MON, 8, BASE),  # summer morning peak 08:00
        (7, 14, 7, BASE),  # winter morning peak 07:00
    ],
)
def test_park_is_sent_two_minutes_before_every_peak(month, day, hour, state):
    p = sp.SimplePolicy(S, TARIFFS)
    before = at(day, hour, 0, month) - 3 * MIN
    p.add_meter(before, 2.5, True)
    assert p.decide(snap(before, state, reading=62)).state == state
    lead = before + MIN
    p.add_meter(lead, 2.5, True)
    d = p.decide(snap(lead, state, reading=62))
    assert (d.state, d.command, d.plan["mode"]) == (OFF, "off", "peak")


def test_the_park_command_slot_is_reserved():
    # A draw at 16:40 leaves the tank needing heat: start storage, which still
    # allows the 16:58 park 18 minutes later. From 16:43 nothing but OFF may
    # be sent, so the park can never be blocked by the spacing rule.
    p = sp.SimplePolicy(S, TARIFFS)
    d = p.decide(snap(at(MON, 16, 40), OFF, reading=55))
    assert (d.state, d.command) == (STORE, "Manual:70")
    d = p.decide(snap(at(MON, 16, 43), OFF, reading=55))
    assert (d.state, d.reason, d.command, d.plan["wanted"]) == (
        OFF,
        "peak_command_reserved",
        None,
        STORE,
    )
    park = p.decide(snap(at(MON, 16, 58), STORE, reading=58, last_command_at=at(MON, 16, 40)))
    assert park.command == "off"


# --- weekday off-peak: 70 °C by the soft target, cheapest window ---------------------------


def test_waits_for_better_solar_later_when_that_is_feasible():
    # Needs about 3 hours (45 -> 70). Overcast now; EMHASS forecasts excellent
    # solar from 13:00. The soft target is 16:30, so waiting is feasible.
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 11, 0), 12, 0.3)
    d = p.decide(snap(now, OFF, reading=45, forecast=from_hour(now, 13)))
    assert (d.state, d.reason, d.command) == (OFF, "storage_waiting_for_cheaper_window", None)
    assert at(MON, 12, 55) <= d.plan["best_start"] <= at(MON, 13, 15)
    assert d.plan["cost_best"] < d.plan["cost_now"]


def test_starts_on_off_peak_when_waiting_would_miss_the_soft_target():
    p = sp.SimplePolicy(S, TARIFFS)
    forecast = from_hour(at(MON, 11), 15)  # sun only from 15:00: too late for 3 h
    d = p.decide(snap(at(MON, 11, 30), OFF, reading=50, forecast=forecast))
    assert d.reason == "storage_waiting_for_cheaper_window"
    hours = (70 - 50) / RATE
    expected = at(MON, 16, 30) - timedelta(hours=hours)
    assert abs((d.plan["latest_start"] - expected).total_seconds()) < 1
    late = p.decide(snap(expected + MIN, OFF, reading=50, forecast=forecast))
    assert (late.state, late.reason, late.command) == (STORE, "storage_latest_start", "Manual:70")


def test_overcast_forecast_starts_storage_at_once_and_a_missing_one_waits():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 11, 5)
    d = p.decide(snap(now, OFF, reading=55, forecast=fc(now, 8, 0.3)))
    assert (d.state, d.reason, d.layer) == (STORE, "storage_cheapest_now", 6)
    # 0.9.1 (audit M4): with no published forecast at all, grid-only heating
    # waits for the latest start; it is no longer started at once.
    d = p.decide(snap(now, OFF, reading=55))
    assert (d.state, d.reason, d.command) == (OFF, "storage_waiting_no_forecast", None)


def test_measured_solar_now_as_good_as_the_forecast_later_starts_now():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 12), 12, -3.4)
    d = p.decide(snap(now, OFF, reading=55, forecast=fc(now, 8, 3.5)))
    assert (d.state, d.reason) == (STORE, "storage_cheapest_now")


def test_satisfied_tank_waits_and_stale_reading_plans_from_a_cold_assumption():
    p = sp.SimplePolicy(S, TARIFFS)
    d = p.decide(snap(at(MON, 13), OFF, reading=70))
    assert (d.state, d.reason, d.command) == (OFF, "storage_target_reached", None)
    now = at(MON, 11, 30)
    sunny_later = from_hour(now, 14)
    fresh = p.decide(snap(now, OFF, reading=60, forecast=sunny_later))
    stale = p.decide(
        snap(now, OFF, reading=60, reading_at=now - timedelta(hours=2), forecast=sunny_later)
    )
    assert stale.plan["reading_fresh"] is False and stale.plan["reading_c"] == 37
    assert stale.plan["latest_start"] < fresh.plan["latest_start"]


def test_target_out_of_reach_heats_off_peak_until_the_peak_boundary():
    p = sp.SimplePolicy(S, TARIFFS)
    d = p.decide(snap(at(MON, 15), OFF, reading=30))
    assert (d.state, d.reason) == (STORE, "storage_target_may_be_missed")
    # The soft target is a planning buffer, not a shutdown.
    d = p.decide(snap(at(MON, 16, 45), STORE, reading=48, last_command_at=at(MON, 15)))
    assert (d.state, d.command) == (STORE, None)
    park = p.decide(snap(at(MON, 16, 58), STORE, reading=50, last_command_at=at(MON, 15)))
    assert (park.state, park.command) == (OFF, "off")


def test_committed_heating_continues_through_clouds_and_imports():
    # Started on solar; a cloud now gives 2.8 kW grid import. The forecast is
    # sunny again later, but a cloud alone can never justify a pause: the
    # measured span is 30 minutes, worth at most about $0.12 of heat.
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 12), 12, 2.8, element=True)
    for forecast in ((), fc(now, 8, 0.2), fc(now, 8, 4.0)):
        d = p.decide(snap(now, STORE, reading=50, forecast=forecast))
        assert (d.state, d.reason, d.command) == (STORE, "storage_until_peak", None)


def test_committed_heating_pauses_only_for_a_clearly_cheaper_window_with_time_to_finish():
    # Started at 11:00 on an overcast forecast; the 11:30 EMHASS update now
    # shows strong solar from 13:00. Heating 2.4 h then would save about $0.57.
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 11, 30), 12, 2.9, element=True)
    better = from_hour(now, 13)
    d = p.decide(snap(now, STORE, reading=50, forecast=better, last_command_at=at(MON, 11)))
    assert (d.state, d.reason, d.command) == (OFF, "storage_paused_for_cheaper_window", "off")
    assert d.plan["pause_saving"] >= S.pause_min_saving
    # Only a little solar later: not worth another command.
    q = sp.SimplePolicy(S, TARIFFS)
    now = feed(q, at(MON, 11, 30), 12, 2.9, element=True)
    d = q.decide(snap(now, STORE, reading=50, forecast=from_hour(now, 13, kw=0.8)))
    assert (d.state, d.reason) == (STORE, "storage_until_peak")
    # Running late: the same solar is not reachable in time, so keep heating.
    r = sp.SimplePolicy(S, TARIFFS)
    now = feed(r, at(MON, 12, 30), 12, 2.9, element=True)
    d = r.decide(snap(now, STORE, reading=40, forecast=from_hour(now, 13)))
    assert (d.state, d.reason) == (STORE, "storage_until_peak")


# --- weekends ------------------------------------------------------------------------------


def test_weekend_baseline_without_solar_and_no_forced_storage():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(SAT, 14), 30, 0.3)
    d = p.decide(snap(now, BASE, reading=44, forecast=fc(now, 6, 0.2)))
    assert (d.state, d.reason) == (BASE, "baseline")
    assert p.decide(snap(at(SUN, 15, 30), BASE, reading=40)).state == BASE  # no deadline


def test_weekend_one_kilowatt_qualifies_only_without_a_better_forecast():
    now = at(SAT, 11)
    p = sp.SimplePolicy(S, TARIFFS)
    feed(p, now - 11 * MIN, 12, -1.1)
    flat = fc(now, 14, 1.0)
    d = p.decide(snap(now, BASE, reading=44, forecast=flat))
    assert (d.state, d.reason, d.command) == (STORE, "solar_opportunity", "Manual:70")
    q = sp.SimplePolicy(S, TARIFFS)
    feed(q, now - 11 * MIN, 12, -1.1)
    brighter = fc(now, 14, lambda i: 3.5 if 3 <= i <= 10 else 1.0)
    d = q.decide(snap(now, BASE, reading=44, forecast=brighter))
    assert (d.state, d.plan["waiting_for"]) == (BASE, "cheaper_window_later")


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
    d = strict.decide(snap(now, BASE, reading=44, forecast=fc(now, 14, 1.1)))
    assert (d.state, d.plan["waiting_for"]) == (BASE, "more_solar")


def test_weekend_session_survives_a_cloud_and_ends_when_solar_has_gone():
    p = sp.SimplePolicy(S, TARIFFS)
    t0 = feed(p, at(SAT, 13), 10, -0.5, element=True)  # heating: available 3.5 kW
    now = feed(p, t0 + MIN, 8, 2.7, element=True)  # cloud: available 0.3 kW for 8 min
    sun_returns = fc(now, 4, 2.5)
    d = p.decide(snap(now, STORE, reading=55, forecast=sun_returns))
    assert (d.state, d.reason) == (STORE, "solar_opportunity_continues")
    d = p.decide(snap(now, STORE, reading=55, forecast=fc(now, 4, 0.3)))
    assert (d.state, d.reason, d.command) == (BASE, "solar_opportunity_ended", "Manual:45")


def test_opportunity_never_starts_what_cannot_finish_before_monday_peak():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 6, 30)
    feed(p, now - 11 * MIN, 12, -1.5)
    assert p.decide(snap(now, BASE, reading=44)).state == BASE


def test_tonights_state_manual_45_heating_in_the_peak_is_parked():
    # 12 Nov 21:09 (Thursday, evening peak): Manual 45, reading 35, heating
    # from the grid.
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(12, 20, 58), 12, 4.5, element=True)
    d = p.decide(snap(now, BASE, reading=35))
    assert (d.state, d.reason, d.command) == (OFF, "peak_no_grid_heating", "off")


# --- simulations ---------------------------------------------------------------------------


class Tank:
    """The Thermann Manual thermostat: on at target - 8 °C, off at the target."""

    def __init__(self, reading, state, settings=S):
        self.t, self.state, self.element, self.s = reading, state, False, settings

    def minute(self):
        target = {OFF: None, BASE: self.s.baseline_c, STORE: self.s.storage_c}[self.state]
        if target is None:
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


def sunny_after(hour):
    def pv(loc):
        return sunny_summer(loc) if loc.hour >= hour else cloudy(loc)

    return pv


def simulate(
    start, hours, reading, state, pv, forecast_pv=None, draws=None, loads=None, settings=S
):
    policy, tank = sp.SimplePolicy(settings, TARIFFS), Tank(reading, state, settings)
    forecast_pv = forecast_pv or pv
    draws, loads = draws or {}, loads or {}
    seen, last_cmd, forecast, times, reasons = (reading, start), None, (), [], []
    log = {"commands": [], "peak_grid_kwh": 0.0, "grid_heat_kwh": 0.0, "at": {}, "reasons": set()}
    log["baseline_peak_minutes"] = 0
    for i in range(hours * 60):
        now = start + i * MIN
        loc = now.astimezone(m.HOBART)
        key = (loc.day, loc.strftime("%H:%M"))
        tank.t -= draws.get(key, 0.0)
        tank.minute()
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
            reasons.append(d.reason)
        heat_grid = min(settings.element_kw, max(0.0, grid)) if tank.element else 0.0
        log["grid_heat_kwh"] += heat_grid / 60
        if m.tariff_at(now, TARIFFS, settings.tariff_clock).kind == "peak":
            log["peak_grid_kwh"] += heat_grid / 60
            if tank.state == BASE:
                log["baseline_peak_minutes"] += 1
        log["at"][key] = tank.t
    # Agreed design: Manual 45 only in off-peak baseline periods, never in a peak.
    assert log["baseline_peak_minutes"] == 0, log["commands"]
    # Every command respects the spacing, except a peak withdrawal (0.9.1, H1).
    for earlier, later, reason in zip(times, times[1:], reasons[1:], strict=False):
        if reason not in sp.SPACING_EXEMPT_REASONS:
            assert later - earlier >= settings.command_spacing, log["commands"]
    return log, tank


def test_sim_summer_weekday_sunny_heats_on_solar_without_peak_grid():
    log, _ = simulate(at(MON, 0), 24, 60, BASE, sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:30")] >= 62  # in the Manual 70 band
    assert [c[1] for c in log["commands"]][:3] == [OFF, STORE, OFF], log["commands"]
    assert log["commands"][0][0] == "Mon 07:58"  # the morning park, two minutes ahead
    assert len(log["commands"]) <= 5, log["commands"]
    assert log["grid_heat_kwh"] < 1.0  # stored almost entirely from solar


def test_sim_summer_weekday_overcast_uses_off_peak_and_meets_target():
    log, _ = simulate(at(MON, 0), 24, 60, BASE, cloudy)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:30")] >= 62  # in the Manual 70 band
    storage = [c for c in log["commands"] if c[1] == STORE]
    assert storage == [("Mon 11:00", STORE, "storage_cheapest_now")]
    assert len(log["commands"]) == 4


def test_sim_emhass_waits_for_afternoon_sun_instead_of_heating_at_11():
    # 45 °C at the end of the morning peak needs about 3 hours. Cloud until
    # 13:00, then sun, and EMHASS forecasts it: heat on the sun, not the grid.
    log, _ = simulate(at(MON, 0), 24, 46, BASE, sunny_after(13))
    storage = [c for c in log["commands"] if c[1] == STORE]
    assert len(storage) == 1 and "Mon 12:45" <= storage[0][0] <= "Mon 13:30", log["commands"]
    assert log["at"][(MON, "16:30")] >= 62  # in the Manual 70 band
    assert log["peak_grid_kwh"] == 0
    early, _ = simulate(at(MON, 0), 24, 46, BASE, sunny_after(13), forecast_pv=cloudy)
    assert log["grid_heat_kwh"] < early["grid_heat_kwh"] - 3  # several kWh off the grid


def test_sim_forecast_error_sunny_forecast_cloudy_day_still_meets_target():
    # It waits for the promised sun, then heats from the grid in time anyway.
    log, _ = simulate(at(MON, 0), 24, 55, BASE, cloudy, forecast_pv=sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(MON, "16:30")] >= 62  # in the Manual 70 band
    storage = [c for c in log["commands"] if c[1] == STORE]
    assert len(storage) == 1 and storage[0][0] >= "Mon 13:00", log["commands"]
    park = [c for c in log["commands"] if c[0] == "Mon 16:58"]
    assert park == [("Mon 16:58", OFF, "peak_ahead_no_qualified_solar")]


def test_sim_committed_heating_rides_through_an_hour_of_cloud():
    def cloud_at_noon(loc):
        return cloudy(loc) if 12 <= loc.hour < 13 else sunny_summer(loc)

    log, _ = simulate(at(MON, 0), 24, 40, BASE, cloud_at_noon)
    storage = [c for c in log["commands"] if c[1] == STORE]
    assert len(storage) == 1, log["commands"]
    assert log["at"][(MON, "16:30")] >= 62  # in the Manual 70 band
    assert "storage_paused_for_cheaper_window" not in log["reasons"]


def test_sim_winter_weekday_target_before_16_00():
    start = datetime(2026, 7, 14, 0, 0, tzinfo=m.HOBART).astimezone(m.UTC)
    log, _ = simulate(start, 24, 58, BASE, sunny_winter)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(14, "15:30")] >= 62  # in the Manual 70 band
    assert len(log["commands"]) <= 5


def test_sim_big_evening_shower_recovers_on_baseline_overnight_not_in_the_peak():
    # Monday 18:30: reading 68 -> 25 after showers.
    log, _ = simulate(at(MON, 12), 20, 66, STORE, sunny_summer, draws={(MON, "18:30"): 43.0})
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
    log, _ = simulate(at(MON, 22), 9, 64, OFF, sunny_summer)
    assert [c[1] for c in log["commands"]] == [BASE]
    assert log["grid_heat_kwh"] == 0  # 64 -> about 62 by morning: no reheat at all


def test_sim_friday_to_monday_weekend_then_weekday():
    log, _ = simulate(at(FRI, 12), 24 * 3 + 18, 60, OFF, sunny_summer)
    assert log["peak_grid_kwh"] == 0
    assert log["at"][(FRI, "16:30")] >= 62 and log["at"][(MON, "16:30")] >= 62
    weekend = [c for c in log["commands"] if c[0][:3] in ("Sat", "Sun")]
    assert len(weekend) <= 4, weekend
    monday = [c for c in log["commands"] if c[0].startswith("Mon")]
    assert monday[0][1] == OFF and monday[0][0] == "Mon 07:58"  # parked for the 08:00 peak


def test_sim_cloudy_weekend_stays_on_baseline():
    log, _ = simulate(at(SAT, 0), 48, 50, BASE, cloudy)
    assert log["commands"] == []
    assert log["at"][(SUN, "20:00")] >= 37


def test_sim_weekend_solar_session_is_not_interrupted_by_a_passing_cloud():
    def cloud_at_noon(loc):
        return cloudy(loc) if loc.hour == 12 and loc.minute < 15 else sunny_summer(loc)

    log, _ = simulate(at(SAT, 6), 14, 44, BASE, cloud_at_noon, forecast_pv=sunny_summer)
    assert [c[1] for c in log["commands"]] == [STORE, BASE], log["commands"]
    assert log["at"][(SAT, "16:00")] >= 62  # in the Manual 70 band


def test_sim_no_command_pairs_closer_than_the_spacing_and_no_flapping():
    def patchy(loc):
        base = sunny_summer(loc)
        return base * (0.3 if (loc.minute // 7) % 2 else 1.0)  # clouds every 7 minutes

    log, _ = simulate(at(SAT, 6), 14, 44, BASE, patchy)
    assert len(log["commands"]) <= 4, log["commands"]
    log, _ = simulate(at(MON, 6), 14, 44, BASE, patchy)
    assert len(log["commands"]) <= 5, log["commands"]


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


# --- requested setpoint versus achieved temperature ----------------------------------------


@pytest.mark.parametrize(
    ("reading", "reason", "reached"),
    [
        (70, "storage_target_reached", True),
        (71, "storage_target_reached", True),
        (69, "storage_within_thermostat_band", False),
        (65, "storage_within_thermostat_band", False),
        (63, "storage_within_thermostat_band", False),
    ],
)
def test_65_is_inside_the_band_not_reported_as_70(reading, reason, reached):
    # No heat would flow at 63-69 °C in Manual 70 (it reheats at 62), so the
    # decision is the same: no command, no forced cycling. Only the report differs.
    p = sp.SimplePolicy(S, TARIFFS)
    for state in (OFF, STORE):
        d = p.decide(snap(at(MON, 13), state, reading=reading))
        assert (d.state, d.reason, d.command) == (state, reason, None)
        assert d.plan["target_reached"] is reached
        assert d.plan["storage_target_c"] == 70
        assert d.plan["setpoint_c"] == (70 if state == STORE else None)


def test_setpoint_is_what_was_requested_and_reached_needs_a_fresh_reading():
    p = sp.SimplePolicy(S, TARIFFS)
    assert (p.setpoint(OFF), p.setpoint(BASE), p.setpoint(STORE), p.setpoint(None)) == (
        None,
        45,
        70,
        None,
    )
    now = at(MON, 13)
    stale = p.decide(snap(now, STORE, reading=70, reading_at=now - timedelta(hours=2)))
    assert stale.plan["target_reached"] is False  # an old 70 proves nothing now
    assert stale.state == STORE and stale.command is None


def test_band_reading_keeps_the_deadline_and_economics_unchanged():
    # At 62 the thermostat would heat in Manual 70, so the plan still runs.
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 11, 5)
    d = p.decide(snap(now, OFF, reading=62, forecast=fc(now, 8, 0.3)))
    assert d.plan["target_reached"] is False and d.plan["thermostat_would_heat_at_storage"]
    assert (d.state, d.reason) == (STORE, "storage_cheapest_now")
    assert d.plan["heating_hours"] == pytest.approx(8 / RATE, abs=0.01)


def test_sim_reports_reached_only_at_the_setpoint():
    p = sp.SimplePolicy(S, TARIFFS)
    tank = Tank(55, STORE)
    reports = []
    now = at(MON, 12)
    for i in range(150):
        tank.minute()
        p.add_meter(now + i * MIN, 3.5 if tank.element else 0.5, tank.element)
        d = p.decide(
            snap(now + i * MIN, tank.state, reading=round(tank.t), reading_at=now + i * MIN)
        )
        reports.append((round(tank.t), d.plan["target_reached"]))
    assert all(reached == (t >= 70) for t, reached in reports)
    assert any(reached for _, reached in reports)
