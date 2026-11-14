"""Structure, safety and consistency of the generated package and dashboard."""

from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from jinja2.sandbox import SandboxedEnvironment
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_monitoring import build, report  # noqa: E402
from energy_monitoring.dashboard import (  # noqa: E402
    CARD_TYPES,
    build_dashboard,
    referenced_entities,
    walk_cards,
)
from energy_monitoring.mapping import DEFAULT_MAP, load, tracked_sources, validate  # noqa: E402
from energy_monitoring.package import build_package, package_entities, slug  # noqa: E402
from energy_template_shim import render  # noqa: E402

READ_ONLY_DOMAINS = {"sensor", "binary_sensor", "input_number"}
FORBIDDEN_KEYS = {
    "tap_action",
    "hold_action",
    "double_tap_action",
    "service",
    "action",
    "perform_action",
    "automation",
    "script",
    "mqtt",
    "rest_command",
    "shell_command",
    "notify",
    "switch",
    "button",
}
FORBIDDEN_WORDS = ("water_heater.", "switch.", "button.", "mqtt", "homeassistant.turn")


def raw_map():
    return yaml.safe_load(DEFAULT_MAP.read_text(encoding="utf-8"))


def variant(meters=0, **edits):
    """The default map with the first ``meters`` CTs mapped, then edited.

    An edit key is a path joined by ``__``, for example ``circuits__0__energy``.
    """
    raw = raw_map()
    for circuit in raw["circuits"][:meters]:
        circuit["power"] = f"sensor.ct_{circuit['key']}_power"
    for path, value in edits.items():
        target = raw
        *parents, leaf = path.split("__")
        for parent in parents:
            target = target[int(parent) if parent.isdigit() else parent]
        target[int(leaf) if leaf.isdigit() else leaf] = value
    return validate(raw)


VARIANTS = {
    "no_meter": variant(0),
    "hot_water_only": variant(1),
    "two_circuits": variant(2),
    "three_circuits": variant(3),
    "native_energy": variant(3, circuits__0__energy="sensor.ct_hot_water_energy"),
    "plug_behind_ct": variant(3, appliances__0__circuit="oven"),
    "no_appliances": variant(1, appliances=[]),
    "own_rate_entities": variant(
        0,
        tariff__peak_rate_entity="sensor.retailer_peak_rate",
        tariff__feed_in_rate_entity="sensor.retailer_feed_in",
    ),
    "local_clock_no_forecast": variant(1, tariff__clock="local", solar__forecast_power=""),
}


def walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield path + (key,), value
            yield from walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + (index,))


def template_entities(package):
    for block in package["template"]:
        for kind in ("sensor", "binary_sensor"):
            yield from block.get(kind, [])


def map_entities(config):
    found = {value for _, value in walk(config) if isinstance(value, str) and "." in value}
    return {value for value in found if value.split(".")[0] in READ_ONLY_DOMAINS}


def test_committed_files_match_the_generator():
    assert build.main(["--check"]) == 0
    for name, text in build.render().items():
        committed = (build.GENERATED / name).read_text(encoding="utf-8")
        assert yaml.safe_load(text) == yaml.safe_load(committed)
        assert text.startswith("# GENERATED")


@pytest.mark.parametrize("name", VARIANTS)
def test_package_is_read_only_and_well_formed(name):
    package = build_package(VARIANTS[name])
    assert set(package) <= {"template", "sensor", "utility_meter", "input_number"}
    keys = {path[-1] for path, _ in walk(package) if isinstance(path[-1], str)}
    assert not keys & FORBIDDEN_KEYS
    text = build.dump(package)
    for word in FORBIDDEN_WORDS:
        assert word not in text

    entities = list(template_entities(package))
    unique = [item["unique_id"] for item in entities]
    unique += [item["unique_id"] for item in package["sensor"]]
    unique += [item["unique_id"] for item in package["utility_meter"].values()]
    assert len(unique) == len(set(unique))
    for item in [*entities, *package["sensor"]]:
        assert item["unique_id"] == slug(item["name"])
        assert item["unique_id"].startswith("em_")
    for key, meter in package["utility_meter"].items():
        assert slug(meter["name"]) == key

    environment = SandboxedEnvironment()
    templates = [value for _, value in walk(package) if isinstance(value, str) and "{" in value]
    assert templates
    for template in templates:
        environment.parse(template)


