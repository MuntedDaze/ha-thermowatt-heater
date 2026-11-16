"""Owner's installed 1.3.17/0.14.0 upgrade: offline faults and full command path."""

from dataclasses import replace
from datetime import timedelta
import importlib
from types import SimpleNamespace

import pytest

from test_audit_regressions_0_9_1 import config, controller_ready, ctl, observation, published
from test_forecast_and_settings import c, forecast, series
from test_integration_0_9_0 import Rig, MON, hobart
from test_simple_policy import MIN, OFF, S, STORE, TARIFFS, at, fc, snap, sp

solar = importlib.import_module(f"{sp.__package__}.solar")


def sun(policy, now):
    for i in range(11):
        policy.add_meter(now - (10 - i) * MIN, -4.0, heater_kw=0)


def ct_free(rig, qualified=True):
    rig.sources["heater_power"] = ""
    rig.entry.options.update(
        normal_storage_c="62",
        heater_meter_verification="",
        ct_free_solar_verification=solar.ct_free_record(c.DEFAULT_SOURCES["grid"], "W", False, 3)
        if qualified
        else "",
    )
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)


@pytest.mark.parametrize("day,hour", [(MON, 9), (MON, 12), (14, 12)])
def test_ct_free_solar_requires_separate_commissioning_at_peak_and_off_peak(day, hour):
    now = at(day, hour)
    p = sp.SimplePolicy(replace(S, normal_c=62), TARIFFS)
    sun(p, now)
    state = snap(now, OFF, reading=45, heater_meter_valid=False, forecast=fc(now, 6, 4))
    assert p.decide(state).reason not in ctl.OPTIONAL_REASONS
    d = p.decide(replace(state, ct_free_solar_valid=True))
    assert d.state == STORE and d.reason in ctl.OPTIONAL_REASONS
    assert d.plan["solar_measurement_basis"] == "commissioned_grid_only"


def test_ct_free_consumed_surplus_and_unrelated_steps_do_not_require_remaining_export():
    now = at(MON, 18)
    p = sp.SimplePolicy(S, TARIFFS)
    # Thermostat/appliance identity is unknown; acceptable net import is enough.
    for i in range(15):
        p.add_meter(now + i * MIN, -0.1 if i < 10 else 0.15, heater_kw=0)
    d = p.decide(
        snap(
            now + 14 * MIN,
            STORE,
            heater_meter_valid=False,
            ct_free_solar_valid=True,
            optional_session_active=True,
        )
    )
    assert d.reason == "peak_solar_continues" and d.command is None


def test_withdrawal_needs_full_continuous_ten_minutes_and_resets_on_good_sample():
    now = at(MON, 18)
    p = sp.SimplePolicy(S, TARIFFS)
    for i in range(22):
        t = now + i * MIN
        p.add_meter(t, 0.1 if i == 10 else 3.5, heater_kw=0)
        d = p.decide(
            snap(
                t,
                STORE,
                heater_meter_valid=False,
                ct_free_solar_valid=True,
                optional_session_active=True,
            )
        )
        assert (d.state == OFF) == (i == 21)


def pending_start(now):
    controller = controller_ready(now)
    assert published(
        controller.step(observation(now), ctl.Want(STORE, "peak_solar_qualified"), config())
    )
    return controller


def latch_exit(controller, now):
    obs = observation(now, bridge_confirmation_pending=True)
    effects = controller.step(obs, ctl.Want(OFF, "peak_meter_unavailable", 4), config())
    assert not published(effects) and controller.protective_exit
    assert "protective_exit_unresolved" in controller.active_alerts


