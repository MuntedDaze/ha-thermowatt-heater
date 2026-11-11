"""Offline model/contract/scenario checks; pure modules need no HA installation."""

from dataclasses import replace
from datetime import datetime, time, timedelta
import importlib
from pathlib import Path
import sys
from types import ModuleType
import json
import ast
from types import SimpleNamespace
from types import MappingProxyType

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


def plan(now, tariffs, values=None, **changes):
    settings = replace(
        m.Settings(target_c=65, meter_verified=True, tariff_verified=True, import_positive=False),
        **changes,
    )
    return m.evaluate(now, now - timedelta(minutes=1), values or readings(now), settings, tariffs)


def test_unconfirmed_owner_settings_show_only_labelled_thermal_estimate(tariffs):
    now = local()
    result = m.evaluate(
        now,
        now - timedelta(minutes=1),
        readings(now, temperature=63, grid=1501),
        m.Settings(target_c=65),
        tariffs,
    )
    assert result.state == "shadow_awaiting_validation"
    assert result.mixed_model_energy_kwh == pytest.approx(0.733, abs=0.0005)
    assert result.estimated_cost_aud is None and result.windows == []
    assert result.peak_start is None
    assert "thermal_model_unqualified" in result.warnings


def test_solar_first_with_qualified_net_export_forecast(tariffs):
    now = local()
    forecast = (m.Forecast(now + timedelta(hours=1), now + timedelta(hours=4), 4),)
    settings = m.Settings(
        target_c=65, meter_verified=True, tariff_verified=True, import_positive=False
    )
    result = m.evaluate(
        now, now - timedelta(minutes=1), readings(now, grid=0), settings, tariffs, forecast
    )
    assert result.state == "shadow_wait_for_window"
    assert result.planned_start == now + timedelta(hours=1)
    assert result.estimated_import_kwh == 0
    assert result.estimated_solar_kwh == pytest.approx(15 * m.TANK_KWH_PER_C + 1.5, abs=0.001)
    assert result.estimated_cost_aud == pytest.approx(result.estimated_solar_kwh * 0.08, abs=0.001)
    assert all(w["source"] == "net_solar" for w in result.windows)


@pytest.mark.parametrize("grid", [0, -4000, 1501, 3000, 3299])
def test_cloudy_no_solar_or_inadequate_export_does_not_claim_solar_only(grid, tariffs):
    now = local()
    result = plan(now, tariffs, readings(now, grid=grid))
    assert result.state != "shadow_solar_opportunity"
    assert result.estimated_import_kwh > 0
    assert result.estimated_solar_kwh <= 3 / 60
    assert "no_net_surplus_forecast_current_export_not_extrapolated" in result.warnings


def test_confirmed_export_uses_only_bounded_solar_window(tariffs):
    now = local()
    result = m.evaluate(
        now,
        now - timedelta(minutes=1),
        readings(now),
        m.Settings(target_c=65, meter_verified=True, tariff_verified=True, import_positive=False),
        tariffs,
        solar_confirmed=True,
    )
    assert result.state == "shadow_solar_opportunity"
    assert result.estimated_solar_kwh == pytest.approx(0.75)
    assert result.estimated_import_kwh > 6


def test_deadline_shortfall_is_not_counted_as_cost_saving(tariffs):
    now = local(hour=6, minute=50)
    result = plan(now, tariffs, readings(now, temperature=17, grid=0))
    assert result.state == "shadow_shortfall"
    assert result.unmet_model_energy_kwh > 9
    assert result.estimated_import_kwh == pytest.approx(0.5)
    assert result.comparison_cost_difference_aud == pytest.approx(0)
    assert "comfort_at_risk_native_or_owner_action_required" in result.warnings


@pytest.mark.parametrize("temperature", [40, 65, 70])
def test_temperature_is_not_a_hygiene_or_reserve_measurement(temperature, tariffs):
    result = plan(local(), tariffs, readings(local(), temperature=temperature))
    assert "bottom_temperature_used_directly_planning_estimate_only" in result.warnings
    assert "hygiene_and_native_fallback_unverified" in result.warnings
    if temperature == 40:
        assert result.mixed_model_energy_kwh > 9
    else:
        assert result.state == "shadow_no_modelled_topup"
        assert "storage_target_met" in result.reasons[0]


@pytest.mark.parametrize(
    "state", ["quota_limited", "auth_locked", "disabled", "backoff", "unavailable"]
)
def test_cloud_failure_never_produces_heating_plan(state, tariffs):
    now = local()
    values = readings(now)
    values["cloud_health"] = replace(values["cloud_health"], value=state)
    result = plan(now, tariffs, values)
    assert result.state == "shadow_blocked"
    assert result.windows == []
    assert "cloud_not_healthy" in result.reasons