@pytest.mark.parametrize("name", VARIANTS)
def test_sensor_classes_are_valid_for_statistics(name):
    for item in template_entities(build_package(VARIANTS[name])):
        device = item.get("device_class")
        state = item.get("state_class")
        unit = item.get("unit_of_measurement")
        if device == "energy":
            assert (state, unit) == ("total_increasing", "kWh"), item["name"]
        if device == "monetary":
            assert (state, unit) == ("total", "AUD"), item["name"]
        if device == "power":
            assert (state, unit) == ("measurement", "W"), item["name"]
        if unit == "kWh" and state:
            assert device == "energy", item["name"]
        if "today" in item["name"] or "this month" in item["name"]:
            assert state is None, f"{item['name']}: a display value must not create statistics"


@pytest.mark.parametrize("name", VARIANTS)
def test_every_internal_reference_resolves(name):
    """Any em_ entity a template or meter reads must be created by the package."""
    config = VARIANTS[name]
    package = build_package(config)
    created = package_entities(config)
    pattern = r"(?:sensor|binary_sensor|input_number)\.em_[a-z0-9_]+"
    used = set(re.findall(pattern, build.dump(package)))
    assert used <= created, used - created
    for item in package["sensor"]:
        assert (item.get("source") or item["entity_id"]) in created
    for meter in package["utility_meter"].values():
        assert meter["source"] in created | map_entities(config)


@pytest.mark.parametrize("name", VARIANTS)
def test_dashboard_is_read_only_and_every_entity_exists(name):
    config = VARIANTS[name]
    dashboard = build_dashboard(config)
    cards = list(walk_cards(dashboard))
    assert cards and {card["type"] for card in cards} <= CARD_TYPES
    keys = {path[-1] for path, _ in walk(dashboard) if isinstance(path[-1], str)}
    assert not keys & FORBIDDEN_KEYS
    known = package_entities(config) | map_entities(config)
    used = referenced_entities(dashboard)
    assert used <= known, used - known
    assert {entity.split(".")[0] for entity in used} <= READ_ONLY_DOMAINS
    editable = {entity for entity in used if entity.startswith("input_number.")}
    assert all("rate" in entity or "supply" in entity for entity in editable)
    paths = [page["path"] for page in dashboard["views"]]
    assert len(paths) == len(set(paths)) == 7


@pytest.mark.parametrize("name", VARIANTS)
def test_statistics_cards_only_use_entities_with_long_term_statistics(name):
    config = VARIANTS[name]
    package = build_package(config)
    recorded = {
        f"sensor.{item['unique_id']}"
        for item in template_entities(package)
        if item.get("state_class")
    }
    recorded |= {
        f"sensor.{item['unique_id']}"
        for item in package["sensor"]
        if item["platform"] == "integration"
    }
    allowed = recorded | map_entities(config)
    for card in walk_cards(build_dashboard(config)):
        if card["type"] == "statistic":
            assert card["entity"] in allowed, card["entity"]
        if card["type"] == "statistics-graph":
            for row in card["entities"]:
                assert row["entity"] in allowed, row["entity"]


def test_hot_water_sensors_exist_only_when_the_ct_is_mapped():
    without = package_entities(VARIANTS["no_meter"])
    with_meter = package_entities(VARIANTS["hot_water_only"])
    assert {
        "sensor.em_hot_water_power",
        "sensor.em_hot_water_energy",
        "sensor.em_hot_water_grid_energy",
        "sensor.em_hot_water_solar_energy",
        "sensor.em_hot_water_grid_cost",
        "sensor.em_hot_water_solar_opportunity_cost",
        "sensor.em_hot_water_last_cycle",
        "sensor.em_hot_water_element_runtime_today",
        "binary_sensor.em_hot_water_element_on",
    } <= with_meter
    assert not {entity for entity in without if "hot_water" in entity}
    text = build.dump(build_dashboard(VARIANTS["no_meter"]))
    assert "The hot-water CT is not mapped yet" in text
    assert "Expected completion" in text
    assert VARIANTS["no_meter"]["hot_water"]["expected_completion"] in text
    unmapped = variant(0, hot_water__expected_completion="")
    assert "Expected completion** is not exposed" in build.dump(build_dashboard(unmapped))


