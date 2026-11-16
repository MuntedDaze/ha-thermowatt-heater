"""Actual runtime report, privacy, bounded events and heartbeat timing."""

from datetime import timedelta
import importlib
import json

from test_integration_0_9_0 import Rig, hobart, MON
from test_shadow_model import m

report = importlib.import_module(f"{m.__package__}.report")
presentation = importlib.import_module(f"{m.__package__}.presentation")


def test_report_collects_real_policy_and_never_copies_raw_dictionaries(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 2), mode="Manual", setpoint=45)
    rig.enable()
    rig.run(hobart(MON, 2, 5))
    secret = "PRIVATE_SECRET_SHOULD_NEVER_APPEAR"
    rig.entry.options.update(password=secret, token=secret, controller_command_topic=secret)
    rig.runtime.native_options.update(rig.entry.options)
    rig.runtime.details["secret"] = secret
    rig.executor.controller.intent = {"payload": secret, "topic": secret, "status": secret}
    rig.runtime.owner_events.append({"at": rig.now(), "reason": secret, "password": secret})
    before = (list(rig.posts), list(rig.ha_publishes), dict(rig.entry.options))
    data = report.build(rig.runtime, rig.now(), "2026.11.1")
    text = report.text_report(data)
    assert secret not in text and "TEST123" not in text
    assert '"password":' not in text and '"token":' not in text and "/CMD/" not in text
    assert data["versions"]["home_assistant"] == "2026.11.1"
    assert data["heater"]["last_bottom_c"] is not None
    assert data["heater"]["observed_at"] is not None
    assert data["preferences"]["normal_storage_c"] == 70  # never overwrite saved options
    assert data["cloud"]["operations"]["status"] > 0
    assert data["measurements"]["grid"]["source_reference"]
    assert data["measurements"]["grid"]["value"] is not None
    assert before == (rig.posts, rig.ha_publishes, rig.entry.options)
    json.dumps(data, allow_nan=False)


def test_event_buffer_is_bounded_redacted_and_deduplicates_idle_ticks(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 2), mode="Manual", setpoint=45)
    rig.enable()
    rig.run(hobart(MON, 2, 5))
    n = len(rig.runtime.owner_events)
    now = rig.now()
    for _ in range(100):
        rig.runtime.record_event(now, rig.executor.last_observation, rig.executor.last_decision)
    assert len(rig.runtime.owner_events) == n
    for i in range(250):
        rig.runtime._event_key = None
        rig.runtime.record_event(
            now + timedelta(minutes=i), rig.executor.last_observation, rig.executor.last_decision
        )
    assert len(rig.runtime.owner_events) == 200
    assert all("last_command" not in v and "at" in v for v in rig.runtime.owner_events)


def test_heartbeat_reduces_state_changes_without_rounding_internal_evaluation():
    heartbeat = presentation.Heartbeat()
    now = hobart(MON, 2)
    assert heartbeat.value(None, "steady") is None
    values = [heartbeat.value(now + timedelta(minutes=i), "steady") for i in range(60)]
    assert len(set(values)) == 4
    assert all(
        timedelta(0) <= now + timedelta(minutes=i) - v < timedelta(minutes=15)
        for i, v in enumerate(values)
    )
    # The unchanged external watchdog's30-minute threshold still has headroom.
    assert heartbeat.value(now + timedelta(minutes=60), "fault") == now + timedelta(minutes=60)
    assert heartbeat.value(None, "fault") == now + timedelta(minutes=60)


def test_nonfinite_or_secret_measurements_and_invalid_timestamps_are_omitted():
    for value in (True, "PRIVATE", "nan", float("inf"), None):
        assert report.numeric(value) is None
    assert report.numeric("-2300") == -2300
    assert report.stamp("2026-11-17T12:00:00") is None
    assert report.stamp("PRIVATE") is None
