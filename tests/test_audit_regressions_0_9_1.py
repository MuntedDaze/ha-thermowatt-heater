"""0.9.1 regression tests for the independent audit of 13 Nov 2026 (main 04a8d3d).

Each end-to-end test replays a scenario that failed in the audit through the
same rig as ``test_integration_0_9_0`` (real controller, real bridge 1.3.13
with production defaults, mocked cloud). Finding numbers are the audit's:

  C1  optional solar cycling used up the daily command limit;
  H1  a peak withdrawal waited for the command spacing;
  M1  ending the 12hr Override in a peak waited for the next poll;
  M2  an appliance's load step was counted as the element;
  M4  without the published forecast, grid heating replaced the optimisation;
  M5  the 10-minute and 5-minute sample windows were shorter than stated;
  M7  the shadow log dropped the next day's identical command.

Everything is offline; no live service, heater or credential."""

from dataclasses import replace
from datetime import datetime, timedelta
import importlib

import pytest

from test_integration_0_9_0 import MON, TUE, Rig, c, drive, hobart, local, m
from test_simple_policy import BASE, MIN, OFF, S, STORE, TARIFFS, at, fc, snap, sp

ctl = importlib.import_module(f"{m.__package__}.controller")
settings_module = importlib.import_module(f"{m.__package__}.settings")


class Sim(Rig):
    """The integration rig with a scripted household load, the peak import
    used by the element, and a per-minute trace."""

    base = staticmethod(lambda loc: 0.5)

    def __init__(self, *args, options=None, **kwargs):
        self.peak_import_kwh = 0.0
        self.log = []
        super().__init__(*args, **kwargs)
        if options:
            self.entry.options.update(options)
            self.executor.configure(self.entry.options)
            self.runtime.apply_options(self.entry.options, self.sources)

    def _meter(self):
        loc = self.now().astimezone(m.HOBART)
        pv = self.pv(loc)
        house = self.base(loc) + (3.0 if self.tank.element else 0.0)
        export = pv - house
        if (
            self.tank.element
            and export < 0
            and m.tariff_at(self.now(), TARIFFS, "standard").kind == "peak"
        ):
            self.peak_import_kwh += min(3.0, -export) / 60
        for key, value in (("grid", export), ("house", house), ("pv", pv)):
            self.report(c.DEFAULT_SOURCES[key], value * 1000, {"unit_of_measurement": "W"})
        self.report(c.DEFAULT_PV_AC, pv * 1000, {"unit_of_measurement": "W"})

    def posts_local(self):
        return [(local(t), e, (j or {}).get("T_SetPoint")) for t, e, j, _ in self.posts]


def trace(rig):
    controller, decision = rig.executor.controller, rig.executor.last_decision
    rig.log.append(
        {
            "at": local(rig.now()),
            "state": controller.state,
            "reason": controller.reason,
            "decision": decision.reason if decision else None,
            "mode": rig.tank.mode,
            "setpoint": rig.tank.setpoint,
            "reading": rig.tank.t,
        }
    )


def bursts(on=9, off=16, high=4.5, low=0.5):
    """Sun in bursts: ``on`` minutes at ``high`` kW, then ``off`` minutes of cloud."""

    def pv(loc):
        if not 6 <= loc.hour < 20:
            return 0.0
        return high if (loc.hour * 60 + loc.minute) % (on + off) < on else low

    return pv


