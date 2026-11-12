"""Compatibility: the REAL bridge (>= 1.3.10) code driven by the REAL controller 0.6.1.

Mocked HTTP and MQTT only. The controller's observation is rebuilt from the
bridge's own published STATUS/DIAGNOSTICS messages, stepping the controller
after EVERY message so publish-order races are exercised."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from conftest import response
from test_shadow_model import m

ctl = __import__(f"{m.__package__}.controller", fromlist=["x"])
if os.environ.get("XCHECK_BRIDGE"):  # local check against another checkout's bridge
    BRIDGE_DIR = Path(os.environ["XCHECK_BRIDGE"])
    _saved = sys.modules.pop("thermowatt_read_only", None)
    sys.path.insert(0, str(BRIDGE_DIR))
    spec = importlib.util.spec_from_file_location(
        "bridge_xcheck", BRIDGE_DIR / "thermowatt_bridge.py"
    )
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    sys.path.remove(str(BRIDGE_DIR))
    if _saved is not None:
        sys.modules["thermowatt_read_only"] = _saved
else:
    from conftest import bridge_module as b

# Runs once the in-tree bridge is >= 1.3.11 (this controller branch is stacked
# on an older base; the bridge PRs are separate). Until then it skips.
pytestmark = pytest.mark.skipif(
    not hasattr(b, "CONFIRM_FOLLOWUPS"), reason="needs the bridge 1.3.11 code in this tree"
)
TOPIC = "P/TEST123/CMD/MODE"
CFG = ctl.ControllerConfig(command_topic=TOPIC, bridge_commands_qualified=True)
TOKENS = {"result": {"accessToken": "SYNTHETIC_ACCESS", "refreshToken": "SYNTHETIC_REFRESH"}}


def status(cmd, setpoint=70, avg=50):
    return response(
        body={
            "result": {
                "T_Avg": str(avg),
                "T_SetPoint": str(setpoint),
                "Cmd": str(cmd),
                "WaterHeaterSts": "32",
            }
        }
    )


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.t


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(b.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")
    clock = Clock()
    session = Mock(spec=requests.Session)
    mqtt = Mock()
    bridge = b.MyThermowattBridge(
        {
            "email": "synthetic@example.invalid",
            "password": "SYNTHETIC_PASSWORD",
            "cloud_enabled": True,
            "commands_enabled": True,
            "auth_retry_generation": 1,
        },
        tmp_path,
        session=session,
        mqtt_client=mqtt,
        clock=clock,
        monotonic=clock,
    )
    bridge.mqtt_connected.set()
    # The 1.3.11 request sequences scripted below; 1.3.13 defaults are covered in
    # test_bridge_1_3_13.py, including this controller round trip.
    bridge.proactive_refresh, bridge.immediate_confirmation_read = False, True
    session.request.side_effect = [response(body=TOKENS)]
    bridge.login()
    bridge.config["devices"] = {"TEST123": {"name": "Synthetic"}}
    bridge.active_devices = {"TEST123"}
    bridge.discovered = True
    return SimpleNamespace(bridge=bridge, clock=clock, session=session, mqtt=mqtt)


class HA:
    """Applies the bridge's MQTT messages to an HA-like view, one at a time."""

    def __init__(self):
        self.status = None
        self.diag = None

    def apply(self, call):
        topic, payload = call.args[0], call.args[1]
        if topic.endswith("/STATUS"):
            self.status = json.loads(payload)["result"]
            return True
        if topic.endswith("/DIAGNOSTICS"):
            self.diag = json.loads(payload)
            return True
        return False

    def observation(self, now):
        s, d = self.status or {}, self.diag or {}
        poll = d.get("last_successful_poll")
        return ctl.Observation(
            now=now,
            poll_at=datetime.fromisoformat(poll) if poll else None,
            mode=s.get("vendor_mode"),
            target_c=float(s["T_SetPoint"]) if s else None,
            temperature_c=float(s["T_Avg"]) if s else None,
            element="off",
            element_confidence="high",
            cloud_health=d.get("cloud_health"),
            auth_mode=d.get("auth_guard_mode"),
            consecutive_failures=d.get("consecutive_failures"),
            cooldown_seconds=d.get("cooldown_remaining_seconds"),
            bridge_available=True,
            bridge_commands_enabled=d.get("commands_enabled"),
            last_command=d.get("last_command"),
            requests_total=d.get("request_attempts"),
            mqtt_ready=True,
            bridge_refresh_limit=d.get("command_status_refresh_limit_24h"),
            bridge_refreshes_24h=d.get("command_status_refreshes_24h"),
            bridge_confirmation_followups=d.get("command_confirmation_followups_seconds"),
            bridge_confirmation_pending=d.get("command_confirmation_pending"),
            bridge_command_policy=d.get("command_policy"),
        )


