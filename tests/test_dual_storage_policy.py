"""Four-state policy and public CT-free/peak settings, offline only."""

from dataclasses import replace
from datetime import datetime, timedelta
from itertools import permutations
import pytest

from test_simple_policy import sp, TARIFFS, at, snap, fc, MIN, MON, SAT, OFF, BASE, STORE
from test_controller_0_9_0 import ctl, cfg, obs, ready, publishes
from test_shadow_model import m

NORMAL = sp.NORMAL
D = sp.PolicySettings()


def sun(policy, now):
    for i in range(11):
        policy.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)


@pytest.mark.parametrize("state", [OFF, BASE, NORMAL, STORE])
@pytest.mark.parametrize("ct", [False, True])
def test_never_peak_overrides_large_export_forecast_and_spacing(state, ct):
    now = at(MON, 18)
    p = sp.SimplePolicy(D, TARIFFS)
    sun(p, now)
    d = p.decide(
        snap(
            now,
            state,
            reading=40,
            heater_meter_valid=ct,
            forecast=fc(now, 4, 4),
            last_command_at=now - MIN,
        )
    )
    assert (d.state, d.reason) == (OFF, "peak_lockout")
    assert d.command == (None if state == OFF else "off")


@pytest.mark.parametrize("ct", [False, True])
def test_cloudy_required_weekday_is_62_not_70_with_optional_ct(ct):
    now = at(MON, 14)
    p = sp.SimplePolicy(D, TARIFFS)
    d = p.decide(snap(now, OFF, reading=40, heater_meter_valid=ct, forecast=fc(now, 6, 0)))
    assert d.state == NORMAL and d.command == "Manual:62"
    assert d.plan["heating_role"] == "required"


def test_strong_sun_direct_70_and_unexpected_topup_are_economic():
    now = at(MON, 12)
    p = sp.SimplePolicy(D, TARIFFS)
    sun(p, now)
    for state, reading in [(OFF, 45), (NORMAL, 62)]:
        d = p.decide(snap(now, state, reading=reading, forecast=fc(now, 6, 4)))
        assert d.state == STORE and d.command == "Manual:70"
        assert d.plan["boost_eligible"] and d.plan["heating_role"] == "optional"
        assert d.plan["boost_extra_kwh"] == pytest.approx(2.93, abs=0.01)


def test_boost_disabled_cannot_target_70_but_owner_override_uses_62():
    now = at(MON, 12)
    p = sp.SimplePolicy(replace(D, boost_enabled=False), TARIFFS)
    sun(p, now)
    assert p.decide(snap(now, NORMAL, reading=54, forecast=fc(now, 6, 4))).state == NORMAL
    assert p.decide(snap(at(MON, 18), OFF, reading=40, override_12h=True)).command == "Manual:62"
    assert p.decide(snap(at(MON, 18), NORMAL, owner_override=True)).state == sp.HOLD


def test_later_clouds_revert_optional_boost_to_required_62_after_debounce():
    p = sp.SimplePolicy(D, TARIFFS)
    now = at(MON, 13)
    for i in range(11):
        p.add_meter(now + i * MIN, 3, heater_kw=3)
    d = p.decide(snap(now + 10 * MIN, STORE, reading=58, forecast=fc(now, 5, 4)))
    assert d.command == "Manual:62" and d.reason == "weekday_solar_boost_withdrawn"


def test_ct_loss_and_low_optional_budget_fall_back_to_required_heat():
    now = at(MON, 15)
    for params in ({"heater_meter_valid": False}, {"optional_allowed": False}):
        p = sp.SimplePolicy(D, TARIFFS)
        sun(p, now)
        d = p.decide(snap(now, OFF, reading=40, forecast=fc(now, 4, 4), **params))
        assert d.command == "Manual:62"


def test_idle_inside_boost_hysteresis_is_not_an_energisation_promise():
    now = at(MON, 13)
    p = sp.SimplePolicy(D, TARIFFS)
    sun(p, now)
    d = p.decide(snap(now, NORMAL, reading=63, forecast=fc(now, 5, 4)))
    assert d.command is None and d.plan["target_reached"]
    assert d.plan["boost_reason"] == "inside_native_hysteresis_no_verified_heat"


def test_weekend_62_waits_for_pv_or_the_deadline_and_night_returns_baseline():
    # 0.17.0: without PV the weekend stays at baseline until the latest start
    # that still meets the 16:00 storage-ready deadline (owner's weekend policy).
    p = sp.SimplePolicy(D, TARIFFS)
    assert (
        p.decide(snap(at(SAT, 9), OFF, reading=40, heater_meter_valid=False)).command == "Manual:45"
    )
    late = p.decide(snap(at(SAT, 14), OFF, reading=40, heater_meter_valid=False))
    assert late.command == "Manual:62"
    assert late.plan["weekend_window_opened_by"] == "deadline_fallback"
    assert (
        p.decide(snap(at(MON, 22, 5), OFF, reading=40, heater_meter_valid=False)).command
        == "Manual:45"
    )


