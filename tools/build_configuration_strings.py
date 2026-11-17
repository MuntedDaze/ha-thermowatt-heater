"""Rebuild only HA configuration translations, without touching dashboard files."""

import argparse
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components/thermann_shadow"


def build():
    package = ModuleType("_configuration_strings")
    package.__path__ = [str(PACKAGE)]
    sys.modules[package.__name__] = package
    text = importlib.import_module(f"{package.__name__}.configuration_text")
    original = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    original["options"] = text.flow_text()
    presentation = importlib.import_module(f"{package.__name__}.presentation")
    sensors = original.setdefault("entity", {}).setdefault("sensor", {})
    for key, labels in presentation.STATE_LABELS.items():
        sensors.setdefault(key, {})["state"] = labels
    original["selector"] = {k: {"options": v} for k, v in text.SELECT_LABELS.items()}
    original["config"]["step"]["user"] = {
        "title": "Connect existing heater and meter readings",
        "description": "Unofficial community integration. Choose the five required bridge readings; all solar, forecast and circuit-meter fields are optional and may be left blank. Reads local Home Assistant states only, with no cloud access or heater commands during setup. Automatic control stays off. You can change these mappings later in Settings.",
        "data": {k: v[0] for k, v in text.SOURCES.items()},
        "data_description": {k: v[1] for k, v in text.SOURCES.items()},
    }
    return json.dumps(original, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = build()
    for target in (PACKAGE / "strings.json", PACKAGE / "translations/en.json"):
        if args.check:
            assert target.read_text(encoding="utf-8") == content, str(target)
        else:
            target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