def test_exit_survives_pending_start_restart_and_returning_sun_then_confirms_cooldown():
    now = at(MON, 18)
    controller = pending_start(now)
    original = dict(controller.intent)
    latch_exit(controller, now + MIN)
    controller = ctl.Controller.from_dict(controller.to_dict())
    controller.restored(now + 2 * MIN)
    assert controller.intent == original
    # A later sunny decision cannot erase the latched OFF.
    sunny = ctl.Want(STORE, "peak_solar_qualified")
    effects = controller.step(
        observation(now + 3 * MIN, "Manual", 70, poll_at=now + 3 * MIN), sunny, config()
    )
    assert published(effects) == ["off@70"]
    assert controller.intent["target"] == OFF
    assert controller.optional_cooldown_until is None
    assert not published(controller.step(observation(now + 4 * MIN, "Manual", 70), sunny, config()))
    effects = controller.step(observation(now + 5 * MIN, poll_at=now + 5 * MIN), sunny, config())
    assert not published(effects)
    assert controller.protective_exit is None
    assert controller.optional_cooldown_until == (now + 20 * MIN).isoformat()
    assert "solar_withdrawal_cooldown" in controller.gate_failures
    p = sp.SimplePolicy(S, TARIFFS)
    sun(p, now + 20 * MIN)  # qualification overlaps cooldown
    d = p.decide(snap(now + 20 * MIN, OFF, reading=45, optional_cooldown_until=now + 20 * MIN))
    assert d.command == "Manual:70"


@pytest.mark.parametrize(
    "guard",
    [
        {"cloud_health": "auth_locked"},
        {"bridge_confirmation_pending": True},
        {"auth_mode": "blocked"},
        {"cooldown_seconds": 600},
        {"mqtt_ready": False},
    ],
)
def test_latched_exit_never_bypasses_existing_command_guards(guard):
    now = at(MON, 18)
    controller = controller_ready(now, "Manual", 70)
    effects = controller.step(
        observation(now, "Manual", 70, **guard), ctl.Want(OFF, "peak_meter_unavailable"), config()
    )
    assert not published(effects) and controller.protective_exit


@pytest.mark.parametrize("action", ["hold", "disable"])
def test_explicit_owner_action_prevents_queued_exit_sends(action):
    now = at(MON, 18)
    controller = pending_start(now)
    latch_exit(controller, now + MIN)
    if action == "hold":
        controller.set_hold(now + MIN)
    else:
        controller.set_enabled(False, now + MIN)
    effects = controller.step(
        observation(now + 2 * MIN, "Manual", 70, poll_at=now + 2 * MIN),
        ctl.Want(STORE, "peak_solar_continues"),
        config(),
    )
    assert not published(effects) and controller.protective_exit


def test_failed_start_confirmation_keeps_exit_faulted_and_reports_growing_exposure():
    now = at(MON, 18)
    controller = pending_start(now)
    latch_exit(controller, now + MIN)
    effects = controller.step(
        observation(
            now + 8 * MIN,
            mode=None,
            last_command={
                "payload": controller.intent["payload"],
                "at": (now + 8 * MIN).isoformat(),
                "result": "not_confirmed_within_limit",
            },
        ),
        ctl.Want(STORE, "peak_solar_continues"),
        config(),
    )
    assert not published(effects) and controller.state == ctl.FAULT_LOCKED
    assert (
        controller.protective_exit
        and controller.summary(now + 8 * MIN)["protective_exit_wait_seconds"] == 420
    )


def test_cooldown_does_not_block_essential_off_peak_baseline():
    now = at(MON, 23)
    controller = controller_ready(now)
    controller.optional_cooldown_until = (now + 15 * MIN).isoformat()
    assert published(
        controller.step(observation(now), ctl.Want("baseline", "baseline"), config())
    ) == ["Manual:45@off"]


@pytest.mark.parametrize("qualified", [False, True])
def test_actual_executor_and_bridge_ct_free_peak_start_and_cloud_withdrawal(
    tmp_path, monkeypatch, qualified
):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(MON, 8, 50),
        reading=45,
        pv=lambda loc: 4.5 if loc.hour == 8 or loc.minute < 18 else 0,
    )
    ct_free(rig, qualified)
    rig.enable()
    rig.run(hobart(MON, 9, 40))
    assert rig.commands() == (["Manual:70@off", "off@70"] if qualified else [])
    assert len(rig.posts) == (2 if qualified else 0)
    assert not rig.runtime.circuit.valid  # never invent CT/element evidence
    if qualified:
        assert rig.executor.controller.optional_cooldown_until
        assert not rig.executor.controller.protective_exit


