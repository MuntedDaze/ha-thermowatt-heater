"""The unified Home dashboard: structure, layout, entities, safe actions, plain-English text, energy."""

from datetime import datetime, timedelta
import importlib.util
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

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

HOBART = ZoneInfo("Australia/Hobart")
MODE = "sensor.thermann_shadow_hot_water_operating_mode"
START = "button.thermann_shadow_start_guest_mode_12_h"
CANCEL = "button.thermann_shadow_cancel_guest_mode"
HOLD = "button.thermann_shadow_hold_heater_owner_override"
RESUME = "button.thermann_shadow_resume_automatic_control"
CONTROL = "sensor.thermann_shadow_automatic_control_state"


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
    return build.build_dashboard(custom=True)


@pytest.fixture(scope="module")
def native():
    return build.build_dashboard(custom=False)


@pytest.fixture(scope="module")
def generic():
    return build.build_dashboard(custom=True, mapping=build.load_mapping(build.GENERIC_MAPPING))


def view(data, path):
    return next(v for v in data["views"] if v["path"] == path)


def stack(data, heading_text, path="home"):
    return next(
        c
        for c in walk(view(data, path))
        if c.get("type") == "vertical-stack"
        and c["cards"][0].get("type") == "heading"
        and c["cards"][0]["heading"] == heading_text
    )


# ------------------------------------------------------------------ reproducible + valid
def test_generated_files_are_current():
    for relative, content in build.render_all().items():
        assert (ROOT / relative).read_text(encoding="utf-8") == content, relative


def test_outputs_are_valid_yaml_with_the_required_views(home):
    for relative in build.render_all():
        assert yaml.safe_load((ROOT / relative).read_text(encoding="utf-8")), relative
    data, _ = home
    assert [v["path"] for v in data["views"]] == [
        "home",
        "energy",
        "hot-water",
        "bathrooms",
        "doors",
        "system",
        "device-energy",
    ]


SUPPORTED = {
    "grid",
    "heading",
    "markdown",
    "tile",
    "entities",
    "conditional",
    "vertical-stack",
    "horizontal-stack",
    "weather-forecast",
    "history-graph",
    "statistic",
    "custom:thermowatt-power-flow-card",
    "custom:thermowatt-device-energy-card",
}


def test_every_card_is_a_supported_native_or_declared_card(home, native, generic):
    for data, _ in (home, native, generic):
        for item in walk(data):
            kind = item.get("type")
            if kind and (
                "entity" in item or "cards" in item or "card" in item or "content" in item
            ):
                assert kind in SUPPORTED | {"sections"}, kind
            if kind == "conditional":
                assert item["conditions"] and item["card"]["type"] in SUPPORTED
            if kind == "tile":
                assert item.get("entity"), item  # a tile card without an entity is a config error


def test_home_layout_is_compact_and_follows_the_preferred_arrangement(home):
    data, _ = home
    h = view(data, "home")
    assert h["type"] == "sections" and h["max_columns"] == 4 and h["dense_section_placement"]
    sections = h["sections"]
    # 4 columns: [flow | energy | hot water | weather] then [Main | Ensuite | lights and doors x2]
    assert [s.get("column_span", 1) for s in sections] == [1, 1, 1, 1, 1, 1, 2]
    flow, energy, hot, weather, main, ensuite, lights_doors = sections
    assert flow["cards"][0]["type"] == "custom:thermowatt-power-flow-card"
    assert any(c.get("type") == "statistic" for c in energy["cards"])
    assert hot["cards"][0]["type"] == "markdown"
    assert weather["cards"][0]["type"] == "weather-forecast"
    # both bathrooms side by side beneath the energy information, one column each
    names = [s["cards"][0]["cards"][0]["heading"] for s in (main, ensuite)]
    assert names == ["Main Bathroom", "Ensuite"]
    assert all(s["cards"][0]["grid_options"]["columns"] == 12 for s in (main, ensuite))
    headings = [c.get("heading") for c in lights_doors["cards"] if c.get("type") == "heading"]
    assert headings == ["Lights and doors"]
    # no graphs or long explanations crowd the main screen
    assert not [c for c in walk(h) if c.get("type") == "history-graph"]
    assert not [c for c in walk(h) if c.get("type") == "entities"]


def test_layout_is_responsive_and_uses_no_fixed_pixel_sizes(home):
    data, _ = home
    for v in data["views"]:
        assert v["type"] == "sections" and v["max_columns"] in (3, 4)
        for sec in v["sections"]:
            assert sec.get("column_span", 1) <= v["max_columns"]
    text = (ROOT / "homeowner/home.yaml").read_text(encoding="utf-8")
    assert "px" not in text.replace("hours_to_show", "")
    for item in walk(data):
        if "grid_options" in item:
            assert 1 <= item["grid_options"]["columns"] <= 12


def test_no_duplicate_fan_tiles(home):
    data, _ = home
    for name in ("Main Bathroom", "Ensuite"):
        tiles = [c for c in walk(stack(data, name)) if c.get("type") == "tile"]
        labels = [t.get("name", "") for t in tiles]
        assert not [n for n in labels if n.startswith("Extraction")]  # no separate Extraction tile
        assert "Shower" not in labels
        assert len([n for n in labels if n.startswith("Fan:")]) == 4  # one control, four states


# ------------------------------------------------------------------ entities exist
def test_thermowatt_entities_are_real_entity_names(home):
    _, ent = home
    package_dir = ROOT / "custom_components/thermann_shadow"
    source = "".join(p.read_text(encoding="utf-8") for p in package_dir.glob("*.py"))
    for eid, name in ent.thermowatt_names.items():
        assert f'"{name}"' in source, (eid, name)
    assert {START, CANCEL, HOLD, RESUME, MODE, CONTROL} <= set(ent.used)


def test_tapo_entities_exist_in_the_published_contract(home, native, generic):
    contract = json.loads(build.TAPO_CONTRACT.read_text(encoding="utf-8"))["entities"]
    assert json.loads(build.TAPO_CONTRACT.read_text(encoding="utf-8"))["version"] == "0.3.1"
    for _, ent in (home, native, generic):
        for eid, source in ent.used.items():
            if source == "tapo_smart_controller":
                assert eid in contract, eid