def run(rig, controller, ha, desire, http, seen):
    """Step the controller after every new MQTT message; deliver any publish to
    the bridge's MQTT callback, then let the bridge tick with ``http``."""
    now = lambda: datetime.fromtimestamp(rig.clock(), timezone.utc)  # noqa: E731
    sent = []

    def drain():
        calls = rig.mqtt.publish.call_args_list
        while seen[0] < len(calls):
            call = calls[seen[0]]
            seen[0] += 1
            if ha.apply(call):
                for effect in controller.step(ha.observation(now()), desire, CFG):
                    if effect.kind == "publish":
                        sent.append(effect.payload)
                        rig.bridge.on_mqtt_message(
                            None,
                            None,
                            SimpleNamespace(
                                topic=effect.topic, payload=effect.payload.encode(), retain=False
                            ),
                        )

    drain()
    for effect in controller.step(ha.observation(now()), desire, CFG):
        if effect.kind == "publish":
            sent.append(effect.payload)
            rig.bridge.on_mqtt_message(
                None,
                None,
                SimpleNamespace(topic=effect.topic, payload=effect.payload.encode(), retain=False),
            )
    rig.clock.t += 5
    rig.session.request.side_effect = http
    rig.bridge.next_cloud = 0
    rig.bridge.tick()
    drain()
    rig.clock.t += 5
    for effect in controller.step(ha.observation(now()), desire, CFG):
        assert effect.kind != "publish", "unexpected second command"
    return sent


def background_poll(rig, cmd, setpoint=70):
    rig.session.request.side_effect = [status(cmd, setpoint)]
    rig.bridge.poll_status("TEST123")


def enabled_parked(rig, ha, seen):
    controller = ctl.Controller()
    start = datetime.fromtimestamp(rig.clock(), timezone.utc)
    controller.set_enabled(True, start - timedelta(hours=3))
    controller.last_transition_at = (start - timedelta(hours=3)).isoformat()
    controller.request_samples = [[(start - timedelta(hours=2)).isoformat(), 0]]
    controller.inspect_after = None
    background_poll(rig, 8)  # heater OFF, Cmd 8, 70 kept (T3)
    calls = rig.mqtt.publish.call_args_list
    for call in calls[seen[0] :]:
        ha.apply(call)
    seen[0] = len(calls)
    controller.step(ha.observation(start), ctl.Desire("hold", "x"), CFG)
    assert controller.state == ctl.PARKED, (
        controller.reason,
        ha.diag["last_command"],
        ha.status,
        ha.diag["last_successful_poll"],
        controller.intent,
    )
    return controller


def test_stale_resume_and_park_round_trip(rig):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60  # status now 20 minutes old: bridge must refresh
    sent = run(
        rig,
        controller,
        ha,
        ctl.Desire("permit", "solar"),
        [status(8), response(204), status(9)],
        seen,
    )
    assert sent == ["Manual:70"]
    assert controller.state == ctl.HEATING_PERMITTED, (controller.reason, ha.diag["last_command"])
    assert ha.diag["last_command"]["status_refresh"] == "refreshed"
    assert ha.diag["request_categories"]["command_refresh"] == 1
    rig.clock.t += 25 * 60
    background_poll(rig, 9)  # the ordinary 30-minute poll, no command
    rig.clock.t += 15 * 60  # status now 15 minutes old again
    sent = run(
        rig, controller, ha, ctl.Desire("park", "done"), [status(9), response(204), status(8)], seen
    )
    assert sent == ["off"]
    assert controller.state == ctl.PARKED, (
        controller.reason,
        ha.diag["last_command"],
        ha.status,
        ha.diag["last_successful_poll"],
        controller.intent,
    )
    posts = [c.args[1] for c in rig.session.request.call_args_list if c.args[0] == "POST"]
    assert [p.rsplit("/", 1)[-1] for p in posts] == ["login", "manual", "off"]


