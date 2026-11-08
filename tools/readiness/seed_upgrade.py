"""Seed a disposable CI volume with authentic 1.3.2-format synthetic data only."""

import json
from pathlib import Path
import sys

sys.path.insert(0, "/")
from thermowatt_bridge import atomic_json  # noqa: E402

snapshot = json.loads(Path("/upgrade.json").read_text())
assert snapshot["source_version"] == "1.3.2"
assert snapshot["options"]["cloud_enabled"] is False
assert snapshot["options"]["commands_enabled"] is False
assert sys.argv[1] in {"authorized", "blocked"}
for name, value in {
    "options.json": snapshot["options"],
    "thermowatt_config.json": snapshot["metadata"],
    "auth_state.json": snapshot["auth_states"][sys.argv[1]],
}.items():
    atomic_json(Path("/data") / name, value)