def test_both_bathrooms_use_identical_cards(home):
    data, _ = home
    main, ensuite = stack(data, "Main Bathroom"), stack(data, "Ensuite")

    def shape(card):
        text = json.dumps(card).replace("main_bathroom", "X").replace("ensuite", "X")
        return text.replace("Main Bathroom", "N").replace("Ensuite", "N")

    assert shape(main) == shape(ensuite)


# ------------------------------------------------------------------ safety of actions
def actions(data):
    for item in walk(data):
        for key in ("tap_action", "icon_tap_action", "hold_action"):
            if key in item:
                yield item[key]


def test_no_garage_or_lock_controls_exist(home, native, generic):
    for data, ent in (home, native, generic):
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
    allowed_buttons = {START, CANCEL, HOLD, RESUME}
    for action in actions(data):
        kind = action["action"]
        if kind in ("more-info", "none", "navigate"):
            continue
        assert kind == "perform-action"
        service, target = action["perform_action"], action["target"]["entity_id"]
        if service == "button.press":
            assert target in allowed_buttons
            assert action["confirmation"]["text"]  # every heating-related press is confirmed
        elif service in ("switch.turn_on", "switch.turn_off"):
            assert target.startswith("switch.tapo_smart_controller_")
            assert target.endswith("_manual_override")
        else:
            assert service == "light.toggle"


def test_dashboard_never_commands_a_physical_relay_or_the_original_devices(home):
    data, ent = home
    originals = {
        e for e, src in ent.used.items() if src == "home_mapping" and e.startswith("switch.")
    }
    assert originals == {
        "switch.main_fan",
        "switch.main_towel_rail",
        "switch.ensuite_fan",
        "switch.ensuite_towel_rail",
    }
    for action in actions(data):
        assert action.get("target", {}).get("entity_id") not in originals


def test_hot_water_override_toggle_is_state_driven_and_confirmed(home):
    data, _ = home
    on, off, unknown, unavailable_now = [
        c for c in view(data, "home")["sections"][2]["cards"] if c["type"] == "conditional"
    ]
    # holiday / disabled: the controller would refuse, so the tile is inert instead of misleading
    assert unavailable_now["card"]["tap_action"] == {"action": "more-info"}
    assert {c["state"] for c in unavailable_now["conditions"][0]["conditions"]} == {
        "holiday",
        "disabled",
    }
    assert on["conditions"] == [{"condition": "state", "entity": MODE, "state": "guest"}]
    assert on["card"]["color"] == "blue" and off["card"]["color"] == "grey"
    assert on["card"]["tap_action"]["target"]["entity_id"] == CANCEL
    assert off["card"]["tap_action"]["target"]["entity_id"] == START
    assert {c["state_not"] for c in off["conditions"]} == {
        "guest",
        "unavailable",
        "unknown",
        "holiday",
        "disabled",
    }
    assert on["card"]["tap_action"]["confirmation"] and off["card"]["tap_action"]["confirmation"]
    assert unknown["card"]["tap_action"] == {"action": "more-info"}
    assert unknown["card"]["color"] == "grey"


def test_hot_water_view_has_one_override_control_and_one_hold_resume_control(home):
    data, _ = home
    hot = view(data, "hot-water")
    pressed = [
        a["target"]["entity_id"] for a in actions(hot) if a.get("perform_action") == "button.press"
    ]
    # one state-aware control each (a tile has the card and icon action): no duplicate big buttons
    assert sorted(set(pressed)) == sorted([START, CANCEL, HOLD, RESUME])
    assert not [c for c in walk(hot) if c.get("type") == "button"]
    held, active, inert = [
        c for c in walk(hot) if c.get("type") == "conditional" and CONTROL in json.dumps(c)
    ]
    assert held["card"]["tap_action"]["target"]["entity_id"] == RESUME
    assert active["card"]["tap_action"]["target"]["entity_id"] == HOLD
    assert (
        held["card"]["tap_action"]["confirmation"] and active["card"]["tap_action"]["confirmation"]
    )
    assert inert["card"]["tap_action"] == {"action": "more-info"}
    not_states = {c["state_not"] for c in inert["conditions"]}
    assert {"owner_override", "observing", "parked", "confirming"} <= not_states  # NOT inert
    assert "fault_locked" not in not_states and "disabled" not in not_states


def test_settings_navigation_is_compact_and_correct(home):
    data, _ = home
    paths = {a["navigation_path"] for a in actions(data) if a.get("action") == "navigate"}
    assert paths == {
        "/config/integrations/integration/thermann_shadow",
        "/config/integrations/integration/tapo_smart_controller",
    }
    for item in walk(view(data, "hot-water")):
        if item.get("icon") == "mdi:cog-outline":
            assert item["type"] == "tile" and item["name"] == "Hot water settings"


# ------------------------------------------------------------------ bathroom toggles
def bathroom_toggles(data, name="Main Bathroom"):
    branches = [c for c in stack(data, name)["cards"] if c["type"] == "conditional"]
    assert len(branches) == 8  # four states each for the fan and the towel rail
    return branches[:4], branches[4:]


def test_toggle_state_reflects_actual_physical_state_not_the_request(home):
    data, _ = home
    fan, towel = bathroom_toggles(data)
    for card in fan:
        assert (
            card["card"]["entity"]
            == "binary_sensor.tapo_smart_controller_main_bathroom_fan_running"
        )
        assert card["card"]["state_content"] == "summary"
    assert towel[0]["card"]["entity"].endswith("_towel_rail_heating")


def test_auto_running_is_distinct_from_an_active_manual_request_and_cancel_is_always_possible(home):
    data, _ = home
    for toggles in bathroom_toggles(data):
        manual, auto, off, _unknown = toggles
        assert manual["card"]["name"].endswith(": manual")
        assert auto["card"]["name"].endswith(": automatic")
        assert off["card"]["name"].endswith(": off")
        # a queued request (still waiting for off-peak) is cancelled whatever the physical state is
        assert [c["state"] for c in manual["conditions"]] == ["on"]
        assert manual["card"]["tap_action"]["perform_action"] == "switch.turn_off"
        assert manual["card"]["color"] == "blue" and auto["card"]["color"] == "blue"
        assert off["card"]["color"] == "grey"
        for card in (auto, off):
            assert card["card"]["tap_action"]["perform_action"] == "switch.turn_on"
            assert card["conditions"][0]["state"] == "off"