def test_hot_water_sensors_do_not_depend_on_the_optional_circuits():
    """The hot-water interface is the same with or without the AC and oven CTs."""
    alone = build_package(VARIANTS["hot_water_only"])
    full = build_package(VARIANTS["three_circuits"])

    def hot_water(package):
        found = {}
        for block in package["template"]:
            for kind in ("sensor", "binary_sensor"):
                for item in block.get(kind, []):
                    if "hot water" in item["name"]:
                        found[item["name"]] = item
        found.update({i["name"]: i for i in package["sensor"] if "hot water" in i["name"]})
        return found

    assert hot_water(alone) == hot_water(full)
    text = build.dump({"hot_water": list(hot_water(full).values())})
    assert "air_conditioner" not in text and "oven" not in text


@pytest.mark.parametrize("document", ["ENTITY_CONTRACT.md", "README.md"])
def test_documented_entity_ids_are_the_generated_ones(document):
    text = (DEFAULT_MAP.parent / document).read_text(encoding="utf-8")
    pattern = r"(?:sensor|binary_sensor|input_number)\.em_[a-z0-9_<>]+"
    documented = set()
    for entity in re.findall(pattern, text):
        keys = ("hot_water", "air_conditioner", "oven") if "<key>" in entity else ("",)
        documented |= {entity.replace("<key>", key) for key in keys}
    assert documented
    created = package_entities(VARIANTS["three_circuits"])
    assert documented <= created, documented - created


def test_a_native_energy_entity_replaces_the_riemann_sum():
    riemann = {item["name"] for item in build_package(VARIANTS["hot_water_only"])["sensor"]}
    native = {item["name"] for item in build_package(VARIANTS["native_energy"])["sensor"]}
    assert "EM hot water energy" in riemann and "EM hot water energy" not in native
    assert "sensor.em_hot_water_energy" in package_entities(VARIANTS["native_energy"])


def test_tracked_sources_never_overlap():
    config = VARIANTS["plug_behind_ct"]
    keys = [source["key"] for source in tracked_sources(config)]
    assert "dryer" not in keys and "oven" in keys and len(keys) == len(set(keys))
    assert "Dryer (on Oven)" in build.dump(build_dashboard(config))
    # With no CT on that circuit the plug is the only measurement, so it counts.
    unmetered = variant(1, appliances__0__circuit="oven")
    assert "dryer" in [source["key"] for source in tracked_sources(unmetered)]


def test_configured_rate_entities_replace_the_helpers():
    package = build_package(VARIANTS["own_rate_entities"])
    assert set(package["input_number"]) == {"em_off_peak_rate", "em_daily_supply_charge"}
    assert "sensor.retailer_peak_rate" in build.dump(package)
    assert all("initial" not in helper for helper in package["input_number"].values())


def test_no_rate_is_hard_coded():
    text = build.dump(build_package(VARIANTS["three_circuits"]))
    for rate in ("0.17", "0.36", "0.09"):
        assert rate not in text


def test_health_summary_markdown_renders():
    dashboard = build_dashboard(VARIANTS["three_circuits"])
    summaries = [
        card["content"]
        for card in walk_cards(dashboard)
        if card["type"] == "markdown" and "sensor.em_monitoring_health" in card["content"]
    ]
    assert len(summaries) == 1
    states = {
        "sensor.em_monitoring_health": {
            "state": "degraded",
            "attributes": {"missing": ["Dryer power"], "stale": [], "rates_set": False},
        },
        "sensor.em_untracked_power": {"state": 0, "attributes": {"raw_residual_w": -12.5}},
    }
    text = render(summaries[0], states)
    assert "Dryer power" in text and "**Stale:** none" in text and "NO: costs" in text
    assert "-12.5 W" in text
    assert "none" in render(summaries[0], {})  # before the package is installed


