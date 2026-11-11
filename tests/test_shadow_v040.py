"""Shadow Planner 0.4.0: dynamic deadlines, 42 °C, freshness, heater state,
incremental economics, native awareness. Offline; no HA, cloud or heater."""

from datetime import date, datetime, time, timedelta
import importlib
import json
from types import SimpleNamespace

import pytest

from test_shadow_model import c, m, local, readings, runtime  # noqa: F401

goals_mod = importlib.import_module(f"{m.__package__}.goals")
strategy = importlib.import_module(f"{m.__package__}.strategy")
hs = importlib.import_module(f"{m.__package__}.heater_state")
advisor_mod = importlib.import_module(f"{m.__package__}.advisor")
settings_mod = importlib.import_module(f"{m.__package__}.settings")

FEED, OFF, PEAK = 0.09276, 0.1702, 0.361878


def owner(**options):
    return c.parse_options(options)


def hobart(at):
    return at.astimezone(m.HOBART)


# --- 1. Tariff and dynamic deadlines ---------------------------------------------


@pytest.mark.parametrize(
    "day,morning,afternoon,basis",
    [
        (date(2026, 11, 10), time(8), time(17), "tariff_peak_start"),  # Tue, AEDT
        (date(2026, 6, 9), time(7), time(16), "tariff_peak_start"),  # Tue, AEST
        (date(2026, 10, 5), time(8), time(17), "tariff_peak_start"),  # Mon after DST starts
        (date(2026, 4, 6), time(7), time(16), "tariff_peak_start"),  # Mon after DST ends
        (date(2026, 11, 14), time(8), time(16), "household_time"),  # Saturday
        (date(2026, 10, 4), time(8), time(16), "household_time"),  # Sun: DST starts 02:00
        (date(2026, 4, 5), time(8), time(16), "household_time"),  # Sun: DST ends 03:00
        (date(2026, 3, 9), time(8), time(17), "tariff_peak_start"),  # Eight Hours Day
    ],
)
def test_weekday_deadlines_follow_actual_peak_and_weekends_use_household_times(
    day, morning, afternoon, basis
):
    settings, tariffs = owner()
    morning_goal, afternoon_goal = goals_mod.goals_for_day(day, settings, tariffs)
    assert hobart(morning_goal.deadline).time() == morning
    assert hobart(afternoon_goal.deadline).time() == afternoon
    assert morning_goal.basis == basis
    assert morning_goal.target_c == 42 and afternoon_goal.target_c == 70
    # Aurora's 2026-27 schedule has no public-holiday exception: a weekday
    # public holiday (Eight Hours Day, 9 Mar) follows weekday periods.


def test_shower_time_can_only_make_weekday_mornings_earlier():
    settings, tariffs = owner(shower_time_enabled=True, shower_time="06:30")
    goal = goals_mod.goals_for_day(date(2026, 11, 10), settings, tariffs)[0]
    assert hobart(goal.deadline).time() == time(6, 30) and goal.basis == "shower_time"
    settings, tariffs = owner(shower_time_enabled=True, shower_time="09:30")
    goal = goals_mod.goals_for_day(date(2026, 11, 10), settings, tariffs)[0]
    assert hobart(goal.deadline).time() == time(8)  # never later than the peak start


@pytest.mark.parametrize(
    "now,expected_change,kind",
    [
        ((2026, 11, 13, 23, 30), (2026, 11, 16, 8, 0), "peak"),  # Fri night -> Mon AEDT
        ((2026, 6, 12, 22, 0), (2026, 6, 15, 7, 0), "peak"),  # Fri winter -> Mon AEST
        ((2026, 11, 10, 0, 0), (2026, 11, 10, 8, 0), "peak"),  # midnight AEDT
        ((2026, 11, 10, 9, 0), (2026, 11, 10, 11, 0), "off_peak"),
        ((2026, 11, 10, 17, 30), (2026, 11, 10, 22, 0), "off_peak"),
    ],
)
def test_next_tariff_change_and_current_period(now, expected_change, kind):
    settings, tariffs = owner()
    at = datetime(*now, tzinfo=m.HOBART).astimezone(m.UTC)
    change, period = goals_mod.next_tariff_change(at, tariffs, settings.tariff_clock)
    assert hobart(change) == datetime(*expected_change, tzinfo=m.HOBART)
    assert period.kind == kind