def minute_of(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


# --- C1 and H1: the partly cloudy weekday ----------------------------------------------


@pytest.fixture(scope="module")
def cloudy_weekday(tmp_path_factory):
    """Monday 07:30 to Tuesday 08:10, sun in 12-minute bursts, production limits."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        rig = Sim(
            tmp_path_factory.mktemp("cloudy_weekday"),
            monkeypatch,
            hobart(MON, 7, 30),
            reading=46.0,
            mode="Manual",
            setpoint=45,
            pv=bursts(on=12, off=13),
        )
        assert rig.executor.cfg.max_commands_per_day == 6  # the production default
        rig.enable()
        rig.run(hobart(TUE, 8, 10), trace)
        yield rig


def test_c1_optional_solar_cycling_never_blocks_the_weekday_heat(cloudy_weekday):
    rig = cloudy_weekday
    posts = rig.posts_local()
    # Before 0.9.1: seven commands by 10:23, then nothing for the rest of the day.
    daytime = [p for p in posts if p[1] == "manual" and p[2] == 70 and "11:00" <= p[0] < "16:43"]
    assert daytime, posts  # the essential weekday start was sent
    at_peak = next(row for row in rig.log if row["at"] == "16:55")
    assert at_peak["reading"] >= 62, at_peak  # heated into the Manual 70 band (was 50 °C)
    assert not any("essential_command_limit" in str(row["reason"]) for row in rig.log)


def test_c1_the_overnight_baseline_is_sent_and_held(cloudy_weekday):
    rig = cloudy_weekday
    evening = [p for p in rig.posts_local() if p[1] == "manual" and p[2] == 45]
    assert evening and "22:00" <= evening[0][0] <= "22:02", rig.posts_local()
    night = next(row for row in rig.log if row["at"] == "03:00")
    assert (night["mode"], night["setpoint"], night["state"]) == ("Manual", 45, "baseline_45")
    assert rig.posts_local()[-1][:2] == ("07:58", "off")  # and Tuesday's park is on time


def test_c1_optional_starts_stop_at_the_configured_limit(cloudy_weekday):
    rig = cloudy_weekday
    morning_peak = [p for p in rig.posts_local() if "08:00" <= p[0] < "11:00" and p[1] == "manual"]
    assert 1 <= len(morning_peak) <= 3, rig.posts_local()
    assert any(row["reason"] == "daily_command_limit_reached" for row in rig.log)


def test_h1_a_peak_withdrawal_is_not_held_by_the_spacing(cloudy_weekday):
    rig = cloudy_weekday
    posts = rig.posts_local()
    pairs = [
        (a, b)
        for a, b in zip(posts, posts[1:], strict=False)
        if a[1] == "manual" and a[2] == 70 and "08:00" <= a[0] < "11:00" and b[1] == "off"
    ]
    assert pairs, posts
    for start, stop in pairs:
        # Before 0.9.1 every one of these was exactly 15 minutes.
        assert minute_of(stop[0]) - minute_of(start[0]) <= 8, posts
    # About 0.75 kWh per cycle (2.25 kWh in the morning) before 0.9.1.
    assert rig.peak_import_kwh <= 0.8, rig.peak_import_kwh


def test_h1_every_other_command_still_respects_the_spacing(cloudy_weekday):
    rig = cloudy_weekday
    history = rig.executor.controller.history
    for earlier, later in zip(history, history[1:], strict=False):
        gap = datetime.fromisoformat(later["created_at"]) - datetime.fromisoformat(
            earlier["created_at"]
        )
        if later["reason"] not in sp.SPACING_EXEMPT_REASONS:
            assert gap >= timedelta(minutes=15), (earlier["payload"], later["payload"], gap)


# --- H1: the exemption is narrow (policy and controller) -------------------------------


def feed(policy, start, minutes, grid_kw, element=False):
    for i in range(minutes + 1):
        policy.add_meter(start + i * MIN, grid_kw, element)
    return start + minutes * MIN


def test_h1_protective_peak_off_is_exempt_in_the_policy():
    assert sp.SPACING_EXEMPT_REASONS == ctl.SPACING_EXEMPT_REASONS == {
        "peak_solar_withdrawn",
        "peak_meter_unavailable",
    }
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(MON, 9, 0), 6, 2.5, element=True)  # importing 2.5 kW in the peak
    d = p.decide(snap(now, STORE, last_command_at=now - 2 * MIN))
    assert (d.reason, d.command) == ("peak_solar_withdrawn", "off")
    # The restart must requalify AND wait for the spacing.
    later = feed(p, now + MIN, 10, -4.0)
    blocked = p.decide(snap(later, OFF, reading=45, last_command_at=later - 11 * MIN))
    assert (blocked.reason, blocked.command) == ("command_spacing", None)
    assert blocked.plan["wanted"] == STORE
    # Ordinary OFF commands still wait: the pre-peak park and an economic pause.
    q = sp.SimplePolicy(S, TARIFFS)
    lead = at(MON, 16, 58)
    q.add_meter(lead, 2.5, True)  # fresh meter: ordinary pre-peak park, not meter loss
    d = q.decide(snap(lead, STORE, last_command_at=lead - 5 * MIN))
    assert (d.reason, d.command) == ("command_spacing", None)
    peak = at(MON, 18, 0)
    d = q.decide(snap(peak, STORE, last_command_at=peak - 5 * MIN))  # no meter samples
    assert (d.state, d.reason, d.command) == (OFF, "peak_meter_unavailable", "off")


def controller_ready(now, mode="Off", target=70.0):
    controller = ctl.Controller()
    controller.set_enabled(True, now - timedelta(minutes=5))
    controller.request_samples = [[(now - timedelta(hours=1)).isoformat(), 90]]
    controller.step(observation(now, mode, target), ctl.Want("hold", "policy"), config())
    return controller


def config(**changes):
    values = {"command_topic": "P/TEST123/CMD/MODE", "three_state_qualified": True}
    values.update(changes)
    return ctl.ControllerConfig(**values)


def observation(now, mode="Off", target=70.0, **changes):
    values = dict(
        now=now,
        poll_at=now - timedelta(seconds=60),
        mode=mode,
        target_c=target,
        temperature_c=50.0,
        cloud_health="ok",
        auth_mode="authorized",
        consecutive_failures=0,
        cooldown_seconds=0,
        bridge_available=True,
        bridge_commands_enabled=True,
        bridge_refresh_limit=24,
        bridge_refreshes_24h=0,
        bridge_confirmation_pending=False,
        bridge_command_policy="automation",
        bridge_transitions=sorted(
            ["Manual:45@70", "Manual:45@off", "Manual:70@45", "Manual:70@off", "off@45", "off@70"]
        ),
        requests_total=100,
        mqtt_ready=True,
    )
    values.update(changes)
    return ctl.Observation(**values)


def published(effects):
    return [effect.payload for effect in effects if effect.kind == "publish"]


def test_h1_the_controller_gate_exempts_protective_peak_off_reasons():
    now = at(MON, 9, 0)
    for reason, expected in (
        ("peak_solar_withdrawn", ["off@70"]),
        ("peak_meter_unavailable", ["off@70"]),
        ("peak_ahead_no_qualified_solar", []),
        ("storage_paused_for_cheaper_window", []),
        ("holiday", []),
    ):
        controller = controller_ready(now, "Manual", 70.0)
        controller.commands = [(now - timedelta(minutes=3)).isoformat()]
        effects = controller.step(
            observation(now, "Manual", 70.0), ctl.Want(sp.OFF, reason), config()
        )
        assert published(effects) == expected, reason
        if not expected:
            assert controller.gate_failures == ["command_spacing"], reason
    # A non-OFF command is never exempt, whatever its reason.
    controller = controller_ready(now)
    controller.commands = [(now - timedelta(minutes=3)).isoformat()]
    effects = controller.step(observation(now), ctl.Want(STORE, "peak_solar_withdrawn"), config())
    assert published(effects) == [] and "command_spacing" in controller.gate_failures


# --- C1: the limits themselves -----------------------------------------------------------


def test_c1_optional_and_essential_limits_and_the_runaway_cap():
    now = at(MON, 12, 0)
    limit = 6

    def attempt(sent, reason, target=STORE, mode="Off", setpoint=70.0):
        controller = controller_ready(now, mode, setpoint)
        controller.commands = [
            (now - timedelta(minutes=30 + i)).isoformat() for i in reversed(range(sent))
        ]
        effects = controller.step(
            observation(now, mode, setpoint),
            ctl.Want(target, reason),
            config(max_commands_per_day=limit),
        )
        return published(effects), controller.gate_failures

    for reason in sorted(ctl.OPTIONAL_REASONS):
        assert attempt(limit - 1, reason)[0] == ["Manual:70@off"]
        assert attempt(limit, reason) == ([], ["daily_command_limit_reached"])
    # Essential commands are not held back by optional activity ...
    for reason, target in (
        ("storage_latest_start", STORE),
        ("storage_cheapest_now", STORE),
        ("12hr_override", STORE),
        ("baseline", BASE),
        ("solar_opportunity_ended", BASE),
    ):
        sent, failures = attempt(limit + 5, reason, target)
        assert len(sent) == 1 and failures == [], reason
        # ... but a runaway loop is still stopped.
        cap = limit + ctl.ESSENTIAL_EXTRA_COMMANDS
        assert attempt(cap, reason, target) == ([], ["daily_essential_command_limit_reached"])
    # OFF is never held back.
    assert attempt(40, "peak_no_grid_heating", OFF, "Manual", 70.0)[0] == ["off@70"]


def test_c1_the_policy_reasons_the_controller_classifies_still_exist():
    source = (sp.__file__ and open(sp.__file__, encoding="utf-8").read()) or ""
    for reason in ctl.OPTIONAL_REASONS | ctl.SPACING_EXEMPT_REASONS:
        assert f'"{reason}"' in source, reason


# --- M1: the 12hr Override ends in a peak -------------------------------------------------


def test_m1_cancelling_the_override_in_a_peak_parks_without_waiting_for_a_poll(
    tmp_path, monkeypatch
):
    rig = Sim(
        tmp_path, monkeypatch, hobart(MON, 17, 31), reading=46.0, mode="Off", pv=lambda loc: 0.0
    )
    rig.enable()
    rig.run(hobart(MON, 17, 40))
    assert rig.executor.controller.start_guest(rig.now())
    rig.run(hobart(MON, 18, 12))
    assert rig.tank.mode == "Manual" and rig.executor.controller.state == "storage_70"
    drive(rig.executor.async_owner_action("guest_cancel"))
    assert rig.executor.controller.state == "storage_70"  # no re-inspection needed
    rig.run(hobart(MON, 18, 40))
    stop = rig.posts_local()[-1]
    # Before 0.9.1 the park waited for the 18:30 poll (26 minutes on peak grid).
    assert stop[1] == "off" and "18:12" <= stop[0] <= "18:14", rig.posts_local()


def test_m1_expiry_takes_the_same_path_and_other_states_still_reinspect():
    now = at(MON, 18, 0)
    controller = controller_ready(now, "Manual", 70.0)
    assert controller.start_guest(now - timedelta(hours=12, minutes=1))
    controller.commands = []
    effects = controller.step(
        observation(now, "Manual", 70.0), ctl.Want(sp.OFF, "peak_no_grid_heating"), config()
    )
    assert controller.guest_until is None and published(effects) == ["off@70"]
    # An observing controller (not steady) is still re-inspected.
    waiting = ctl.Controller()
    waiting.set_enabled(True, now)
    waiting.guest_started = waiting.guest_until = (now + timedelta(hours=1)).isoformat()
    assert waiting.cancel_guest(now) and waiting.state == ctl.OBSERVING
    assert waiting.reason == "guest_mode_cancelled_reinspecting"


# --- M2: an appliance is not the element ---------------------------------------------------


def test_m2_an_appliance_step_with_the_heater_off_never_qualifies_a_peak_start(
    tmp_path, monkeypatch
):
    class Oven(Sim):
        base = staticmethod(
            lambda loc: 0.5 + (2.5 if 545 <= loc.hour * 60 + loc.minute < 590 else 0.0)
        )

    # Export 3.1 kW before the oven (below the 3.3 kW start); 0.6 kW with it on.
    rig = Oven(
        tmp_path, monkeypatch, hobart(MON, 8, 20), reading=46.0, mode="Off", pv=lambda loc: 3.6
    )
    rig.enable()
    seen = []
    rig.run(hobart(MON, 10, 30), lambda r: seen.append(r.runtime.heater.state))
    assert "on" in seen  # the estimator did read the oven's step as the element
    assert rig.posts == [], rig.posts_local()  # 0.9.0: Manual 70 at 09:17, 0.6 kWh peak import
    assert rig.peak_import_kwh == 0


def test_m2_a_real_element_is_still_counted_once_the_heater_is_in_manual(tmp_path, monkeypatch):
    rig = Sim(
        tmp_path, monkeypatch, hobart(MON, 8, 20), reading=46.0, mode="Off", pv=lambda loc: 4.5
    )
    rig.enable()
    rig.run(hobart(MON, 10, 55), trace)
    # Export is only 1 kW while the element runs; counting the element keeps it on.
    assert [p[1:] for p in rig.posts_local()] == [("manual", 70)], rig.posts_local()
    assert rig.peak_import_kwh == 0


# --- M4: published forecasts ---------------------------------------------------------------


def test_m4_automatic_control_cannot_be_enabled_without_published_forecasts(rig):
    rig.entry.options["forecast_enabled"] = False
    rig.executor.configure(rig.entry.options)
    with pytest.raises(RuntimeError, match="published_forecasts_not_enabled"):
        rig.enable()
    assert rig.executor.controller.enabled is False
    rig.entry.options["forecast_enabled"] = True
    rig.executor.configure(rig.entry.options)
    rig.enable()
    assert rig.executor.controller.enabled is True


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch, hobart(MON, 10, 50))


def test_m4_the_forecast_switch_is_not_a_preference_and_is_locked_while_control_is_on():
    assert "forecast_enabled" in settings_module.PRESERVE_ON_RESTORE
    assert "forecast_enabled" in settings_module.LOCKED_WHILE_ACTIVE
    saved = c.saved_options({"forecast_enabled": True, "forecast_uncertainty": 0.4})
    restored = settings_module.recommended_options(saved)
    assert restored["forecast_enabled"] is True  # 0.9.0: the restore turned it off
    assert restored["forecast_uncertainty"] == c.DEFAULT_OPTIONS["forecast_uncertainty"]
    assert settings_module.locked_changes(saved, {**saved, "forecast_enabled": False}) == [
        "forecast_enabled"
    ]


def test_m4_without_a_forecast_grid_heating_waits_for_the_latest_start():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 11, 5)
    waiting = p.decide(snap(now, OFF, reading=55))
    assert (waiting.state, waiting.reason, waiting.command) == (
        OFF,
        "storage_waiting_no_forecast",
        None,
    )
    latest = waiting.plan["latest_start"]
    assert latest - timedelta(hours=waiting.plan["heating_hours"]) < waiting.plan["soft_target"]
    started = p.decide(snap(latest, OFF, reading=55))
    assert (started.reason, started.command) == ("storage_latest_start", "Manual:70")
    # Measured solar still starts it sooner, and a published overcast forecast
    # still starts at once (every window costs the same).
    q = sp.SimplePolicy(S, TARIFFS)
    sunny = feed(q, now - 10 * MIN, 10, -4.0)
    assert q.decide(snap(sunny, OFF, reading=55)).reason == "storage_cheapest_now"
    assert p.decide(snap(now, OFF, reading=55, forecast=fc(now, 8, 0.3))).reason == (
        "storage_cheapest_now"
    )


def test_m4_a_lost_forecast_is_reported_and_still_heats_on_solar(tmp_path, monkeypatch):
    from test_integration_0_9_0 import sunny_after

    rig = Sim(
        tmp_path, monkeypatch, hobart(MON, 10, 50), reading=46.0, mode="Off", pv=sunny_after(13)
    )
    rig._forecast = lambda pv=None: None  # EMHASS stops publishing
    rig.enable()
    rig.run(hobart(MON, 17, 10), trace)
    start, park = rig.posts_local()
    # 0.9.0 with no forecast: Manual 70 at 11:01, 5.2 kWh from the grid.
    assert start[1:] == ("manual", 70) and "13:00" <= start[0] <= "13:35", rig.posts_local()
    assert park[:2] in {("16:58", "off"), ("16:59", "off")}
    assert any(key.endswith("forecast_unavailable") for key in rig.notifications)
    assert "forecast_unavailable" in rig.executor.controller.active_alerts


def test_m4_a_short_forecast_gap_does_not_alert():
    now = at(MON, 12, 0)
    controller = controller_ready(now)
    want = ctl.Want("hold", "policy")
    controller.step(observation(now, forecast_available=False), want, config())
    controller.step(
        observation(now + timedelta(minutes=59), forecast_available=False), want, config()
    )
    assert "forecast_unavailable" not in controller.active_alerts
    controller.step(
        observation(now + timedelta(minutes=61), forecast_available=False), want, config()
    )
    assert "forecast_unavailable" in controller.active_alerts
    controller.step(
        observation(now + timedelta(minutes=62), forecast_available=True), want, config()
    )
    assert "forecast_unavailable" not in controller.active_alerts
    assert controller.forecast_missing_since is None


# --- M5: the sample windows ------------------------------------------------------------------


def first_true(grid_kw, window, test, drift_ms=3, minutes=90):
    """Minute index at which ``test`` first holds, with Home Assistant's timer drift."""
    policy = sp.SimplePolicy(S, TARIFFS)
    start = at(MON, 9, 0)
    for i in range(minutes):
        now = start + i * MIN + timedelta(milliseconds=drift_ms * i)
        policy.add_meter(now, grid_kw(i), False)
        if policy.sustained(now, window, test):
            return i
    return None


def qualifies(sample):
    return sample[2] >= S.peak_start_kw


def withdraws(sample):
    return sample[1] > S.peak_import_tolerance_kw or sample[2] < 2.8


@pytest.mark.parametrize("drift_ms", [0, 3, 40])
def test_m5_ten_minutes_means_ten_and_five_means_five(drift_ms):
    # Surplus from minute 20: the first qualifying decision is 10 minutes later
    # (0.9.0: 7 to 8 minutes later).
    assert first_true(lambda i: -4.0 if i >= 20 else 0.5, S.qualify, qualifies, drift_ms) == 30
    # Import from minute 20: withdrawal 5 minutes later (0.9.0: 3 minutes later).
    assert first_true(lambda i: 2.5 if i >= 20 else -4.0, S.withdraw, withdraws, drift_ms) == 25


def test_m5_a_short_blip_is_tolerated_but_the_window_edges_must_pass():
    # One cloudy minute inside ten sunny ones does not reset the qualification.
    assert first_true(lambda i: 0.5 if i == 25 else -4.0, S.qualify, qualifies) == 10
    assert first_true(lambda i: 0.5 if i in (20, 25) or i < 20 else -4.0, S.qualify, qualifies) == (
        31
    )
    # A good minute now always defers a withdrawal; a mostly-importing pattern withdraws.
    assert first_true(lambda i: -4.0 if i % 4 == 3 else 2.5, S.withdraw, withdraws) == 5
    assert first_true(lambda i: -4.0 if i % 2 else 2.5, S.withdraw, withdraws) is None


def test_m5_a_meter_gap_still_prevents_both():
    policy = sp.SimplePolicy(S, TARIFFS)
    start = at(MON, 9, 0)
    for i in list(range(0, 5)) + list(range(9, 12)):
        policy.add_meter(start + i * MIN, -4.0, False)
    assert not policy.sustained(start + 11 * MIN, S.qualify, qualifies)
    assert replace(S).qualify == timedelta(minutes=10) and S.withdraw == timedelta(minutes=5)


# --- M7: the shadow log ------------------------------------------------------------------------


def test_m7_each_days_park_is_recorded_in_shadow_observation(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 7, 30), reading=60.0, mode="Manual", setpoint=45)
    rig.run(hobart(TUE, 8, 10))
    assert rig.commands() == [] and rig.posts == []  # shadow: nothing is ever sent
    parks = [
        local(datetime.fromisoformat(item["at"]))
        for item in rig.executor.shadow
        if item["would_send"] == "off@45"
    ]
    # Monday morning, Monday evening and (0.9.0 dropped it) Tuesday morning.
    assert len(parks) == 3 and parks[-1] == "07:58", rig.executor.shadow
    # Within one day the recurring wish is still recorded once.
    payloads = [item["would_send"] for item in rig.executor.shadow]
    assert len(payloads) <= 6, payloads