@pytest.mark.parametrize("mutation", ["unit", "direction", "rating", "mapped_ct"])
def test_ct_free_record_cannot_follow_changed_measurement_or_failed_ct(
    tmp_path, monkeypatch, mutation
):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 9), reading=45, pv=lambda loc: 4.5)
    ct_free(rig)
    if mutation == "unit":
        rig.entry.options["ct_free_solar_verification"] = rig.entry.options[
            "ct_free_solar_verification"
        ].replace("|W|", "|kW|")
    elif mutation == "direction":
        rig.entry.options["ct_free_solar_verification"] = rig.entry.options[
            "ct_free_solar_verification"
        ].replace("export_positive", "import_positive")
    elif mutation == "rating":
        rig.entry.options["element_kw"] = 2.4
    else:
        rig.sources["heater_power"] = "sensor.missing_commissioned_ct"
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    rig.enable()
    rig.run(hobart(MON, 9, 20))
    assert not rig.commands()


@pytest.mark.parametrize("load", [None, "zero", "immature", "stale"])
def test_missing_zero_immature_and_stale_load_use_explicit_nonzero_assumption(load):
    now = at(MON, 12)
    settings, _ = c.parse_options({"forecast_enabled": True})
    state = None if load is None else series(now, "load", 0)
    if load in {"immature", "stale"}:
        state = SimpleNamespace(
            state="700",
            last_reported=now,
            attributes={
                "unit_of_measurement": "W",
                "age_coverage_ratio": 0.01,
                "source_value_valid": True,
            },
        )
        if load == "stale":
            state.last_reported -= timedelta(hours=4)
    result = forecast.build_forecast(
        now, now - MIN, settings, series(now), state, measured_house=1.7
    )
    assert result.load_floor_kw == 1.7
    assert result.load_quality == "provisional_not_daily_history" and result.slots
    assert all(row[2] >= 1.7 for row in result.load_series)
    assert result.slots[0].export_kw < 4 * (1 - settings.forecast_uncertainty) - 1.7


def test_request_reserve_counts_diagnostics_without_poll_and_survives_counter_reset():
    now = at(MON, 18)
    controller = controller_ready(now)
    for i in range(1, 101):
        controller.step(
            observation(now + i * timedelta(seconds=1), requests_total=100 + i),
            ctl.Want("hold", "test"),
            config(),
        )
    assert controller.requests_last_24h(now + 2 * MIN) == 110
    restored = ctl.Controller.from_dict(controller.to_dict())
    restored.step(observation(now + 3 * MIN, requests_total=2), ctl.Want("hold", "test"), config())
    assert restored.requests_last_24h(now + 3 * MIN) == 112
    assert "optional_exit_request_reserve" in restored.gates(
        observation(now + 3 * MIN),
        STORE,
        config(max_requests_per_day=120),
        "Manual:70@off",
        "peak_solar_qualified",
    )


def test_upgrade_from_exact_legacy_counter_shape_cannot_grant_negative_usage():
    now = at(MON, 18)
    controller = ctl.Controller.from_dict(
        {
            "request_samples": [
                [(now - 2 * MIN).isoformat(), 150],
                [(now - MIN).isoformat(), 200],
            ]
        }
    )
    controller.step(observation(now, requests_total=2), ctl.Want("hold", "test"), config())
    assert controller.requests_last_24h(now) == 52


def test_missing_bridge_transaction_diagnostics_cannot_clear_latched_exit():
    now = at(MON, 18)
    controller = controller_ready(now, "Manual", 70)
    latch_exit(controller, now + MIN)
    effects = controller.step(
        observation(now + 2 * MIN, poll_at=now + 2 * MIN, bridge_confirmation_pending=None),
        ctl.Want(OFF, "peak_lockout"),
        config(),
    )
    assert controller.protective_exit and not published(effects)
    assert controller.optional_cooldown_until is None