@pytest.mark.parametrize(
    "edits,message",
    [
        ({"version": 2}, "version"),
        ({"grid__power": ""}, "grid.power"),
        ({"grid__power": "Not An Entity"}, "not an entity ID"),
        ({"tariff__clock": "utc"}, "tariff.clock"),
        ({"tariff__utc_offset_hours": 30}, "utc_offset_hours"),
        ({"tariff__peak_windows__0__start": "7am"}, "HH:MM"),
        ({"tariff__peak_windows__0__end": "06:00"}, "end after it starts"),
        ({"tariff__peak_windows__0__days": [7]}, "days"),
        ({"circuits__1__key": "hot_water"}, "duplicated"),
        ({"circuits__1__key": "grid"}, "reserved"),
        ({"circuits__1__role": "hot_water"}, "only one circuit"),
        ({"circuits__0__energy": "sensor.x_energy"}, "needs a power entity"),
        ({"circuits__0__element_on_watts": 0}, "element_on_watts"),
        ({"appliances__0__circuit": "pool"}, "not a circuit key"),
        ({"appliances__0__key": "oven"}, "duplicated"),
        ({"freshness_seconds__core": -1}, "negative"),
    ],
)
def test_a_bad_map_is_rejected_with_a_clear_message(edits, message):
    with pytest.raises(ValueError, match=message):
        variant(0, **edits)


def test_more_than_three_circuits_is_rejected():
    raw = raw_map()
    raw["circuits"].append({"key": "pool", "name": "Pool", "power": "", "energy": ""})
    with pytest.raises(ValueError, match="at most 3"):
        validate(raw)


def test_an_end_of_midnight_means_the_end_of_the_day():
    config = variant(0, tariff__peak_windows=[{"days": [5], "start": "22:00", "end": "00:00"}])
    assert config["tariff"]["peak_windows"] == [{"days": [5], "start": 1320, "end": 1440}]


def test_build_writes_to_a_chosen_directory(tmp_path, capsys):
    assert build.main(["--out", str(tmp_path)]) == 0
    assert build.main(["--out", str(tmp_path), "--check"]) == 0
    (tmp_path / build.PACKAGE_FILE).write_text("stale", encoding="utf-8")
    assert build.main(["--out", str(tmp_path), "--check"]) == 1
    assert "out of date" in capsys.readouterr().err


def test_report_rolls_statistics_up_by_local_calendar_period(tmp_path, capsys):
    config = load()
    hobart = ZoneInfo("Australia/Hobart")

    def rows(values):
        # Each day's start as UTC, which is how the Recorder stores it.
        return [
            {
                "start": datetime(2026, 10, day, tzinfo=hobart)
                .astimezone(timezone.utc)
                .isoformat(),
                "change": value,
            }
            for day, value in values.items()
        ]

    epoch_ms = datetime(2026, 10, 5, tzinfo=hobart).timestamp() * 1000
    response = {
        "statistics": {
            config["solar"]["energy"]: rows({3: 20.0, 4: 22.0, 5: 18.0}),
            config["grid"]["import_energy"]: rows({3: 5.0, 4: 6.0, 5: 7.5})
            + [
                {"start": epoch_ms, "change": 1.0},
                {"start": "2026-10-06T13:00:00+00:00", "change": None},
            ],
            "sensor.em_grid_import_cost": rows({4: 1.25}),
        }
    }
    weekly = report.table(response, config, "week", hobart)
    # Sat 3 and Sun 4 Oct (the night the clocks go forward) are ISO week 40.
    assert "| 2026-W40 | 42.00 | 11.00 | 1.25 |" in weekly
    assert "| 2026-W41 | 18.00 | 8.50 | – |" in weekly
    assert "Not in the response: House" in weekly
    assert report.table({}, config, "day", hobart).startswith("No matching")

    saved = tmp_path / "response.yaml"
    saved.write_text(yaml.safe_dump(response), encoding="utf-8")
    assert report.main([str(saved), "--period", "year"]) == 0
    assert "| 2026 | 60.00 | 19.50 | 1.25 |" in capsys.readouterr().out
    assert report.main(["--request"]) == 0
    request = yaml.safe_load(capsys.readouterr().out)
    assert request["action"] == "recorder.get_statistics"
    assert request["data"]["period"] == "day" and request["data"]["types"] == ["change"]
    assert "sensor.em_untracked_energy" in request["data"]["statistic_ids"]
    assert "sensor.em_hot_water_grid_cost" not in request["data"]["statistic_ids"]