@pytest.mark.parametrize(
    "app_cmd,app_setpoint,expected",
    [
        (17, 70, "refused_mode_mismatch"),
        (8, 65, "refused_target_mismatch"),
        (9, 70, "already_in_requested_state"),
    ],
)
def test_owner_app_change_since_last_poll_pauses_control_without_a_write(
    rig, app_cmd, app_setpoint, expected
):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60
    sent = run(
        rig, controller, ha, ctl.Desire("permit", "solar"), [status(app_cmd, app_setpoint)], seen
    )
    assert sent == ["Manual:70"]
    assert ha.diag["last_command"]["result"] == expected
    assert controller.state == ctl.OWNER_OVERRIDE, controller.reason
    assert controller.reason == "mode_or_target_changed_outside_controller"
    assert not [c for c in rig.session.request.call_args_list if c.args[0] == "POST"][1:]


def test_refresh_failure_locks_controller_and_nothing_is_written(rig):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60
    sent = run(rig, controller, ha, ctl.Desire("permit", "solar"), [requests.Timeout()], seen)
    assert sent == ["Manual:70"]
    assert ha.diag["last_command"]["result"] == "refused_status_refresh_failed"
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "bridge_refused_or_dropped"
    # login, the background poll, then only the failed pre-command read
    assert [c.args[0] for c in rig.session.request.call_args_list] == ["POST", "GET", "GET"]


def test_fresh_status_needs_no_refresh(rig):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    sent = run(rig, controller, ha, ctl.Desire("permit", "solar"), [response(204), status(9)], seen)
    assert sent == ["Manual:70"] and controller.state == ctl.HEATING_PERMITTED, (
        controller.reason,
        ha.diag["last_command"],
        ha.status,
    )
    assert ha.diag["request_categories"]["command_refresh"] == 0


def follow(rig, controller, ha, desire, at, http, seen):
    """Let the bridge tick at ``at`` (epoch seconds) with ``http``; step the
    controller after every resulting message. Returns any controller publish."""
    now = lambda: datetime.fromtimestamp(rig.clock(), timezone.utc)  # noqa: E731
    sent = []
    rig.clock.t = at
    rig.session.request.side_effect = http
    rig.bridge.next_cloud = 0
    rig.bridge.tick()
    calls = rig.mqtt.publish.call_args_list
    while seen[0] < len(calls):
        call = calls[seen[0]]
        seen[0] += 1
        if ha.apply(call):
            for effect in controller.step(ha.observation(now()), desire, CFG):
                if effect.kind == "publish":
                    sent.append(effect.payload)
    for effect in controller.step(ha.observation(now()), desire, CFG):
        if effect.kind == "publish":
            sent.append(effect.payload)
    return sent


def http_posts(rig):
    return [
        c.args[1].rsplit("/", 1)[-1]
        for c in rig.session.request.call_args_list
        if c.args[0] == "POST"
    ]