# --- N1 (second audit): the element is counted only in Manual 70 °C ------------------------
#
# The element's 3 kW is added back to the measured surplus only while the policy
# is in STORAGE (Manual 70 °C) and the estimate is at least medium confidence.
# In Manual 45 °C an appliance's load step read as "element on" (medium, because
# the heater is in Manual) and created solar that was not there.

SAT = 14  # 2026-11-14, a weekend day: Manual 45 °C baseline, optional solar storage


class Weekend(Sim):
    """Actual PV and the published forecast are scripted separately."""

    forecast_pv = staticmethod(lambda loc: 0.0)

    def _forecast(self, pv=None):
        super()._forecast(self.forecast_pv)


def element_trace(rig):
    trace(rig)
    rig.log[-1].update(
        estimate=rig.runtime.heater.state,
        confidence=rig.runtime.heater.confidence,
        element=rig.tank.element,
        measured=rig.executor.policy.typical_available(rig.now()),
    )


def between(rig, first, last):
    return [row for row in rig.log if first <= row["at"] <= last]


def test_n1_an_appliance_in_manual_45_creates_no_solar_and_no_command(tmp_path, monkeypatch):
    class Oven(Weekend):
        # Export 0.7 kW (below the 1 kW weekend floor); a 2.5 kW oven from 10:02.
        base = staticmethod(lambda loc: 0.5 + (2.5 if loc.hour * 60 + loc.minute >= 602 else 0.0))
        forecast_pv = staticmethod(lambda loc: 1.7)  # promises 1.2 kW of surplus all day

    rig = Oven(
        tmp_path,
        monkeypatch,
        hobart(SAT, 9, 20),
        reading=46.0,
        mode="Manual",
        setpoint=45,
        pv=lambda loc: 1.2,
    )
    rig.enable()
    rig.run(hobart(SAT, 11, 40), element_trace)
    # The estimator does read the oven as the element (medium: the heater is in Manual) ...
    fooled = [row for row in rig.log if row["estimate"] == "on" and not row["element"]]
    assert fooled and "medium" in {row["confidence"] for row in fooled}
    # ... but in Manual 45 °C it adds nothing: the surplus stays what the meter shows.
    assert all((row["measured"] or 0.0) < 1.0 for row in between(rig, "09:35", "11:40"))
    # At 9cd5fa4 this sent Manual:70@45 (reason solar_opportunity) on 0.7 kW of real surplus.
    assert rig.posts == [] and rig.commands() == [], rig.posts_local()
    assert rig.executor.controller.state == "baseline_45"


