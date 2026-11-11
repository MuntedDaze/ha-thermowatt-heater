"""0.5.0 production controller: state machine, gates, confirmation, reconciliation,
planner boundary and end-to-end simulation. Offline only: no HA, MQTT, cloud or
heater. The bridge is either a faithful model of the 1.3.9 contract or the REAL
1.3.8 bridge code with mocked HTTP."""

from datetime import timedelta
import importlib
from types import SimpleNamespace

import pytest

from conftest import STATUS, response
from test_shadow_model import c, local, m, runtime  # noqa: F401
from test_cloud_and_commands import ready

ctl = importlib.import_module(f"{m.__package__}.controller")
plan_mod = importlib.import_module(f"{m.__package__}.control_plan")
native = importlib.import_module(f"{m.__package__}.native")
advisor_mod = importlib.import_module(f"{m.__package__}.advisor")
goals_mod = importlib.import_module(f"{m.__package__}.goals")

TOPIC = "P/TEST123/CMD/MODE"


def cfg(**overrides):
    values = {
        "command_topic": TOPIC,
        "bridge_commands_qualified": True,
    }
    values.update(overrides)
    return ctl.ControllerConfig(**values)


def obs(now, **kw):
    values = {
        "poll_at": now - timedelta(seconds=10),
        "mode": "Off",
        "target_c": None,  # OFF's setpoint is not an operating target
        "temperature_c": 50.0,
        "element": "off",
        "element_confidence": "high",
        "cloud_health": "ok",
        "auth_mode": "authorized",
        "consecutive_failures": 0,
        "cooldown_seconds": 0,
        "bridge_available": True,
        "bridge_commands_enabled": True,
        "requests_total": 1000,
        "mqtt_ready": True,
    }
    values.update(kw)
    if values["mode"] == "Manual" and "target_c" not in kw:
        values["target_c"] = 70.0
    return ctl.Observation(now=now, **values)


PERMIT = ctl.Desire("permit", "planned_block_heat_now_cheapest")
PARK = ctl.Desire("park", "planned_block_ending")
HOLD = ctl.Desire("hold", "flexible")


def publishes(effects):
    return [e for e in effects if e.kind == "publish"]


def notices(effects):
    return [e.key for e in effects if e.kind == "notify"]


def parked_controller(now, **kw):
    """Enabled controller that has inspected a parked heater (software OFF)."""
    controller = ctl.Controller()
    controller.set_enabled(True, now - timedelta(hours=2))
    controller.step(
        obs(now - timedelta(hours=1, minutes=59), poll_at=now - timedelta(hours=1, minutes=59)),
        HOLD,
        cfg(**kw),
    )
    # Two request samples so the 24 h budget is known.
    controller.step(
        obs(now - timedelta(hours=1), poll_at=now - timedelta(hours=1), requests_total=990),
        HOLD,
        cfg(**kw),
    )
    assert controller.state == ctl.PARKED, controller.reason
    controller.last_transition_at = (now - timedelta(hours=3)).isoformat()
    return controller


