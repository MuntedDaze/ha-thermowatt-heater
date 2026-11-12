"""Shadow Planner 0.4.0: dynamic deadlines, 42 °C, freshness, heater state,
incremental economics, native awareness. Offline; no HA, cloud or heater."""

from datetime import date, datetime, time, timedelta
import importlib
import importlib.util
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
READINESS = {
    "met",
    "satisfied_by_native_thermostat",
    "native_predicted_ready",
    "at_risk_with_native_schedule",
    "unachievable",
}


def owner(**options):
    return c.parse_options(options)


def hobart(at):
    return at.astimezone(m.HOBART)


# --- 1. Tariff and dynamic deadlines ---------------------------------------------


@pytest.mark.parametrize(
    "day,afternoon,basis",
    [
        (date(2026, 11, 10), time(17), "tariff_peak_start"),  # Tue, AEDT
        (date(2026, 6, 9), time(16), "tariff_peak_start"),  # Tue, AEST
        (date(2026, 10, 5), time(17), "tariff_peak_start"),  # Mon after DST starts
        (date(2026, 4, 6), time(16), "tariff_peak_start"),  # Mon after DST ends
        (date(2026, 11, 14), time(16), "household_time"),  # Saturday
        (date(2026, 10, 4), time(16), "household_time"),  # Sun: DST starts 02:00
        (date(2026, 4, 5), time(16), "household_time"),  # Sun: DST ends 03:00
        (date(2026, 3, 9), time(17), "tariff_peak_start"),  # Eight Hours Day
    ],
)
def test_afternoon_follows_actual_peak_and_morning_is_06_00_preferred_07_00_hard(
    day, afternoon, basis
):
    settings, tariffs = owner()
    morning_goal, afternoon_goal = goals_mod.goals_for_day(day, settings, tariffs)
    # 0.7.0: morning comfort is a household time EVERY day, DST-correct.
    assert hobart(morning_goal.deadline).time() == time(6)
    assert hobart(morning_goal.hard_deadline).time() == time(7)
    assert morning_goal.basis == "preferred_morning_time"
    assert hobart(afternoon_goal.deadline).time() == afternoon
    assert afternoon_goal.basis == basis
    assert morning_goal.target_c == 42 and afternoon_goal.target_c == 70
    # Aurora's 2026-27 schedule has no public-holiday exception: a weekday
    # public holiday (Eight Hours Day, 9 Mar) follows weekday periods.


def test_missed_preferred_morning_moves_to_the_hard_deadline_never_dropped():
    settings, tariffs = owner()
    for hour, minute, expected, basis in (
        (5, 59, time(6), "preferred_morning_time"),
        (6, 0, time(7), "hard_morning_deadline"),
        (6, 45, time(7), "hard_morning_deadline"),
    ):
        goals = goals_mod.upcoming_goals(local(hour=hour, minute=minute), settings, tariffs)
        assert goals[0].kind == "morning" and goals[1].kind == "afternoon"
        assert hobart(goals[0].deadline).time() == expected and goals[0].basis == basis
    after = goals_mod.upcoming_goals(local(hour=7), settings, tariffs)
    assert after[0].kind == "afternoon"  # today's morning is over at 07:00


def test_legacy_shower_settings_no_longer_move_the_morning_goal():
    settings, tariffs = owner(shower_time_enabled=True, shower_time="05:30", morning_time="09:00")
    goal = goals_mod.goals_for_day(date(2026, 11, 10), settings, tariffs)[0]
    assert hobart(goal.deadline).time() == time(6)
    settings, tariffs = owner(morning_preferred_time="05:30", morning_hard_time="06:30")
    goal = goals_mod.goals_for_day(date(2026, 11, 10), settings, tariffs)[0]
    assert hobart(goal.deadline).time() == time(5, 30)
    assert hobart(goal.hard_deadline).time() == time(6, 30)
    with pytest.raises(ValueError):
        owner(morning_preferred_time="07:30", morning_hard_time="07:00")


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
    assert hobart(goals[0].deadline) == datetime(2026, 11, 11, 6, tzinfo=m.HOBART)


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
        satisfied_deadline=local(hour=17),
    )
    assert result.code == "no_heating_needed"
    assert result.native_satisfied_goal == "afternoon"
    assert "63 °C" in result.explanation and "not necessarily reached" in result.explanation


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
    assert values["afternoon_readiness"] in READINESS
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
    assert run({})["minor_version"] == 2
    assert run({"morning_threshold_c": 40.0}, minor=2) == {}


