"""Owner-confirmed Tariff 93, practical temperature goals and solar backstop."""

from datetime import timedelta

import pytest

from test_shadow_model import c, local, m, readings, runtime  # noqa: F401


def owner_plan(now, temperature=50, export=0, **options):
    settings, tariffs = c.parse_options(options)
    return m.evaluate(
        now, now - timedelta(minutes=1), readings(now, temperature, export), settings, tariffs
    )


@pytest.mark.parametrize("temperature", [40, 41, 63, 70])
def test_morning_ready_does_not_heat_just_because_native_schedule_permits_it(temperature):
    result = owner_plan(local(hour=5), temperature)
    assert result.planning_target_c == 40
    assert result.state == "shadow_no_modelled_topup"
    assert result.reasons == ["morning_threshold_met_no_morning_heat_required"]
    assert result.mixed_model_energy_kwh == result.modelled_heating_minutes == 0
    assert result.windows == [] and result.grid_fallback_start is None


def test_morning_shortage_uses_40_threshold_and_full_margin():
    now = local(hour=3)
    result = owner_plan(now, 35)
    assert result.mixed_model_energy_kwh == pytest.approx(1.831, abs=0.001)
    assert result.modelled_heating_minutes == pytest.approx(66.6, abs=0.1)
    assert result.deadline == local(hour=7)
    assert result.grid_fallback_start == pytest.approx(
        result.deadline - timedelta(minutes=66.6275), abs=timedelta(seconds=1)
    )
    assert result.state == "shadow_wait_for_window"
    assert all(w["source"] == "off_peak" for w in result.windows)
    assert "40C_is_comfort_threshold_not_storage_setpoint" in result.warnings


def test_editable_morning_threshold_is_independent_of_storage_target():
    result = owner_plan(local(hour=4), 42, morning_threshold_c=45)
    assert result.planning_target_c == 45
    assert result.mixed_model_energy_kwh > 0
    assert c.parse_options({})[0].target_c == 70


@pytest.mark.parametrize("month,day,peak_hour", [(1, 13, 17), (6, 9, 16)])
def test_summer_winter_full_storage_deadline_uses_fixed_aest_peak(month, day, peak_hour):
    now = local(month=month, day=day, hour=11)
    result = owner_plan(now, 63)
    assert result.planning_target_c == 70
    assert result.peak_start == result.deadline == local(month=month, day=day, hour=peak_hour)
    assert result.comfort_deadline == local(month=month, day=day, hour=16)
    assert result.mixed_model_energy_kwh == pytest.approx(2.564, abs=0.001)
    assert result.modelled_heating_minutes == pytest.approx(81.3, abs=0.1)
    assert result.current_price_aud == 0.170200
    assert "within_thermostat_hysteresis_no_forced_heating_verified" in result.warnings


@pytest.mark.parametrize(
    "month,day,local_hour,kind",
    [
        (1, 13, 7, "off_peak"),
        (1, 13, 8, "peak"),
        (1, 13, 10, "peak"),
        (1, 13, 11, "off_peak"),
        (1, 13, 16, "off_peak"),
        (1, 13, 17, "peak"),
        (1, 13, 21, "peak"),
        (1, 13, 22, "off_peak"),
        (6, 9, 6, "off_peak"),
        (6, 9, 7, "peak"),
        (6, 9, 9, "peak"),
        (6, 9, 10, "off_peak"),
        (6, 9, 15, "off_peak"),
        (6, 9, 16, "peak"),
        (6, 9, 20, "peak"),
        (6, 9, 21, "off_peak"),
    ],
)
def test_confirmed_tariff_boundaries_do_not_need_manual_dst_edits(month, day, local_hour, kind):
    settings, tariffs = c.parse_options({})
    item = m.tariff_at(local(month=month, day=day, hour=local_hour), tariffs, settings.tariff_clock)
    assert item.kind == kind
    assert item.rate == (0.361878 if kind == "peak" else 0.170200)
    assert settings.feed_in_rate == 0.092760


@pytest.mark.parametrize("month,day", [(1, 17), (6, 13), (4, 5), (10, 4)])
def test_weekends_have_comfort_goal_but_no_evening_peak(month, day):
    result = owner_plan(local(month=month, day=day, hour=10))
    assert result.peak_start is None
    assert result.deadline_kind == "afternoon_comfort"
    assert result.deadline == local(month=month, day=day, hour=16)
    assert result.current_price_aud == 0.170200