def permitted_controller(now, since_minutes=60):
    controller = parked_controller(now - timedelta(minutes=since_minutes + 1))
    start = now - timedelta(minutes=since_minutes)
    effects = controller.step(obs(start, temperature_c=50), PERMIT, cfg())
    assert publishes(effects)
    controller.step(
        obs(
            start + timedelta(seconds=30),
            poll_at=start + timedelta(seconds=20),
            mode="Manual",
            element="on",
        ),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED
    return controller


# --- commissioning and disabled operation -------------------------------------------


def test_fresh_installation_cannot_command_anything():
    controller = ctl.Controller()
    default = ctl.ControllerConfig()
    assert set(default.missing_commissioning()) == {
        "command_topic_not_configured",
        "bridge_commands_not_qualified_t3",
    }
    now = local(hour=12)
    for minute in range(0, 120):
        effects = controller.step(obs(now + timedelta(minutes=minute)), PERMIT, default)
        assert not publishes(effects)
    assert controller.state == ctl.DISABLED
    # Even if enabled, an uncommissioned controller cannot publish.
    controller.set_enabled(True, now)
    controller.step(
        obs(now + timedelta(minutes=121), poll_at=now + timedelta(minutes=121)), HOLD, default
    )
    effects = controller.step(obs(now + timedelta(minutes=122)), PERMIT, default)
    assert not publishes(effects)
    assert "command_topic_not_configured" in controller.gate_failures
    # Options defaults agree: blank topic, both confirmations false.
    options = c.DEFAULT_OPTIONS
    assert options["controller_command_topic"] == ""
    assert "controller_empty_schedule_confirmed" not in options  # removed in 0.6.0
    assert options["controller_bridge_qualified"] is False


@pytest.mark.parametrize(
    "topic",
    [
        "",
        "P//CMD/MODE",
        "P/TEST123/CMD/TEMP",
        "x/TEST123/CMD/MODE",
        "P/TE ST/CMD/MODE",
        "P/TEST123/refresh",
    ],
)
def test_only_a_mode_command_topic_is_accepted(topic):
    assert not ctl.valid_topic(topic)
    assert "command_topic_not_configured" in cfg(command_topic=topic).missing_commissioning()


def test_disabled_controller_never_changes_mode_and_reenable_inspects_first():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.set_enabled(False, now)
    for minute in range(60):
        assert not publishes(controller.step(obs(now + timedelta(minutes=minute)), PERMIT, cfg()))
    assert controller.state == ctl.DISABLED
    # Owner switches to Manual in the app while disabled; re-enable adopts it
    # ONLY after a new status, never assuming the last requested state.
    later = now + timedelta(minutes=61)
    controller.set_enabled(True, later)
    assert controller.state == ctl.OBSERVING
    effects = controller.step(
        obs(later, poll_at=later - timedelta(minutes=5), mode="Manual"), PARK, cfg()
    )
    assert not publishes(effects) and controller.state == ctl.OBSERVING
    effects = controller.step(
        obs(later + timedelta(minutes=1), poll_at=later + timedelta(seconds=50), mode="Manual"),
        HOLD,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED


# --- normal cycle ----------------------------------------------------------------------


def test_successful_manual_start_and_schedule_park_each_one_command():
    now = local(hour=11)
    controller = parked_controller(now)
    effects = controller.step(obs(now), PERMIT, cfg())
    [message] = publishes(effects)
    assert (message.topic, message.payload) == (TOPIC, "Manual:70")
    assert controller.state == ctl.CONFIRMING
    intent = controller.intent
    assert intent["action"] == "permit" and intent["prior_mode"] == "Off"
    # Planner keeps asking every minute: nothing is re-sent.
    for second in (20, 40, 60, 90):
        assert not publishes(
            controller.step(
                obs(now + timedelta(seconds=second), poll_at=now - timedelta(seconds=10)),
                PERMIT,
                cfg(),
            )
        )
    confirm = now + timedelta(seconds=30)
    controller.step(
        obs(confirm + timedelta(seconds=70), poll_at=confirm, mode="Manual", element="on"),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED
    assert controller.history[-1]["status"] == "confirmed"
    # 30 minutes later the plan ends: one Auto at the next poll slot.
    later = now + timedelta(minutes=31)
    effects = controller.step(obs(later, mode="Manual", element="on"), PARK, cfg())
    [message] = publishes(effects)
    assert message.payload == "off"
    controller.step(
        obs(later + timedelta(minutes=1), poll_at=later + timedelta(seconds=25)), PARK, cfg()
    )
    assert controller.state == ctl.PARKED and len(controller.commands) == 2


def test_already_in_desired_mode_sends_nothing():
    now = local(hour=11)
    controller = parked_controller(now)
    assert not publishes(controller.step(obs(now), PARK, cfg()))
    assert not publishes(controller.step(obs(now), HOLD, cfg()))
    assert controller.state == ctl.PARKED
    permitted = permitted_controller(local(hour=13))
    at = local(hour=13, minute=1)
    assert not publishes(permitted.step(obs(at, mode="Manual", element="on"), PERMIT, cfg()))


def test_command_waits_for_the_next_poll_slot_then_sends_once():
    now = local(hour=11, minute=5)
    controller = parked_controller(now)
    stale = obs(now, poll_at=now - timedelta(minutes=4))
    assert not publishes(controller.step(stale, PERMIT, cfg()))
    assert controller.state == ctl.HEATING_REQUESTED
    assert controller.reason == "waiting_for_next_bridge_poll"
    slot = now + timedelta(minutes=26)
    effects = controller.step(obs(slot, poll_at=slot - timedelta(seconds=5)), PERMIT, cfg())
    assert len(publishes(effects)) == 1


def test_thermostat_hysteresis_means_no_command_above_62():
    now = local(hour=11)
    controller = parked_controller(now)
    effects = controller.step(obs(now, temperature_c=63), PERMIT, cfg())
    assert not publishes(effects)
    assert controller.state == ctl.PARKED
    assert controller.reason == "thermostat_would_not_call_for_heat"
    assert publishes(
        controller.step(
            obs(
                now + timedelta(minutes=30),
                poll_at=now + timedelta(minutes=30) - timedelta(seconds=5),
                temperature_c=62,
            ),
            PERMIT,
            cfg(),
        )
    )


def test_thermostat_cutoff_allows_park_before_minimum_heating_but_never_toggles():
    now = local(hour=12)
    controller = permitted_controller(now, since_minutes=10)
    # Element still on: minimum heating period holds the park.
    assert not publishes(controller.step(obs(now, mode="Manual", element="on"), PARK, cfg()))
    assert "minimum_dwell_not_elapsed" in controller.gate_failures
    # The thermostat reached its own cut-off: park is allowed early.
    assert publishes(
        controller.step(
            obs(
                now + timedelta(minutes=1),
                poll_at=now + timedelta(seconds=50),
                mode="Manual",
                element="off",
            ),
            PARK,
            cfg(),
        )
    )


def test_minimum_rest_and_daily_command_limit():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.last_transition_at = (now - timedelta(minutes=10)).isoformat()
    assert not publishes(controller.step(obs(now), PERMIT, cfg()))
    assert "minimum_dwell_not_elapsed" in controller.gate_failures
    controller.last_transition_at = (now - timedelta(hours=2)).isoformat()
    controller.commands = [(now - timedelta(hours=h)).isoformat() for h in (1, 2, 3, 4)]
    assert not publishes(controller.step(obs(now + timedelta(seconds=1)), PERMIT, cfg()))
    assert "economic_command_budget_reached" in controller.gate_failures
    comfort = ctl.Desire("permit", "comfort_fallback_latest_start", comfort=True)
    reserve = ctl.Controller.from_dict(controller.to_dict())
    assert publishes(reserve.step(obs(now + timedelta(seconds=1)), comfort, cfg()))
    controller.commands = [(now - timedelta(hours=h)).isoformat() for h in range(1, 7)]
    assert not publishes(controller.step(obs(now + timedelta(seconds=2)), comfort, cfg()))
    assert "daily_command_limit_reached" in controller.gate_failures
    controller.commands = [(now - timedelta(hours=25)).isoformat()] * 4
    assert publishes(controller.step(obs(now + timedelta(seconds=2)), PERMIT, cfg()))


def test_cloud_request_budget_blocks_commands():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.request_samples = [
        [(now - timedelta(hours=20)).isoformat(), 1000],
        [(now - timedelta(minutes=1)).isoformat(), 1230],
    ]
    assert not publishes(controller.step(obs(now, requests_total=1230), PERMIT, cfg()))
    assert "daily_cloud_request_budget_reached" in controller.gate_failures
    controller.request_samples = []
    controller.last_poll_seen = None
    assert not publishes(controller.step(obs(now, requests_total=None), PERMIT, cfg()))
    assert "request_accounting_unavailable" in controller.gate_failures


@pytest.mark.parametrize(
    "change,failure",
    [
        ({"cloud_health": "backoff"}, "cloud_health_backoff"),
        ({"cloud_health": "auth_locked"}, "cloud_health_auth_locked"),
        ({"auth_mode": "blocked"}, "bridge_auth_not_authorized"),
        ({"consecutive_failures": 1}, "bridge_in_backoff"),
        ({"cooldown_seconds": 600}, "bridge_in_backoff"),
        ({"bridge_available": False}, "bridge_unavailable"),
        ({"bridge_commands_enabled": False}, "bridge_commands_disabled_or_unknown"),
        ({"bridge_commands_enabled": None}, "bridge_commands_disabled_or_unknown"),
        ({"mqtt_ready": False}, "mqtt_not_ready"),
        ({"temperature_c": None}, "temperature_unavailable"),
    ],
)
def test_cloud_auth_bridge_and_measurement_gates(change, failure):
    now = local(hour=12)
    controller = parked_controller(now)
    assert not publishes(controller.step(obs(now, **change), PERMIT, cfg()))
    assert failure in controller.gate_failures


# --- confirmation, ambiguity and reconciliation -------------------------------------


def started(now):
    controller = parked_controller(now)
    assert publishes(controller.step(obs(now), PERMIT, cfg()))
    return controller


def test_bridge_dropped_or_refused_command_locks_without_retry():
    now = local(hour=11)
    controller = started(now)
    report = {
        "kind": "MODE",
        "payload": "Manual:70",
        "result": "dropped_status_older_than_60s",
        "at": (now + timedelta(seconds=15)).isoformat(),
    }
    effects = controller.step(obs(now + timedelta(seconds=20), last_command=report), PERMIT, cfg())
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "bridge_refused_or_dropped"
    assert "fault_bridge_refused_or_dropped" in notices(effects)
    for minute in range(1, 120):
        assert not publishes(controller.step(obs(now + timedelta(minutes=minute)), PERMIT, cfg()))
    assert controller.history[-1]["status"] == "not_applied"


def test_wrong_target_refusal_and_unexpected_target_both_stop_control():
    now = local(hour=11)
    controller = started(now)
    report = {"payload": "Manual:70", "result": "refused_target_mismatch", "at": now.isoformat()}
    controller.step(obs(now + timedelta(seconds=20), last_command=report), PERMIT, cfg())
    assert controller.state == ctl.FAULT_LOCKED
    # While OFF the reported setpoint is not an operating target: 65 (or 40,
    # or an invalid value) neither counts as an owner change nor blocks the
    # guarded resume, which sends 70 explicitly.
    for reported in (65, 40, 0, None):
        parked = parked_controller(now)
        effects = parked.step(
            obs(now + timedelta(seconds=5), poll_at=now, target_c=reported), PERMIT, cfg()
        )
        assert [e.payload for e in publishes(effects)] == ["Manual:70"], reported
    # In Manual a target other than 70 is an owner change: control pauses.
    permitted = permitted_controller(local(hour=13))
    at = local(hour=13, minute=2)
    permitted.step(
        obs(at, poll_at=at - timedelta(seconds=5), mode="Manual", target_c=65), HOLD, cfg()
    )
    assert permitted.state == ctl.OWNER_OVERRIDE
    assert permitted.reason == "mode_or_target_changed_outside_controller"
    # Confirmation of a resume requires Manual AT 70, not merely Manual.
    resumed = started(now)
    poll = now + timedelta(minutes=30)
    resumed.step(
        obs(poll + timedelta(seconds=5), poll_at=poll, mode="Manual", target_c=65), PERMIT, cfg()
    )
    assert resumed.state != ctl.HEATING_PERMITTED


def test_immediate_read_before_cloud_applies_waits_for_next_poll_then_confirms():
    now = local(hour=11)
    controller = started(now)
    report = {
        "payload": "Manual:70",
        "result": "not_observed_in_immediate_status",
        "at": (now + timedelta(seconds=16)).isoformat(),
    }
    controller.step(
        obs(now + timedelta(seconds=30), poll_at=now + timedelta(seconds=16), last_command=report),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.CONFIRMING
    poll = now + timedelta(minutes=30)
    controller.step(
        obs(
            poll + timedelta(seconds=5),
            poll_at=poll,
            mode="Manual",
            element="on",
            last_command=report,
        ),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED


def test_command_never_applied_is_detected_at_the_next_background_poll():
    now = local(hour=11)
    controller = started(now)
    poll = now + timedelta(minutes=30)
    effects = controller.step(obs(poll + timedelta(seconds=5), poll_at=poll), PERMIT, cfg())
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "command_not_applied"
    assert "fault_command_not_applied" in notices(effects)


def test_lost_confirmation_times_out_and_is_never_resent():
    now = local(hour=11)
    controller = started(now)
    for minute in range(1, 66):
        effects = controller.step(
            obs(now + timedelta(minutes=minute), poll_at=now - timedelta(seconds=10), mode=None),
            PERMIT,
            cfg(),
        )
        assert not publishes(effects)
    effects = controller.step(
        obs(now + timedelta(minutes=66), poll_at=now - timedelta(seconds=10), mode=None),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "confirmation_timeout"
    assert controller.history[-1]["status"] == "timeout"


def test_unavailable_heater_during_command_is_not_mistaken_for_a_change():
    now = local(hour=11)
    controller = started(now)
    controller.step(
        obs(now + timedelta(seconds=20), poll_at=now + timedelta(seconds=16), mode=None),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.CONFIRMING


def test_unexpected_mode_during_confirmation_is_owner_override():
    now = local(hour=11)
    controller = started(now)
    controller.step(
        obs(now + timedelta(minutes=2), poll_at=now + timedelta(minutes=1), mode="Eco"),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.OWNER_OVERRIDE
    assert controller.history[-1]["status"] == "ambiguous"


def test_ha_restart_after_sending_reconciles_from_status_and_never_resends():
    now = local(hour=11)
    controller = started(now)
    saved = controller.to_dict()
    restored = ctl.Controller.from_dict(saved)
    restored.restored(now + timedelta(minutes=2))
    assert (
        restored.state == ctl.CONFIRMING and restored.reason == "reconciling_command_after_restart"
    )
    effects = restored.step(
        obs(now + timedelta(minutes=3), poll_at=now - timedelta(seconds=10)), PERMIT, cfg()
    )
    assert not publishes(effects)
    poll = now + timedelta(minutes=30)
    restored.step(obs(poll + timedelta(seconds=3), poll_at=poll, mode="Manual"), PERMIT, cfg())
    assert restored.state == ctl.HEATING_PERMITTED
    # Unresolved after restart -> its own fault; still nothing re-sent.
    again = ctl.Controller.from_dict(saved)
    again.restored(now + timedelta(minutes=2))
    for minute in range(3, 70):
        assert not publishes(
            again.step(obs(now + timedelta(minutes=minute), poll_at=None), PERMIT, cfg())
        )
    assert again.fault == "intent_unresolved_after_restart"


def test_ha_restart_in_steady_state_reinspects_instead_of_assuming():
    now = local(hour=13)
    controller = permitted_controller(now)
    restored = ctl.Controller.from_dict(controller.to_dict())
    restored.restored(now)
    assert restored.state == ctl.OBSERVING
    # Heater was turned OFF while HA was down (owner, in the app): adopted as parked.
    restored.step(obs(now + timedelta(minutes=1), poll_at=now + timedelta(seconds=40)), HOLD, cfg())
    assert restored.state == ctl.PARKED
    assert ctl.Controller.from_dict({"state": "nonsense"}).state == ctl.OBSERVING
    assert ctl.Controller.from_dict(None).state == ctl.DISABLED


def test_bridge_restart_resets_request_history_without_false_budget():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.step(
        obs(now + timedelta(minutes=30), poll_at=now + timedelta(minutes=29), requests_total=12),
        HOLD,
        cfg(),
    )
    assert controller.requests_last_24h(now + timedelta(minutes=30)) == 0


def test_duplicate_mqtt_status_is_ignored():
    now = local(hour=11)
    controller = parked_controller(now)
    first = obs(now)
    assert controller._ingest_poll(first) is True
    assert controller._ingest_poll(first) is False
    assert controller._ingest_poll(obs(now, poll_at=now - timedelta(minutes=5))) is False


# --- owner precedence, supervision and notifications -----------------------------------


def test_app_change_takes_precedence_and_is_not_reversed_until_resume():
    now = local(hour=12)
    controller = parked_controller(now)
    effects = controller.step(obs(now, mode="Manual"), PARK, cfg())
    assert controller.state == ctl.OWNER_OVERRIDE
    assert any(key.startswith("override_") for key in notices(effects))
    for minute in range(1, 180):
        assert not publishes(
            controller.step(obs(now + timedelta(minutes=minute), mode="Manual"), PARK, cfg())
        )
    assert controller.resume(now + timedelta(hours=3))
    controller.step(
        obs(
            now + timedelta(hours=3, minutes=1),
            poll_at=now + timedelta(hours=3, seconds=30),
            mode="Manual",
        ),
        HOLD,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED


def test_owner_hold_blocks_everything_until_resume():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.set_hold(now)
    assert controller.state == ctl.OWNER_OVERRIDE
    assert not publishes(controller.step(obs(now + timedelta(seconds=1)), PERMIT, cfg()))
    assert controller.resume(now) and controller.state == ctl.OBSERVING


def test_fault_acknowledgement_reinspects_and_reports_restoration():
    now = local(hour=11)
    controller = started(now)
    poll = now + timedelta(minutes=30)
    controller.step(obs(poll, poll_at=poll - timedelta(seconds=1)), PERMIT, cfg())
    assert controller.state == ctl.FAULT_LOCKED
    assert not controller.resume(poll)  # resume is not acknowledgement
    assert controller.acknowledge(poll)
    effects = controller.step(
        obs(poll + timedelta(minutes=31), poll_at=poll + timedelta(minutes=30)), HOLD, cfg()
    )
    assert controller.state == ctl.PARKED
    assert "control_restored" in notices(effects)


def test_unexplained_heating_while_parked_is_never_interrupted_and_blocks_commands():
    now = local(hour=2)
    controller = parked_controller(now)
    effects = controller.step(obs(now, element="on", temperature_c=50), PERMIT, cfg())
    assert "unexplained_heating" in notices(effects)
    assert not publishes(effects)
    assert "unexplained_heating_in_progress" in controller.gate_failures
    # Repeated minutes: no duplicate notification within the cooldown.
    effects = controller.step(obs(now + timedelta(minutes=5), element="on"), PERMIT, cfg())
    assert "unexplained_heating" not in notices(effects)
    effects = controller.step(
        obs(
            now + timedelta(minutes=40),
            poll_at=now + timedelta(minutes=40) - timedelta(seconds=5),
            element="off",
        ),
        HOLD,
        cfg(),
    )
    assert any(e.kind == "resolve" and e.key == "unexplained_heating" for e in effects)


def test_manual_selected_but_element_never_heats_alerts_without_repeating():
    now = local(hour=12)
    controller = permitted_controller(now, since_minutes=5)
    keys = []
    for minute in range(0, 20):
        effects = controller.step(
            obs(
                now + timedelta(minutes=minute),
                poll_at=now - timedelta(minutes=5),
                mode="Manual",
                element="off",
                temperature_c=45,
            ),
            PERMIT,
            cfg(),
        )
        assert not publishes(effects)
        keys += notices(effects)
    assert keys.count("permitted_not_heating") == 1


def test_stale_status_and_missing_measurements_alert():
    now = local(hour=12)
    controller = parked_controller(now)
    effects = controller.step(
        obs(now, poll_at=now - timedelta(minutes=70)),
        ctl.Desire("hold", "data_unavailable", planner_ok=False),
        cfg(),
    )
    assert {"status_stale", "planner_unavailable"} <= set(notices(effects))


def test_publish_failure_locks():
    now = local(hour=11)
    controller = started(now)
    effects = controller.publish_failed(now)
    assert controller.state == ctl.FAULT_LOCKED and controller.intent is None
    assert "fault_publish_failed" in notices(effects)


# --- planner boundary -------------------------------------------------------------------


def advice(code, blocks=(), readiness=None, satisfied=None):
    best = SimpleNamespace(blocks=list(blocks))
    return SimpleNamespace(
        code=code,
        economic_code=code,
        assessment=SimpleNamespace(plans={"best_overall": best} if blocks else {}),
        readiness=readiness or {},
        satisfied=satisfied,
        heater=SimpleNamespace(state="off"),
    )


def test_desire_follows_plan_blocks_rounded_to_command_slots():
    now = local(hour=11)
    block = (now + timedelta(minutes=10), now + timedelta(hours=2))
    desire = plan_mod.desire_from_advice(
        now, advice("wait_cheaper_later", [block]), False, 30, None
    )
    assert desire.action == "permit"  # starts within half a poll interval
    later = (now + timedelta(minutes=40), now + timedelta(hours=2))
    desire = plan_mod.desire_from_advice(
        now, advice("wait_cheaper_later", [later]), False, 30, None
    )
    assert desire.action == "park" and desire.next_start == later[0]
    ending = (now - timedelta(hours=1), now + timedelta(minutes=10))
    desire = plan_mod.desire_from_advice(now, advice("heat_now_cheapest", [ending]), True, 30, None)
    assert desire.action == "park" and desire.reason == "planned_block_ending"
    # A following block that starts right after keeps heating instead of toggling.
    following = (now + timedelta(minutes=20), now + timedelta(hours=1))
    desire = plan_mod.desire_from_advice(
        now, advice("heat_now_cheapest", [ending, following]), True, 30, None
    )
    assert desire.action == "permit"


def test_desire_comfort_peak_satisfied_and_unavailable_rules():
    now = local(hour=16, minute=40)
    peak = local(hour=17)
    block = (now - timedelta(hours=1), now + timedelta(hours=1))

    def at_peak(code, element):
        return plan_mod.desire_from_advice(now, advice(code, [block]), True, 30, peak, element)

    assert at_peak("heat_now_comfort_fallback", "on").action == "permit"
    assert at_peak("insufficient_time", "on").action == "permit"
    # Element not heating at the last slot before a peak: park, even for comfort.
    for code in ("heat_now_comfort_fallback", "insufficient_time", "heat_now_cheapest"):
        for element in ("off", "unknown"):
            assert at_peak(code, element).reason == "peak_starting_element_not_heating"
    assert at_peak("heat_now_cheapest", "on").reason == "peak_starting"
    assert (
        plan_mod.desire_from_advice(
            now, advice("heat_now_cheapest", [block]), True, 30, peak, "on"
        ).reason
        == "peak_starting"
    )
    assert (
        plan_mod.desire_from_advice(now, advice("insufficient_time"), False, 30, None).action
        == "permit"
    )
    sat = plan_mod.desire_from_advice(
        local(hour=14), advice("heat_now_cheapest", [block], satisfied={"at": "x"}), True, 30, None
    )
    assert sat.action == "park" and sat.reason == "native_thermostat_satisfied"
    assert (
        plan_mod.desire_from_advice(now, advice("no_heating_needed"), True, 30, None).action
        == "park"
    )
    missing = plan_mod.desire_from_advice(now, None, False, 30, peak)
    assert missing.action == "hold" and not missing.planner_ok
    assert plan_mod.desire_from_advice(now, None, True, 30, peak).action == "park"
    gated = advice("data_unavailable")
    assert plan_mod.desire_from_advice(local(hour=12), gated, True, 30, peak).action == "hold"
    risk = plan_mod.desire_from_advice(
        now,
        advice("insufficient_time", readiness={"afternoon": {"status": "unachievable"}}),
        False,
        30,
        None,
    )
    assert risk.comfort_risk == "afternoon"


def test_session_temperature_caps_t1_sensor_overshoot_but_not_long_heating():
    # T1, 11 Nov 2026: ~3.7 min of element time, reading 55 -> 62 °C.
    session = plan_mod.SessionTemperature()
    t0 = local(day=11, hour=20, minute=36)
    session.update(t0, 55, "on")
    session.update(t0 + timedelta(minutes=2, seconds=40), 55, "on")
    session.update(t0 + timedelta(minutes=3), 55, "off")
    session.update(t0 + timedelta(minutes=5), 55, "on")
    session.update(t0 + timedelta(minutes=6), 55, "on")
    capped = session.update(t0 + timedelta(minutes=12), 62, "off")
    assert capped < 57.5  # 55 + ~0.19 kWh / 0.366 + 1 °C allowance
    # After 90 minutes settled, the raw reading is trusted again.
    assert session.update(t0 + timedelta(minutes=110), 60, "off") == 60
    # 11 Nov morning: 4 h at 3 kW moved 16 -> 49 °C; never capped below the raw.
    long = plan_mod.SessionTemperature()
    start = local(day=11, hour=4)
    long.update(start, 16, "on")
    for minute in range(1, 241):
        reading = long.update(start + timedelta(minutes=minute), 16 + 33 * minute / 240, "on")
    assert reading == pytest.approx(49, abs=0.01)
    # A hot-water draw (reading below the start) ends the session.
    assert long.update(start + timedelta(minutes=250), 14, "off") == 14
    assert plan_mod.SessionTemperature().update(start, None, "on") is None


def test_empty_weekly_schedule_is_a_valid_native_reference():
    assert native.parse_native("[]") == ()
    settings, _ = c.parse_options({"native_schedule_periods": "[]"})
    assert native.scheduled_permission(local(hour=12), (), "local") != "within_reported_window"


def test_controller_options_are_bounded_and_commissioning_preserved_on_restore():
    for key, value in {
        "controller_max_commands_per_day": 11,
        "controller_min_heating_minutes": 10,
        "controller_confirmation_timeout_minutes": 30,
        "controller_execution_latency_minutes": 61,
        "controller_command_topic": "x" * 65,
        "controller_bridge_qualified": "yes",
    }.items():
        with pytest.raises(ValueError):
            c.parse_options({key: value})
    settings_mod = importlib.import_module(f"{m.__package__}.settings")
    for key in (
        "controller_command_topic",
        "controller_bridge_qualified",
        "controller_notify_service",
    ):
        assert key in settings_mod.PRESERVE_ON_RESTORE


def test_controlled_advisor_reserves_latency_and_reports_controller_readiness():
    adv = advisor_mod.Advisor()
    now = local(hour=12)
    settings, tariffs = c.parse_options({})
    plan = m.Plan(state="shadow_wait_for_window")
    inputs = advisor_mod.TickInputs(
        temperature=55,
        house_kw=0.9,
        pv_ac_kw=0.5,
        export_kw=-0.4,
        status_raw=32,
        status_at=now,
        in_window=lambda at: False,
        controlled=True,
        latency_minutes=30,
    )
    result = adv.tick(now, plan, settings, tariffs, inputs)
    afternoon = result.readiness["afternoon"]
    assert afternoon["status"] == "planned_by_controller"
    assert afternoon["deadline"] - afternoon["planning_deadline"] == timedelta(minutes=30)


# --- real bridge 1.3.8 and the 1.3.9 contract --------------------------------------------


def test_guarded_payload_is_harmless_on_the_real_1_3_8_bridge(factory, clock):
    """If 1.3.9 is not installed, Manual:70 is an unknown payload: no request at all.
    The controller then locks at the next poll (command_not_applied)."""
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()


def test_park_payload_is_the_existing_auto_contract_on_the_real_bridge(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=9)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "17", "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", ctl.PARK_PAYLOAD))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/off") and read.args[1].endswith("/status")


class SimBridge:
    """Faithful model of the bridge 1.3.9 command contract plus a thermostat heater.

    Background poll every 30 min; commands processed ~15 s after publish; drop if
    the command is >30 s old or the confirmed status >60 s old; guarded Manual
    refused unless the observed target is 70; one POST then one confirmation
    read; the cloud may apply late (``apply_delay``) or never (``lose``)."""

    def __init__(self, start, temperature=45.0, apply_delay=timedelta(0), lose=False):
        self.mode, self.target, self.temperature = "Off", 70.0, temperature
        self.off_setpoint = 0.0  # what the cloud reports while OFF (unknown in reality)
        self.element = False
        self.poll_at = start
        self.requests = 1000
        self.pending = None  # (apply_at, mode)
        self.queue = []
        self.apply_delay, self.lose = apply_delay, lose
        self.last_command = None
        self.posts = []

    def publish(self, now, payload):
        self.queue.append((now, payload))

    def tick(self, now, draw_c=0.0):
        for issued, payload in list(self.queue):
            processed = issued + timedelta(seconds=15)
            if processed > now:
                continue
            self.queue.remove((issued, payload))
            if processed - self.poll_at > timedelta(seconds=60):
                self.last_command = {
                    "payload": payload,
                    "result": "dropped_status_older_than_60s",
                    "at": processed.isoformat(),
                }
                continue
            if payload == "Manual:70" and self.mode != "Off" and self.target != 70:
                self.last_command = {
                    "payload": payload,
                    "result": "refused_target_mismatch",
                    "at": processed.isoformat(),
                }
                continue
            wanted = {"Manual:70": "Manual", "off": "Off"}[payload]
            self.posts.append((processed, payload))
            self.requests += 2
            if not self.lose:
                self.pending = (processed + self.apply_delay, wanted)
            self._apply(processed + timedelta(seconds=1))
            self.poll_at = processed + timedelta(seconds=1)
            result = (
                "observed_in_status" if self.mode == wanted else "not_observed_in_immediate_status"
            )
            self.last_command = {"payload": payload, "result": result, "at": processed.isoformat()}
        self._apply(now)
        # Thermostat: 8 °C hysteresis, Manual only (OFF never heats ordinarily).
        if self.mode == "Manual" and self.temperature <= self.target - 8:
            self.element = True
        if self.element and (self.mode != "Manual" or self.temperature >= self.target):
            self.element = False
        if self.element:
            self.temperature += 3.0 / 60 / m.TANK_KWH_PER_C
        self.temperature -= 0.2 / 60 + draw_c
        if now - self.poll_at >= timedelta(minutes=30):
            self.poll_at = now
            self.requests += 3  # GET 401 -> refresh -> GET, as measured

    def _apply(self, at):
        if self.pending and self.pending[0] <= at:
            self.mode = self.pending[1]
            self.pending = None

    def observe(self, now):
        return obs(
            now,
            poll_at=self.poll_at,
            mode=self.mode,
            target_c=self.target if self.mode == "Manual" else None,
            temperature_c=round(self.temperature),
            element="on" if self.element else "off",
            requests_total=self.requests,
            last_command=self.last_command,
        )


def run_day(sim, controller, desire_at, start, minutes, draws=None):
    for minute in range(minutes):
        for second in (0, 30):
            now = start + timedelta(minutes=minute, seconds=second)
            sim.tick(now, (draws or {}).get(minute, 0.0) if second == 0 else 0.0)
            for effect in controller.step(sim.observe(now), desire_at(now), cfg()):
                if effect.kind == "publish":
                    sim.publish(now, effect.payload)


def enabled(start):
    controller = ctl.Controller()
    controller.set_enabled(True, start - timedelta(hours=1))
    controller.last_transition_at = (start - timedelta(hours=3)).isoformat()
    controller.request_samples = [[(start - timedelta(hours=1)).isoformat(), 990]]
    return controller


def test_end_to_end_solar_window_with_hot_water_draw_uses_two_commands():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), temperature=45)
    controller = enabled(start)
    window = (local(hour=11), local(hour=14))

    def desire(now):
        if window[0] - timedelta(minutes=15) <= now < window[1] - timedelta(minutes=15):
            return PERMIT
        return PARK

    run_day(sim, controller, desire, start, 300, draws={90: 6.0})  # a shower at ~12:20
    assert [payload for _, payload in sim.posts] == ["Manual:70", "off"]
    assert controller.state == ctl.PARKED and controller.fault is None
    assert sim.temperature > 60 and sim.mode == "Off"
    assert all(item["status"] == "confirmed" for item in controller.history)
    assert len(controller.commands) == 2


def test_end_to_end_late_cloud_application_confirms_at_the_next_poll():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), apply_delay=timedelta(minutes=5))
    controller = enabled(start)
    run_day(sim, controller, lambda now: PERMIT, start, 90)
    assert [p for _, p in sim.posts] == ["Manual:70"]
    assert controller.state == ctl.HEATING_PERMITTED


def test_end_to_end_lost_command_locks_once_and_never_retries():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), lose=True)
    controller = enabled(start)
    run_day(sim, controller, lambda now: PERMIT, start, 240)
    assert [p for _, p in sim.posts] == ["Manual:70"]
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "command_not_applied"


def test_end_to_end_owner_app_change_mid_session_is_respected():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29))
    controller = enabled(start)
    run_day(sim, controller, lambda now: PERMIT, start, 45)
    assert sim.mode == "Manual"
    sim.mode = "Schedule"  # owner parks it in the official app
    run_day(sim, controller, lambda now: PERMIT, start + timedelta(minutes=45), 120)
    assert controller.state == ctl.OWNER_OVERRIDE
    assert [p for _, p in sim.posts] == ["Manual:70"]  # never forced back on