def test_upcoming_goals_after_peak_roll_to_tomorrow():
    settings, tariffs = owner()
    goals = goals_mod.upcoming_goals(local(hour=18), settings, tariffs)
    assert [g.kind for g in goals[:2]] == ["morning", "afternoon"]
    assert hobart(goals[0].deadline) == datetime(2026, 11, 11, 8, tzinfo=m.HOBART)


# --- 2. Incremental economics -----------------------------------------------------


def slot(now, rate, pv, base, hours=1.0):
    return strategy.Slot(now, now + timedelta(hours=hours), hours, rate, pv, pv, base, base, True)


@pytest.mark.parametrize(
    "rate,expected", [(OFF, 0.4332), (PEAK, 0.8165)]
)  # 1 kW export with the heater available: 1 kW solar + 2 kW import for an hour
def test_owner_partial_solar_examples(rate, expected):
    now = local()
    assert slot(now, rate, pv=1.9, base=0.9).cost(FEED) == pytest.approx(expected, abs=1e-4)
    assert slot(now, OFF, pv=2.9, base=0.9).cost(FEED) == pytest.approx(0.35572, abs=1e-5)
    assert slot(now, OFF, pv=4.0, base=0.0).cost(FEED) == pytest.approx(3 * FEED)  # $0.278


def test_observed_case_golden_numbers_for_on_off_unknown_without_double_counting():
    """11 Nov 11:42: PV 4.97 kW AC (clipped), house 3.90 kW, 6.593 kWh needed."""
    now = local(day=11, hour=11, minute=42)
    hours = 6.593 / 3
    cases = {
        "on": hs.HeaterState(state="on"),
        "off": hs.HeaterState(state="off"),
        "unknown": hs.HeaterState(state="unknown"),
    }
    costs = {}
    for name, state in cases.items():
        low, high = hs.base_load(3.90, state)
        costs[name] = slot(now, OFF, pv=4.97, base=low, hours=hours).cost(FEED)
        if name == "unknown":
            costs["unknown_high"] = slot(now, OFF, pv=4.97, base=high, hours=hours).cost(FEED)
    assert costs["on"] == pytest.approx(6.593 * FEED, abs=0.002)  # $0.61: all solar
    assert costs["off"] == pytest.approx(0.94, abs=0.005)
    assert costs["unknown"] == pytest.approx(costs["on"])  # robust: optimistic now
    assert costs["unknown_high"] == pytest.approx(costs["off"])
    # 0.3.0 priced it at $1.035 because the real element's 3 kW was hidden in
    # the meter reading; base load removes it exactly once.
    assert hs.base_load(3.90, cases["on"]) == (pytest.approx(0.90), pytest.approx(0.90))


def build(now, deadline_hours, pv_fn, base=0.8, settings=None, tariffs=None, forecast=True):
    settings_, tariffs_ = owner()
    settings = settings or settings_
    tariffs = tariffs or tariffs_
    horizon = now + timedelta(hours=deadline_hours)
    series = tuple(
        (now + timedelta(minutes=15 * k), now + timedelta(minutes=15 * (k + 1)), pv_fn(k))
        for k in range(int(deadline_hours * 4) + 1)
    )
    return strategy.build_slots(
        now,
        horizon,
        settings,
        tariffs,
        pv_fn(0),
        (base, base),
        base,
        series if forecast else (),
        (),
    ), settings


def afternoon_goal(at, target=70):
    return goals_mod.Goal("afternoon", at, target, "tariff_peak_start", at)