def test_toggles_are_inert_when_the_request_or_actual_state_is_unknown(home):
    data, _ = home
    for toggles in bathroom_toggles(data):
        _manual, auto, off, unknown = toggles
        assert unknown["card"]["tap_action"] == {"action": "more-info"}
        assert unknown["card"]["color"] == "grey"
        assert unknown["conditions"][0]["state_not"] == "on"
        inner = unknown["conditions"][1]["conditions"]
        assert {c["state"] for c in inner} == {"unavailable", "unknown"} and len(inner) == 4
        for card in (auto, off):
            assert card["conditions"][0]["state"] == "off"  # only a KNOWN off request switch acts


def test_starting_towel_heating_is_confirmed(home):
    data, _ = home
    _, towel = bathroom_toggles(data)
    for card in towel[1:3]:
        assert card["card"]["tap_action"]["confirmation"]["text"]


def test_bathroom_history_uses_original_entities_and_relays(home, generic):
    data, _ = home
    graphs = [c for c in walk(view(data, "bathrooms")) if c.get("type") == "history-graph"]
    assert [g["entities"] for g in graphs] == [
        ["sensor.main_temp_humidity", "sensor.main_temp_temperature"],
        ["switch.main_fan", "switch.main_towel_rail"],
        ["sensor.ensuite_temp_humidity", "sensor.ensuite_temp_temperature"],
        ["switch.ensuite_fan", "switch.ensuite_towel_rail"],
    ]
    # the generic profile has no original entities, so it falls back to the controller's own sensors
    gdata, _ = generic
    gg = [c for c in walk(view(gdata, "bathrooms")) if c.get("type") == "history-graph"]
    assert gg[0]["entities"][0] == "sensor.tapo_smart_controller_main_bathroom_humidity"


# ------------------------------------------------------------------ hot water text
SHIM_ENTITIES = {
    "sensor.thermann_shadow_bottom_temperature": "52.44",
    "sensor.thermann_shadow_status_age": "7",
    "sensor.thermann_shadow_thermann_mode": "Manual",
    "sensor.thermann_shadow_thermann_target": "62.0",
    "sensor.thermann_shadow_desired_thermostat_temperature": "62.0",
    MODE: "automatic",
    "sensor.thermann_shadow_current_tariff": "off_peak",
    "sensor.thermann_shadow_solar_boost_status": "idle",
    "sensor.thermann_shadow_next_intended_action": "wait_for_off_peak",
    "sensor.thermann_shadow_next_cloud_poll": "2026-11-22T14:30:00+11:00",
    "sensor.home_last_successful_poll": "2026-11-22T14:05:00+11:00",
    "sensor.thermann_shadow_guest_mode_ends": "unknown",
}
NOW = datetime(2026, 11, 22, 14, 10, tzinfo=HOBART)


def hot_water_text(**changes):
    states = {**SHIM_ENTITIES, **changes}
    card = view(build.build_dashboard()[0], "home")["sections"][2]["cards"][0]
    return render(card["content"], states, NOW)


def test_hot_water_summary_is_compact_and_plain_english():
    text = hot_water_text()
    assert text.splitlines()[0] == "# 52.4 °C"
    assert "updated 7 min ago" in text and "last poll 14:05" in text
    assert "**Heater** Manual · target 62 °C" in text
    assert "desired" not in text  # identical reported/desired values are shown once
    assert "**Control** Automatic" in text and "**Tariff** Off-peak" in text
    assert "**Solar boost** Idle" in text and "**Next** Wait for off peak" in text
    assert "next poll 14:30" in text
    assert "Override ends" not in text  # never "Unknown" during normal automatic operation
    assert "unknown" not in text.lower()
    assert len(text.splitlines()) <= 8


def test_reported_and_desired_targets_both_show_when_they_differ():
    text = hot_water_text(**{"sensor.thermann_shadow_desired_thermostat_temperature": "45.0"})
    assert "target 62 °C · desired 45 °C" in text


def test_override_expiry_shows_only_while_an_override_is_active():
    active = hot_water_text(
        **{MODE: "guest", "sensor.thermann_shadow_guest_mode_ends": "2026-11-23T02:10:00+11:00"}
    )
    assert "**Control** 12 h override" in active and "**Override ends** 02:10" in active


def test_missing_values_show_a_dash_never_a_guess():
    text = hot_water_text(
        **{
            "sensor.thermann_shadow_bottom_temperature": "unavailable",
            "sensor.thermann_shadow_status_age": "unknown",
            "sensor.home_last_successful_poll": "unavailable",
            MODE: "unavailable",
        }
    )
    assert text.splitlines()[0] == "# —"
    assert "age unknown" in text and "last poll —" in text and "**Control** —" in text


def test_hot_water_diagnostics_show_plain_english_not_internal_codes():
    card = [
        c
        for c in walk(view(build.build_dashboard()[0], "hot-water"))
        if c.get("type") == "markdown" and "Why this decision" in c["content"]
    ][0]
    states = {
        "sensor.thermann_shadow_current_heating_plan": "Heat to 62 °C before 16:00",
        "sensor.thermann_shadow_next_intended_action": "wait_for_off_peak",
        "sensor.thermann_shadow_next_heating_start": "2026-11-22T23:00:00+11:00",
        "sensor.thermann_shadow_solar_boost_status": "no_qualified_session",
        "sensor.thermann_shadow_why_thermowatt_made_this_decision": "peak_no_grid_heating",
        "sensor.thermann_shadow_last_command_result": "confirmed",
        "sensor.thermann_shadow_cloud_requests_in_last_24_hours": "31",
    }
    text = render(card["content"], states, NOW)
    assert "_" not in text  # no internal identifiers
    assert "**Next action** Wait for off peak" in text and "**Next heating start** 23:00" in text
    assert "**Why this decision** Peak no grid heating" in text
    blank = render(card["content"], {}, NOW)
    assert "—" in blank and "none planned" in blank  # missing values are dashes, not guesses