def test_schedule_advisor_compares_native_windows_without_changing_them():
    now = local(hour=3)
    slots, settings = build(now, 14, lambda k: 0.0 if k < 28 else 4.0)
    goals = [
        goals_mod.Goal("morning", local(hour=8), 42, "x", None),
        afternoon_goal(local(hour=17)),
    ]
    current = (((0, 1, 2, 3, 4), 240, 480), ((0, 1, 2, 3, 4), 660, 1020), ((5, 6), 360, 1320))
    advice = strategy.schedule_advice(now, 50, goals, slots, settings, current, "local", False)
    names = [item["name"] for item in advice["candidates"]]
    assert names[0] == "current reference" and len(names) == 4
    assert advice["cheapest_meeting_goals"] in names
    assert "not a recommendation" in advice["basis"]


def test_version_comparison_report_reproduces():
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "compare_versions_test", Path(__file__).parents[1] / "tools/compare_versions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = module.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert saved == module.markdown(module.run())
    rows = {row["case"]: row for row in module.run()}
    observed = rows["Observed 11 Nov 11:42, element ON"]
    assert observed["before"]["label"] == "WAIT FOR SOLAR"
    assert observed["after"]["label"] == "HEATING NOW (NATIVE)"
    assert rows["Unchanged MQTT payload (written 50 min ago, poll 5 min ago)"]["before"][
        "label"
    ] == ("DATA UNAVAILABLE")


# --- Review of ac38eaf (ChatGPT): satisfied lifetime, block rules, presentation ----


def satisfied_run(adv, events, settings=None, tariffs=None):
    """Drive _track_satisfaction with (time, state, reading, in_window) tuples."""
    settings_, tariffs_ = owner()
    settings, tariffs = settings or settings_, tariffs or tariffs_
    for at, state, reading, window in events:
        heater = hs.HeaterState(state=state, confidence="high")
        inputs = advisor_mod.TickInputs(
            temperature=reading,
            house_kw=None,
            pv_ac_kw=None,
            export_kw=None,
            status_raw=None,
            status_at=None,
            in_window=lambda t, w=window: w,
        )
        goals = goals_mod.upcoming_goals(at, settings, tariffs)[:2]
        adv._track_satisfaction(at, heater, inputs, goals)
    return adv.satisfied


def heated_then_off(start, reading=63, window=True):
    return [(start, "on", reading, window), (start + timedelta(minutes=15), "off", reading, window)]


def test_satisfied_event_is_scoped_to_todays_afternoon_goal_and_expires():
    adv = advisor_mod.Advisor()
    event = satisfied_run(adv, heated_then_off(local(hour=15)))
    assert event is not None and event["deadline"] == local(hour=17)  # 16:00 AEST = 17:00 AEDT
    # Still before the deadline with a small loss: kept.
    assert satisfied_run(adv, [(local(hour=16, minute=30), "off", 61, True)]) is not None
    # At the deadline it expires; tomorrow's goal is never treated as met.
    assert satisfied_run(adv, [(local(hour=17), "off", 61, False)]) is None
    assert satisfied_run(adv, [(local(day=11, hour=0, minute=5), "off", 60, False)]) is None


def test_satisfied_event_resets_on_three_degree_loss_and_new_heating():
    adv = advisor_mod.Advisor()
    satisfied_run(adv, heated_then_off(local(hour=13)))
    assert satisfied_run(adv, [(local(hour=14), "off", 60.5, True)]) is not None
    assert satisfied_run(adv, [(local(hour=14, minute=10), "off", 59.5, True)]) is None
    satisfied_run(adv, heated_then_off(local(hour=15)))
    assert satisfied_run(adv, [(local(hour=15, minute=20), "on", 63, True)]) is None


def test_switch_off_after_todays_deadline_never_satisfies_tomorrow():
    # Saturday: native window 06:00-22:00, household afternoon time 16:00.
    adv = advisor_mod.Advisor()
    assert satisfied_run(adv, heated_then_off(local(day=14, hour=18))) is None
    # Window-end switch-offs and short blips are not thermostat decisions either.
    assert (
        satisfied_run(advisor_mod.Advisor(), heated_then_off(local(hour=15), window=False)) is None
    )
    short = [(local(hour=15), "on", 63, True), (local(hour=15, minute=5), "off", 63, True)]
    assert satisfied_run(advisor_mod.Advisor(), short) is None