def test_morning_partial_solar_heats_now_when_later_is_grid():
    now = local(hour=9)  # Tue, peak until 11:00 AEDT
    slots, settings = build(now, 8, lambda k: 3.0 if k < 8 else 0.2)
    goal = afternoon_goal(local(hour=17))
    result = strategy.assess(now, 60, [goal], slots, settings, "off", True)
    assert result.label == "HEAT NOW"
    assert result.plans["best_overall"].start == now  # known sun now beats later grid


def test_wait_only_for_a_meaningful_saving_with_viable_fallback():
    now = local(hour=11, minute=0)  # off-peak
    # 0.3 kW surplus now, 3.5 kW from 12:00: waiting saves real money.
    slots, settings = build(now, 6, lambda k: 1.1 if k < 4 else 4.3)
    goal = afternoon_goal(local(hour=17))
    result = strategy.assess(now, 55, [goal], slots, settings, "off", True)
    assert result.code == "wait_cheaper_later", result.explanation
    assert result.saving_by_waiting_aud > settings.wait_benefit_aud_per_kwh * 1.5
    best = result.plans["best_overall"]
    assert best.start >= local(hour=12) and best.feasible
    assert best.energy_kwh == pytest.approx(result.plans["best_starting_now"].energy_kwh)
    assert "saves about" in result.explanation
    # Same situation with only a marginal improvement later: heat now.
    slots, settings = build(now, 6, lambda k: 1.8 if k < 4 else 2.1)
    result = strategy.assess(now, 55, [goal], slots, settings, "off", True)
    assert result.code in {"heat_now_cheapest", "heat_now_saving_too_small"}


def test_peak_partial_solar_versus_off_peak_grid_later():
    now = local(hour=9)  # peak (08:00-11:00 AEDT)
    slots, settings = build(now, 8, lambda k: 1.7)  # 0.9 kW surplus all day
    goal = afternoon_goal(local(hour=17))
    result = strategy.assess(now, 64, [goal], slots, settings, "off", True)
    # $0.8165/h now (peak) vs ~$0.43/h after 11:00 with the same surplus.
    assert result.code == "wait_cheaper_later"
    assert result.plans["best_overall"].start >= local(hour=11)


def test_abundant_solar_now_but_forecast_cloudy_later_uses_it_now():
    now = local(hour=11)
    slots, settings = build(now, 6, lambda k: 4.5 if k < 6 else 0.3)
    goal = afternoon_goal(local(hour=17))
    result = strategy.assess(now, 60, [goal], slots, settings, "off", True)
    assert result.code == "heat_now_cheapest"
    assert result.plans["best_overall"].solar_kwh > 3


def test_no_forecast_never_assumes_future_solar():
    now = local(hour=11)
    slots, settings = build(now, 6, lambda k: 3.0, forecast=False)
    assert all(s.pv50 == 0 for s in slots if not s.measured)
    assert any(s.pv50 == 3.0 for s in slots if s.measured)


def test_insufficient_time_reports_shortfall_and_fallback_due():
    now = local(hour=16)
    slots, settings = build(now, 1, lambda k: 0.0)
    result = strategy.assess(
        now, 40, [afternoon_goal(local(hour=17))], slots, settings, "off", True
    )
    assert result.code == "insufficient_time"
    assert result.plans["heat_now_continuous"].shortfall_kwh > 5
    now = local(hour=14)
    slots, settings = build(now, 3, lambda k: 0.0)
    result = strategy.assess(
        now, 50, [afternoon_goal(local(hour=17))], slots, settings, "off", True
    )
    assert result.code == "heat_now_comfort_fallback"  # 7.3 kWh + 30 min allowance


def test_off_peak_equal_cost_is_no_hurry_not_heat_now():
    now = local(hour=1)
    slots, settings = build(now, 7, lambda k: 0.0)
    morning = goals_mod.Goal("morning", local(hour=8), 42, "tariff_peak_start", local(hour=8))
    result = strategy.assess(now, 38, [morning], slots, settings, "off", True)
    assert result.code == "flexible_no_cost_difference"
    assert result.label == "NO HURRY"