@pytest.mark.parametrize("ct", [False, True])
def test_restart_into_already_heating_peak_does_not_grant_grid_grace(ct):
    now = at(MON, 18)
    p = sp.SimplePolicy(S, TARIFFS)
    p.add_meter(now, 3)
    d = p.decide(
        snap(
            now,
            STORE,
            heater_meter_valid=ct,
            ct_free_solar_valid=not ct,
            optional_session_active=False,
        )
    )
    assert d.command == "off" and d.reason == "peak_no_qualified_session"


def test_real_bridge_slow_start_meter_loss_restart_and_latched_off(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 8, 50), reading=45, pv=lambda loc: 4.5)
    ct_free(rig)
    apply = rig.tank.apply

    def slow_apply(mode, setpoint, now):
        apply(mode, setpoint, now)
        if mode == "Manual":
            rig.tank.change_at = now + 180

    rig.tank.apply = slow_apply
    rig.enable()
    latched = []
    restarted = []

    def fault(r):
        controller = r.executor.controller
        if controller.intent and controller.intent["target"] == STORE:
            r.report(c.DEFAULT_SOURCES["grid"], "unavailable", {"unit_of_measurement": "W"})
        if controller.protective_exit:
            latched.append(r.now())
            if not restarted:
                r.executor = r._executor()
                restarted.append(True)

    rig.run(hobart(MON, 9, 20), fault)
    assert latched and restarted
    assert rig.commands() == ["Manual:70@off", "off@70"]
    assert [row[1] for row in rig.posts] == ["manual", "off"]
    assert rig.executor.controller.protective_exit is None
    assert rig.executor.controller.optional_cooldown_until


@pytest.mark.parametrize("action", ["hold", "disable", "app"])
def test_owner_intervention_retires_optional_session_authority(action):
    now = at(MON, 18)
    controller = controller_ready(now, "Manual", 70)
    controller.solar_session_active = True
    if action == "hold":
        controller.set_hold(now)
    elif action == "disable":
        controller.set_enabled(False, now)
    else:
        controller.step(
            observation(now + MIN, "Manual", 45, poll_at=now + MIN),
            ctl.Want(STORE, "peak_solar_continues"),
            config(),
        )
    assert controller.solar_session_active is False


@pytest.mark.parametrize(
    "hour,reading,age,expected",
    [
        (6, 44, 0, "at_risk"),
        (7, 41, 0, "minimum_shortfall_observed"),
        (7, 45, 60, "unverified"),
        (7, 45, 0, "latest_probe_above_requirement"),
    ],
)
def test_morning_requirements_report_evidence_without_authorising_extra_heat(
    hour, reading, age, expected
):
    comfort = importlib.import_module(f"{sp.__package__}.comfort")
    now = at(MON, hour)
    result = comfort.morning_availability(now, reading, now - age * MIN, "Australia/Hobart")
    assert result["state"] == expected
    assert result["proves_deadline_met"] is False


def test_local_ticks_cannot_extend_qualification_or_import_report_coverage():
    now = at(MON, 18)
    for grid in (-4, 3):
        p = sp.SimplePolicy(S, TARIFFS)
        for i in range(10):
            p.add_meter(now + i * MIN, grid)
        if grid < 0:
            assert not p.sustained(now + 10 * MIN, S.qualify, lambda x: x[2] >= 3.3)
        else:
            assert not p.importing_continuously(now + 10 * MIN)


def test_new_solar_start_requires_continuous_surplus_and_not_eighty_percent():
    now = at(MON, 18)
    p = sp.SimplePolicy(S, TARIFFS)
    for minute in range(17):
        p.add_meter(now + minute * MIN, -1 if minute == 5 else -4)
        assert p.surplus_qualified(now + minute * MIN) == (minute == 16)


