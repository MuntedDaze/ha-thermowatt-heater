"""Offline model/contract/scenario checks; pure modules need no HA installation."""

from datetime import datetime
import importlib
from pathlib import Path
import sys
from types import ModuleType
import json
import ast
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "custom_components/thermann_shadow"
# Load the standalone model/config without executing the HA integration adapter.
package = ModuleType("_shadow_model_tests")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package
m = importlib.import_module(f"{package.__name__}.model")
c = importlib.import_module(f"{package.__name__}.config")


def local(year=2026, month=11, day=10, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=m.HOBART).astimezone(m.UTC)


def readings(now, temperature=50, grid=4000):
    return {
        key: m.Reading(value, now, unit)
        for key, value, unit in [
            ("temperature", temperature, "°C"),
            ("target", 70, "°C"),
            ("mode", "Schedule", None),
            ("last_poll", now.isoformat(), None),
            ("cloud_health", "ok", None),
            ("grid", grid, "W"),
        ]
    }


@pytest.fixture
def tariffs():
    weekdays, weekend = tuple(range(5)), (5, 6)
    result = tuple(
        m.Tariff(weekdays, start, end, rate, kind)
        for start, end, rate, kind in [
            (0, 7 * 60, 0.2, "off_peak"),
            (7 * 60, 10 * 60, 0.5, "peak"),
            (10 * 60, 16 * 60, 0.2, "off_peak"),
            (16 * 60, 21 * 60, 0.5, "peak"),
            (21 * 60, 0, 0.2, "off_peak"),
        ]
    ) + (m.Tariff(weekend, 0, 0, 0.2, "off_peak"),)
    m.validate_tariffs(result, "local")
    return result


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"days": [0], "start": "00:00", "end": "00:00", "kind": "off_peak"}],
        [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "25:00", "end": "00:00", "kind": "off_peak"}],
    ],
)
def test_tariff_gaps_or_invalid_periods_are_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        c.parse_options({"tariff_periods": json.dumps(bad)})


@pytest.mark.parametrize(
    "option,value",
    [
        ("target_c", 40),
        ("target_c", 71),
        ("feed_in_rate", float("nan")),
        ("meter_verified", "true"),
        ("tariff_clock", "UTC"),
        ("status_max_age_minutes", 500),
        ("peak_rate", 100),
    ],
)
def test_bad_settings_rejected(option, value):
    with pytest.raises((ValueError, TypeError)):
        c.parse_options({option: value})


def test_sources_defaults_match_owner_and_validate_only_provisional_sign():
    settings, _ = c.parse_options({})
    assert settings.import_positive is False
    assert settings.meter_verified is settings.tariff_verified is True
    assert settings.tariff_clock == "standard"
    assert c.DEFAULT_SOURCES["heater"] == "water_heater.home_boiler_home"
    assert c.DEFAULT_SOURCES["mode"] == "sensor.home_boiler_home_vendor_mode"


def test_only_the_executor_can_actuate_and_no_network_imports():
    """0.5.0: exactly ONE module (executor.py) may publish a heater command or
    call a service, and it may only publish through HA's MQTT helper and call
    notify services. The planner, controller logic and entities cannot."""
    forbidden = {"requests", "socket", "aiohttp", "paho", "httpx", "subprocess"}
    actuation = {"async_call", "publish", "async_publish", "async_register", "open_connection"}
    seen = {}
    for path in PACKAGE.glob("*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.split(".")[0] in forbidden for n in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
            if isinstance(node, ast.Attribute) and node.attr in actuation:
                seen.setdefault(path.name, set()).add(node.attr)
        assert "_attr_state_class" not in source
    assert seen == {"executor.py": {"async_publish", "async_call"}}
    executor = (PACKAGE / "executor.py").read_text()
    # One command publish, and one guarded on-demand status request (refresh topic only).
    assert executor.count("mqtt.async_publish(") == 2
    assert "refresh_topic(self.cfg.command_topic)" in executor
    assert '"notify",' in executor and executor.count(".async_call(") == 1
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    assert manifest["requirements"] == [] and manifest["version"] == "0.9.1"
    assert manifest["integration_type"] == "hub"
    assert "mqtt" not in manifest.get("dependencies", [])  # loads without MQTT


@pytest.fixture
def runtime(monkeypatch):
    clock = [local()]
    util = ModuleType("homeassistant.util")
    util.dt = SimpleNamespace(utcnow=lambda: clock[0])
    ha = ModuleType("homeassistant")
    ha.__path__ = []
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.util", util)
    spec = importlib.util.spec_from_file_location(
        f"{package.__name__}.runtime", PACKAGE / "runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    states = {}
    hass = SimpleNamespace(
        states=SimpleNamespace(get=states.get),
        config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")),
    )
    settings, tariffs = c.parse_options({})
    instance = module.ShadowRuntime(hass, c.DEFAULT_SOURCES, settings, tariffs)

    def report(key, value, attrs=None, at=None):
        entity = c.DEFAULT_PV_AC if key == "pv_ac" else c.DEFAULT_SOURCES[key]
        when = at or clock[0]
        states[entity] = SimpleNamespace(
            state=str(value), attributes=attrs or {}, last_reported=when, last_updated=when
        )

    report("heater", "unknown", {"current_temperature": 63, "temperature": 70})
    for key, value in {
        "mode": "Schedule",
        "last_poll": clock[0].isoformat(),
        "cloud_health": "ok",
        "requests": 4,
    }.items():
        report(key, value)
    for key, value in {"grid": 1501, "pv": 2322, "pv_ac": 2322, "house": 821}.items():
        report(key, value, {"unit_of_measurement": "W"})
    return instance, report, clock


def test_custom_settings_and_dashboard_have_no_control_actions():
    import yaml

    translation = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    steps = translation["options"]["step"]
    shown = set(steps["preferences"]["data"]) | set(steps["system"]["data"])
    catalog = importlib.import_module(f"{package.__name__}.settings")
    # 0.8.0: every setting is on exactly one Configure page, except retired ones.
    assert shown == set(c.DEFAULT_OPTIONS) - catalog.RETIRED
    assert not set(steps["preferences"]["data"]) & set(steps["system"]["data"])
    assert set(steps["init"]["menu_options"]) == {"preferences", "system", "sources"}
    dashboard = yaml.safe_load(
        (ROOT / "shadow_controller/dashboard.yaml").read_text(encoding="utf-8")
    )
    content = json.dumps(dashboard)
    for forbidden in ("call-service", "water_heater.", "/CMD/", "/refresh"):
        assert forbidden not in content
    # The only dashboard actions restore/undo LOCAL preferences, with confirmation.
    # Walk nested sections/grids so no action can hide inside a container card.
    actions = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("tap_action", "hold_action", "double_tap_action"):
                if isinstance(node.get(key), dict) and node[key].get("action") not in {
                    None,
                    "navigate",
                    "more-info",
                    "none",
                }:
                    actions.append(node[key])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(dashboard)
    # Restore/undo local preferences, plus the controller's owner buttons
    # (hold / resume / acknowledge), each with a confirmation. None commands the heater.
    assert {action["target"]["entity_id"] for action in actions} == {
        "button.thermann_shadow_restore_recommended_preferences",
        "button.thermann_shadow_undo_last_restore",
        "button.thermann_shadow_hold_heater_owner_override",
        "button.thermann_shadow_resume_automatic_control",
        "button.thermann_shadow_acknowledge_controller_fault",
    }
    for action in actions:
        assert action["action"] == "perform-action" and action["perform_action"] == "button.press"
        assert action["confirmation"]["text"]