# --- closed loop through the REAL 0.4.0 advisor -----------------------------------------


def sunny_pv(at):
    hour = at.astimezone(m.HOBART).hour + at.astimezone(m.HOBART).minute / 60
    return max(0.0, 5.0 * (1 - ((hour - 13.0) / 6.0) ** 2))


def closed_loop(start, minutes, temperature, pv=sunny_pv, draws=None, forecast=True):
    """Minute-by-minute: bridge model -> HA-like observation -> advisor ->
    desire -> controller -> MQTT message -> bridge model. Returns the trace."""
    settings, tariffs = c.parse_options(
        {"forecast_enabled": forecast, "native_schedule_periods": "[]"}
    )
    advisor = advisor_mod.Advisor()
    session = plan_mod.SessionTemperature()
    sim = SimBridge(start - timedelta(minutes=29), temperature=temperature)
    controller = enabled(start)
    trace = []
    previous = "unknown"
    for minute in range(minutes):
        now = start + timedelta(minutes=minute)
        sim.tick(now, (draws or {}).get(minute, 0.0))
        house = 0.6 + (3.0 if sim.element else 0.0)
        pv_now = pv(now)
        series = (
            tuple(
                (
                    now + timedelta(minutes=15 * k),
                    now + timedelta(minutes=15 * (k + 1)),
                    pv(now + timedelta(minutes=15 * k)),
                )
                for k in range(96)
            )
            if forecast
            else ()
        )
        reading = session.update(now, round(sim.temperature), previous)
        permitted = controller.state in {ctl.HEATING_PERMITTED, ctl.PARK_REQUESTED}
        inputs = advisor_mod.TickInputs(
            temperature=reading,
            house_kw=house,
            pv_ac_kw=pv_now,
            export_kw=pv_now - house,
            status_raw=33 if sim.element else 32,
            status_at=sim.poll_at,
            in_window=lambda at, p=permitted: p,
            pv_series=series,
            forecast_available=forecast,
            controlled=True,
            latency_minutes=30,
        )
        advice = advisor.tick(
            now, m.Plan(state="shadow_wait_for_window"), settings, tariffs, inputs
        )
        previous = advice.heater.state
        change = goals_mod.next_tariff_change(now, tariffs, settings.tariff_clock)
        peak = change[0] if change and change[1].kind == "peak" else None
        desire = plan_mod.desire_from_advice(now, advice, permitted, 30, peak, advice.heater.state)
        observation = sim.observe(now)
        observation.element, observation.element_confidence = (
            advice.heater.state,
            advice.heater.confidence,
        )
        for effect in controller.step(observation, desire, cfg()):
            if effect.kind == "publish":
                sim.publish(now, effect.payload)
        trace.append(
            (now, sim.mode, sim.element, round(sim.temperature, 1), desire.action, controller.state)
        )
    return sim, controller, trace