def test_off_status_before_terminal_diagnostics_resolves_without_next_poll_or_cooldown_reset():
    now = at(MON, 18)
    controller = controller_ready(now, "Manual", 70)
    assert published(
        controller.step(
            observation(now, "Manual", 70), ctl.Want(OFF, "peak_solar_withdrawn"), config()
        )
    ) == ["off@70"]
    # Bridge publishes STATUS before terminal diagnostics, then the same status
    # is evaluated again on the local safety tick with explicit pendingFalse.
    poll = now + MIN
    progress = {"payload": "off@70", "at": poll.isoformat(), "result": "awaiting_confirmation"}
    assert not published(
        controller.step(
            observation(
                poll, poll_at=poll, bridge_confirmation_pending=True, last_command=progress
            ),
            ctl.Want(OFF, "peak_lockout"),
            config(),
        )
    )
    assert controller.intent and controller.protective_exit
    terminal = {**progress, "result": "confirmed", "at": (poll + timedelta(seconds=1)).isoformat()}
    controller.step(
        observation(poll + timedelta(seconds=1), poll_at=poll, last_command=terminal),
        ctl.Want(OFF, "peak_lockout"),
        config(),
    )
    assert controller.intent is None and controller.protective_exit is None
    cooldown = controller.optional_cooldown_until
    controller.step(
        observation(poll + MIN, poll_at=poll, last_command=terminal),
        ctl.Want(OFF, "peak_lockout"),
        config(),
    )
    assert controller.optional_cooldown_until == cooldown


def test_actual_bridge_restart_retains_pending_start_and_protective_exit_without_replay(
    tmp_path, monkeypatch
):
    from test_integration_0_9_0 import b, SERIAL

    rig = Rig(tmp_path, monkeypatch, hobart(MON, 8, 50), reading=45, pv=lambda loc: 4.5)
    ct_free(rig)
    apply = rig.tank.apply

    def slow(mode, setpoint, now):
        apply(mode, setpoint, now)
        if mode == "Manual":
            rig.tank.change_at = now + 180

    rig.tank.apply = slow
    rig.enable()
    restarted = []

    def fault(r):
        if r.executor.controller.intent and r.executor.controller.intent["target"] == STORE:
            r.report(c.DEFAULT_SOURCES["grid"], "unavailable", {"unit_of_measurement": "W"})
        if r.executor.controller.protective_exit and not restarted:
            previous = r.bridge
            pending = dict(previous.pending)
            r.bridge = b.MyThermowattBridge(
                dict(previous.options),
                tmp_path,
                session=previous.session,
                mqtt_client=previous.mqtt_client,
                clock=lambda: r.t,
                monotonic=lambda: r.t,
            )
            r.bridge.mqtt_connected.set()
            r.bridge.config["devices"] = {SERIAL: {"name": "Synthetic"}}
            r.bridge.active_devices = {SERIAL}
            r.bridge.discovered = True
            assert r.bridge.pending and r.bridge.pending["payload"] == pending["payload"]
            assert (
                r.bridge.options["auth_retry_generation"]
                == previous.options["auth_retry_generation"]
            )
            restarted.append(True)

    rig.run(hobart(MON, 9, 15), fault)
    assert restarted
    assert rig.commands() == ["Manual:70@off", "off@70"]
    assert [row[1] for row in rig.posts] == ["manual", "off"]
    assert rig.executor.controller.protective_exit is None


@pytest.mark.parametrize("ct", [False, True])
def test_qualified_session_crosses_peak_boundary_without_requiring_remaining_export(ct):
    now = at(MON, 16, 58)
    p = sp.SimplePolicy(S, TARIFFS)
    for minute in range(11):
        p.add_meter(now - (10 - minute) * MIN, -0.1, heater_kw=3 if ct else 0)
    d = p.decide(
        snap(
            now,
            STORE,
            heater_meter_valid=ct,
            ct_free_solar_valid=not ct,
            optional_session_active=True,
        )
    )
    assert d.reason == "peak_solar_continues" and d.command is None


