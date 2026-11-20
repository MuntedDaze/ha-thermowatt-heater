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
    {"cloud_polling": "existing"},
    {"cloud_polling": "minimum"},
    {"cloud_polling": True},
    {"on_demand_refresh_enabled": "not-a-boolean"},
    {"min_cloud_retry_minutes": 4},
    {"min_cloud_retry_minutes": 1441},
    {"min_cloud_retry_minutes": "not-a-number"},
):
    try:
        options.validate({**raw["options"], **change})
    except vol.Invalid:
        continue
    raise AssertionError("Supervisor accepted an invalid synthetic option")
# 1.5.0 update path: options saved by 1.4.1 contain keys that no longer exist.
# Supervisor must accept them and drop the unknown keys (the add-on then sees
# only the new schema), never refuse to start the updated app.
saved_1_4_1 = {
    **{key: value for key, value in raw["options"].items() if key != "cloud_polling"},
    "polling_mode": "existing",
    "poll_interval_minutes": 15,
    "poll_interval_unit": "minutes",
    "adaptive_polling_enabled": False,
    "adaptive_polling_qualified": False,
    "event_aware_polling_qualified": False,
}
updated = options.validate({**raw["options"], **saved_1_4_1})
assert updated["cloud_polling"] == "smart", updated
assert not set(updated) - set(raw["options"]), "removed 1.4.1 options were not dropped"
print(
    json.dumps(
        {
            "supervisor": SUPERVISOR_VERSION,
            "config": "PASS",
            "options": "PASS",
            "update_from_1_4_1_options": "PASS",
            "mqtt_dependency_declaration": "PASS",
            "network": "none",
            "supervisor_daemon_started": False,
        }
    )
)