def peak_grid_minutes(trace, tariffs, settings, pv=sunny_pv):
    """Minutes the element ran in a PEAK tariff period without solar covering it."""
    count = 0
    for at, _mode, element, *_ in trace:
        if element and m.tariff_at(at, tariffs, settings.tariff_clock).kind == "peak":
            if pv(at) - 0.6 < 2.5:
                count += 1
    return count


def test_closed_loop_sunny_weekday_heats_on_solar_and_is_ready_before_the_peak():
    start = local(hour=5)  # Tue 10 Nov 2026, daylight time: peaks 08-11 and 17-22 local
    sim, controller, trace = closed_loop(start, 13 * 60, 50, draws={210: 10.0})  # shower 08:30
    posts = [(at.astimezone(m.HOBART).strftime("%H:%M"), payload) for at, payload in sim.posts]
    assert controller.fault is None, (controller.reason, posts)
    assert [payload for _, payload in posts] == ["Manual:70", "off"], posts
    assert "09:00" <= posts[0][0] <= "14:00", posts  # solar, not the 04:00 off-peak grid
    by_time = {at.astimezone(m.HOBART).strftime("%H:%M"): row for at, *row in trace}
    assert by_time["08:00"][2] >= 42  # morning ready without any heating
    assert by_time["17:00"][2] >= 65, by_time["17:00"]  # ready before the evening peak
    assert sim.mode == "Off" and posts[1][0] <= "17:00"
    settings, tariffs = c.parse_options({})
    assert peak_grid_minutes(trace, tariffs, settings) == 0
    assert all(item["status"] == "confirmed" for item in controller.history)