def test_morning_met_still_considers_economic_afternoon_storage():
    now = local(hour=6)
    slots, settings = build(now, 11, lambda k: 0.0 if k < 8 else 4.0)
    morning = goals_mod.Goal("morning", local(hour=8), 42, "tariff_peak_start", local(hour=8))
    result = strategy.assess(
        now, 50, [morning, afternoon_goal(local(hour=17))], slots, settings, "off", True
    )
    reqs = {goal.kind: kwh for goal, kwh in result.requirements}
    assert reqs["morning"] == 0 and reqs["afternoon"] > 0
    assert result.code == "wait_cheaper_later"  # solar after 08:00 beats off-peak now


def test_requirements_include_morning_draw_and_standing_loss_assumptions():
    settings, _ = owner(expected_morning_draw_c=10, standing_loss_c_per_hour=0.2)
    now = local(hour=5)
    morning = goals_mod.Goal("morning", local(hour=8), 42, "x", None)
    afternoon = afternoon_goal(local(hour=17))
    reqs = dict(
        (g.kind, kwh) for g, kwh in strategy.requirements(now, 45, [morning, afternoon], settings)
    )
    assert reqs["morning"] == pytest.approx(max(0, 42 - (45 - 0.6)) * m.TANK_KWH_PER_C)
    assert reqs["afternoon"] == pytest.approx((70 - (45 - 2.4 - 10)) * m.TANK_KWH_PER_C)


def test_inverter_clipping_caps_slot_pv_at_single_ac_limit():
    now = local(hour=12)
    slots, settings = build(now, 2, lambda k: 6.5)
    assert max(s.pv50 for s in slots) == settings.pv_ac_limit_kw == 5.0


def test_other_appliance_load_reduces_surplus_for_heater():
    now = local(hour=12)
    quiet, settings = build(now, 1, lambda k: 4.0, base=0.8)
    busy, _ = build(now, 1, lambda k: 4.0, base=2.8)  # e.g. dryer running
    assert quiet[0].solar() == 3.0 and busy[0].solar() == pytest.approx(1.2)


def test_storage_satisfied_by_native_thermostat_means_no_afternoon_heat():
    now = local(hour=16, minute=47)
    slots, settings = build(now, 0.25, lambda k: 0.0)
    result = strategy.assess(
        now,
        63,
        [afternoon_goal(local(hour=17))],
        slots,
        settings,
        "off",
        True,
        storage_satisfied=True,
    )
    assert result.code == "no_heating_needed"


def test_native_outlook_reports_readiness_and_cost():
    now = local(hour=3)
    slots, settings = build(now, 5, lambda k: 0.0)
    morning = goals_mod.Goal("morning", local(hour=8), 42, "x", None)
    outlook = strategy.native_outlook(
        now, 16, [morning], slots, settings, lambda at: hobart(at).hour >= 4, False
    )
    assert outlook["readiness"]["morning"]["met"] is True
    assert outlook["first_heating"] == local(hour=4).isoformat()


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


def test_meter_pre_commissioning_signature_blocks_house_load():
    adv = advisor_mod.Advisor()
    now = local(hour=11)
    settings, tariffs = owner()
    plan = m.Plan(state="shadow_wait_for_window")
    for minute in range(12):
        inputs = advisor_mod.TickInputs(
            temperature=50,
            house_kw=4.5,
            pv_ac_kw=4.5,
            export_kw=0.0,
            status_raw=32,
            status_at=now,
            in_window=lambda at: True,
        )
        advice = adv.tick(now + timedelta(minutes=minute), plan, settings, tariffs, inputs)
    assert advice.meter_suspect and advice.code == "data_unavailable"