@pytest.mark.parametrize(
    "key", ["grid", "temperature", "target", "last_poll", "mode", "cloud_health"]
)
@pytest.mark.parametrize("failure", ["missing", "stale", "restored", "future"])
def test_missing_stale_restored_future_sources_fail_closed(key, failure, tariffs):
    now = local()
    values = readings(now)
    if failure == "missing":
        del values[key]
    elif failure == "stale":
        values[key] = replace(values[key], observed_at=now - timedelta(hours=2))
    elif failure == "future":
        values[key] = replace(values[key], observed_at=now + timedelta(seconds=1))
    else:
        values[key] = replace(values[key], restored=True)
    result = plan(now, tariffs, values)
    if key != "grid" and failure in {"stale", "future"}:
        # 0.4.0 (Stage 1 F1): HA MQTT entities keep their old report time when a
        # poll repeats the same value. Cloud readings are proven fresh by the
        # bridge's poll timestamp, so an old/odd entity report time is NOT stale.
        assert result.state != "shadow_blocked", result.reasons
        return
    assert result.state == "shadow_blocked" and result.windows == []


def test_missed_polls_and_restart_wait_for_new_poll_without_any_refresh(tariffs):
    now = local()
    values = readings(now)
    values["last_poll"] = replace(
        values["last_poll"], value=(now - timedelta(minutes=46)).isoformat()
    )
    assert plan(now, tariffs, values).reasons == ["status_stale_or_pre_restart"]
    result = m.evaluate(now, now + timedelta(seconds=1), readings(now), m.Settings(), tariffs)
    assert result.state == "shadow_blocked"
    assert result.windows == []


@pytest.mark.parametrize(
    "mode,target,intervention",
    [
        ("Manual", 70, False),
        ("Off", 70, False),
        ("Unknown", 70, False),
        ("Eco", 70, False),
        ("Holiday", 70, False),
        ("Schedule", 65, False),
        ("Schedule", 70, True),
    ],
)
def test_manual_intervention_never_acquires_or_restores_control(
    mode, target, intervention, tariffs
):
    now = local()
    values = readings(now)
    values["mode"] = replace(values["mode"], value=mode)
    values["target"] = replace(values["target"], value=target)
    result = m.evaluate(
        now,
        now - timedelta(minutes=1),
        values,
        m.Settings(meter_verified=True, tariff_verified=True),
        tariffs,
        intervention=intervention,
    )
    assert result.state == "shadow_native_intervention" and result.windows == []


@pytest.mark.parametrize(
    "value,unit",
    [
        (1.5, "MW"),
        (1501, "kWh"),
        (float("nan"), "W"),
        (float("inf"), "kW"),
        (True, "W"),
        (31000, "W"),
        ("PRIVATE_SENSITIVE_STATE", "W"),
    ],
)
def test_bad_meter_units_and_values_are_not_guessed_or_exposed(value, unit, tariffs):
    now = local()
    values = readings(now)
    values["grid"] = replace(values["grid"], value=value, unit=unit)
    result = plan(now, tariffs, values)
    assert result.state == "shadow_blocked" and result.windows == []
    assert "PRIVATE_SENSITIVE_STATE" not in str(result)


def test_meter_sign_units_and_split_inputs_are_explicit(tariffs):
    now = local()
    expected = plan(now, tariffs, readings(now, grid=1501)).net_export_kw
    values = readings(now, grid=-1.501)
    values["grid"] = replace(values["grid"], unit="kW")
    assert plan(now, tariffs, values, import_positive=True).net_export_kw == expected
    del values["grid"]
    values.update(grid_import=m.Reading(0, now, "W"), grid_export=m.Reading(1501, now, "W"))
    assert plan(now, tariffs, values).net_export_kw == expected


@pytest.mark.parametrize("month,day,hours", [(4, 5, 7.5), (10, 4, 5.5)])
def test_tasmania_dst_deadlines_follow_local_calendar(month, day, hours, tariffs):
    now = local(month=month, day=day, hour=0, minute=30)
    # Both DST change days are Sundays (no peak): the household morning time
    # applies. Pin it to 07:00 so this test still checks the 23 h/25 h arithmetic.
    result = plan(now, tariffs, morning=time(7))
    assert result.deadline.astimezone(m.HOBART).hour == 7
    assert (result.deadline - now).total_seconds() / 3600 == hours