def test_closed_loop_shower_just_before_the_deadline_puts_comfort_first():
    start = local(hour=5)
    sim, controller, trace = closed_loop(start, 4 * 60, 50, draws={150: 8.0})  # 07:30
    posts = [(at.astimezone(m.HOBART).strftime("%H:%M"), payload) for at, payload in sim.posts]
    assert controller.fault is None
    assert posts[0] == ("07:31", "Manual:70"), posts  # comfort fallback at the next poll
    assert len(posts) <= 4


def test_closed_loop_cloudy_day_falls_back_to_off_peak_grid_before_the_peak():
    start = local(hour=9)
    sim, controller, trace = closed_loop(start, 9 * 60, 45, pv=lambda at: 0.2)
    posts = [(at.astimezone(m.HOBART).strftime("%H:%M"), payload) for at, payload in sim.posts]
    assert controller.fault is None, (controller.reason, posts)
    assert posts and posts[0][1] == "Manual:70", posts
    assert "11:00" <= posts[0][0] <= "14:00", posts  # after the morning peak, latest start honoured
    by_time = {at.astimezone(m.HOBART).strftime("%H:%M"): row for at, *row in trace}
    assert by_time["17:00"][2] >= 65, by_time["17:00"]
    assert len(sim.posts) <= 4
    settings, tariffs = c.parse_options({})
    assert peak_grid_minutes(trace, tariffs, settings, pv=lambda at: 0.2) == 0