def test_importing_optional_session_does_not_carry_grid_heat_into_peak():
    now = at(MON, 16, 58)
    p = sp.SimplePolicy(S, TARIFFS)
    p.add_meter(now, 0.5, heater_kw=3)
    d = p.decide(snap(now, STORE, optional_session_active=True))
    assert d.command == "off" and d.reason == "peak_ahead_no_qualified_solar"


@pytest.mark.parametrize("ct", [False, True])
def test_existing_normal_62_can_upgrade_to_economic_70_during_peak(ct):
    now = at(MON, 18)
    p = sp.SimplePolicy(replace(S, normal_c=62), TARIFFS)
    sun(p, now)
    d = p.decide(
        snap(now, sp.NORMAL, reading=62, heater_meter_valid=ct, ct_free_solar_valid=not ct)
    )
    assert (d.state, d.reason, d.command) == (STORE, "peak_solar_qualified", "Manual:70")
    assert d.plan["boost_expected_saving_aud"] >= p.s.boost_min_saving
    assert ctl.payload_for(d.state, sp.NORMAL) == "Manual:70@62"


@pytest.mark.parametrize("block", ["disabled", "budget", "cooldown", "unresolved_exit"])
def test_peak_normal_upgrade_keeps_all_optional_gates(block):
    now = at(MON, 18)
    p = sp.SimplePolicy(replace(S, normal_c=62, boost_enabled=block != "disabled"), TARIFFS)
    sun(p, now)
    d = p.decide(
        snap(
            now,
            sp.NORMAL,
            reading=62,
            optional_allowed=block != "budget",
            optional_cooldown_until=now + MIN if block == "cooldown" else None,
            protective_exit_pending=block == "unresolved_exit",
        )
    )
    assert d.state == sp.NORMAL and d.command is None


@pytest.mark.parametrize("ct", [False, True])
def test_real_bridge_upgrades_existing_62_to_70_with_peak_surplus(tmp_path, monkeypatch, ct):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(MON, 8, 50),
        reading=62,
        mode="Manual",
        setpoint=62,
        pv=lambda loc: 4.5,
    )
    if not ct:
        ct_free(rig)
    else:
        rig.entry.options["normal_storage_c"] = "62"
        rig.runtime.apply_options(rig.entry.options, rig.sources)
        rig.executor.configure(rig.entry.options)
    rig.enable()
    rig.run(hobart(MON, 9, 10))
    assert rig.commands() == ["Manual:70@62"]
    assert len(rig.posts) == 1 and rig.posts[0][2] == {"T_SetPoint": 70}
    assert rig.executor.controller.solar_session_active is True


@pytest.mark.parametrize("block", ["surplus", "value"])
def test_peak_normal_upgrade_requires_real_surplus_and_extra_heat_value(block):
    now = at(MON, 18)
    p = sp.SimplePolicy(
        replace(S, normal_c=62, boost_min_saving=2 if block == "value" else 0.1), TARIFFS
    )
    for minute in range(11):
        p.add_meter(now - (10 - minute) * MIN, -3.2 if block == "surplus" else -4)
    d = p.decide(snap(now, sp.NORMAL, reading=62))
    assert d.command != "Manual:70"


@pytest.mark.parametrize("block", ["reserve", "spacing"])
def test_peak_normal_upgrade_passes_optional_arbiter_backstops(block):
    now = at(MON, 18)
    controller = controller_ready(now, "Manual", 62)
    obs = observation(now, "Manual", 62)
    obs.bridge_transitions.append("Manual:70@62")
    if block == "spacing":
        controller.commands.append((now - MIN).isoformat())
    cfg = config(four_state_qualified=True, max_requests_per_day=15 if block == "reserve" else 220)
    effects = controller.step(obs, ctl.Want(STORE, "peak_solar_qualified"), cfg)
    assert not published(effects)
    assert (
        "optional_exit_request_reserve" if block == "reserve" else "command_spacing"
    ) in controller.gate_failures