def test_satisfied_only_zeroes_the_matching_goal_and_says_target_not_reached():
    now = local(hour=15, minute=30)
    slots, settings = build(now, 17.5, lambda k: 0.0)
    morning = goals_mod.Goal("morning", local(day=11, hour=8), 42, "x", None)
    today = afternoon_goal(local(hour=17))
    result = strategy.assess(
        now, 63, [today, morning], slots, settings, "off", True, satisfied_deadline=local(hour=17)
    )
    reqs = {goal.kind: kwh for goal, kwh in result.requirements}
    assert reqs["afternoon"] == 0 and result.native_satisfied_goal == "afternoon"
    # A different (tomorrow's) deadline is untouched by today's event.
    tomorrow = afternoon_goal(local(day=11, hour=17))
    result = strategy.assess(
        now,
        63,
        [tomorrow],
        *build(now, 26, lambda k: 0.0),
        "off",
        True,
        satisfied_deadline=local(hour=17),
    )
    assert result.native_satisfied_goal is None and result.requirements[0][1] > 0


def alternating_slots(now, count, cheap=0.0, dear=0.5):
    """Alternating cheap/dear 15-min slots would invite 15-minute blocks."""
    return [
        strategy.Slot(
            now + timedelta(minutes=15 * k),
            now + timedelta(minutes=15 * (k + 1)),
            0.25,
            cheap if k % 2 == 0 else dear,
            0.0,
            0.0,
            0.5,
            0.5,
            False,
        )
        for k in range(count)
    ]


def test_block_rules_prevent_short_and_adjacent_blocks():
    now = local(hour=10)
    slots = alternating_slots(now, 24)
    needs = [(24, 3.0)]  # 4 slots of energy
    free = strategy.optimise(slots, needs, FEED, min_run=1, min_gap=1)
    # Without rules the optimiser happily schedules a 15-minute block.
    assert any(b - a < timedelta(minutes=30) for a, b in free.blocks)
    ruled = strategy.optimise(slots, needs, FEED, min_run=2, min_gap=2)
    settings, _ = owner()
    assert strategy.constraint_violations(ruled, settings, now) == []
    assert all((b - a) >= timedelta(minutes=30) for a, b in ruled.blocks[:-1])
    for previous, current in zip(ruled.blocks, ruled.blocks[1:], strict=False):
        assert current[0] - previous[1] >= timedelta(minutes=30)
    assert ruled.energy_kwh == pytest.approx(free.energy_kwh) == pytest.approx(3.0)
    assert ruled.cost_aud >= free.cost_aud  # rules can only cost more, never less
    single = strategy.optimise(slots, needs, FEED, max_blocks=1, min_run=2, min_gap=2)
    assert len(single.blocks) == 1


def test_small_job_may_be_shorter_than_one_cycle_and_deadline_boundary_is_exact():
    now = local(hour=10)
    slots = alternating_slots(now, 8, cheap=0.1, dear=0.1)
    small = strategy.optimise(slots, [(8, 0.5)], FEED, min_run=2, min_gap=2)
    assert small.feasible and len(small.blocks) == 1 and small.energy_kwh == pytest.approx(0.5)
    exact = strategy.optimise(slots, [(4, 3.0)], FEED, min_run=2, min_gap=2)
    assert exact.blocks == [(now, now + timedelta(hours=1))]  # fills the window exactly
    assert strategy.optimise(slots, [(4, 3.1)], FEED, min_run=2, min_gap=2) is None


def test_forced_start_with_short_partial_slot_still_runs_a_full_cycle():
    now = local(hour=10, minute=55)  # 5-minute first slot
    settings, tariffs = owner()
    slots = strategy.build_slots(now, local(hour=14), settings, tariffs, 0.0, (0.5, 0.5), 0.5)
    plan = strategy.optimise(
        slots, [(len(slots), 4.0)], FEED, force_first=True, min_run=2, min_gap=2
    )
    first = plan.blocks[0]
    assert first[0] == now and first[1] - first[0] >= timedelta(minutes=35)
    assert strategy.constraint_violations(plan, settings, now) == []