def test_n1_manual_45_heating_by_its_own_thermostat_then_a_real_weekend_start(
    tmp_path, monkeypatch
):
    class Sunny(Weekend):
        forecast_pv = staticmethod(lambda loc: 3.2)

    # Reading 36.5 °C: the Manual 45 thermostat is heating (it starts at 37 °C).
    rig = Sunny(
        tmp_path,
        monkeypatch,
        hobart(SAT, 9, 20),
        reading=36.5,
        mode="Manual",
        setpoint=45,
        pv=lambda loc: 3.2,
    )
    rig.enable()
    rig.run(hobart(SAT, 12, 30), element_trace)
    heating = [row for row in rig.log if row["element"] and row["setpoint"] == 45]
    assert len(heating) >= 45  # the baseline thermostat really ran (36.5 to 45 °C)
    # While it heats, the meter shows a 0.3 kW import; nothing is added to it.
    settled = [row for row in heating if row["at"] >= "09:35"]
    assert settled and all((row["measured"] or 0.0) <= 0.0 for row in settled)
    stopped = next(row["at"] for row in rig.log if row["at"] > heating[-1]["at"])
    # The start comes only from surplus the meter really shows (2.7 kW once the
    # thermostat is satisfied), held for the full 10 minutes.
    start = rig.posts_local()[0]
    assert start[1:] == ("manual", 70), rig.posts_local()
    assert minute_of(start[0]) - minute_of(stopped) >= 10, (stopped, rig.posts_local())
    assert rig.commands() == ["Manual:70@45"]
    # In Manual 70 °C the genuine element IS counted: the meter exports nothing
    # while it runs, and the surplus still reads about 2.7 kW, so the session holds.
    storage = [row for row in rig.log if row["state"] == "storage_70" and row["element"]]
    assert len(storage) >= 20
    later = [row for row in storage if minute_of(row["at"]) >= minute_of(storage[0]["at"]) + 12]
    assert later and all(2.5 <= row["measured"] <= 2.9 for row in later), later[:3]
    assert len(rig.posts) == 1