def winter_pv(at):
    hour = at.astimezone(m.HOBART).hour + at.astimezone(m.HOBART).minute / 60
    return max(0.0, 3.2 * (1 - ((hour - 12.0) / 4.0) ** 2))


def ready_at(trace, hhmm):
    return {at.astimezone(m.HOBART).strftime("%H:%M"): row for at, *row in trace}[hhmm][2]


@pytest.mark.parametrize(
    "label,start,minutes,pv,deadline",
    [
        # Winter weekday (AEST): evening peak starts 16:00 local; weak solar.
        ("winter_weekday", local(month=7, day=14, hour=5), 11 * 60 + 30, winter_pv, "16:00"),
        # Weekend: all off-peak; household afternoon time 16:00.
        ("weekend", local(day=14, hour=5), 11 * 60 + 30, sunny_pv, "16:00"),
        # Daylight saving starts in Tasmania on Sun 4 Oct 2026 (02:00 -> 03:00).
        ("dst_start_sunday", local(month=10, day=4, hour=4), 12 * 60 + 30, sunny_pv, "16:00"),
    ],
)
def test_closed_loop_calendar_cases_are_ready_without_peak_grid(
    label, start, minutes, pv, deadline
):
    sim, controller, trace = closed_loop(start, minutes, 45, pv=pv)
    assert controller.fault is None, (label, controller.reason)
    assert 1 <= len(sim.posts) <= 4, (label, sim.posts)
    assert ready_at(trace, deadline) >= 65, (label, ready_at(trace, deadline))
    settings, tariffs = c.parse_options({})
    assert peak_grid_minutes(trace, tariffs, settings, pv=pv) == 0, label