def test_weekends_and_fixed_standard_tariff_clock(tariffs):
    weekend = plan(local(day=14), tariffs)
    assert weekend.peak_start is None
    assert weekend.comfort_deadline.astimezone(m.HOBART).hour == 16
    moment = local(hour=16, minute=30)
    assert m.tariff_at(moment, tariffs, "local").kind == "peak"
    assert m.tariff_at(moment, tariffs, "standard").kind == "off_peak"


def test_actual_peak_is_separate_from_household_comfort_deadline():
    now = local()
    tariffs = (
        m.Tariff(tuple(range(7)), 0, 15 * 60 + 58, 0.2, "off_peak"),
        m.Tariff(tuple(range(7)), 15 * 60 + 58, 0, 0.5, "peak"),
    )
    result = plan(now, tariffs)
    assert result.deadline == local(hour=15, minute=58)
    assert result.peak_start == result.deadline
    # 0.4.0: weekday comfort deadlines ARE the actual peak start (owner rule);
    # the household 16:00 time applies only on days without a peak.
    assert result.comfort_deadline == result.deadline


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
    assert executor.count("mqtt.async_publish(") == 1
    assert '"notify",' in executor and executor.count(".async_call(") == 1
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    assert manifest["requirements"] == [] and manifest["version"] == "0.6.2"
    assert manifest["integration_type"] == "hub"
    assert "mqtt" not in manifest.get("dependencies", [])  # loads without MQTT


@pytest.mark.parametrize(
    "day,hour,expected",
    [
        (10, 3, False),
        (10, 4, True),
        (10, 7, True),
        (10, 8, False),
        (10, 11, True),
        (10, 17, False),
        (14, 5, False),
        (14, 6, True),
        (14, 21, True),
        (14, 22, False),
    ],
)
def test_owner_reported_schedule_permission_is_not_element_power(day, hour, expected):
    native = importlib.import_module(f"{package.__name__}.native")
    periods = native.parse_native(c.DEFAULT_OPTIONS["native_schedule_periods"])
    result = native.scheduled_permission(local(day=day, hour=hour), periods, "local")
    assert (result == "within_reported_window") is expected


def test_native_morning_windows_do_not_guarantee_depleted_tank_recovery():
    native = importlib.import_module(f"{package.__name__}.native")
    periods = native.parse_native(c.DEFAULT_OPTIONS["native_schedule_periods"])
    assert native.permitted_minutes(local(hour=3), local(hour=7), periods, "local") == 180
    assert (
        native.permitted_minutes(local(day=14, hour=3), local(day=14, hour=7), periods, "local")
        == 60
    )


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


def test_mocked_ha_unknown_mode_attributes_native_reference_and_zero_extra_requests(runtime):
    instance, _, clock = runtime
    instance.update(clock[0])
    assert instance.values["temperature"] == 63 and instance.values["target"] == 70
    assert instance.values["measured_net_export_kw"] == 1.501
    assert instance.values["pv"] == 2.322 and instance.values["house"] == 0.821
    assert instance.values["t_comfort_reference_c"] == 10
    assert "t_comfort_10C_not_practical_hot_water_reserve" in instance.plan.warnings
    assert instance.plan.state == "shadow_advising"
    assert instance.details["additional_cloud_requests"] == 0
    assert instance.details["control_capable"] is False
    assert instance.details["observed_refresh_pattern_attempts_per_day"] == 144
    assert not hasattr(instance.hass, "services")  # reads cannot call one


@pytest.mark.parametrize("scenario", ["planning", "missing", "manual", "quota", "stale"])
def test_diagnostic_attributes_copy_config_mapping_and_remain_json_compatible(runtime, scenario):
    instance, report, clock = runtime
    instance.sources = MappingProxyType(dict(instance.sources))
    if scenario == "missing":
        instance.hass.states = SimpleNamespace(get=lambda entity: None)
    elif scenario == "manual":
        report("mode", "Manual")
    elif scenario == "quota":
        report("cloud_health", "quota_limited")
    elif scenario == "stale":
        clock[0] += timedelta(hours=1)
    instance.update(clock[0])
    encoded = json.dumps(instance.details, allow_nan=False)
    assert json.loads(encoded)["sources"] == dict(instance.sources)
    assert type(instance.details["sources"]) is dict
    assert instance.details["sources"] is not instance.sources
    assert instance.details["control_capable"] is False


def test_startup_without_any_source_states_stays_loaded_and_blocked(runtime):
    instance, _, clock = runtime
    instance.hass.states = SimpleNamespace(get=lambda entity: None)
    instance.update(clock[0])
    assert instance.plan.state == "shadow_blocked"
    assert instance.plan.reasons == ["required_mapping_missing"]
    assert instance.values["temperature"] is None
    assert instance.values["target"] is None
    assert instance.values["grid"] is None


