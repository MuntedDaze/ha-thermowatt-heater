"""New owner policy: actual policy/controller, synthetic measurements only."""

from dataclasses import replace
from datetime import timedelta
import importlib

import pytest

from test_shadow_model import c, m
from test_simple_policy import sp, S, TARIFFS, at, MON, SAT, MIN, snap, fc, BASE, OFF, STORE
from test_audit_regressions_0_9_1 import ctl, controller_ready, observation, config, published

S = replace(S, normal_c=62)

comfort = importlib.import_module(f"{m.__package__}.comfort")
solar = importlib.import_module(f"{m.__package__}.solar")


def pv(policy, now, minutes=15, kw=0.5):
    for i in range(minutes + 1):
        policy.add_pv(now - (minutes - i) * MIN, kw)


def test_override_is_62_even_at_peak_and_boost_off():
    now = at(MON, 18)
    p = sp.SimplePolicy(replace(S, boost_enabled=False), TARIFFS)
    d = p.decide(snap(now, OFF, override_12h=True))
    assert (d.state, d.command) == (sp.NORMAL, "Manual:62")
    controller = controller_ready(now)
    assert controller.start_guest(now)
    assert controller.guest_target_c == 62
    assert controller.guest_until == (now + timedelta(hours=12)).isoformat()
    obs = observation(now)
    obs.bridge_transitions.append("Manual:62@off")
    assert published(
        controller.step(
            obs,
            ctl.Want(d.state, d.reason),
            replace(config(), four_state_qualified=True),
        )
    ) == ["Manual:62@off"]


def test_legacy_active_override_and_pending_intent_survive_without_replay():
    now = at(MON, 12)
    original = controller_ready(now)
    original.start_guest(now)
    data = original.to_dict()
    data.pop("guest_target_c")
    controller = ctl.Controller.from_dict(data)
    assert controller.guest_target_c == 70
    assert controller.guest_until == original.guest_until
    controller.restored(now + MIN)
    assert not published(
        controller.step(
            observation(now + MIN, poll_at=now), ctl.Want(STORE, "12hr_override"), config()
        )
    )
    assert controller.cancel_guest(now + 2 * MIN)
    assert controller.start_guest(now + 3 * MIN) and controller.guest_target_c == 62


@pytest.mark.parametrize(
    "minutes,kw,expected", [(0, 0.499, BASE), (15, 0.499, BASE), (0, 0.5, sp.NORMAL)]
)
def test_weekend_real_pv_trigger_allows_grid_assisted_comfort(minutes, kw, expected):
    # 0.17.0: one fresh report of at least 0.5 kW opens the window (no
    # qualification delay, no 09:00 restriction).
    now = at(SAT, 7)
    p = sp.SimplePolicy(replace(S, boost_enabled=False), TARIFFS)
    pv(p, now, minutes, kw)
    d = p.decide(snap(now, BASE, reading=40, heater_meter_valid=False))
    assert d.state == expected
    assert (d.plan.get("weekend_grid_assistance_permitted") is True) == (expected == sp.NORMAL)


def test_stale_or_invalid_pv_never_opens_the_weekend_window():
    now = at(SAT, 11)
    p = sp.SimplePolicy(S, TARIFFS)
    p.add_pv(now - 4 * MIN, 0.7)  # older than the 3-minute meter age
    assert p.decide(snap(now, BASE)).state == BASE
    pv(p, now + 20 * MIN, 15, 0.7)
    p.add_pv(None, None)  # an invalid report clears PV evidence
    assert p.decide(snap(now + 20 * MIN, BASE)).state == BASE
    p.add_pv(now + 21 * MIN, 0.7)
    assert p.decide(snap(now + 21 * MIN, BASE)).state == sp.NORMAL


def test_weekend_latch_holds_until_18_whatever_the_pv_does():
    # 0.17.0: clouds or low late-day PV no longer end the window early.
    now = at(SAT, 13)
    p = sp.SimplePolicy(replace(S, boost_enabled=False), TARIFFS)
    pv(p, now, 15, 0.1)
    assert p.decide(snap(now, sp.NORMAL, weekend_latched=True)).state == sp.NORMAL
    pv(p, now + 4 * 60 * MIN, 60, 0.0)
    d = p.decide(snap(now + 4 * 60 * MIN, sp.NORMAL, weekend_latched=True))
    assert d.state == sp.NORMAL and not d.plan.get("weekend_day_ended")
    d = p.decide(snap(at(SAT, 18), sp.NORMAL, weekend_latched=True))
    assert d.state == BASE and d.plan["weekend_day_ended"] and d.command == "Manual:45"
    assert p.decide(snap(at(SAT, 18, 30), BASE, weekend_ended=True)).state == BASE


def test_weekend_direct_45_to_70_requires_stronger_evidence_and_useful_heat():
    now = at(SAT, 11)
    p = sp.SimplePolicy(S, TARIFFS)
    pv(p, now)
    for i in range(11):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    d = p.decide(
        snap(
            now,
            BASE,
            reading=48,
            ct_free_solar_valid=True,
            heater_meter_valid=False,
            forecast=fc(now, 6, 4),
        )
    )
    assert d.command == "Manual:70"
    assert (
        p.decide(
            snap(
                now,
                sp.NORMAL,
                reading=63,
                ct_free_solar_valid=True,
                heater_meter_valid=False,
                forecast=fc(now, 6, 4),
                weekend_latched=True,
            )
        ).state
        == sp.NORMAL
    )


def test_pre_peak_warning_ignores_shower_drops_and_unfresh_readings():
    now = at(MON, 6, 30)
    peak = now + 30 * MIN
    assess = comfort.pre_peak_availability
    assert assess(now, 33, now, peak)["state"] == "low"
    assert assess(now, 35, now, peak)["state"] == "latest_probe_above_warning"
    assert assess(now, 33, now - 60 * MIN, peak)["state"] == "unverified"
    assert assess(now, 33, now + MIN, peak)["state"] == "unverified"
    assert assess(now - 120 * MIN, 33, now - 120 * MIN, peak)["state"] == "not_due"
    assert assess(now, None, None, peak)["state"] == "unverified"
    control = controller_ready(now)
    obs = observation(now, low_water_assessment=assess(now, 33, now, peak))
    first = control.step(obs, ctl.Want(BASE, "baseline"), config())
    assert any(e.key == "pre_peak_low_hot_water" for e in first)
    assert not published(first) or published(first) == ["Manual:45@off"]
    assert not any(
        e.key == "pre_peak_low_hot_water" and e.kind == "notify"
        for e in control.step(obs, ctl.Want(BASE, "baseline"), config())
    )


@pytest.mark.parametrize(
    "grid,ac,house,why",
    [
        (-3.5, 4, 0.5, "consistent_measured_site_power"),
        (-3.5, None, 0.5, "fresh_grid_inverter_and_house_readings_required"),
        (-6, 6, 0.5, "inverter_or_house_reading_implausible"),
        (-4, 1, 0.5, "export_exceeds_measured_inverter_output"),
        (3.5, 4, 0.5, "grid_sign_or_whole_house_balance_inconsistent"),
    ],
)
def test_ct_free_site_balance_has_no_nominal_element_credit(grid, ac, house, why):
    assert solar.grid_sanity(grid, ac, house, 5) == why


def test_new_defaults_validate_and_preserve_all_legacy_values():
    options = {**c.DEFAULT_OPTIONS, "baseline_c": "45", "extra_legacy": {"id": 7}}
    c.parse_options(options)
    assert c.saved_options(options) == options
    assert options["solar_cooldown_minutes"] == 10
