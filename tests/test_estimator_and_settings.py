"""Shadow Planner 0.4.0: dynamic deadlines, 42 °C, freshness, heater state,
incremental economics, native awareness. Offline; no HA, cloud or heater."""

from datetime import time, timedelta
import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from test_shadow_model import c, m, local, readings, runtime  # noqa: F401

hs = importlib.import_module(f"{m.__package__}.heater_state")
settings_mod = importlib.import_module(f"{m.__package__}.settings")

FEED, OFF, PEAK = 0.09276, 0.1702, 0.361878


def owner(**options):
    return c.parse_options(options)


def hobart(at):
    return at.astimezone(m.HOBART)


# --- 1. Tariff and dynamic deadlines ---------------------------------------------


# Aurora's 2026-27 schedule has no public-holiday exception: a weekday
# public holiday (Eight Hours Day, 9 Mar) follows weekday periods.


# --- 2. Incremental economics -----------------------------------------------------


# --- 3. Heater-state estimator ----------------------------------------------------


def feed_minutes(estimator, start, values, status, status_at, window=True):
    result = None
    for minute, house in enumerate(values):
        at = start + timedelta(minutes=minute)
        result = estimator.update(at, house, status, status_at, window)
    return result


def test_estimator_on_off_unknown_and_contradictions():
    now = local(hour=11)
    est = hs.HeaterStateEstimator()
    assert est.update(now, 3.9, 33, now, True).state == "on"
    assert est.update(now, 3.9, 33, now, True).confidence == "high"
    result = hs.HeaterStateEstimator().update(now, 0.9, 33, now, True)
    assert result.state == "off" and "status_bit_on_contradicted_by_house_load" in result.basis
    assert hs.HeaterStateEstimator().update(now, 3.9, None, None, True).state == "unknown"
    assert hs.HeaterStateEstimator().update(now, None, 33, now, True).confidence == "low"
    verified = hs.HeaterStateEstimator().update(now, 3.9, 32, now, True, heater_power_kw=2.98)
    assert verified.state == "on" and verified.confidence == "verified"
    stale = hs.HeaterStateEstimator().update(now, 3.9, 33, now - timedelta(minutes=50), True)
    assert stale.state == "unknown"  # poll too old to use the status bit


def test_estimator_catches_switch_on_after_poll_and_masked_switch_off():
    start = local(hour=11)
    est = hs.HeaterStateEstimator()
    poll = start - timedelta(minutes=1)
    result = feed_minutes(est, start, [0.8] * 6 + [3.9] * 8, 32, poll)
    assert result.state == "on" and "3kW_step_up_after_last_poll" in result.basis
    # Element stops while a 2.7 kW appliance runs: no sharp step, stale bit 1.
    est = hs.HeaterStateEstimator()
    poll = start
    feed_minutes(est, start, [3.9] * 10, 33, poll)
    later = start + timedelta(minutes=10)
    # Real 10 Nov pattern: load dips below 2.6 kW, then a ~2.7 kW appliance.
    result = feed_minutes(est, later, [2.4, 2.5, 2.7, 2.7, 2.65, 2.7], 33, poll)
    assert result.state == "off", result.basis
    assert "status_bit_older_than_observed_switch_off" in result.basis


# --- 4. Freshness (Stage 1 F1) and runtime --------------------------------------------


# --- 5. Settings, migration and truthful defaults --------------------------------------


def test_new_defaults_and_original_values_are_truthful():
    assert c.DEFAULT_OPTIONS["morning_threshold_c"] == 42.0
    info = settings_mod.describe("morning_threshold_c", 40.0)
    assert info["recommended_default"] == 42.0 and info["original_default"] == 40.0
    assert not info["recommended_equals_original"]
    assert settings_mod.describe("morning_time", "07:00")["original_default"] == "07:00"
    settings, _ = c.parse_options({})
    assert settings.shower_time == time(7) and not settings.shower_time_enabled
    assert settings.morning == time(8) and settings.pv_ac_limit_kw == 5.0