def test_system_status_uses_plain_english_without_hiding_faults():
    card = [
        c for c in walk(view(build.build_dashboard()[0], "system")) if c.get("type") == "markdown"
    ][0]
    base = {
        "sensor.thermann_shadow_controller_fault": "none",
        "sensor.thermann_shadow_cloud_health": "ok",
        CONTROL: "observing",
        "sensor.tapo_smart_controller_electricity_tariff_status": "off_peak",
        "sensor.tapo_smart_controller_active_health_warnings": "0",
        "binary_sensor.tapo_smart_controller_controller_health_problem": "off",
        "binary_sensor.tapo_smart_controller_simulation_mode_active": "off",
    }
    ok = render(card["content"], base, NOW)
    assert "Cloud connection: Connected" in ok and "No problems detected" in ok
    assert "Observing: checking the heater before acting" in ok
    assert "Tariff read by the controller: Off-peak" in ok and "Live control" in ok
    assert "off_peak" not in ok and "lock_integration" not in ok
    bad = render(
        card["content"],
        {
            **base,
            "sensor.thermann_shadow_controller_fault": "off_restoration_unconfirmed",
            "sensor.thermann_shadow_cloud_health": "auth_locked",
            CONTROL: "fault_locked",
            "binary_sensor.tapo_smart_controller_controller_health_problem": "on",
            "binary_sensor.tapo_smart_controller_simulation_mode_active": "on",
        },
        NOW,
    )
    assert "Heating control problem: Off restoration unconfirmed" in bad  # a fault stays a fault
    assert "Sign-in locked" in bad and "Fault: needs acknowledgement" in bad
    assert "Problem reported" in bad and "Simulation: no devices are switched" in bad
    unknown = render(
        card["content"], {**base, "sensor.thermann_shadow_controller_fault": "unavailable"}, NOW
    )
    assert "Heating control problem: Unknown" in unknown  # unknown is never shown as healthy


# ------------------------------------------------------------------ doors
def test_doors_view_shows_plain_status_and_never_implies_locked(home):
    data, _ = home
    doors = view(data, "doors")
    tiles = [
        c for c in walk(doors) if c.get("type") == "tile" and c.get("state_content") == "summary"
    ]
    assert {t["entity"] for t in tiles} == {
        "sensor.tapo_smart_controller_garage_door_status",
        "sensor.tapo_smart_controller_front_door_lock_status",
    }
    text = json.dumps(doors)
    assert "lock_integration_unavailable" not in text
    assert "does not mean the front door is locked" in text
    graph = next(c for c in walk(doors) if c.get("type") == "history-graph")
    assert graph["entities"] == ["binary_sensor.garage_door", "binary_sensor.front_door_door"]


# ------------------------------------------------------------------ mappings
def test_homeowner_profile_is_fully_mapped_and_verified(home):
    data, ent = home
    mapping = ent.mapping
    assert mapping["profile"] == "homeowner" and mapping["energy"]["battery_present"] is False
    assert mapping["weather"] == {"entity": "weather.home", "status": "verified"}
    assert mapping["lights"]["dining_room"]["entity"] == "light.dining_room_light"
    assert mapping["lights"]["living_room"]["entity"] == "light.living_room_light"
    assert ent.unresolved == []
    assert "mapping needed" not in json.dumps(data)
    weather = next(c for c in walk(data) if c.get("type") == "weather-forecast")
    assert weather["entity"] == "weather.home" and weather["name"] == "Rokeby, TAS"
    assert (
        weather["forecast_type"] == "daily" and weather["show_current"] and weather["show_forecast"]
    )
    light_tiles = [
        c
        for c in walk(data)
        if c.get("type") == "tile" and c.get("entity", "").startswith("light.")
    ]
    assert {t["entity"] for t in light_tiles} == {
        "light.dining_room_light",
        "light.living_room_light",
    }
    for item in light_tiles:
        assert item["features"] == [{"type": "light-brightness"}] and item["color"] == "blue"
        assert item["tap_action"]["perform_action"] == "light.toggle"


def test_generic_profile_assumes_nothing_about_this_household(generic):
    data, ent = generic
    mapping = ent.mapping
    assert mapping["profile"] == "generic"
    assert mapping["energy"]["battery_present"] == "unknown"
    assert mapping["weather"]["entity"] == "" and mapping["lights"]["dining_room"]["entity"] == ""
    assert sorted(set(ent.unresolved)) == [
        "device_energy.rates",
        "lights.dining_room",
        "lights.living_room",
        "weather",
    ]
    text = json.dumps(data)
    assert "weather.home" not in text and "light.dining_room_light" not in text
    assert "binary_sensor.garage_door" not in text
    package = build.build_package(build.load_mapping(build.GENERIC_MAPPING))
    status = next(
        i for i in package["template"][0]["sensor"] if i["unique_id"] == "home_energy_status"
    )
    assert "{% if not false %}battery_unconfirmed" in status["state"]


def test_a_custom_profile_can_be_built_without_touching_the_committed_outputs(tmp_path):
    mapping = build.load_mapping()
    mapping["profile"] = "custom"
    mapping["weather"]["entity"] = "weather.elsewhere"
    path = tmp_path / "mine.yaml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    rendered = build.render_profile(path)
    assert "weather.elsewhere" in rendered["home"] and "weather.home" not in rendered["home"]


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
    assert "em_" not in json.dumps(data)


