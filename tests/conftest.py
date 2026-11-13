"""All tests are offline. An unmocked socket or HTTP request is a test failure."""

import importlib.util
from pathlib import Path
import socket
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parents[1] / "thermowatt-heater"))
SPEC = importlib.util.spec_from_file_location(
    "thermowatt_bridge", Path(__file__).parents[1] / "thermowatt-heater/thermowatt_bridge.py"
)
bridge_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge_module
SPEC.loader.exec_module(bridge_module)


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    monkeypatch.setattr(bridge_module.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")

    def denied(*args, **kwargs):
        raise AssertionError("Unmocked network access prohibited")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(requests.Session, "request", denied)


@pytest.fixture
def module():
    return bridge_module


@pytest.fixture
def clock():
    class Clock:
        now = 1_728_000_000  # a whole number of days: clock-aligned polls (1.3.13) line up

        def __call__(self):
            return self.now

        def advance(self, seconds=600):
            self.now += seconds

    return Clock()


@pytest.fixture
def factory(tmp_path, clock):
    def create(proactive_refresh=False, legacy_confirmation=True, **overrides):
        options = {
            "email": "synthetic@example.invalid",
            "password": "SYNTHETIC_PASSWORD",
            "cloud_enabled": True,
            "commands_enabled": False,
            "auth_retry_generation": 1,
        }
        options.update(overrides)
        session = Mock(spec=requests.Session)
        session.request.side_effect = AssertionError("Unexpected cloud request")
        bridge = bridge_module.MyThermowattBridge(
            options, tmp_path, session=session, mqtt_client=Mock(), clock=clock, monotonic=clock
        )
        bridge.mqtt_connected.set()
        # Tests written before 1.3.13 script exact request sequences around a
        # reactive 401 refresh. Proactive refresh is tested on its own
        # (test_bridge_1_3_13.py) with the real threshold.
        if not proactive_refresh:
            bridge.proactive_refresh = False
        # Likewise their scripted immediate confirmation read (removed in 1.3.13).
        bridge.immediate_confirmation_read = legacy_confirmation
        return bridge

    return create


def response(status=200, body=None):
    value = Mock(spec=requests.Response)
    value.status_code = status
    if isinstance(body, Exception):
        value.json.side_effect = body
    else:
        value.json.return_value = body
    return value


TOKENS = {"result": {"accessToken": "SYNTHETIC_ACCESS", "refreshToken": "SYNTHETIC_REFRESH"}}
STATUS = {"result": {"T_Avg": "48", "T_SetPoint": "60", "Cmd": "9", "WaterHeaterSts": "1"}}


def authenticate(bridge):
    bridge.session.request.side_effect = [response(body=TOKENS)]
    bridge.login()
    bridge.session.request.reset_mock(side_effect=True)
    bridge.session.request.side_effect = AssertionError("Unexpected cloud request")
