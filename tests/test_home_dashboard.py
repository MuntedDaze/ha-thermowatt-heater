"""The unified Home dashboard: structure, entities, safety of every action, and energy templates."""

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from energy_template_shim import render  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "build_home_dashboard", ROOT / "tools/build_home_dashboard.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

MODE = "sensor.thermann_shadow_hot_water_operating_mode"
START = "button.thermann_shadow_start_guest_mode_12_h"
CANCEL = "button.thermann_shadow_cancel_guest_mode"
NOW = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def walk(node):
    """Every dict in a nested structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


@pytest.fixture(scope="module")
def home():
    data, ent = build.build_dashboard(custom=True)
    return data, ent


@pytest.fixture(scope="module")
def native():
    return build.build_dashboard(custom=False)


def view(data, path):
    return next(v for v in data["views"] if v["path"] == path)


# ------------------------------------------------------------------ reproducible + valid
def test_generated_files_are_current():
    rendered = build.render_all()
    for key, content in rendered.items():
        assert build.OUTPUTS[key].read_text(encoding="utf-8") == content, key


def test_outputs_are_valid_yaml_with_the_required_views(home):
    for key in ("home", "native", "package"):
        assert yaml.safe_load(build.OUTPUTS[key].read_text(encoding="utf-8"))
    data, _ = home
    assert [v["path"] for v in data["views"]] == [
        "home",
        "energy",
        "hot-water",
        "bathrooms",
        "doors",
        "system",
    ]


def test_every_card_is_a_supported_lovelace_card(home):
    supported = {
        "grid",
        "heading",
        "markdown",
        "tile",
        "entities",
        "button",
        "conditional",
        "vertical-stack",
        "weather-forecast",
        "history-graph",
        "statistic",
        "custom:thermowatt-power-flow-card",
    }
    data, _ = home
    for item in walk(data):
        if item.get("type") and "cards" in item or item.get("type") in supported:
            assert item["type"] in supported | {"sections"} or item["type"] == "grid"
    for item in walk(data):
        if item.get("type") == "conditional":
            assert item["conditions"] and item["card"]["type"]
        if item.get("type") == "tile":
            assert item["entity"]


def test_layout_is_responsive_by_construction(home):
    data, _ = home
    for v in data["views"]:
        assert v["type"] == "sections" and 1 <= v["max_columns"] <= 3
    text = build.OUTPUTS["home"].read_text(encoding="utf-8")
    assert "px" not in text.replace("hours_to_show", "")  # no fixed pixel widths in the dashboard
    for item in walk(data):
        if item.get("type") == "grid" and "columns" in item:
            assert item["columns"] <= 2  # phone-friendly


# ------------------------------------------------------------------ entities exist
def test_thermowatt_entities_are_real_entity_names(home):
    _, ent = home
    source = "".join(
        (ROOT / "custom_components/thermann_shadow" / f).read_text(encoding="utf-8")
        for f in ("sensor.py", "button.py", "switch.py")
    )
    for eid, name in ent.thermowatt_names.items():
        assert f'"{name}"' in source, (eid, name)
    assert START in ent.used and CANCEL in ent.used and MODE in ent.used


def test_tapo_entities_exist_in_the_published_contract(home, native):
    contract = json.loads(build.TAPO_CONTRACT.read_text(encoding="utf-8"))["entities"]
    for _, ent in (home, native):
        for eid, source in ent.used.items():
            if source == "tapo_smart_controller":
                assert eid in contract, eid


def test_both_bathrooms_use_identical_cards(home):
    data, _ = home
    cards = [
        c
        for c in walk(view(data, "home"))
        if c.get("type") == "vertical-stack"
        and c["cards"][0].get("type") == "heading"
        and c["cards"][0]["heading"] in ("Main Bathroom", "Ensuite")
    ]
    assert len(cards) == 2

    def shape(card):
        text = json.dumps(card).replace("main_bathroom", "X").replace("ensuite", "X")
        return text.replace("Main Bathroom", "N").replace("Ensuite", "N")

    assert shape(cards[0]) == shape(cards[1])


# ------------------------------------------------------------------ safety of actions
def actions(data):
    for item in walk(data):
        for key in ("tap_action", "icon_tap_action", "hold_action"):
            if key in item:
                yield item[key]


def test_no_garage_or_lock_controls_exist(home, native):
    for data, ent in (home, native):
        text = json.dumps(data).lower()
        for forbidden in (
            "open_cover",
            "close_cover",
            "stop_cover",
            "cover.",
            "lock.lock",
            "lock.unlock",
            "lock.open",
        ):
            assert forbidden not in text
        for eid in ent.used:
            assert not eid.startswith(("cover.", "lock."))
        for action in actions(data):
            target = json.dumps(action.get("target", {}))
            assert "garage" not in target and "door" not in target


def test_only_whitelisted_actions_exist(home):
    data, _ = home
    allowed_buttons = {
        START,
        CANCEL,
        "button.thermann_shadow_hold_heater_owner_override",
        "button.thermann_shadow_resume_automatic_control",
    }
    for action in actions(data):
        kind = action["action"]
        if kind in ("more-info", "none", "navigate"):
            continue
        assert kind == "perform-action"
        service, target = action["perform_action"], action["target"]["entity_id"]
        if service == "button.press":
            assert target in allowed_buttons
        elif service in ("switch.turn_on", "switch.turn_off"):
            assert target.startswith("switch.tapo_smart_controller_")
            assert target.endswith("_manual_override")
        else:
            assert service == "light.toggle"


def test_hot_water_override_toggle_is_state_driven_and_confirmed(home):
    data, _ = home
    card = next(
        c
        for c in walk(view(data, "home"))
        if c.get("type") == "vertical-stack" and c["cards"][0].get("heading") == "Hot water"
    )
    branches = [c for c in card["cards"] if c["type"] == "conditional"]
    on, off, unknown = branches
    assert on["conditions"] == [{"condition": "state", "entity": MODE, "state": "guest"}]
    assert on["card"]["color"] == "blue"
    assert on["card"]["tap_action"]["target"]["entity_id"] == CANCEL  # ON -> cancel
    assert off["card"]["color"] == "grey"
    assert (
        off["card"]["tap_action"]["target"]["entity_id"] == START
    )  # OFF -> existing 12 h override
    assert {c["state_not"] for c in off["conditions"]} == {"guest", "unavailable", "unknown"}
    assert (
        "confirmation" in on["card"]["tap_action"] and "confirmation" in off["card"]["tap_action"]
    )
    assert unknown["card"]["tap_action"] == {"action": "more-info"}  # unknown status: no command
    assert unknown["card"]["color"] == "grey"


def test_toggle_state_reflects_actual_physical_state_not_the_request(home):
    data, _ = home
    stacks = [
        c
        for c in walk(view(data, "home"))
        if c.get("type") == "vertical-stack" and c["cards"][0].get("heading") == "Main Bathroom"
    ]
    cards = stacks[0]["cards"]
    pairs = [c for c in cards if c["type"] == "conditional"]
    assert len(pairs) == 4
    fan_cancel, fan_request, towel_cancel, towel_request = pairs
    # Tile entity = actual state (binary_sensor), the switch only decides what a tap does.
    assert fan_cancel["card"]["entity"].startswith("binary_sensor.") and fan_cancel["card"][
        "entity"
    ].endswith("_fan_running")
    assert towel_cancel["card"]["entity"].endswith("_towel_rail_heating")
    assert fan_cancel["conditions"][0]["state"] == "on"
    assert fan_cancel["card"]["tap_action"]["perform_action"] == "switch.turn_off"
    assert fan_request["card"]["tap_action"]["perform_action"] == "switch.turn_on"
    assert towel_request["card"]["tap_action"]["confirmation"][
        "text"
    ]  # starting heating is confirmed
    assert towel_cancel["card"]["state_content"] == "summary"  # queued / waiting / remaining shown


# ------------------------------------------------------------------ mappings (nothing invented)
def test_unmapped_weather_and_lights_become_mapping_notes_not_broken_cards(home):
    data, ent = home
    text = json.dumps(data)
    assert "weather-forecast" not in text and "light.toggle" not in text
    assert text.count("mapping needed") == 3
    assert sorted(set(ent.unresolved)) == ["lights.dining_room", "lights.living_room", "weather"]


def test_mapped_weather_and_lights_produce_real_cards(monkeypatch):
    mapping = build.load_mapping()
    mapping["weather"]["entity"] = "weather.rokeby"
    mapping["lights"]["dining_room"]["entity"] = "light.dining"
    mapping["lights"]["living_room"]["entity"] = "light.living"
    monkeypatch.setattr(build, "load_mapping", lambda: mapping)
    data, ent = build.build_dashboard(custom=True)
    text = json.dumps(data)
    assert "weather.rokeby" in text and text.count("light.toggle") >= 2
    assert "mapping needed" not in text
    assert {"weather.rokeby", "light.dining", "light.living"} <= set(ent.used)
    weather = next(c for c in walk(data) if c.get("type") == "weather-forecast")
    assert (
        weather["forecast_type"] == "daily" and weather["show_current"] and weather["show_forecast"]
    )


def test_power_flow_uses_verified_measured_entities_and_native_fallback_has_no_custom_card(
    home, native
):
    data, _ = home
    card = next(c for c in walk(data) if c.get("type") == "custom:thermowatt-power-flow-card")
    assert card["solar_entity"] == "sensor.goodwe_inverter_pv_power"
    assert card["house_entity"] == "sensor.goodwe_inverter_house_consumption"
    assert card["grid_entity"] == "sensor.goodwe_inverter_meter_active_power"
    assert card["grid_export_positive"] is True
    assert "custom:" not in json.dumps(native[0])
    assert "em_" not in json.dumps(data)  # no dependency on the optional energy package


# ------------------------------------------------------------------ energy package templates
def package_templates():
    package = build.build_package()
    return {item["unique_id"]: item for item in package["template"][0]["sensor"]}


def value(unique, states):
    item = package_templates()[unique]
    available = render(item["availability"], states, NOW)
    return available, (render(item["state"], states, NOW) if available else None)


GRID = "sensor.goodwe_inverter_meter_active_power"
PV = "sensor.goodwe_inverter_pv_power"
HOUSE = "sensor.goodwe_inverter_house_consumption"
SOLAR_TODAY = "sensor.goodwe_inverter_today_s_pv_generation"
EXPORT_TODAY = "sensor.home_grid_export_today"


def test_kw_conversion_directions_and_three_decimals():
    states = {PV: "4123", HOUSE: "1200", GRID: "2923"}  # exporting
    assert value("home_solar_power_kw", states) == (True, 4.123)
    assert value("home_house_power_kw", states) == (True, 1.2)
    assert value("home_grid_export_kw", states) == (True, 2.923)
    assert value("home_grid_import_kw", states) == (True, 0.0)
    assert value("home_grid_state", states) == (True, "Grid Export")
    importing = {PV: "800", HOUSE: "3000", GRID: "-2200"}  # solar AND import together
    assert value("home_grid_import_kw", importing) == (True, 2.2)
    assert value("home_grid_state", importing) == (True, "Grid Import")


def test_night_zero_and_idle_flows():
    assert value("home_grid_state", {PV: "0", HOUSE: "400", GRID: "-400"}) == (True, "Grid Import")
    assert value("home_solar_power_kw", {PV: "0"}) == (True, 0.0)
    assert value("home_grid_state", {GRID: "3"}) == (True, "Grid Idle")  # inside the 5 W idle band
    assert value("home_grid_state", {GRID: "0"}) == (True, "Grid Idle")


@pytest.mark.parametrize("bad", ["unavailable", "unknown", "not_a_number"])
def test_unavailable_readings_are_never_converted_to_zero(bad):
    for unique in (
        "home_solar_power_kw",
        "home_house_power_kw",
        "home_grid_import_kw",
        "home_grid_export_kw",
        "home_grid_state",
    ):
        assert value(unique, {PV: bad, HOUSE: bad, GRID: bad})[0] is False
    assert value("home_grid_state", {})[0] is False  # entity missing


def test_solar_used_directly_and_self_consumption_when_trustworthy():
    states = {SOLAR_TODAY: "20.0", EXPORT_TODAY: "12.5"}
    assert value("home_solar_used_directly_today", states) == (True, 7.5)
    assert value("home_self_consumption_today", states) == (True, 38.0)  # 7.5 / 20


def test_self_consumption_is_withheld_when_not_trustworthy():
    # night / start of day: too little generation to be meaningful
    assert (
        value("home_self_consumption_today", {SOLAR_TODAY: "0.2", EXPORT_TODAY: "0.0"})[0] is False
    )
    # counters disagree (export > generation): reset-timing mismatch
    assert (
        value("home_self_consumption_today", {SOLAR_TODAY: "5.0", EXPORT_TODAY: "9.0"})[0] is False
    )
    # unavailable counters
    assert (
        value("home_self_consumption_today", {SOLAR_TODAY: "5.0", EXPORT_TODAY: "unavailable"})[0]
        is False
    )
    assert (
        value("home_solar_used_directly_today", {SOLAR_TODAY: "unavailable", EXPORT_TODAY: "1"})[0]
        is False
    )


def test_battery_presence_withholds_derived_self_consumption(monkeypatch):
    mapping = build.load_mapping()
    mapping["energy"]["battery_present"] = True
    package = build.build_package(mapping)
    items = {i["unique_id"]: i for i in package["template"][0]["sensor"]}
    assert items["home_self_consumption_today"]["availability"] == "{{ false }}"
    assert items["home_solar_used_directly_today"]["availability"] == "{{ false }}"


def test_daily_meters_are_reset_aware_and_use_measured_sources():
    package = build.build_package()
    meters = package["utility_meter"]
    assert all(m["cycle"] == "daily" for m in meters.values())
    assert (
        meters["home_grid_import_today"]["source"]
        == "sensor.goodwe_inverter_meter_total_energy_import"
    )
    assert (
        meters["home_grid_export_today"]["source"]
        == "sensor.goodwe_inverter_meter_total_energy_export"
    )
    house = package["sensor"][0]
    assert house["source"] == HOUSE and house["max_sub_interval"]  # steady zero still integrates
    for forbidden in ("p_pv_forecast", "forecast"):
        assert forbidden not in json.dumps(package)  # EMHASS forecasts are never measurements


# ------------------------------------------------------------------ the custom card
def test_power_flow_card_unit_tests():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/js/power_flow_card.test.mjs")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_card_resource_path_and_documentation_match():
    js = ROOT / "homeowner/www/thermowatt-power-flow-card.js"
    assert js.is_file() and "thermowatt-power-flow-card" in js.read_text(encoding="utf-8")
    assert build.CARD_RESOURCE.endswith(js.name)
