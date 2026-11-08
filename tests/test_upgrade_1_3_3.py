"""Read real 1.3.2-format synthetic state with 1.3.3; all HTTP remains prohibited."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml

FIXTURE = Path(__file__).parent / "fixtures/upgrade_1_3_2.json"


def snapshot():
    return json.loads(FIXTURE.read_text())


def test_upgrade_config_only_changes_version_and_attention_marker():
    old = snapshot()["addon_config"]
    new = yaml.safe_load((FIXTURE.parents[2] / "thermowatt-heater/config.yaml").read_text())
    assert old["version"] == "1.3.2" and new["version"] == "1.3.3"
    assert set(old["breaking_versions"]) <= set(new["breaking_versions"])
    assert "1.3.3" in new["breaking_versions"]
    for key in ("version", "breaking_versions"):
        old.pop(key)
        new.pop(key)
    # Includes slug, schema, option defaults, architecture, boot and dependencies.
    assert new == old


@pytest.mark.parametrize(
    "cloud,commands", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("state_name", ["authorized", "blocked", "retry", "in_flight"])
def test_persistent_upgrade_keeps_options_tokens_guard_and_entity_ids(
    module, tmp_path, cloud, commands, state_name
):
    old = snapshot()
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
    if state_name == "authorized":
        assert bridge.login() is True  # Reuse state without another password request.
    elif state_name in {"blocked", "in_flight"}:
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
    assert len(ids) == len(old["mqtt_ids"]) + 1  # Only the already-reviewed vendor-mode sensor.
