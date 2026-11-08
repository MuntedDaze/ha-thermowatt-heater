"""Run inside the official Supervisor image, without starting its daemon."""

from copy import deepcopy
import json
from pathlib import Path

from supervisor.apps.options import AppOptions
from supervisor.apps.validate import SCHEMA_APP_CONFIG
from supervisor.const import SUPERVISOR_VERSION
import voluptuous as vol

raw = json.loads(Path("/app-config.json").read_text())
validated = SCHEMA_APP_CONFIG(deepcopy(raw))
assert not raw.keys() - validated.keys(), "Supervisor silently removed an unknown config key"
assert set(validated["arch"]) == {"amd64", "aarch64"}
assert validated["services"] == ["mqtt:need"]
assert validated["init"] is False
assert not validated["host_network"]
assert not validated["docker_api"]
assert not validated["full_access"]
options = AppOptions(None, validated["schema"], validated["name"], validated["slug"])
assert options.validate(deepcopy(raw["options"])) == raw["options"]
for change in (
    {"auth_retry_generation": -1},
    {"cloud_enabled": "not-a-boolean"},
    {"password": 123},
):
    try:
        options.validate({**raw["options"], **change})
    except vol.Invalid:
        continue
    raise AssertionError("Supervisor accepted an invalid synthetic option")
print(
    json.dumps(
        {
            "supervisor": SUPERVISOR_VERSION,
            "config": "PASS",
            "options": "PASS",
            "mqtt_dependency_declaration": "PASS",
            "network": "none",
            "supervisor_daemon_started": False,
        }
    )
)