# ------------------------------------------------------------------ energy package
GRID = "sensor.goodwe_inverter_meter_active_power"
PV = "sensor.goodwe_inverter_pv_power"
HOUSE = "sensor.goodwe_inverter_house_consumption"
SOLAR_TODAY = "sensor.goodwe_inverter_today_s_pv_generation"
IMPORT_TOTAL = "sensor.goodwe_inverter_meter_total_energy_import"
EXPORT_TOTAL = "sensor.goodwe_inverter_meter_total_energy_export"
IMPORT_METER = "sensor.home_grid_import_meter"
EXPORT_METER = "sensor.home_grid_export_meter"
CONSUMPTION_METER = "sensor.home_consumption_meter"
STATUS = "sensor.home_energy_status"
MIDNIGHT = datetime(2026, 11, 22, 0, 0, tzinfo=HOBART)
DAY_NOW = datetime(2026, 11, 22, 10, 0, tzinfo=HOBART)


def owner_package(**energy):
    mapping = build.load_mapping()
    mapping["energy"].update(energy)
    return {i["unique_id"]: i for i in build.build_package(mapping)["template"][0]["sensor"]}


def counter(state, unit="kWh", klass="total_increasing", age=60):
    attrs = {"unit_of_measurement": unit}
    if klass:
        attrs["state_class"] = klass
    return {"state": state, "attributes": attrs, "age": age}


def meter(state, reset, valid=True):
    return {
        "state": state,
        "attributes": {"last_reset": reset.isoformat(), "last_valid_state": 3.0 if valid else None},
    }


def day(solar="20.0", export="12.5", imp="3.0", cons="11.0", reset=MIDNIGHT, **over):
    states = {
        SOLAR_TODAY: counter(solar, klass=None),
        IMPORT_TOTAL: counter("1000"),
        EXPORT_TOTAL: counter("500"),
        HOUSE: {"state": "800"},
        EXPORT_METER: meter(export, reset),
        IMPORT_METER: meter(imp, reset),
        CONSUMPTION_METER: meter(cons, reset),
    }
    states.update(over)
    return states


def status_of(states, now=DAY_NOW, package=None):
    item = (package or owner_package())["home_energy_status"]
    return render(item["state"], states, now)


def value(unique, states, now=DAY_NOW, package=None):
    package = package or owner_package()
    states = {**states, STATUS: status_of(states, now, package)}
    item = package[unique]
    available = render(item["availability"], states, now) if "availability" in item else True
    return available, (render(item["state"], states, now) if available else None)


def test_kw_conversion_directions_and_three_decimals():
    states = {PV: {"state": "4123"}, HOUSE: {"state": "1200"}, GRID: {"state": "2923"}}
    assert value("home_solar_power_kw", states) == (True, 4.123)
    assert value("home_house_power_kw", states) == (True, 1.2)
    assert value("home_grid_export_kw", states) == (True, 2.923)
    assert value("home_grid_import_kw", states) == (True, 0.0)
    assert value("home_grid_state", states) == (True, "Grid Export")
    importing = {PV: {"state": "800"}, HOUSE: {"state": "3000"}, GRID: {"state": "-2200"}}
    assert value("home_grid_import_kw", importing) == (True, 2.2)
    assert value("home_grid_state", importing) == (True, "Grid Import")


def test_night_zero_and_idle_flows():
    assert value("home_grid_state", {GRID: {"state": "-400"}}) == (True, "Grid Import")
    assert value("home_solar_power_kw", {PV: {"state": "0"}}) == (True, 0.0)
    assert value("home_grid_state", {GRID: {"state": "3"}}) == (True, "Grid Idle")
    assert value("home_grid_state", {GRID: {"state": "0"}}) == (True, "Grid Idle")


@pytest.mark.parametrize("bad", ["unavailable", "unknown", "not_a_number"])
def test_unavailable_readings_are_never_converted_to_zero(bad):
    states = {PV: {"state": bad}, HOUSE: {"state": bad}, GRID: {"state": bad}}
    for unique in (
        "home_solar_power_kw",
        "home_house_power_kw",
        "home_grid_import_kw",
        "home_grid_export_kw",
        "home_grid_state",
    ):
        assert value(unique, states)[0] is False
    assert value("home_grid_state", {})[0] is False


def test_full_day_figures_are_measured_and_consistent():
    states = day()
    assert status_of(states) == "ready"
    assert value("home_solar_used_directly_today", states) == (True, 7.5)
    assert value("home_self_consumption_today", states) == (True, 38.0)
    assert value("home_grid_export_today", states) == (True, 12.5)
    assert value("home_grid_import_today", states) == (True, 3.0)
    # household = solar + import - export from the inverter counters (a measured balance)
    assert value("home_consumption_today", states) == (True, 10.5)
    # the integrated-power figure is a separate, labelled estimate
    assert value("home_consumption_estimate_today", states) == (True, 11.0)
    item = owner_package()["home_consumption_estimate_today"]
    assert "estimate" in item["attributes"]["basis"]


def test_first_day_collecting_withholds_figures_with_an_explanation_state():
    """Meters created mid-day (or not yet fed) hold only part of the day."""
    installed = datetime(2026, 11, 22, 8, 30, tzinfo=HOBART)
    states = day(solar="10.0", export="0.0", reset=installed)
    assert status_of(states) == "collecting_first_day"
    for unique in (
        "home_solar_used_directly_today",
        "home_self_consumption_today",
        "home_grid_export_today",
        "home_grid_import_today",
        "home_consumption_today",
    ):
        assert value(unique, states)[0] is False, unique
    # a never-initialised meter (unknown, last_valid_state None) is "collecting", not a failure
    fresh = day(**{EXPORT_METER: meter("unknown", MIDNIGHT, valid=False)})
    assert status_of(fresh) == "collecting_first_day"
    assert value("home_solar_used_directly_today", fresh)[0] is False


