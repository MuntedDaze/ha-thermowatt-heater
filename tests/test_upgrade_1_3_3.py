"""Read released 1.3.2/1.3.3 synthetic state with 1.3.6; HTTP is always mocked."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml

from conftest import STATUS, TOKENS, response

FIXTURE = Path(__file__).parent / "fixtures/upgrade_1_3_2.json"


def snapshot(version="1.3.2"):
    path = FIXTURE.with_name(f"upgrade_{version.replace('.', '_')}.json")
    return json.loads(path.read_text())


@pytest.mark.parametrize("source_version", ["1.3.2", "1.3.3", "1.3.6"])
def test_upgrade_config_only_adds_poll_interval_version_and_attention_marker(source_version):
    old = snapshot(source_version)["addon_config"]
    new = yaml.safe_load((FIXTURE.parents[2] / "thermowatt-heater/config.yaml").read_text())
    assert old["version"] == source_version and new["version"] == "1.3.9"
    assert set(old["breaking_versions"]) <= set(new["breaking_versions"])
    assert {"1.3.8", "1.3.9"} <= set(new["breaking_versions"])
    assert new["options"].pop("command_policy") == "automation"
    assert new["schema"].pop("command_policy") == "list(automation|legacy)"
    assert new["options"].pop("on_demand_refresh_enabled") is False
    assert new["schema"].pop("on_demand_refresh_enabled") == "bool"
    assert new["options"].pop("poll_interval_minutes") == 30
    assert new["schema"].pop("poll_interval_minutes") == "int(1,7200)"
    assert new["options"].pop("poll_interval_unit") == "minutes"
    assert new["schema"].pop("poll_interval_unit") == "list(seconds|minutes)"
    assert new["options"].pop("min_cloud_retry_minutes") == 60
    assert new["schema"].pop("min_cloud_retry_minutes") == "int(5,1440)"
    if source_version == "1.3.6":
        assert old["options"].pop("poll_interval_minutes") == 30
        assert old["schema"].pop("poll_interval_minutes") == "int(5,120)"
        assert old["options"].pop("min_cloud_retry_minutes") == 60
        assert old["schema"].pop("min_cloud_retry_minutes") == "int(5,1440)"
    for key in ("version", "breaking_versions"):
        old.pop(key)
        new.pop(key)
    # Includes slug, schema, option defaults, architecture, boot and dependencies.
    assert new == old


@pytest.mark.parametrize(
    "cloud,commands", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize(
    "source_version,state_name",
    [
        (version, state)
        for version in ("1.3.2", "1.3.3", "1.3.6")
        for state in ("authorized", "blocked", "retry", "in_flight")
    ]
    + [
        (version, state)
        for version in ("1.3.3", "1.3.6")
        for state in ("authorized_refresh", "blocked_refresh")
    ],
)
def test_persistent_upgrade_keeps_options_tokens_guard_and_entity_ids(
    module, tmp_path, cloud, commands, source_version, state_name
):
    old = snapshot(source_version)
    options = {**old["options"], "cloud_enabled": cloud, "commands_enabled": commands}
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps(options))
    original_options = options_path.read_bytes()
    (tmp_path / "thermowatt_config.json").write_text(json.dumps(old["metadata"]))
    original_guard = deepcopy(old["auth_states"][state_name])
    (tmp_path / "auth_state.json").write_text(json.dumps(original_guard))
    session = Mock(spec=requests.Session)
    session.request.side_effect = AssertionError("Upgrade cannot contact cloud")
    bridge = module.MyThermowattBridge(
        module.load_options(options_path),
        tmp_path,
        session=session,
        mqtt_client=Mock(),
        clock=lambda: 1000,
    )
    assert bridge.options == options
    assert bridge.poll_interval == options.get("poll_interval_minutes", 30) * 60
    assert bridge.min_cloud_retry == options.get("min_cloud_retry_minutes", 60) * 60
    assert options_path.read_bytes() == original_options
    assert bridge.config == old["metadata"]
    expected_guard = deepcopy(original_guard)
    if state_name == "in_flight":
        # An interrupted auth must stay fail-closed, not restart that attempt.
        expected_guard.update(
            mode="blocked", reason="interrupted_auth", access_token=None, refresh_token=None
        )
    assert bridge.guard.state == expected_guard
    assert json.loads((tmp_path / "auth_state.json").read_text()) == expected_guard
    assert bridge.guard.state["generation"] == options["auth_retry_generation"]
    if state_name.startswith("authorized"):
        assert bridge.login() is True  # Reuse state without another password request.
    elif state_name.startswith("blocked") or state_name == "in_flight":
        with pytest.raises(module.AuthBlocked):
            bridge.login()
    else:
        with pytest.raises(
            module.CloudError, match="auth_retry_wait" if cloud else "cloud_disabled"
        ):
            bridge.login()
    session.request.assert_not_called()
    bridge.publish_discovery("SYNTHETIC123", "Synthetic heater")
    ids = {
        call.args[0]: json.loads(call.args[1])["unique_id"]
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0].endswith("/config")
    }
    assert {topic: ids[topic] for topic in old["mqtt_ids"]} == old["mqtt_ids"]
    # No added entity since 1.3.3; only its already-reviewed vendor sensor since 1.3.2.
    assert len(ids) == len(old["mqtt_ids"]) + (source_version == "1.3.2") + 5


@pytest.mark.parametrize("state_name", ["authorized", "authorized_refresh"])
def test_legacy_authorized_session_can_read_and_refresh_without_password_login(
    factory, tmp_path, clock, state_name
):
    old = snapshot("1.3.3")
    (tmp_path / "auth_state.json").write_text(json.dumps(old["auth_states"][state_name]))
    (tmp_path / "thermowatt_config.json").write_text(json.dumps(old["metadata"]))
    bridge = factory(**{**old["options"], "cloud_enabled": True})
    assert bridge.guard.state["next_retry"] == 0  # No cooldown invented at upgrade.
    bridge.login()
    bridge.session.request.assert_not_called()
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.poll_status("SYNTHETIC123")
    assert bridge.guard.state == old["auth_states"][state_name]
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("SYNTHETIC123")
    assert bridge.guard.state["next_retry"] == clock() + 300
    assert bridge.guard.state["generation"] == old["options"]["auth_retry_generation"]
    assert not any(c.args[1].endswith("/login") for c in bridge.session.request.call_args_list)


def test_existing_authorized_cooldown_and_cloud_lockout_records_survive_restart(
    factory, tmp_path, clock, module
):
    old = snapshot("1.3.3")
    cooldown = {**old["auth_states"]["authorized_refresh"], "next_retry": clock() + 300}
    (tmp_path / "auth_state.json").write_text(json.dumps(cooldown))
    (tmp_path / "thermowatt_config.json").write_text(json.dumps(old["metadata"]))
    options = {**old["options"], "cloud_enabled": True}
    bridge = factory(**options)
    assert bridge.guard.state == cooldown
    bridge.login()
    bridge.session.request.assert_not_called()
    bridge.session.request.side_effect = [response(body=STATUS), response(401)]
    bridge.poll_status("SYNTHETIC123")
    assert bridge.guard.state == cooldown  # Normal reads do not consume/extend the deadline.
    with pytest.raises(module.AuthBlocked, match="cloud_refresh_cooldown"):
        bridge.poll_status("SYNTHETIC123")
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)
    locked = deepcopy(bridge.guard.state)
    assert locked["reason"] == "cloud_http_401"
    clock.advance(600)
    restart = factory(**options)
    assert restart.guard.state == locked  # Expired cooldown never unlocks blocked state.
    restart.tick()
    restart.session.request.assert_not_called()
