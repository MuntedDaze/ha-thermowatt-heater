"""The real executor/bridge path, synthetic HA/MQTT/HTTP only.

Do not construct Want manually: the regression is the policy's real HOLD after
a fault clears the current heater state, despite a genuine previous OFF report.
"""

from datetime import datetime, timedelta

import pytest
import requests

from conftest import response
from test_integration_0_9_0 import Rig, SERIAL, drive, hobart, MON, m

ALERT = "parked_off_cannot_restore"
NOTICE = f"thermann_shadow_{ALERT}"


def evaluate(rig):
    rig._meter()
    rig.runtime.update(rig.now())
    drive(rig.executor.async_step(rig.now()))
    return rig.executor.last_decision


def advance(rig, when):
    """Respect the real bridge backoff/confirmation clock; no forced retry."""
    while rig.now() < when:
        rig.t = min(when.timestamp(), rig.t + 20)
        rig.bridge.tick()
        evaluate(rig)


def heater_posts(rig):
    return [
        call
        for call in rig.bridge.session.request.call_args_list
        if call.args[0] == "POST" and call.args[1].rsplit("/", 1)[-1] in {"manual", "off"}
    ]


@pytest.fixture
def parked(tmp_path, monkeypatch):
    # Peak ends at 22:00 Hobart (21:00 fixed AEST). The controller observes OFF
    # genuinely after enable/inspection, just before baseline restoration.
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(MON, 21, 59) + timedelta(seconds=20),
        mode="Off",
        setpoint=45,
        reading=45,
    )
    options = {
        **rig.entry.options,
        "normal_storage_c": "62",
        "peak_heating_policy": "Never schedule heating during peak",
        "heater_meter_verification": "",
    }
    rig.sources.pop("heater_power")
    rig.entry.options.update(options)
    rig.runtime.apply_options(options, rig.sources)
    rig.executor.configure(options)
    rig.enable()
    rig.t += 30
    rig.bridge.token_obtained_at = rig.t - 1190
    rig.bridge.poll_status(SERIAL)
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.last_observed_heater == "off" and controller.heater == "off"
    assert controller.parked_off_restore_since is None
    assert not rig.commands() and not rig.posts
    rig.bridge.session.request.reset_mock()
    return rig


def fail_restore(rig, kind="auth", *, settle_fault=True):
    rig.t += 11 if kind not in {"status", "status_quota"} else 71
    if kind != "auth":
        rig.bridge.token_obtained_at = rig.t  # test a GET/POST failure, not token refresh
    decision = evaluate(rig)
    assert decision.state == "baseline" and decision.command == "Manual:45"
    assert rig.commands() == ["Manual:45@off"]
    started = rig.executor.controller.parked_off_restore_since
    assert started == rig.now().isoformat()
    rig.bridge.session.request.side_effect = (
        [response(401)]
        if kind == "auth"
        else (lambda *a, **k: response(body={"error": "Daily request limit exceeded"}))
        if kind == "status_quota"
        else requests.Timeout()
    )
    rig.bridge.tick()
    if kind == "auth":
        assert rig.bridge.last_command["result"] == "refused_authentication_before_command"
        assert not heater_posts(rig) and rig.bridge.pending is None
    elif kind in {"status", "status_quota"}:
        assert rig.bridge.last_command["result"] == "refused_status_refresh_failed"
        assert not heater_posts(rig) and rig.bridge.pending is None
    else:
        assert rig.bridge.pending and len(heater_posts(rig)) == 1
    if not settle_fault:
        return datetime.fromisoformat(started)
    advance(rig, rig.now() + timedelta(minutes=8 if kind == "post" else 1))
    controller = rig.executor.controller
    if kind == "status":
        # Transient pre-command status timeout defers safely without locking,
        # while retaining parked-OFF restore age and sending no retries.
        assert controller.state in {"parked", "change_requested"}
        assert controller.fault is None and controller.heater == "off"
        assert controller.last_observed_heater == "off"
        assert controller.parked_off_restore_since == started
        return datetime.fromisoformat(started)
    assert controller.state == "fault_locked" and controller.heater is None
    assert controller.last_observed_heater == "off"
    decision = rig.executor.last_decision
    assert decision.state == "hold" and decision.reason == "heater_state_not_controlled"
    assert decision.command is None
    assert decision.plan.get("unconfirmed_restore_target_c") == 45
    assert controller.parked_off_restore_since == started
    return datetime.fromisoformat(started)