def test_midnight_rollover_and_stale_previous_day_resets():
    just_reset = MIDNIGHT + timedelta(seconds=5)
    assert status_of(day(reset=just_reset)) == "ready"
    assert status_of(day(reset=MIDNIGHT + timedelta(seconds=90))) == "ready"  # late scheduler
    assert status_of(day(reset=MIDNIGHT - timedelta(seconds=20))) == "ready"  # clock skew
    # a meter first installed at 00:09, or last reset at 23:55 the day before, does NOT hold a whole day
    assert status_of(day(reset=MIDNIGHT + timedelta(minutes=9))) == "collecting_first_day"
    assert status_of(day(reset=MIDNIGHT - timedelta(minutes=5))) == "collecting_first_day"
    assert status_of(day(reset=MIDNIGHT + timedelta(minutes=3))) == "collecting_first_day"
    # a missed midnight reset leaves yesterday's reset time: NOT today's coverage
    assert status_of(day(reset=MIDNIGHT - timedelta(days=1))) == "collecting_first_day"
    assert status_of(day(reset=MIDNIGHT - timedelta(hours=2))) == "collecting_first_day"
    assert status_of(day(reset=MIDNIGHT + timedelta(hours=2))) == "collecting_first_day"
    # right after rollover, before the meters have reset, today's figures are not claimed
    just_after = MIDNIGHT + timedelta(minutes=1)
    assert (
        status_of(day(reset=MIDNIGHT - timedelta(days=1)), now=just_after) == "collecting_first_day"
    )


def test_daylight_saving_changeover_day_still_resets_at_local_midnight():
    """Hobart DST starts Sunday 4 Oct 2026 at 02:00: midnight itself is unaffected."""
    dst_day = datetime(2026, 10, 4, 0, 0, tzinfo=HOBART)
    now = datetime(2026, 10, 4, 15, 0, tzinfo=HOBART)
    assert now.utcoffset() == timedelta(hours=11) and dst_day.utcoffset() == timedelta(hours=10)
    assert status_of(day(reset=dst_day), now=now) == "ready"
    assert status_of(day(reset=dst_day - timedelta(days=1)), now=now) == "collecting_first_day"
    # end of DST: Sunday 5 April 2026 at 03:00 clocks go back
    end_day = datetime(2026, 4, 5, 0, 0, tzinfo=HOBART)
    after = datetime(2026, 4, 5, 15, 0, tzinfo=HOBART)
    assert status_of(day(reset=end_day), now=after) == "ready"


def test_export_exceeding_generation_is_withheld_never_negative_or_clamped():
    for export in ("20.01", "20.05", "25.0"):  # even a hair over generation is refused
        states = day(solar="20.0", export=export)
        assert status_of(states) == "inconsistent"
        for unique in (
            "home_solar_used_directly_today",
            "home_self_consumption_today",
            "home_consumption_today",
        ):
            assert value(unique, states)[0] is False
    equal = day(solar="20.0", export="20.0")
    assert value("home_solar_used_directly_today", equal) == (True, 0.0)
    assert value("home_self_consumption_today", equal) == (True, 0.0)


def test_derived_values_are_always_physically_meaningful():
    for solar, export, imp in (("20", "0", "5"), ("1.0", "1.0", "9"), ("33.3", "30.1", "0")):
        states = day(solar=solar, export=export, imp=imp)
        used = value("home_solar_used_directly_today", states)[1]
        pct = value("home_self_consumption_today", states)[1]
        cons = value("home_consumption_today", states)[1]
        assert used >= 0 and 0 <= pct <= 100 and cons >= used


def test_too_little_generation_withholds_the_percentage_only():
    states = day(solar="0.2", export="0.0")
    assert value("home_self_consumption_today", states)[0] is False
    assert value("home_solar_used_directly_today", states) == (True, 0.2)


@pytest.mark.parametrize(
    "broken",
    [
        {SOLAR_TODAY: counter("unavailable", klass=None)},
        {IMPORT_TOTAL: counter("unavailable")},
        {EXPORT_TOTAL: counter("unknown")},
        {IMPORT_TOTAL: counter("1000", unit="Wh")},  # wrong unit: not a kWh counter
        {EXPORT_TOTAL: counter("-3")},  # a counter cannot be negative
        {IMPORT_TOTAL: counter("1000", age=7200)},  # not recently reported
        {EXPORT_TOTAL: counter("500", age=7200)},
        {SOLAR_TODAY: counter("20.0", klass=None, age=7200)},
    ],
)
def test_invalid_or_stale_sources_are_unavailable_not_zero(broken):
    states = day(**broken)
    assert status_of(states) == "sources_unavailable"
    for unique in (
        "home_solar_used_directly_today",
        "home_self_consumption_today",
        "home_consumption_today",
        "home_grid_import_today",
        "home_grid_export_today",
    ):
        assert value(unique, states)[0] is False


def test_a_counter_declared_as_a_non_cumulative_measurement_is_rejected():
    for lifetime in (IMPORT_TOTAL, EXPORT_TOTAL):
        states = day(**{lifetime: counter("500", klass="measurement")})
        assert status_of(states) == "sources_unavailable"
    for klass in ("total", "total_increasing"):
        assert status_of(day(**{EXPORT_TOTAL: counter("500", klass=klass)})) == "ready"
    # the inverter's daily generation counter keeps its legitimate characteristics (no class required)
    assert status_of(day(**{SOLAR_TODAY: counter("20.0", klass="total_increasing")})) == "ready"


def test_status_states_the_availability_limitation_it_cannot_detect():
    attrs = owner_package()["home_energy_status"]["attributes"]
    assert "offline" in attrs["limitation"] and "gap" in attrs["limitation"]


def test_a_counter_without_a_state_class_is_still_accepted():
    """utility_meter does not need a state class, so the package must not lock out such a counter."""
    assert status_of(day(**{EXPORT_TOTAL: counter("500", klass=None)})) == "ready"


def test_meter_that_reports_the_string_none_is_not_initialised():
    states = day(
        **{
            EXPORT_METER: {
                "state": "0",
                "attributes": {"last_reset": MIDNIGHT.isoformat(), "last_valid_state": "None"},
            }
        }
    )
    assert status_of(states) == "collecting_first_day"


def test_a_missing_inverter_entity_is_handled():
    for gone in (SOLAR_TODAY, IMPORT_TOTAL, EXPORT_TOTAL):
        states = day()
        del states[gone]
        assert status_of(states) == "sources_unavailable"


def test_battery_unknown_or_present_withholds_derived_figures():
    for flag in ("unknown", True):
        package = owner_package(battery_present=flag)
        states = day()
        assert status_of(states, package=package) == "battery_unconfirmed"
        for unique in ("home_solar_used_directly_today", "home_consumption_today"):
            assert value(unique, states, package=package)[0] is False
    assert build.load_mapping()["energy"]["battery_present"] is False  # owner-confirmed