@pytest.mark.parametrize("confirming_read", [1, 2])
def test_delayed_readback_old_mode_first_then_requested_mode(rig, confirming_read):
    """T3b: the read right after the POST still shows Manual; a later bounded
    follow-up shows OFF. One POST; the controller confirms only then."""
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60  # stale: the bridge reads status before the command
    sent = run(
        rig,
        controller,
        ha,
        ctl.Desire("permit", "solar"),
        [status(8), response(204), status(9)],
        seen,
    )
    assert sent == ["Manual:70"] and controller.state == ctl.HEATING_PERMITTED, (
        controller.reason,
        ha.diag["last_command"],
        ha.status,
    )
    rig.clock.t += 25 * 60
    background_poll(rig, 9)
    rig.clock.t += 15 * 60
    park = ctl.Desire("park", "done")
    sent = run(rig, controller, ha, park, [status(9), response(204), status(9)], seen)
    assert sent == ["off"]
    assert ha.diag["last_command"]["result"] == "awaiting_confirmation"
    assert controller.state == ctl.CONFIRMING and controller.fault is None
    posted = rig.bridge.pending["posted_at"]
    if confirming_read == 2:
        assert follow(rig, controller, ha, park, posted + 60, [status(9)], seen) == []
        assert ha.diag["last_command"]["result"] == "awaiting_confirmation"
        assert controller.state == ctl.CONFIRMING
    at = posted + (60, 300)[confirming_read - 1]
    assert follow(rig, controller, ha, park, at, [status(8)], seen) == []
    assert ha.diag["last_command"]["result"] == "observed_in_status"
    assert controller.state == ctl.PARKED, controller.reason
    assert http_posts(rig) == ["login", "manual", "off"]


def test_never_confirmed_locks_the_controller_once_and_nothing_is_resent(rig):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60  # stale: the bridge reads status before the command
    permit = ctl.Desire("permit", "solar")
    sent = run(rig, controller, ha, permit, [status(8), response(204), status(8)], seen)
    assert sent == ["Manual:70"] and controller.state == ctl.CONFIRMING
    posted = rig.bridge.pending["posted_at"]
    assert follow(rig, controller, ha, permit, posted + 60, [status(8)], seen) == []
    assert follow(rig, controller, ha, permit, posted + 300, [status(8)], seen) == []
    assert ha.diag["last_command"]["result"] == "not_confirmed_within_limit"
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "command_not_confirmed"
    for minutes in range(6, 60):  # background polls may fall due; never a command
        assert follow(rig, controller, ha, permit, posted + minutes * 60, [status(8)], seen) == []
    assert http_posts(rig) == ["login", "manual"]


def test_owner_change_during_confirmation_is_owner_override(rig):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60  # stale: the bridge reads status before the command
    permit = ctl.Desire("permit", "solar")
    run(rig, controller, ha, permit, [status(8), response(204), status(8)], seen)
    posted = rig.bridge.pending["posted_at"]
    follow(rig, controller, ha, permit, posted + 60, [status(17)], seen)  # app: Schedule
    assert ha.diag["last_command"]["result"] == "unexpected_state_after_command"
    assert controller.state == ctl.OWNER_OVERRIDE, controller.reason
    assert http_posts(rig) == ["login", "manual"]


def test_follow_up_timeout_then_confirmation_and_a_bridge_restart_never_resends(rig, tmp_path):
    ha, seen = HA(), [0]
    controller = enabled_parked(rig, ha, seen)
    rig.clock.t += 20 * 60  # stale: the bridge reads status before the command
    permit = ctl.Desire("permit", "solar")
    run(rig, controller, ha, permit, [status(8), response(204), status(8)], seen)
    posted = rig.bridge.pending["posted_at"]
    follow(rig, controller, ha, permit, posted + 60, [requests.Timeout()], seen)
    assert controller.state == ctl.CONFIRMING and controller.fault is None
    # Bridge restart (same /data): the pending command is reloaded, never re-sent.
    restarted = b.MyThermowattBridge(
        dict(rig.bridge.options),
        tmp_path,
        session=rig.session,
        mqtt_client=rig.mqtt,
        clock=rig.clock,
        monotonic=rig.clock,
    )
    restarted.mqtt_connected.set()
    restarted.proactive_refresh, restarted.immediate_confirmation_read = False, True
    assert restarted.pending is not None
    rig.bridge = restarted
    follow(
        rig,
        controller,
        ha,
        permit,
        posted + 120,
        [response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}), status(9)],
        seen,
    )
    assert ha.diag["last_command"]["result"] == "observed_in_status"
    assert controller.state == ctl.HEATING_PERMITTED, controller.reason
    assert http_posts(rig) == ["login", "manual"]