def test_n1_manual_70_with_the_thermostat_idle_withdraws_on_real_surplus_only(
    tmp_path, monkeypatch
):
    def pv(loc):  # export 4.0 kW until 09:00, then 2.0 kW: less than the element needs
        return 4.5 if loc.hour < 9 else 2.5

    # Manual 70 °C in the morning peak with the tank hot: the thermostat is idle.
    rig = Sim(
        tmp_path, monkeypatch, hobart(MON, 8, 20), reading=69.9, mode="Manual", setpoint=70, pv=pv
    )
    rig.enable()
    rig.run(hobart(MON, 9, 30), element_trace)
    idle = between(rig, "08:35", "08:59")
    assert idle and not any(row["element"] for row in idle)
    assert all(row["estimate"] == "off" for row in idle)
    assert all(3.9 <= row["measured"] <= 4.1 for row in idle)  # nothing added while idle
    assert {row["decision"] for row in idle} == {"peak_solar_continues"}
    # Too little surplus for the element, although it is not running: withdrawn in 5-6 min.
    stop = rig.posts_local()
    assert len(stop) == 1 and stop[0][1] == "off" and "09:05" <= stop[0][0] <= "09:07", stop
    assert rig.peak_import_kwh == 0


def test_n1_manual_70_heating_in_a_peak_is_counted_and_keeps_qualified_solar(tmp_path, monkeypatch):
    rig = Sim(
        tmp_path, monkeypatch, hobart(MON, 8, 20), reading=46.0, mode="Off", pv=lambda loc: 4.5
    )
    rig.enable()
    rig.run(hobart(MON, 10, 55), element_trace)
    # Qualified on 4.0 kW of measured surplus (the heater OFF, nothing added) ...
    assert [p[1:] for p in rig.posts_local()] == [("manual", 70)], rig.posts_local()
    before = between(rig, "08:35", rig.posts_local()[0][0])
    assert all(3.9 <= row["measured"] <= 4.1 for row in before[:-1])
    # ... and with the element running the meter exports only 1.0 kW, yet the
    # surplus still reads 4.0 kW (element counted), so it is never withdrawn.
    heating = [row for row in rig.log if row["state"] == "storage_70" and row["element"]]
    settled = [r for r in heating if minute_of(r["at"]) >= minute_of(heating[0]["at"]) + 12]
    assert settled and all(3.9 <= row["measured"] <= 4.1 for row in settled), settled[:3]
    assert {row["decision"] for row in settled} == {"peak_solar_continues"}
    assert rig.peak_import_kwh == 0