def test_every_assessed_strategy_obeys_block_rules_and_equal_energy():
    now = local(hour=9)
    slots, settings = build(now, 8, lambda k: 3.5 if k % 3 else 0.5)
    result = strategy.assess(
        now, 50, [afternoon_goal(local(hour=17))], slots, settings, "off", True
    )
    energies = set()
    for name, plan in result.plans.items():
        assert strategy.constraint_violations(plan, settings, now) == [], name
        energies.add(round(plan.energy_kwh, 6))
    assert len(energies) == 1  # all strategies deliver the same required energy


def test_unknown_state_bounds_surplus_and_cost_with_qualified_confidence():
    adv = advisor_mod.Advisor()
    now = local(day=11, hour=11, minute=42)
    settings, tariffs = owner(forecast_enabled=True)
    plan = m.Plan(state="shadow_wait_for_window")
    inputs = advisor_mod.TickInputs(
        temperature=52,
        house_kw=3.9,
        pv_ac_kw=4.97,
        export_kw=1.07,
        status_raw=None,
        status_at=None,
        in_window=lambda at: True,
        forecast_available=True,
        pv_series=((now, now + timedelta(hours=8), 3.43),),
    )
    advice = adv.tick(now, plan, settings, tariffs, inputs)
    assert advice.heater.state == "unknown"
    low, high = advice.surplus_bounds_kw
    assert advice.surplus_now_kw == low == pytest.approx(1.07) and high == pytest.approx(4.07)
    assert advice.surplus_basis == "element_unknown_lower_bound"
    lo_cost, hi_cost = advice.assessment.heat_now_cost_range_aud
    assert hi_cost - lo_cost > 0.3
    assert advice.confidence in {"low", "medium"}
    assert "between" in advice.explanation


def test_physical_state_overrides_stabilised_economics_immediately():
    adv = advisor_mod.Advisor()
    now = local(day=11, hour=11, minute=30)
    settings, tariffs = owner(forecast_enabled=True)
    plan = m.Plan(state="shadow_wait_for_window")

    def tick(minute, house, status):
        inputs = advisor_mod.TickInputs(
            temperature=52,
            house_kw=house,
            pv_ac_kw=4.97,
            export_kw=4.97 - house,
            status_raw=status,
            status_at=now,
            in_window=lambda at: True,
            forecast_available=True,
            pv_series=((now, now + timedelta(hours=8), 4.5),),
        )
        return adv.tick(now + timedelta(minutes=minute), plan, settings, tariffs, inputs)

    on = tick(0, 3.9, 33)
    assert on.label == "HEATING NOW (NATIVE)" and on.heater.state == "on"
    off = tick(1, 0.9, 33)  # element stops; house load falls below 2.6 kW
    assert off.heater.state == "off"
    assert off.label != "HEATING NOW (NATIVE)"  # same tick, no 10-minute lag
    assert off.economic_code == on.economic_code  # economics may still be held


def test_readiness_comes_from_native_outlook_not_hypothetical_plan():
    adv = advisor_mod.Advisor()
    now = local(hour=12)
    settings, tariffs = owner()
    plan = m.Plan(state="shadow_wait_for_window")
    inputs = advisor_mod.TickInputs(
        temperature=55,
        house_kw=0.9,
        pv_ac_kw=0.5,
        export_kw=-0.4,
        status_raw=32,
        status_at=now,
        in_window=lambda at: False,  # native windows closed all afternoon
    )
    advice = adv.tick(now, plan, settings, tariffs, inputs)
    afternoon = advice.readiness["afternoon"]
    assert afternoon["hypothetical_plan_feasible"] is True
    assert afternoon["native_predicted_ready"] is False
    assert afternoon["status"] == "at_risk_with_native_schedule"


def test_medium_confidence_on_says_likely_and_state_claims_change_immediately():
    decision = ("heat_now_cheapest", "HEAT NOW", "x", "high")
    assert (
        strategy.compose_with_heater(decision, "on", None, "medium")[1] == "HEATING LIKELY (NATIVE)"
    )
    assert strategy.compose_with_heater(decision, "on", None, "high")[1] == "HEATING NOW (NATIVE)"
    assert strategy.compose_with_heater(decision, "off", None, "high")[1] == "HEAT NOW"
    adv = advisor_mod.Advisor()
    now = local(hour=16, minute=50)
    adv._stabilise(now, ("no_heating_needed", "NO HEATING NEEDED", "", "high"), 10)
    shown, pending = adv._stabilise(
        now + timedelta(minutes=10), ("wait_cheaper_later", "WAIT", "", "high"), 10
    )
    assert shown[0] == "wait_cheaper_later" and pending is None  # not held
