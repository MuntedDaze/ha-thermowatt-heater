"""Dollar opportunity cost and consequential controller guards."""

from dataclasses import replace
from datetime import timedelta

from test_audit_regressions_0_9_1 import config, controller_ready, ctl, observation, published
from test_simple_policy import MIN, MON, OFF, S, STORE, TARIFFS, at, snap, sp
from test_shadow_model import c as configuration
import pytest


def test_future_status_cannot_confirm_an_outstanding_command():
    now = at(MON, 12)
    c = controller_ready(now)
    assert published(c.step(observation(now), ctl.Want(STORE, "storage_latest_start"), config()))
    c.step(
        observation(now + MIN, "Manual", 70, poll_at=now + timedelta(hours=1)),
        ctl.Want(STORE, "policy"),
        config(),
    )
    assert c.state == ctl.CONFIRMING and c.intent is not None


def test_optional_peak_start_is_rejected_when_feed_in_exceeds_later_grid():
    p = sp.SimplePolicy(replace(S, feed_in_rate=0.20), TARIFFS)
    for i in range(11):
        p.add_meter(at(MON, 9) + i * MIN, -4, heater_kw=0)
    d = p.decide(snap(at(MON, 9, 10), OFF))
    assert d.state == OFF and d.command is None


def test_measured_low_element_power_advances_required_latest_start():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(MON, 12)
    nominal = p.decide(snap(now, OFF, reading=45))
    actual = p.decide(snap(now, OFF, reading=45, measured_element_kw=2.7))
    assert actual.plan["latest_start"] < nominal.plan["latest_start"]
    assert actual.plan["heating_hours"] > nominal.plan["heating_hours"]


def test_optional_request_reserve_preserves_capacity_for_exit():
    now = at(MON, 9)
    c = controller_ready(now)
    c.request_samples = [[(now - timedelta(hours=1)).isoformat(), 0], [now.isoformat(), 215]]
    effects = c.step(
        observation(now, requests_total=215), ctl.Want(STORE, "peak_solar_qualified"), config()
    )
    assert not published(effects) and "optional_exit_request_reserve" in c.gate_failures
    # Essential weekday heating retains its ordinary allowance.
    assert published(
        c.step(
            observation(now, requests_total=215), ctl.Want(STORE, "storage_latest_start"), config()
        )
    )


def test_unverified_tariff_is_an_explicit_commissioning_gate():
    now = at(MON, 12)
    c = controller_ready(now)
    effects = c.step(
        observation(now), ctl.Want(STORE, "storage_latest_start"), config(tariff_verified=False)
    )
    assert not published(effects) and "tariff_contract_not_verified" in c.gate_failures


@pytest.mark.parametrize(
    "changes",
    [
        {"optional_heat_margin_aud_per_kwh": -0.01},
        {"pause_min_saving_aud": 0},
        {"pause_min_saving_aud": float("nan")},
    ],
)
def test_economic_preferences_validate_atomically(changes):
    with pytest.raises(ValueError):
        configuration.parse_options(changes)


def test_persistent_raw_meter_failure_alerts_once_and_resolves_on_recovery():
    now = at(MON, 12)
    c = controller_ready(now)
    missing = {"heater_meter_mapped": True, "heater_meter_quality": "stale_or_invalid"}
    c.step(observation(now, **missing), ctl.Want("hold", "policy"), config())
    later = now + 5 * MIN
    effects = c.step(observation(later, **missing), ctl.Want("hold", "policy"), config())
    assert [e.key for e in effects if e.kind == "notify"] == ["heater_meter_unavailable"]
    assert not published(effects)
    again = c.step(observation(later + MIN, **missing), ctl.Want("hold", "policy"), config())
    assert not [e for e in again if e.kind == "notify"]
    recovered = c.step(
        observation(later + 2 * MIN, heater_meter_mapped=True, heater_meter_quality="verified"),
        ctl.Want("hold", "policy"),
        config(),
    )
    assert "heater_meter_unavailable" in [e.key for e in recovered if e.kind == "resolve"]