def test_closed_loop_forecast_error_sunny_forecast_cloudy_reality_still_ready():
    """The forecast promises sun; reality is cloud. Measured PV corrects nothing
    here (the test feeds the optimistic series), so readiness relies on the
    latest-start comfort fallback with the 30-minute latency reserve."""
    start = local(hour=9)
    settings, tariffs = c.parse_options({"forecast_enabled": True, "native_schedule_periods": "[]"})
    advisor = advisor_mod.Advisor()
    sim = SimBridge(start - timedelta(minutes=29), temperature=45)
    controller = enabled(start)
    trace = []
    for minute in range(9 * 60):
        now = start + timedelta(minutes=minute)
        sim.tick(now)
        house = 0.6 + (3.0 if sim.element else 0.0)
        actual = 0.3
        series = tuple(
            (
                now + timedelta(minutes=15 * k),
                now + timedelta(minutes=15 * (k + 1)),
                sunny_pv(now + timedelta(minutes=15 * k)),
            )
            for k in range(96)
        )
        permitted = controller.state in {ctl.HEATING_PERMITTED, ctl.PARK_REQUESTED}
        inputs = advisor_mod.TickInputs(
            temperature=round(sim.temperature),
            house_kw=house,
            pv_ac_kw=actual,
            export_kw=actual - house,
            status_raw=33 if sim.element else 32,
            status_at=sim.poll_at,
            in_window=lambda at, p=permitted: p,
            pv_series=series,
            forecast_available=True,
            controlled=True,
            latency_minutes=30,
        )
        advice = advisor.tick(
            now, m.Plan(state="shadow_wait_for_window"), settings, tariffs, inputs
        )
        change = goals_mod.next_tariff_change(now, tariffs, settings.tariff_clock)
        peak = change[0] if change and change[1].kind == "peak" else None
        desire = plan_mod.desire_from_advice(now, advice, permitted, 30, peak, advice.heater.state)
        observation = sim.observe(now)
        observation.element, observation.element_confidence = (
            advice.heater.state,
            advice.heater.confidence,
        )
        for effect in controller.step(observation, desire, cfg()):
            if effect.kind == "publish":
                sim.publish(now, effect.payload)
        trace.append(
            (now, sim.mode, sim.element, round(sim.temperature, 1), desire.action, controller.state)
        )
    assert controller.fault is None
    assert ready_at(trace, "17:00") >= 65, ready_at(trace, "17:00")
    assert len(sim.posts) <= 4


def test_disabled_controller_is_silent_while_the_native_schedule_heats():
    """Stage A: installed but disabled, with the EXISTING (non-empty) native
    programme still heating. No notifications, no tracking, no commands."""
    now = local(hour=11)
    controller = ctl.Controller()
    for minute in range(0, 180):
        at = now + timedelta(minutes=minute)
        effects = controller.step(
            obs(at, poll_at=now - timedelta(minutes=90), element="on", mode="Off"),
            ctl.Desire("hold", "data_unavailable", planner_ok=False, comfort_risk="afternoon"),
            ctl.ControllerConfig(),
        )
        assert not [e for e in effects if e.kind in {"publish", "notify"}], effects
    assert controller.state == ctl.DISABLED
    assert controller.unexplained_since is None and controller.alerts == {}
    # Disabling after an alert resolves it rather than leaving it standing.
    enabled_ = parked_controller(now)
    enabled_.step(obs(now, element="on"), PERMIT, cfg())
    assert "unexplained_heating" in enabled_.alerts
    enabled_.set_enabled(False, now)
    effects = enabled_.step(obs(now + timedelta(minutes=1), element="on"), PERMIT, cfg())
    assert any(e.kind == "resolve" and e.key == "unexplained_heating" for e in effects)
    assert not [e for e in effects if e.kind == "notify"]


# --- native clock and fallback warnings: empty versus non-empty programme ---------------

CLOCK_WARNING = "check_thermann_clock_manual_dst_adjustment_required"
FALLBACK_WARNING = "native_programme_is_primary_comfort_fallback"
PROTECTIVE = "manufacturer_antibacterial_and_frost_protection_may_heat_while_parked"
NO_HEAT = "empty_native_schedule_and_automatic_control_off_no_normal_heating"


def evaluate_at(instance, at, options):
    instance.set_native_reference(options)
    instance.update(at)
    return instance.values["device_clock_check"], set(instance.plan.warnings)


@pytest.mark.parametrize(
    "at",
    [
        local(day=10, hour=12),  # ordinary summer weekday
        local(month=10, day=4, hour=12),  # DST starts (Sun 4 Oct 2026)
        local(month=10, day=5, hour=12),  # first weekday after DST start
        local(year=2027, month=4, day=4, hour=12),  # DST ends (Sun 4 Apr 2027)
        local(year=2027, month=4, day=5, hour=12),  # first weekday after DST end
    ],
)
def test_empty_programme_has_no_clock_or_fallback_warning_but_keeps_protective(runtime, at):  # noqa: F811
    instance, _, _ = runtime
    check, warnings = evaluate_at(instance, at, {"native_schedule_periods": "[]"})
    assert check == "not_applicable_empty_schedule"
    assert CLOCK_WARNING not in warnings and FALLBACK_WARNING not in warnings
    assert "native_schedule_times_approximate_clock_unverified" not in warnings
    assert "reported_native_windows_may_not_fit_depleted_tank_scenario" not in warnings
    assert PROTECTIVE in warnings  # protective functions are never hidden
    assert NO_HEAT in warnings  # before commissioning nothing heats ordinarily
    instance.controller_active = True
    _, warnings = evaluate_at(instance, at, {"native_schedule_periods": "[]"})
    assert NO_HEAT not in warnings and PROTECTIVE in warnings


def test_existing_programme_keeps_clock_and_fallback_warnings_across_dst(runtime):  # noqa: F811
    instance, _, _ = runtime
    # Today's programme (the default reference), clock never checked.
    check, warnings = evaluate_at(instance, local(day=10, hour=12), {})
    assert check == "check_required"
    assert {CLOCK_WARNING, FALLBACK_WARNING} <= warnings and PROTECTIVE not in warnings
    # Checked after the October DST change: no clock warning until the next one.
    verified = {"native_schedule_clock_verified": True, "native_clock_check_date": "2026-10-05"}
    check, warnings = evaluate_at(instance, local(day=10, hour=12), verified)
    assert check == "checked_this_dst_period" and CLOCK_WARNING not in warnings
    assert FALLBACK_WARNING in warnings
    check, warnings = evaluate_at(instance, local(year=2027, month=4, day=5, hour=12), verified)
    assert check == "check_required" and CLOCK_WARNING in warnings
    # Switching to the empty programme (commissioning Stage C) clears both.
    check, warnings = evaluate_at(
        instance,
        local(year=2027, month=4, day=5, hour=12),
        {**verified, "native_schedule_periods": "[]"},
    )
    assert check == "not_applicable_empty_schedule" and CLOCK_WARNING not in warnings


@pytest.mark.parametrize(
    "at,expected_local",
    [
        (local(day=10, hour=16, minute=30), "17:00"),  # AEDT: 16:00 AEST peak = 17:00 local
        (local(month=7, day=14, hour=15, minute=30), "16:00"),  # AEST winter
        (local(month=10, day=5, hour=7, minute=30), "08:00"),  # first weekday after DST start
        (local(year=2027, month=4, day=5, hour=6, minute=30), "07:00"),  # after DST end
    ],
)
def test_tariff_93_boundaries_stay_fixed_aest_across_dst(at, expected_local):
    settings, tariffs = c.parse_options({"native_schedule_periods": "[]"})
    change = goals_mod.next_tariff_change(at, tariffs, settings.tariff_clock)
    assert change[1].kind == "peak"
    assert change[0].astimezone(m.HOBART).strftime("%H:%M") == expected_local


# --- 0.6.0: software OFF as the parked state ---------------------------------------------