@pytest.mark.parametrize("failure", ["auth", "status", "status_quota", "post"])
def test_real_restoration_failure_warns_at_thirty_minutes_without_more_commands(parked, failure):
    rig = parked
    started = fail_restore(rig, failure)
    controller = rig.executor.controller
    attempts = len(heater_posts(rig))
    cloud_attempts = rig.bridge.session.request.call_count
    advance(rig, started + timedelta(minutes=30) - timedelta(seconds=1))
    assert NOTICE not in rig.notifications
    advance(rig, started + timedelta(minutes=30))
    assert ALERT in controller.active_alerts and rig.notifications.count(NOTICE) == 1
    advance(rig, started + timedelta(minutes=60))
    assert rig.notifications.count(NOTICE) == 1  # existing notification cooldown
    assert controller.parked_off_restore_since == started.isoformat()
    assert rig.commands() == ["Manual:45@off"] and len(heater_posts(rig)) == attempts
    if failure == "status":
        assert controller.state == "change_requested" and controller.heater == "off"
    else:
        assert controller.state == "fault_locked" and controller.heater is None
    if failure == "auth":
        assert rig.bridge.session.request.call_count == cloud_attempts
        assert rig.bridge.guard.state["mode"] == "blocked"


def test_acknowledging_fault_during_outage_preserves_warning_and_requires_new_status(parked):
    rig = parked
    started = fail_restore(rig)
    advance(rig, started + timedelta(minutes=10))
    assert drive(rig.executor.async_owner_action("acknowledge"))
    controller = rig.executor.controller
    assert controller.state == "observing" and controller.fault is None
    advance(rig, started + timedelta(minutes=30))
    assert rig.executor.last_decision.state == "hold"
    assert controller.reason == "waiting_for_new_heater_status"
    assert controller.parked_off_restore_since == started.isoformat()
    assert rig.notifications.count(NOTICE) == 1
    assert not heater_posts(rig) and rig.commands() == ["Manual:45@off"]
    assert rig.bridge.guard.state["mode"] == "blocked"


def test_unavailable_entities_retain_genuine_off_evidence_for_unknown_state_warning(parked):
    rig = parked
    started = fail_restore(rig)
    rig.report(rig.sources["mode"], "unavailable")
    rig.report(rig.sources["heater"], "unavailable")
    advance(rig, started + timedelta(minutes=30))
    assert rig.executor.last_observation.mode is None
    assert rig.executor.controller.last_observed_heater == "off"
    assert rig.executor.last_decision.state == "hold"
    assert rig.executor.last_decision.plan["unconfirmed_restore_target_c"] == 45
    assert rig.notifications.count(NOTICE) == 1
    assert not heater_posts(rig) and rig.commands() == ["Manual:45@off"]


@pytest.mark.parametrize("restart_minutes", [15, 31])
def test_executor_restart_retains_restore_age_fault_and_notification_deduplication(
    parked, restart_minutes
):
    rig = parked
    started = fail_restore(rig)
    advance(rig, started + timedelta(minutes=restart_minutes))
    rig.executor = rig._executor()  # actual Store save/load + Controller.restored
    assert rig.executor.controller.parked_off_restore_since == started.isoformat()
    assert rig.executor.controller.state == "fault_locked"
    advance(rig, started + timedelta(minutes=32))
    assert rig.executor.last_decision.state == "hold"
    assert rig.executor.last_decision.plan["unconfirmed_restore_target_c"] == 45
    assert rig.notifications.count(NOTICE) == 1
    assert not heater_posts(rig) and rig.commands() == ["Manual:45@off"]


def test_genuine_restoration_clears_warning_without_automatically_acknowledging_fault(parked):
    rig = parked
    started = fail_restore(rig, "status_quota")
    advance(rig, started + timedelta(minutes=31))
    assert ALERT in rig.executor.controller.active_alerts
    rig.tank.apply("Manual", 45, rig.t)  # simulated external owner restoration
    rig.tank.minute(rig.t + 30)
    rig.bridge.session.request.side_effect = rig.cloud
    advance(rig, datetime.fromtimestamp(rig.bridge.next_poll + 1, m.UTC))
    controller = rig.executor.controller
    assert controller.last_observed_heater == "baseline"
    assert controller.parked_off_restore_since is None and ALERT not in controller.active_alerts
    assert controller.state == "fault_locked" and controller.fault is not None
    assert rig.executor.values()["parked_off_restore_since"] is None
    assert not heater_posts(rig) and rig.commands() == ["Manual:45@off"]
    assert drive(rig.executor.async_owner_action("acknowledge"))
    advance(rig, datetime.fromtimestamp(rig.bridge.next_poll + 1, m.UTC))
    assert controller.heater == "baseline" and controller.fault is None
    assert rig.commands() == ["Manual:45@off"] and not heater_posts(rig)