def test_no_solar_waits_only_until_off_peak_backstop_then_heats():
    now = local(hour=11)
    first = owner_plan(now, 50)
    assert first.state == "shadow_wait_for_window"
    assert first.grid_fallback_start > now
    later = owner_plan(first.grid_fallback_start, 50)
    assert later.state == "shadow_heat_now"
    assert later.planned_start == first.grid_fallback_start
    assert later.unmet_model_energy_kwh == 0
    assert later.estimated_solar_kwh == 0
    assert later.estimated_cost_aud == pytest.approx(later.estimated_import_kwh * 0.1702, abs=0.001)


def test_depleted_winter_tank_uses_only_necessary_peak_time_to_protect_comfort():
    now = local(month=6, day=9, hour=9)
    result = owner_plan(now, 17)
    assert "insufficient_off_peak_time_comfort_priority" in result.warnings
    assert result.grid_fallback_start > now
    assert result.unmet_model_energy_kwh == 0
    peak_hours = sum(
        (m.timestamp(w["end"]) - m.timestamp(w["start"])).total_seconds() / 3600
        for w in result.windows
        if w["source"] == "peak"
    )
    required = result.mixed_model_energy_kwh + 1.5
    assert 3 * peak_hours == pytest.approx(required - 18, abs=0.001)


def test_forecast_does_not_move_the_full_grid_reservation_later():
    now = local(hour=11)
    settings, tariffs = c.parse_options({})
    baseline = owner_plan(now, 50)
    forecast = (m.Forecast(local(hour=15), local(hour=17), 4),)
    result = m.evaluate(
        now, now - timedelta(minutes=1), readings(now, 50, 0), settings, tariffs, forecast
    )
    assert result.grid_fallback_start == baseline.grid_fallback_start
    due = result.grid_fallback_start
    cloudy = owner_plan(due, 50)
    assert cloudy.planned_start == due and cloudy.unmet_model_energy_kwh == 0


def test_element_is_always_modelled_as_full_3kw_not_a_modulated_load():
    result = owner_plan(local(hour=11), 50)
    hours = sum(
        (m.timestamp(w["end"]) - m.timestamp(w["start"])).total_seconds() / 3600
        for w in result.windows
    )
    assert hours * 3 == pytest.approx(result.mixed_model_energy_kwh + 1.5, abs=0.001)


def test_short_export_spike_does_not_start_solar_opportunity(runtime):  # noqa: F811
    instance, report, clock = runtime
    report("grid", 4000, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    assert not instance.details["solar_hold_satisfied"]
    assert instance.plan.state == "shadow_wait_for_window"
    for minute in range(1, 11):
        clock[0] += timedelta(minutes=1)
        report("grid", 4000, {"unit_of_measurement": "W"})
        instance.update(clock[0])
        assert instance.details["solar_hold_satisfied"] == (minute == 10)
    assert instance.plan.state == "shadow_solar_opportunity"
    assert instance.plan.estimated_solar_kwh == pytest.approx(0.75)
    report("grid", 1501, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    assert instance.details["solar_hold_satisfied"]  # partial surplus remains useful
    assert not instance.cycle.active  # separate economic benefit/qualification gate
    assert instance.details["additional_cloud_requests"] == 0


def test_stale_or_repeated_meter_reports_cannot_satisfy_solar_hold(runtime):  # noqa: F811
    instance, report, clock = runtime
    report("grid", 4000, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    clock[0] += timedelta(minutes=10)
    instance.update(clock[0])
    assert not instance.details["solar_hold_satisfied"]
    assert instance.plan.state == "shadow_blocked"
    report("grid", 4000, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    assert not instance.details["solar_hold_satisfied"]


def test_manual_device_clock_check_is_independent_of_tariff_clock():
    native = __import__(f"{m.__package__}.native", fromlist=["clock_check_required"])
    assert native.clock_check_required(local(month=10, day=4), "2026-10-03")
    assert not native.clock_check_required(local(month=11, day=10), "2026-10-04")
    assert native.clock_check_required(local(month=4, day=5), "2026-04-04")
    assert native.clock_check_required(local(), "")
    assert native.clock_check_required(local(), "2027-01-01")


def test_saved_settings_are_not_overwritten_by_new_owner_defaults():
    settings, _ = c.parse_options(
        {
            "meter_verified": False,
            "tariff_verified": False,
            "target_c": 65,
            "import_positive": True,
            "off_peak_rate": 0.2,
            "tariff_clock": "local",
        }
    )
    assert not settings.meter_verified and not settings.tariff_verified
    assert settings.target_c == 65 and settings.import_positive is True
    assert settings.tariff_clock == "local"