def test_decision_stabiliser_holds_optional_changes_but_not_comfort():
    adv = advisor_mod.Advisor()
    now = local()
    first = adv._stabilise(now, ("wait_cheaper_later", "WAIT", "", "high"), 10)
    assert first[0][0] == "wait_cheaper_later"
    shown, pending = adv._stabilise(
        now + timedelta(minutes=1), ("heat_now_cheapest", "HEAT NOW", "", "high"), 10
    )
    assert shown[0] == "wait_cheaper_later" and pending == "heat_now_cheapest"
    shown, _ = adv._stabilise(
        now + timedelta(minutes=12), ("heat_now_cheapest", "HEAT NOW", "", "high"), 10
    )
    assert shown[0] == "heat_now_cheapest"
    shown, _ = adv._stabilise(
        now + timedelta(minutes=13), ("heat_now_comfort_fallback", "HEAT NOW", "", "high"), 10
    )
    assert shown[0] == "heat_now_comfort_fallback"  # comfort is immediate


# --- 4. Freshness (Stage 1 F1) and runtime --------------------------------------------


def test_unchanged_mqtt_payloads_stay_fresh_while_polls_succeed(runtime):  # noqa: F811
    instance, report, clock = runtime
    start = clock[0]
    instance.update(start)
    assert instance.plan.state == "shadow_advising"
    # 50 minutes later: heater, mode and health entities were NOT rewritten (an
    # identical MQTT payload causes no HA state write); only the poll time moves.
    clock[0] = start + timedelta(minutes=50)
    report("last_poll", (clock[0] - timedelta(minutes=5)).isoformat())
    for key, value in {"grid": 1501, "pv_ac": 2322, "house": 821}.items():
        report(key, value, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    assert instance.plan.state == "shadow_advising", instance.plan.reasons
    assert instance.values["temperature"] == 63  # displayed, not falsely stale
    # A genuinely old poll still blocks, conservatively.
    clock[0] = start + timedelta(minutes=120)
    for key, value in {"grid": 1501, "pv_ac": 2322, "house": 821}.items():
        report(key, value, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    assert instance.plan.state == "shadow_blocked"
    assert instance.values["temperature"] is None


def test_restart_accepts_retained_status_by_its_real_poll_time(runtime):  # noqa: F811
    instance, report, clock = runtime
    report("last_poll", (clock[0] - timedelta(minutes=10)).isoformat())
    instance.boot = clock[0]  # HA restarted; retained STATUS re-delivered
    instance.update(clock[0])
    assert instance.plan.state != "shadow_blocked", instance.plan.reasons
    assert instance.plan.status_age_minutes == pytest.approx(10)


def test_runtime_exposes_state_basis_tariff_and_readiness(runtime):  # noqa: F811
    instance, report, clock = runtime
    report("mode", "Schedule", {"WaterHeaterSts": 33})
    report("house", 3900, {"unit_of_measurement": "W"})
    instance.update(clock[0])
    values, details = instance.values, instance.details
    assert values["heater_element_state"] == "on"
    assert values["base_load_kw"] == pytest.approx(0.9)
    assert details["heater_state"]["status_semantics"].startswith("empirical")
    assert values["next_tariff_change"] is not None and values["next_tariff_kind"]
    assert values["afternoon_readiness"] in {"met", "on_track", "at_risk", "shortfall"}
    assert values["decision"] and values["decision_confidence"]
    assert "strategies" in details and details["native_outlook"] is not None
    json.dumps(details, allow_nan=False, default=str)
    assert not hasattr(instance.hass, "services")


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
        **{k: k.lower() for k in ("SENSOR", "NUMBER", "TIME", "SWITCH", "SELECT", "TEXT", "BUTTON")}
    )
    sys.modules["homeassistant.core"].callback = lambda f: f
    sys.modules["homeassistant.helpers.config_validation"].config_entry_only_config_schema = (
        lambda d: None
    )
    sys.modules["homeassistant.helpers"].config_validation = sys.modules[
        "homeassistant.helpers.config_validation"
    ]
    sys.modules["homeassistant.helpers.event"].async_track_time_interval = None
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
    assert run({})["minor_version"] == 2
    assert run({"morning_threshold_c": 40.0}, minor=2) == {}
