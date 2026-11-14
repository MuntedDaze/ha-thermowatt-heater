"""Closed four-state protocol: synthetic MQTT/HTTP and credentials only."""

from itertools import permutations
import json
import pytest

from conftest import response
from test_bridge_1_3_13 import commanded, posts
from test_cloud_and_commands import last_command
from test_command_refresh_1_3_10 import SERIAL, body, calls, set_status

STATES = ("off", 45, 62, 70)
PAIRS = list(permutations(STATES, 2))


def payload(target, prior):
    return f"{'off' if target == 'off' else f'Manual:{target}'}@{prior}"


def test_advertised_protocol_is_exactly_the_closed_twelve_transitions(factory):
    bridge = commanded(factory)
    bridge.publish_diagnostics(force=True)
    data = json.loads(
        [
            c.args[1]
            for c in bridge.mqtt_client.publish.call_args_list
            if "DIAGNOSTICS" in c.args[0]
        ][-1]
    )
    assert set(data["command_transitions"]) == {payload(t, p) for t, p in PAIRS}


@pytest.mark.parametrize("target,prior", PAIRS)
def test_all_twelve_exact_transitions_post_once_and_confirm(factory, clock, target, prior):
    bridge = commanded(factory)
    set_status(bridge, 8 if prior == "off" else 9, 70 if prior == "off" else prior)
    bridge.session.request.side_effect = [response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", payload(target, prior)))
    assert posts(bridge) == [("POST", "off" if target == "off" else "manual")]
    clock.advance(60)
    bridge.session.request.side_effect = [
        body(
            {
                "Cmd": "8" if target == "off" else "9",
                "T_SetPoint": str(70 if target == "off" else target),
                "T_Avg": "52",
                "WaterHeaterSts": "32",
            }
        )
    ]
    bridge.tick()
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


@pytest.mark.parametrize("target,prior", PAIRS)
def test_owner_changed_prior_is_never_overwritten(factory, clock, target, prior):
    bridge = commanded(factory)
    set_status(bridge, 17, 55)  # owner Schedule, never a controller-owned state
    bridge.process_command((clock(), SERIAL, "MODE", payload(target, prior)))
    assert calls(bridge) == [] and bridge.pending is None


@pytest.mark.parametrize(
    "value",
    [
        "Manual:61@off",
        "Manual:62.0@off",
        "Manual:62@62",
        "Manual:62@55",
        "Manual:63@62",
        "off@61",
        "Manual:62",
        "Manual:062@off",
        "Manual:62@Off",
    ],
)
def test_unsupported_spelling_or_setpoint_never_contacts_cloud(factory, clock, value):
    bridge = commanded(factory)
    set_status(bridge, 8, 70)
    bridge.process_command((clock(), SERIAL, "MODE", value))
    assert calls(bridge) == []