def test_n1_only_storage_with_a_confident_estimate_counts_the_element(rig):
    """The rule itself, for every policy state and confidence."""
    executor, runtime = rig.executor, rig.runtime
    rig.enable()
    heater_state = importlib.import_module(f"{m.__package__}.heater_state")
    now = rig.now()
    runtime.grid_import_kw = 0.5
    counted = {}
    for state in (sp.OFF, sp.BASELINE, sp.STORAGE, None):
        for confidence in ("verified", "high", "medium", "low", "none"):
            executor.controller.state = ctl.ACTIVE_OF.get(state, ctl.OBSERVING)
            executor.controller.heater = state
            runtime.heater = heater_state.HeaterState(state="on", confidence=confidence)
            executor.reset_policy()
            executor.decide(now, executor.observe(now))
            counted[(state, confidence)] = executor.policy.samples[-1][3]
    assert {key for key, value in counted.items() if value} == {
        (sp.STORAGE, "verified"),
        (sp.STORAGE, "high"),
        (sp.STORAGE, "medium"),
    }
    # An estimate of "off" or "unknown" is never counted, in any state.
    for estimate in ("off", "unknown"):
        runtime.heater = heater_state.HeaterState(state=estimate, confidence="high")
        executor.controller.heater = sp.STORAGE
        executor.controller.state = ctl.STORAGE_ACTIVE
        executor.reset_policy()
        executor.decide(now, executor.observe(now))
        assert executor.policy.samples[-1][3] is False
