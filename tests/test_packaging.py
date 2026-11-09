import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
ADDON = ROOT / "thermowatt-heater"


def test_supervisor_options_and_release_metadata(module):
    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    assert config["version"] == "1.3.5"
    # Diagnostic-only release: retain attention markers without adding a new one.
    assert config["breaking_versions"] == ["1.3.2", "1.3.3", "1.3.4"]
    assert set(config["arch"]) == {"amd64", "aarch64"}
    assert config["init"] is False
    assert config["boot"] == "manual"
    assert config["services"] == ["mqtt:need"]
    assert "mqtt" not in config
    assert set(config["options"]) == set(config["schema"])
    assert config["options"]["cloud_enabled"] is False
    assert config["options"]["commands_enabled"] is False
    assert config["options"]["auth_retry_generation"] == 0
    assert config["schema"]["password"] == "password"
    assert "## [1.3.5]" in (ADDON / "CHANGELOG.md").read_text()
    assert (ADDON / "CHANGELOG.md").read_bytes() == (ROOT / "CHANGELOG.md").read_bytes()


def test_entrypoint_no_command_line_credentials_or_unused_keys():
    run = (ADDON / "run.sh").read_text()
    assert "bashio::config" not in run
    assert '"$PASSWORD"' not in run
    assert "exec /opt/venv/bin/python3 -u /thermowatt_bridge.py" in run
    assert b"\r" not in (ADDON / "run.sh").read_bytes()
    dockerfile = (ADDON / "Dockerfile").read_text()
    assert "ca-certificates" in dockerfile
    for name in ("client.key", "client.crt", "root.pem"):
        assert not (ADDON / name).exists()
        assert name not in dockerfile


@pytest.mark.parametrize(
    "options",
    [
        [],
        None,
        {"password": 123},
        {"email": []},
        {"cloud_enabled": "true"},
        {"commands_enabled": 1},
        {"auth_retry_generation": -1},
        {"auth_retry_generation": True},
    ],
)
def test_invalid_options_fail_before_network(module, tmp_path, options):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    with pytest.raises(ValueError):
        module.load_options(path)


def test_real_mqtt_client_uses_v5_and_initialises_without_network(module, tmp_path):
    bridge = module.MyThermowattBridge({}, tmp_path)
    assert bridge.mqtt_client.protocol == module.mqtt.MQTTv5
    assert bridge.session.get_adapter("https://").max_retries.total == 0
    assert bridge.session.trust_env is False
    bridge.session.close()


def test_atomic_state_permissions_on_linux(module, tmp_path):
    path = tmp_path / "private.json"
    module.atomic_json(path, {"synthetic": True})
    assert json.loads(path.read_text()) == {"synthetic": True}
    if module.os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]
