"""Packaged-image demand worker smoke; network none, synthetic services only."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, "/")
import requests  # noqa: E402
from thermowatt_bridge import MyThermowattBridge  # noqa: E402


def forbidden(*args, **kwargs):
    raise AssertionError("Unmocked HTTP/socket prohibited")


requests.Session.request = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden


def response(body):
    result = Mock(spec=requests.Response)
    result.status_code = 200
    result.json.return_value = body
    return result


clock = SimpleNamespace(now=1000)
options = {
    "email": "synthetic@example.invalid",
    "password": "SYNTHETIC_PASSWORD",
    "cloud_enabled": True,
    "commands_enabled": False,
    "auth_retry_generation": 1,
    "on_demand_refresh_enabled": True,
}
status = {"result": {"T_Avg": "48", "T_SetPoint": "60", "Cmd": "17", "WaterHeaterSts": "1"}}
with tempfile.TemporaryDirectory(dir=os.environ.get("THERMOWATT_SMOKE_TMP")) as directory:
    session = Mock(spec=requests.Session)
    bridge = MyThermowattBridge(
        options,
        Path(directory),
        session=session,
        mqtt_client=Mock(),
        clock=lambda: clock.now,
        monotonic=lambda: clock.now,
    )
    bridge.guard.success("SYNTHETIC_ACCESS", "SYNTHETIC_REFRESH")  # Local seed, never auth.
    bridge.config["devices"] = {"TEST123": {"name": "Synthetic heater"}}
    bridge.active_devices = {"TEST123"}
    bridge.discovered = True
    bridge.mqtt_connected.set()
    session.request.side_effect = [response(status)]
    bridge.tick()
    clock.now += 300
    message = SimpleNamespace(topic="P/TEST123/refresh", payload=b"refresh", retain=False)
    for _ in range(100):
        bridge.on_mqtt_message(None, None, message)
    assert session.request.call_count == 1 and len(bridge.refresh_requested) == 1
    session.request.side_effect = [response(status)]
    bridge.tick()
    assert session.request.call_count == 2
    assert bridge.next_poll == clock.now + 1800
    clock.now += 300
    bridge.on_mqtt_message(None, None, message)
    session.request.side_effect = [
        response({"success": False, "error": "Daily request limit exceeded"})
    ]
    bridge.tick()
    assert session.request.call_count == 3 and bridge.cloud_health == "quota_limited"
    restart_session = Mock(spec=requests.Session)
    restart_session.request.side_effect = forbidden
    restart = MyThermowattBridge(
        options,
        Path(directory),
        session=restart_session,
        mqtt_client=Mock(),
        clock=lambda: clock.now,
    )
    restart.mqtt_connected.set()
    restart.on_mqtt_message(None, None, message)
    restart.tick()
    restart_session.request.assert_not_called()
    assert restart.next_cloud == clock.now + 3600
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert bridge.usage.counts["command"] == bridge.usage.counts["confirmation"] == 0
print(
    json.dumps(
        {
            "status": "PASS",
            "coalesced_read": "PASS",
            "quota_restart_barrier": "PASS",
            "mock_http_attempts": 3,
            "live_http_attempts": 0,
            "heater_commands": 0,
        }
    )
)