@pytest.mark.parametrize("prior,target", list(permutations((OFF, BASE, NORMAL, STORE), 2)))
def test_controller_all_twelve_transitions_require_exact_fresh_prior_and_confirm(prior, target):
    now = at(MON, 12)
    mode = "Off" if prior == OFF else "Manual"
    temp = 70 if prior == OFF else ctl.TARGET_C[prior]
    c = ready(now, mode, temp)
    transitions = [ctl.payload_for(t, p) for p, t in permutations((OFF, BASE, NORMAL, STORE), 2)]
    settings = cfg(four_state_qualified=True, requires_four_states=True)
    o = obs(now, mode, temp, bridge_transitions=transitions)
    assert publishes(c.step(o, ctl.Want(target, "test_transition"), settings)) == [
        ctl.payload_for(target, prior)
    ]
    later = now + MIN
    newmode = "Off" if target == OFF else "Manual"
    result = c.step(
        obs(
            later,
            newmode,
            70 if target == OFF else ctl.TARGET_C[target],
            poll_at=later,
            bridge_transitions=transitions,
        ),
        ctl.Want("hold", "confirmed"),
        settings,
    )
    assert not publishes(result) and c.heater == target and c.intent is None


def test_peak_solar_policy_can_heat_normal_without_optional_70():
    p = sp.SimplePolicy(replace(D, peak_policy=sp.PEAK_SOLAR, boost_enabled=False), TARIFFS)
    now = at(MON, 9)
    sun(p, now)
    assert p.decide(snap(now, OFF, reading=45)).command == "Manual:62"


def test_lockout_unconfirmed_does_not_claim_electrical_zero():
    now = at(MON, 17)
    c = ready(now, "Manual", 62)
    o = obs(now, "Manual", 62, bridge_transitions=["off@62"])
    assert publishes(c.step(o, ctl.Want(OFF, "peak_lockout"), cfg(four_state_qualified=True)))
    c.step(
        obs(now + MIN, "Manual", 62, cloud_health="auth_locked"),
        ctl.Want(OFF, "peak_lockout"),
        cfg(),
    )
    assert c.state == ctl.CONFIRMING and c.heater == NORMAL and c.intent is not None


@pytest.mark.parametrize("mode,target", [("Manual", 70), ("Manual", 55), ("Holiday", 62)])
def test_app_changes_from_normal_are_preserved_even_during_peak(mode, target):
    now = at(MON, 17)
    c = ready(now, "Manual", 62)
    effects = c.step(
        obs(now + MIN, mode, target, poll_at=now + MIN), ctl.Want(OFF, "peak_lockout"), cfg()
    )
    assert not publishes(effects) and c.state == ctl.OWNER_OVERRIDE


def test_restart_during_peak_reinspects_before_one_guarded_off():
    now = at(MON, 17)
    c = ready(now, "Manual", 62)
    restored = ctl.Controller.from_dict(c.to_dict())
    restored.restored(now)
    wanted = ctl.Want(OFF, "peak_lockout")
    settings = cfg(four_state_qualified=True, requires_four_states=True)
    first = restored.step(obs(now, "Manual", 62, poll_at=now), wanted, settings)
    assert not publishes(first)
    assert any(e.key == "peak_lockout_unverified" for e in first if e.kind == "notify")
    later = now + MIN
    effects = restored.step(
        obs(later, "Manual", 62, poll_at=later, bridge_transitions=["off@62"]), wanted, settings
    )
    assert publishes(effects) == ["off@62"]
    assert "peak_lockout_unverified" in restored.active_alerts
    assert not [e for e in effects if e.kind == "notify"]  # notification deduplicates


def test_forecast_fluctuation_does_not_toggle_a_qualified_boost():
    now = at(MON, 13)
    p = sp.SimplePolicy(D, TARIFFS)
    for i in range(11):
        p.add_meter(now - (10 - i) * MIN, -1, heater_kw=3)
    for forecast in (fc(now, 6, 4), fc(now, 6, 0), ()):
        d = p.decide(snap(now, STORE, reading=58, forecast=forecast, measured_element_kw=3))
        assert d.state == STORE and d.command is None


@pytest.mark.parametrize("month,day,local_hour", [(3, 30, 8), (4, 6, 7), (9, 28, 7), (10, 5, 8)])
@pytest.mark.parametrize("clock", ["standard", "local"])
def test_peak_lockout_and_return_to_baseline_across_dst_clock_boundaries(
    month, day, local_hour, clock
):
    p = sp.SimplePolicy(replace(D, tariff_clock=clock, boost_enabled=False), TARIFFS)
    zone = m.STANDARD if clock == "standard" else m.HOBART
    peak = datetime(2026, month, day, 7, tzinfo=zone).astimezone(m.UTC)
    if clock == "standard":
        assert peak.astimezone(m.HOBART).hour == local_hour
    # A restart has no old measurement qualification; lockout still wins.
    for minute in (-2, 0, 1):
        d = p.decide(snap(peak + minute * MIN, NORMAL, heater_meter_valid=False))
        assert (d.command, d.reason) == ("off", "peak_lockout")
    after_evening_peak = datetime(2026, month, day, 21, 1, tzinfo=zone).astimezone(m.UTC)
    assert p.decide(snap(after_evening_peak, OFF, heater_meter_valid=False)).command == "Manual:45"
    # Reserved OFF is exempt from ordinary spacing, but not the real executor's budgets/guards.
    d = p.decide(snap(peak - 2 * MIN, NORMAL, last_command_at=peak - timedelta(minutes=3)))
    assert d.command == "off"