def test_restart_during_uncertain_post_preserves_restore_age_without_replaying_it(parked):
    rig = parked
    started = fail_restore(rig, "post", settle_fault=False)
    advance(rig, started + timedelta(minutes=2))
    assert rig.bridge.pending and rig.executor.controller.state == "confirming"
    rig.executor = rig._executor()
    assert rig.executor.controller.reason == "reconciling_command_after_restart"
    advance(rig, started + timedelta(minutes=30))
    assert rig.executor.controller.state == "fault_locked" and rig.bridge.pending is None
    assert rig.executor.last_decision.state == "hold"
    assert rig.executor.last_decision.plan["unconfirmed_restore_target_c"] == 45
    assert rig.executor.controller.parked_off_restore_since == started.isoformat()
    assert rig.notifications.count(NOTICE) == 1
    assert rig.commands() == ["Manual:45@off"] and len(heater_posts(rig)) == 1


@pytest.mark.parametrize(
    "off_reason",
    [
        "peak",
        "peak_lead",
        "reserved_slot",
        "holiday",
        "owner_hold",
        "economic_wait",
        "unknown_prior",
    ],
)
def test_unknown_current_state_never_warns_for_legitimate_off_or_unknown_prior(parked, off_reason):
    rig = parked
    controller = rig.executor.controller
    # A known controller fault, not a constructed policy Want. The initial OFF
    # observation came from the real bridge. Check the actual executor decision.
    controller._lock("bridge_refused_or_dropped", "Synthetic fault", [])
    if off_reason == "peak":
        rig.t = hobart(MON + 1, 18).timestamp()
    elif off_reason == "peak_lead":
        rig.t = hobart(MON + 1, 16, 58).timestamp()
    elif off_reason == "reserved_slot":
        rig.t = hobart(MON + 1, 16, 50).timestamp()
    elif off_reason == "holiday":
        today = rig.now().astimezone(m.HOBART).date()
        assert controller.set_holiday(rig.now(), today, today + timedelta(days=2))
    elif off_reason == "owner_hold":
        controller.set_hold(rig.now())
    elif off_reason == "economic_wait":
        rig.t = hobart(MON + 1, 11, 5).timestamp()
    else:
        saved = controller.to_dict()
        saved.pop("last_observed_heater")  # old/unknown persisted provenance
        controller = type(controller).from_dict(saved)
        rig.executor.controller = controller
    # No bridge read during this check: keep genuine prior provenance unchanged.
    # Use fresh source reports to isolate the policy's current tariff/economics.
    rig._forecast()
    for _ in range(120):
        rig.t += 10
        decision = evaluate(rig)
        assert decision.state == "hold" and decision.command is None
        assert "unconfirmed_restore_target_c" not in decision.plan
        assert controller.parked_off_restore_since is None
    assert NOTICE not in rig.notifications
    assert rig.commands() == [] and not heater_posts(rig)


def test_owner_change_to_uncontrolled_mode_does_not_become_a_restore_requirement(parked):
    rig = parked
    rig.t += 1
    rig.tank.apply("Schedule", 45, rig.t)
    rig.tank.minute(rig.t + 30)
    rig.bridge.poll_status(SERIAL)
    evaluate(rig)
    assert rig.executor.controller.state == "owner_override"
    for _ in range(40):
        rig.t += 60
        decision = evaluate(rig)
        assert decision.state == "hold" and decision.reason == "owner_override"
    assert rig.executor.controller.parked_off_restore_since is None
    assert NOTICE not in rig.notifications and not rig.commands() and not heater_posts(rig)


@pytest.mark.parametrize("mode,target", [("Schedule", 45), ("Manual", 55)])
def test_fresh_uncontrolled_observation_invalidates_old_off_evidence_even_while_fault_locked(
    parked, mode, target
):
    rig = parked
    controller = rig.executor.controller
    controller._lock("bridge_refused_or_dropped", "Synthetic fault", [])
    rig.t += 1
    rig.tank.apply(mode, target, rig.t)
    rig.tank.minute(rig.t + 30)
    rig.bridge.poll_status(SERIAL)
    evaluate(rig)
    assert controller.state == "fault_locked" and controller.heater is None
    assert controller.last_observed_heater is None
    for _ in range(40):
        rig.t += 60
        decision = evaluate(rig)
        assert decision.state == "hold"
        assert "unconfirmed_restore_target_c" not in decision.plan
    assert controller.parked_off_restore_since is None
    assert NOTICE not in rig.notifications and not rig.commands() and not heater_posts(rig)