@pytest.mark.parametrize(
    "key,value",
    [
        ("shower_time", "12:30"),
        ("expected_morning_draw_c", 41),
        ("wait_benefit_aud_per_kwh", -0.1),
        ("pv_ac_limit_kw", 0.5),
        ("base_load_source", "guess"),
        ("shower_time_enabled", "yes"),
    ],
)
def test_new_settings_validate_atomically(key, value):
    with pytest.raises((ValueError, TypeError)):
        c.parse_options({key: value})


def test_entry_migration_moves_only_the_untouched_old_threshold(monkeypatch):
    import sys
    from types import ModuleType

    for name in (
        "homeassistant",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.config_validation",
        "homeassistant.helpers.event",
        "homeassistant.util",
    ):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules["homeassistant.const"].Platform = SimpleNamespace(
        **{
            k: k.lower()
            for k in ("SENSOR", "NUMBER", "TIME", "SWITCH", "SELECT", "TEXT", "BUTTON", "DATETIME")
        }
    )
    sys.modules["homeassistant.core"].callback = lambda f: f
    sys.modules["homeassistant.helpers.config_validation"].config_entry_only_config_schema = (
        lambda d: None
    )
    sys.modules["homeassistant.helpers"].config_validation = sys.modules[
        "homeassistant.helpers.config_validation"
    ]
    sys.modules["homeassistant.helpers.event"].async_track_time_interval = None
    sys.modules["homeassistant.helpers.event"].async_track_state_change_event = None
    monkeypatch.setitem(sys.modules, f"{m.__package__}.executor", ModuleType("ex"))
    sys.modules[f"{m.__package__}.executor"].Executor = object
    sys.modules["homeassistant.util"].dt = SimpleNamespace(utcnow=lambda: local())
    spec = importlib.util.spec_from_file_location(
        f"{m.__package__}.__init__", c.__file__.replace("config.py", "__init__.py")
    )
    monkeypatch.setitem(sys.modules, f"{m.__package__}.runtime", ModuleType("rt"))
    sys.modules[f"{m.__package__}.runtime"].ShadowRuntime = object
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(options, minor=1):
        updates = {}
        entry = SimpleNamespace(version=1, minor_version=minor, options=options)
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=lambda e, **kw: updates.update(kw))
        )
        coroutine = module.async_migrate_entry(hass, entry)
        try:
            coroutine.send(None)  # no awaits inside: completes immediately
        except StopIteration as done:
            assert done.value is True
        return updates

    assert run({"morning_threshold_c": 40.0})["options"]["morning_threshold_c"] == 42.0
    assert run({"morning_threshold_c": 45.0})["options"]["morning_threshold_c"] == 45.0
    assert run({})["minor_version"] == 3
    # 1.2 entries keep their threshold and only get the 0.7.1 range check.
    assert run({"morning_threshold_c": 40.0}, minor=2)["options"]["morning_threshold_c"] == 40.0
    assert run({"morning_threshold_c": 40.0}, minor=3) == {}
    # 0.7.1: out-of-range values move to the nearest allowed value; others stay.
    moved = run(
        {
            "status_max_age_minutes": 30.0,
            "forecast_max_age_minutes": 15.0,
            "peak_rate": 3.0,
            "controller_max_commands_per_day": 5.5,
            "controller_min_rest_minutes": 240.0,
            "controller_notify_service": "notify.mobile_app_phone",
            "target_c": 66.0,
        },
        minor=2,
    )["options"]
    assert moved == {
        "status_max_age_minutes": 35.0,
        "forecast_max_age_minutes": 35.0,
        "peak_rate": 2.0,
        "controller_max_commands_per_day": 5.0,
        "controller_min_rest_minutes": 60.0,
        "controller_notify_service": "mobile_app_phone",
        "target_c": 66.0,
    }
    c.parse_options(moved)  # the migrated entry loads
    untouched = c.saved_options({})
    assert run(dict(untouched), minor=2)["options"] == untouched


# --- Review of ac38eaf (ChatGPT): satisfied lifetime, block rules, presentation ----
