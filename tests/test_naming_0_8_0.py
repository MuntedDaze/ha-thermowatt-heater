"""0.8.0 display names: Thermann Controller, Thermann Hot Water, 12hr Override.

Only names change. The integration domain, app slug, MQTT topics, entity IDs
(existing AND fresh installs) and saved settings stay the same."""

import importlib
import json

import yaml

from test_shadow_model import ROOT, c, package

naming = importlib.import_module(f"{package.__name__}.naming")
settings = importlib.import_module(f"{package.__name__}.settings")
PACKAGE = ROOT / "custom_components/thermann_shadow"


def test_renamed_entities_keep_their_historical_ids():
    assert naming.entity_id("button", "Start 12hr Override") == (
        "button.thermann_shadow_start_guest_mode_12_h"
    )
    assert naming.entity_id("button", "Cancel 12hr Override") == (
        "button.thermann_shadow_cancel_guest_mode"
    )
    assert naming.entity_id("sensor", "12hr Override ends") == (
        "sensor.thermann_shadow_guest_mode_ends"
    )
    assert naming.entity_id("time", settings.CATALOG["evening_time"].name) == (
        "time.thermann_shadow_afternoon_comfort_preference"
    )
    # Unrenamed entities: the same ID the old "Thermann Shadow" device produced.
    assert naming.entity_id("switch", "Automatic heater control") == (
        "switch.thermann_shadow_automatic_heater_control"
    )
    assert naming.entity_id("button", "Hold heater (owner override)") == (
        "button.thermann_shadow_hold_heater_owner_override"
    )


def test_display_names_and_unofficial_labels():
    fields = naming.device_info_fields(c.DOMAIN, "entry")
    assert fields["identifiers"] == {("thermann_shadow", "entry")}  # same device identity
    assert fields["name"] == "Thermann Controller"
    assert "Unofficial" in fields["manufacturer"]
    assert "not a Thermann product" in fields["manufacturer"]
    assert c.DOMAIN == "thermann_shadow"
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "thermann_shadow" and manifest["name"] == "Thermann Controller"
    strings = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    assert strings["title"] == "Thermann Controller"
    assert "Unofficial" in strings["config"]["step"]["user"]["description"]
    app = yaml.safe_load((ROOT / "thermowatt-heater/config.yaml").read_text(encoding="utf-8"))
    assert app["name"] == "Thermann Hot Water" and app["slug"] == "thermowatt_boiler"
    assert "Unofficial" in app["description"]
    for source in PACKAGE.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert 'name="Thermann Shadow"' not in text, source
        if source.name != "naming.py":
            assert "Start guest mode (12 h)" not in text, source


def test_dashboard_uses_the_same_entity_ids_as_the_integration():
    spec = importlib.util.spec_from_file_location(
        "dashboard_naming", ROOT / "tools/build_shadow_dashboard.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for key, meta in settings.CATALOG.items():
        assert builder.entity(key) == naming.entity_id(meta.kind, meta.name), key
    dashboard = builder.build()
    assert dashboard["title"] == "Hot Water"
    assert dashboard["views"][0]["title"] == "Hot Water"
