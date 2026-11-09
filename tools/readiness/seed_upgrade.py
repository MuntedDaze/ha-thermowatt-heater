"""Seed a disposable CI volume with released 1.3.2/1.3.3 synthetic data only."""

import json
from pathlib import Path
import sys

sys.path.insert(0, "/")
from thermowatt_bridge import atomic_json  # noqa: E402

snapshot = json.loads(Path("/upgrade.json").read_text())
assert snapshot["source_version"] in {"1.3.2", "1.3.3", "1.3.6"}
assert snapshot["options"]["cloud_enabled"] is False
assert snapshot["options"]["commands_enabled"] is False
assert sys.argv[1] in {"authorized", "authorized_refresh", "blocked", "blocked_refresh"}
for name, value in {
    "options.json": snapshot["options"],
    "thermowatt_config.json": snapshot["metadata"],
    "auth_state.json": snapshot["auth_states"][sys.argv[1]],
}.items():
    atomic_json(Path("/data") / name, value)