def test_observed_request_growth_includes_refresh_replay_and_detects_reset(runtime):
    instance, report, clock = runtime
    instance.update(clock[0])
    clock[0] += timedelta(minutes=30)
    report("requests", 7)
    instance.update(clock[0])
    assert instance.values["requests_since_start"] == 3
    assert instance.values["observed_requests_per_hour"] == 6
    report("requests", 1)
    instance.update(clock[0])
    assert "request_counter_reset_history_incomplete" in instance.plan.warnings
    assert instance.values["requests_since_start"] == 0


def test_manual_intervention_latches_without_any_restoration_or_cloud_request(runtime):
    instance, report, clock = runtime
    instance.update(clock[0])
    report("mode", "Manual")
    instance.update(clock[0])
    assert instance.plan.state == "shadow_native_intervention"
    report("mode", "Schedule")
    instance.update(clock[0])
    assert instance.plan.state == "shadow_native_intervention"
    assert instance.details["additional_cloud_requests"] == 0


def test_missing_or_stale_grid_blocks_while_local_listeners_clean_up(runtime):
    instance, _, clock = runtime
    calls = []
    unsubscribe = instance.subscribe(lambda: calls.append(1))
    clock[0] += timedelta(minutes=5)
    instance.update(clock[0])
    assert instance.plan.state == "shadow_blocked"
    assert "input_stale_or_restored" in instance.plan.reasons
    assert instance.values["grid"] is None
    unsubscribe()
    assert not instance.listeners and len(calls) == 1


def test_custom_settings_and_dashboard_have_no_control_actions():
    import yaml

    translation = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    assert set(translation["options"]["step"]["settings"]["data"]) == set(c.DEFAULT_OPTIONS)
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


def test_synthetic_replay_of_owner_observations_outages_and_shortage():
    spec = importlib.util.spec_from_file_location("shadow_replay", ROOT / "tools/replay_shadow.py")
    replay_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay_module)
    result = replay_module.replay(ROOT / "shadow_controller/scenarios.json")
    assert result["live_requests"] == result["heater_commands"] == 0
    plans = [row["plan"] for row in result["results"]]
    assert plans[0]["net_export_kw"] == 1.501
    assert plans[3]["state"] == "shadow_shortfall"
    assert plans[5]["reasons"] == ["cloud_not_healthy"]
    assert plans[7]["reasons"] == ["status_stale_or_pre_restart"]
    assert plans[8]["state"] == "shadow_native_intervention"


@pytest.mark.parametrize("case", ["negative", "nan", "overlap", "expired", "naive", "too_far"])
def test_invalid_net_forecast_scenarios_never_produce_plans(case, tariffs):
    now = local()
    forecast = [m.Forecast(now + timedelta(hours=1), now + timedelta(hours=2), 4)]
    if case == "negative":
        forecast[0] = replace(forecast[0], export_kw=-1)
    elif case == "nan":
        forecast[0] = replace(forecast[0], export_kw=float("nan"))
    elif case == "overlap":
        forecast.append(forecast[0])
    elif case == "expired":
        forecast[0] = replace(forecast[0], start=now - timedelta(hours=1))
    elif case == "naive":
        forecast[0] = replace(forecast[0], start=now.replace(tzinfo=None))
    else:
        forecast[0] = replace(forecast[0], end=now + timedelta(hours=49))
    result = m.evaluate(
        now,
        now - timedelta(minutes=1),
        readings(now),
        m.Settings(meter_verified=True, tariff_verified=True),
        tariffs,
        tuple(forecast),
    )
    assert result.state == "shadow_blocked" and result.windows == []
    assert result.reasons == ["forecast_invalid"]


def test_tariff_changes_and_pause_only_change_shadow_model_outputs():
    now = local()
    settings, cheap = c.parse_options(
        {"meter_verified": True, "tariff_verified": True, "off_peak_rate": 0.2}
    )
    _, expensive = c.parse_options({"off_peak_rate": 0.5})
    values = readings(now, grid=0)
    first = m.evaluate(now, now - timedelta(minutes=1), values, settings, cheap)
    second = m.evaluate(now, now - timedelta(minutes=1), values, settings, expensive)
    assert first.estimated_import_kwh == second.estimated_import_kwh
    assert second.estimated_cost_aud > first.estimated_cost_aud
    paused = m.evaluate(
        now, now - timedelta(minutes=1), values, replace(settings, paused=True), expensive
    )
    assert paused.state == "shadow_paused" and paused.windows == []