def test_estimate_requires_a_full_day_and_fresh_power():
    assert value("home_consumption_estimate_today", day(cons="9"))[0] is True
    partial = datetime(2026, 11, 22, 9, 0, tzinfo=HOBART)
    part = day(**{CONSUMPTION_METER: meter("9", partial)})
    assert value("home_consumption_estimate_today", part)[0] is False
    stale = day(**{HOUSE: {"state": "800", "age": 3600}})
    assert value("home_consumption_estimate_today", stale)[0] is False


def test_daily_meters_keep_their_ids_and_use_measured_sources():
    package = build.build_package()
    meters = package["utility_meter"]
    assert sorted(meters) == [
        "home_consumption_meter",
        "home_grid_export_meter",
        "home_grid_import_meter",
    ]  # unique IDs unchanged: the package upgrades in place and keeps accumulated data
    assert all(m["cycle"] == "daily" for m in meters.values())
    assert meters["home_grid_import_meter"]["source"] == IMPORT_TOTAL
    assert meters["home_grid_export_meter"]["source"] == EXPORT_TOTAL
    house = package["sensor"][0]
    assert house["unique_id"] == "home_house_energy_total" and house["max_sub_interval"]
    for forbidden in ("p_pv_forecast", "forecast"):
        assert forbidden not in json.dumps(package)  # EMHASS forecasts are never measurements


def test_template_unique_ids_are_stable_for_an_in_place_upgrade():
    assert {
        "home_solar_power_kw",
        "home_house_power_kw",
        "home_grid_import_kw",
        "home_grid_export_kw",
        "home_grid_state",
        "home_grid_import_today",
        "home_grid_export_today",
        "home_consumption_today",
        "home_solar_used_directly_today",
        "home_self_consumption_today",
    } <= set(owner_package())  # every ID the installed package already created still exists


def test_home_shows_collecting_text_instead_of_unavailable_tiles(home):
    data, _ = home
    energy = view(data, "home")["sections"][1]["cards"]
    ready = [
        c
        for c in energy
        if c.get("type") == "conditional" and c["conditions"][0].get("state") == "ready"
    ]
    waiting = [
        c
        for c in energy
        if c.get("type") == "conditional" and c["conditions"][0].get("state_not") == "ready"
    ]
    assert len(ready) == 3 and len(waiting) == 1
    content = waiting[0]["card"]["content"]
    assert render(content, {STATUS: "collecting_first_day"}, DAY_NOW).startswith(
        "**Collecting daily data.**"
    )
    assert render(content, {STATUS: "sources_unavailable"}, DAY_NOW).startswith(
        "**Energy readings unavailable.**"
    )
    # import/export come from existing long-term statistics, available from day one
    stats = [c["entity"] for c in energy if c.get("type") == "statistic"]
    assert stats == [IMPORT_TOTAL, EXPORT_TOTAL]


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


# ------------------------------------------------------------------ device energy view
DEVICE_ENERGY_TYPE = "custom:thermowatt-device-energy-card"


def device_card(data):
    return next(
        c
        for c in walk(view(data, "device-energy"))
        if c.get("type") == "custom:thermowatt-device-energy-card"
    )


def test_device_energy_is_the_seventh_view_with_an_energy_icon(home):
    data, _ = home
    v = data["views"][-1]
    assert v["path"] == "device-energy" and v["title"] == "Device Energy"
    assert v["icon"] == "mdi:meter-electric"
    assert len(data["views"]) == 7


def test_rates_live_in_one_central_place_and_are_not_hardcoded_elsewhere(home):
    data, _ = home
    card = device_card(data)
    # the start date of the current prices is not confirmed: null, so history is labelled as assumed
    assert card["rates"] == [{"effective_from": None, "offpeak": 0.1419, "peak": 0.1907}]
    mapping = build.load_mapping()
    assert mapping["device_energy"]["rates"][0]["offpeak"] == 0.1419
    for path in (
        ROOT / "homeowner/www/thermowatt-power-flow-card.js",
        ROOT / "tools/build_home_dashboard.py",
        ROOT / "tests/js/device_energy.test.mjs",
    ):
        text = path.read_text(encoding="utf-8")
        if (
            path.name != "device_energy.test.mjs"
        ):  # the unit tests use the owner's rates as fixtures
            assert "0.1419" not in text and "0.1907" not in text, path


def test_tariff_windows_come_from_the_existing_energy_map_not_a_second_schedule(home):
    data, _ = home
    source = yaml.safe_load(
        (ROOT / "energy_monitoring/entity_map.yaml").read_text(encoding="utf-8")
    )["tariff"]
    tariff = device_card(data)["tariff"]
    assert (
        tariff["clock"] == source["clock"]
        and tariff["utc_offset_hours"] == source["utc_offset_hours"]
    )
    assert tariff["peak_windows"] == [
        {"days": w["days"], "start": w["start"], "end": w["end"]} for w in source["peak_windows"]
    ]
    assert device_card(data)["timezone"] == "Australia/Hobart"


def test_no_device_list_or_device_entity_is_hardcoded(home):
    data, ent = home
    card = device_card(data)
    assert set(card) == {
        "type",
        "tariff",
        "rates",
        "platforms",
        "history_months",
        "grid_options",
        "timezone",
        "part",
        "house",
    }
    assert card["platforms"] == [
        "tplink",
        "tapo",
    ]  # discovery scope only: devices come from the registries
    assert "exclude" not in card and "include_only" not in card
    text = json.dumps(view(data, "device-energy"))
    # the only entity IDs are the inverter's verified whole-house sources, taken from the mapping
    for entity in ("solar", "import", "export"):
        text = text.replace(card["house"][entity], "")
    assert "sensor." not in text and "switch." not in text
    assert not [e for e, s in ent.used.items() if "device" in s]


def test_device_energy_view_sends_no_commands(home):
    data, _ = home
    assert not list(actions(view(data, "device-energy")))