def test_off_manual_off_cycle_ignores_off_setpoint_and_requires_70_in_manual():
    now = local(hour=11)
    controller = parked_controller(now)
    # Parked OFF reports a setpoint of 40 (as the app showed with an empty Schedule).
    [start] = publishes(controller.step(obs(now, target_c=40), PERMIT, cfg()))
    assert start.payload == "Manual:70" and controller.intent["prior_mode"] == "Off"
    confirm = now + timedelta(seconds=20)
    controller.step(
        obs(confirm + timedelta(seconds=5), poll_at=confirm, mode="Manual", element="on"),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED
    later = now + timedelta(minutes=45)
    [park] = publishes(controller.step(obs(later, mode="Manual", element="on"), PARK, cfg()))
    assert park.payload == "off"
    done = later + timedelta(seconds=20)
    # OFF confirmation does not depend on what OFF reports as its setpoint.
    controller.step(obs(done + timedelta(seconds=5), poll_at=done, target_c=None), PARK, cfg())
    assert controller.state == ctl.PARKED
    assert [item["status"] for item in controller.history] == ["confirmed", "confirmed"]


def test_park_gate_requires_manual_at_70_and_permit_gate_requires_off():
    now = local(hour=12)
    permitted = permitted_controller(now)
    assert "target_not_70" in permitted.gates(
        obs(now, mode="Manual", target_c=65), "park", cfg(), True
    )
    parked = parked_controller(now)
    failures = parked.gates(obs(now, mode="Manual"), "permit", cfg(), True)
    assert "heater_not_off" in failures
    assert parked.gates(obs(now, target_c=None), "permit", cfg(), True) == []


@pytest.mark.parametrize("mode", ["Schedule", "Eco", "Holiday", "Unknown"])
def test_any_mode_other_than_off_or_manual_70_is_owner_control(mode):
    now = local(hour=12)
    controller = ctl.Controller()
    controller.set_enabled(True, now - timedelta(minutes=5))
    controller.step(obs(now, mode=mode, target_c=70), PERMIT, cfg())
    assert controller.state == ctl.OWNER_OVERRIDE
    assert "OFF or in Manual at 70" in controller.guidance()


@pytest.mark.parametrize(
    "start_mode,app_mode", [("Off", "Manual"), ("Manual", "Off"), ("Off", "Schedule")]
)
def test_app_changes_in_either_direction_take_precedence(start_mode, app_mode):
    now = local(hour=12)
    controller = parked_controller(now) if start_mode == "Off" else permitted_controller(now)
    at = now + timedelta(minutes=5)
    effects = controller.step(
        obs(at, poll_at=at - timedelta(seconds=5), mode=app_mode), PERMIT, cfg()
    )
    assert controller.state == ctl.OWNER_OVERRIDE and not publishes(effects)
    for minute in range(1, 120):
        t = at + timedelta(minutes=minute)
        desire = PARK if app_mode == "Manual" else PERMIT
        assert not publishes(
            controller.step(obs(t, poll_at=t - timedelta(seconds=5), mode=app_mode), desire, cfg())
        )


def test_protective_heating_while_off_is_never_interrupted():
    now = local(day=12, hour=2)
    controller = parked_controller(now)
    effects = controller.step(obs(now, element="on", temperature_c=55), PERMIT, cfg())
    assert not publishes(effects)
    keys = notices(effects)
    assert "unexplained_heating" in keys
    notice = next(e for e in effects if e.key == "unexplained_heating")
    assert "antibacterial" in notice.message and "OFF" in notice.title
    # During it, neither a comfort start nor anything else is sent.
    comfort = ctl.Desire("permit", "comfort_fallback_latest_start", comfort=True)
    for minute in range(1, 40):
        t = now + timedelta(minutes=minute)
        assert not publishes(
            controller.step(obs(t, poll_at=t - timedelta(seconds=5), element="on"), comfort, cfg())
        )
    t = now + timedelta(minutes=41)
    assert publishes(
        controller.step(obs(t, poll_at=t - timedelta(seconds=5), element="off"), comfort, cfg())
    )


def test_cloud_failure_while_off_sends_nothing_and_alerts_once():
    now = local(hour=12)
    controller = parked_controller(now)
    keys = []
    for minute in range(0, 90):
        t = now + timedelta(minutes=minute)
        effects = controller.step(
            obs(t, cloud_health="backoff", consecutive_failures=2), PERMIT, cfg()
        )
        assert not publishes(effects)
        keys += notices(effects)
    assert keys.count("cloud_fault") == 1
    assert controller.state == ctl.HEATING_REQUESTED  # wanted, but gated


def test_restart_while_off_or_resuming_never_resends():
    now = local(hour=11)
    steady = ctl.Controller.from_dict(parked_controller(now).to_dict())
    steady.restored(now)
    assert steady.state == ctl.OBSERVING
    steady.step(
        obs(now + timedelta(minutes=1), poll_at=now + timedelta(seconds=30), target_c=None),
        HOLD,
        cfg(),
    )
    assert steady.state == ctl.PARKED
    pending = ctl.Controller.from_dict(started(now).to_dict())
    pending.restored(now + timedelta(minutes=1))
    assert pending.state == ctl.CONFIRMING
    for minute in range(2, 30):
        t = now + timedelta(minutes=minute)
        assert not publishes(
            pending.step(obs(t, poll_at=now - timedelta(seconds=10)), PERMIT, cfg())
        )
    poll = now + timedelta(minutes=30)
    pending.step(obs(poll + timedelta(seconds=5), poll_at=poll, mode="Manual"), PERMIT, cfg())
    assert pending.state == ctl.HEATING_PERMITTED


def test_bridge_1_3_8_cannot_poll_off_with_an_out_of_range_setpoint(factory, module):
    """Why bridge 1.3.9 is required for OFF parking: 1.3.8 rejects an OFF status
    whose setpoint is outside 20-75 °C, which would back the bridge off while the
    heater stays OFF. (What OFF really reports is a T3 observation.)"""
    bridge = factory()
    ready(bridge)
    body = {"result": {**STATUS["result"], "Cmd": "16", "T_SetPoint": "0"}}
    bridge.session.request.side_effect = [response(body=body)]
    with pytest.raises(module.CloudError):
        bridge.poll_status("TEST123")


def test_off_path_on_the_real_bridge_posts_off_and_confirms_cmd_16(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=9)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "16", "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", ctl.PARK_PAYLOAD))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/off") and write.kwargs["data"] == ""
    assert bridge.confirmed["TEST123"][1]["Cmd"] == 16


class ProtectiveSimBridge(SimBridge):
    """OFF heater that runs an antibacterial cycle (element on while OFF)."""

    def __init__(self, *args, protective=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.protective = protective  # (start, end)

    def tick(self, now, draw_c=0.0):
        super().tick(now, draw_c)
        if (
            self.protective
            and self.mode == "Off"
            and self.protective[0] <= now < self.protective[1]
        ):
            self.element = True
            self.temperature += 3.0 / 60 / m.TANK_KWH_PER_C


@pytest.mark.parametrize("off_setpoint", [0.0, 40.0, 70.0])
def test_closed_loop_off_park_with_antibacterial_cycle_and_any_off_setpoint(off_setpoint):
    start = local(hour=10, minute=50)
    cycle = (local(hour=12, minute=30), local(hour=13, minute=10))
    sim = ProtectiveSimBridge(start - timedelta(minutes=29), temperature=45, protective=cycle)
    sim.off_setpoint = off_setpoint
    controller = enabled(start)
    window = (local(hour=11), local(hour=12))

    def desire(now):
        if window[0] - timedelta(minutes=15) <= now < window[1] - timedelta(minutes=15):
            return PERMIT
        return PERMIT if now >= local(hour=12, minute=40) else PARK

    run_day(sim, controller, desire, start, 240)
    payloads = [payload for at, payload in sim.posts]
    assert payloads[:2] == ["Manual:70", "off"], sim.posts
    # No command while the protective cycle ran (12:30-13:10), even though the
    # planner asked to heat from 12:40.
    during = [at for at, _ in sim.posts if cycle[0] <= at < cycle[1] + timedelta(seconds=20)]
    assert during == []
    assert controller.fault is None