def test_exclusions_flow_from_the_mapping_into_the_card():
    mapping = build.load_mapping()
    mapping["device_energy"]["exclude"] = ["Dryer"]
    mapping["device_energy"]["exclude_label"] = "no_energy_report"
    data, _ = build.build_dashboard(True, mapping)
    card = device_card(data)
    assert card["exclude"] == ["Dryer"] and card["exclude_label"] == "no_energy_report"


def test_generic_profile_needs_rates_before_showing_costs(generic):
    data, ent = generic
    assert "device_energy.rates" in ent.unresolved
    assert not [
        c
        for c in walk(view(data, "device-energy"))
        if c.get("type") == "custom:thermowatt-device-energy-card"
    ]
    assert "mapping needed" in json.dumps(view(data, "device-energy"))


def test_native_fallback_explains_that_the_card_is_required(native):
    data, _ = native
    text = json.dumps(view(data, "device-energy"))
    assert "needs the Thermowatt card" in text and "custom:" not in text


def test_device_energy_card_has_no_services_polling_or_cloud_calls():
    js = (ROOT / "homeowner/www/thermowatt-power-flow-card.js").read_text(encoding="utf-8")
    block = js[js.index("Device energy: <thermowatt-device-energy-card>") :]
    for forbidden in ("callService", "fetch(", "XMLHttpRequest", "WebSocket(", "setInterval"):
        assert forbidden not in block, forbidden
    requests = set(re.findall(r'type: "(recorder/[a-z_]+)"', block))
    assert requests == {"recorder/get_statistics_metadata", "recorder/statistics_during_period"}
    assert "callWS" in block and block.count("hass.callWS(") == 2


def test_device_energy_javascript_unit_tests():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [
            node,
            "--test",
            *sorted(str(path) for path in (ROOT / "tests/js").glob("*.test.mjs")),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "bad",
    [
        {"effective_from": None, "offpeak": -0.1, "peak": 0.2},
        {"effective_from": None, "offpeak": float("nan"), "peak": 0.2},
        {"effective_from": None, "offpeak": float("inf"), "peak": 0.2},
        {"effective_from": None, "offpeak": 0.1},
        {"effective_from": None, "offpeak": "cheap", "peak": 0.2},
        {"effective_from": "2026-02-30", "offpeak": 0.1, "peak": 0.2},
        {"effective_from": "July 2026", "offpeak": 0.1, "peak": 0.2},
    ],
)
def test_invalid_rate_entries_are_rejected_by_the_generator(bad):
    with pytest.raises(ValueError):
        build._validated_rates([bad])


def test_duplicate_rate_dates_are_rejected_and_valid_schedules_are_kept_as_given():
    with pytest.raises(ValueError):
        build._validated_rates(
            [
                {"effective_from": "2026-07-01", "offpeak": 0.1, "peak": 0.2},
                {"effective_from": "2026-07-01", "offpeak": 0.2, "peak": 0.3},
            ]
        )
    schedule = [
        {"effective_from": None, "offpeak": 0.1419, "peak": 0.1907},
        {"effective_from": "2027-07-01", "offpeak": 0.2, "peak": 0.3},
    ]
    assert build._validated_rates(schedule) == schedule


def test_device_energy_is_split_into_parts_that_use_the_screen_width(home):
    data, _ = home
    sections = view(data, "device-energy")["sections"]
    parts = [[c["part"] for c in section["cards"]] for section in sections]
    assert parts == [["summary", "balance"], ["daily", "monthly"], ["history"]]


def test_whole_house_sources_come_from_the_mapping_not_from_code(home):
    data, _ = home
    energy = build.load_mapping()["energy"]
    house = device_card(data)["house"]
    assert house == {
        "solar": energy["solar_today_energy"]["entity"],
        "import": energy["grid_import_total"]["entity"],
        "export": energy["grid_export_total"]["entity"],
        "battery_present": False,  # the owner's confirmed battery-free installation
    }
    # every part of the view shares one configuration (one statistics load)
    parts = [c for c in walk(view(data, "device-energy")) if c.get("type") == DEVICE_ENERGY_TYPE]
    assert {
        json.dumps({k: v for k, v in c.items() if k != "part"}, sort_keys=True) for c in parts
    } == {json.dumps({k: v for k, v in parts[0].items() if k != "part"}, sort_keys=True)}


def test_house_battery_presence_is_passed_through_exactly():
    assert (
        build._house_sources(
            {
                "energy": {
                    "battery_present": False,
                    "grid_import_total": {"entity": "sensor.i", "status": "verified"},
                }
            }
        )["battery_present"]
        is False
    )
    assert (
        build._house_sources(
            {
                "energy": {
                    "battery_present": "unknown",
                    "grid_import_total": {"entity": "sensor.i", "status": "verified"},
                }
            }
        )["battery_present"]
        == "unknown"
    )
    assert (
        build._house_sources(
            {
                "energy": {
                    "battery_present": True,
                    "grid_import_total": {"entity": "sensor.i", "status": "verified"},
                }
            }
        )["battery_present"]
        is True
    )
    assert build._house_sources({"energy": {}}) is None  # nothing mapped: nothing invented


def test_the_balance_never_creates_helpers_pollers_or_new_meters(home):
    """The balance reuses recorder statistics: the energy package is unchanged by it."""
    package = build.build_package(build.load_mapping())
    unique_ids = {i["unique_id"] for i in package["template"][0]["sensor"]}
    assert not any("balance" in unique for unique in unique_ids)
    assert "recorder/statistics_during_period" in (
        ROOT / "homeowner/www/thermowatt-power-flow-card.js"
    ).read_text(encoding="utf-8")


def test_unverified_inverter_mappings_are_never_used_for_the_balance():
    mapping = {
        "energy": {
            "battery_present": False,
            "solar_today_energy": {"entity": "sensor.solar", "status": "verified"},
            "grid_import_total": {"entity": "sensor.import", "status": "owner-confirmed"},
            "grid_export_total": {"entity": "sensor.export", "status": "unverified"},
        }
    }
    house = build._house_sources(mapping)
    assert house == {"solar": "sensor.solar", "import": "sensor.import", "battery_present": False}
