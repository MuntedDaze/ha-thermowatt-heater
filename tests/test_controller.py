"""Production controller (0.6.2): state machine, gates, confirmation,
reconciliation, planner boundary and end-to-end simulation. Offline only: no HA,
MQTT, cloud or heater. The bridge is either a faithful model of the 1.3.11
contract or the REAL in-tree bridge code with mocked HTTP."""

from datetime import timedelta
import importlib
from types import SimpleNamespace

import pytest

from conftest import STATUS, response
from test_shadow_model import c, local, m, runtime  # noqa: F401
from test_cloud_and_commands import ready

ctl = importlib.import_module(f"{m.__package__}.controller")
ROOT_PACKAGE = __import__("pathlib").Path(ctl.__file__).parent
plan_mod = importlib.import_module(f"{m.__package__}.control_plan")
permission_mod = importlib.import_module(f"{m.__package__}.permission")
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
        "bridge_refresh_limit": 24,  # bridge >= 1.3.10
        "bridge_refreshes_24h": 0,
        "bridge_confirmation_followups": [60, 300],  # bridge >= 1.3.11
        "bridge_confirmation_pending": False,
        "bridge_command_policy": "automation",  # bridge app option (0.7.1 gate)
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


def test_stale_status_no_longer_waits_for_a_poll_with_bridge_1_3_10():
    """0.6.1: the bridge reads status once before a command when its status is
    older than 60 s, so the controller publishes when the planner decides."""
    now = local(hour=11, minute=5)
    controller = parked_controller(now)
    stale = obs(now, poll_at=now - timedelta(minutes=24))
    effects = controller.step(stale, PERMIT, cfg())
    assert [e.payload for e in publishes(effects)] == ["Manual:70"]
    assert controller.state == ctl.CONFIRMING


def test_bridge_without_pre_command_refresh_is_never_commanded():
    """Bridge 1.3.9 reports OFF (Cmd 8) as Unknown and drops stale commands."""
    now = local(hour=11, minute=5)
    controller = parked_controller(now)
    for poll_age in (5, 600):
        old = obs(now, poll_at=now - timedelta(seconds=poll_age), bridge_refresh_limit=None)
        assert not publishes(controller.step(old, PERMIT, cfg()))
        assert "bridge_1_3_11_required" in controller.gate_failures


def test_exhausted_bridge_refresh_budget_waits_for_a_background_poll():
    now = local(hour=11, minute=5)
    controller = parked_controller(now)
    spent = {"bridge_refreshes_24h": 24, "bridge_refresh_limit": 24}
    assert not publishes(
        controller.step(obs(now, poll_at=now - timedelta(minutes=10), **spent), PERMIT, cfg())
    )
    assert controller.reason == "bridge_refresh_budget_exhausted"
    later = now + timedelta(minutes=20)
    fresh = obs(later, poll_at=later - timedelta(seconds=10), **spent)  # no refresh needed
    assert len(publishes(controller.step(fresh, PERMIT, cfg()))) == 1


def test_status_older_than_one_poll_interval_blocks_commands():
    now = local(hour=11, minute=5)
    controller = parked_controller(now)
    assert not publishes(
        controller.step(obs(now, poll_at=now - timedelta(minutes=36)), PERMIT, cfg())
    )
    assert "heater_status_too_old" in controller.gate_failures


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
    # 0.6.1: the bridge's FRESH status showed another target: owner control.
    assert controller.state == ctl.OWNER_OVERRIDE
    assert controller.reason == "mode_or_target_changed_outside_controller"
    assert controller.history[-1]["status"] == "external_change"
    # While OFF: 70 or no usable setpoint (unreported or outside 20-75) allows
    # the guarded resume, which sends 70 explicitly.
    for reported in (70, 0, 90, None):
        parked = parked_controller(now)
        effects = parked.step(
            obs(now + timedelta(seconds=5), poll_at=now, target_c=reported), PERMIT, cfg()
        )
        assert [e.payload for e in publishes(effects)] == ["Manual:70"], reported
    # A usable OTHER target while OFF may be the owner's setting: never
    # silently replaced; control pauses with an explicit notice.
    for reported in (65, 40, 20, 75):
        parked = parked_controller(now)
        effects = parked.step(
            obs(now + timedelta(seconds=5), poll_at=now, target_c=reported), PERMIT, cfg()
        )
        assert not publishes(effects), reported
        assert parked.state == ctl.OWNER_OVERRIDE and parked.reason == "off_target_not_70"
        assert any(f"{reported}" in e.message for e in effects if e.kind == "notify")
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


# --- the REAL in-tree bridge (1.3.11) with mocked HTTP ------------------------------------


def test_resume_from_schedule_is_refused_by_the_real_bridge(factory, clock):
    """The controller resumes only from OFF; Schedule at 70 is the owner's choice,
    so the bridge refuses it with no request (refused_mode_mismatch)."""
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert bridge.last_command["result"] == "refused_mode_mismatch"


def test_park_payload_posts_off_once_on_the_real_bridge(factory, clock):
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
    # A third state after the POST is never success (bridge 1.3.11).
    assert bridge.last_command["result"] == "unexpected_state_after_command"


class SimBridge:
    """Faithful model of the bridge 1.3.11 command contract plus a thermostat heater.

    Background poll every 30 min; commands processed ~15 s after publish; drop if
    the command is >30 s old. Status older than 60 s gets ONE pre-command read
    (counted, at most 24 a day). The FRESH status is then re-checked under the
    automation policy: Manual:70 only from OFF (target 70 or unusable), off only
    from Manual 70; otherwise refused (owner choice); already in the requested
    state sends nothing. One POST (never repeated) then an immediate read; if
    that still shows the old mode the command is ``awaiting_confirmation`` and at
    most two follow-up reads (60 s, 300 s after the POST; background polls count)
    decide it, else ``not_confirmed_within_limit``. No other command is accepted
    meanwhile. The cloud may apply late (``apply_delay``) or never (``lose``).
    OFF reports ``off_setpoint``."""

    def __init__(self, start, temperature=45.0, apply_delay=timedelta(0), lose=False):
        self.mode, self.target, self.temperature = "Off", 70.0, temperature
        self.off_setpoint = 70.0  # T3: OFF keeps reporting 70
        self.element = False
        self.poll_at = start
        self.requests = 1000
        self.pending = None  # (apply_at, mode)
        self.queue = []
        self.apply_delay, self.lose = apply_delay, lose
        self.last_command = None
        self.posts = []
        self.refreshes = []  # times of pre-command status reads
        self.awaiting = None  # [posted, payload, wanted, followups_done, refresh]
        self.refused_while_pending = []

    def publish(self, now, payload):
        self.queue.append((now, payload))

    def _result(self, payload, result, at, refresh):
        self.last_command = {
            "payload": payload,
            "result": result,
            "status_refresh": refresh,
            "at": at.isoformat(),
        }

    def reported_target(self):
        return self.target if self.mode == "Manual" else self.off_setpoint

    def tick(self, now, draw_c=0.0):
        for issued, payload in list(self.queue):
            processed = issued + timedelta(seconds=15)
            if processed > now:
                continue
            self.queue.remove((issued, payload))
            if self.awaiting:
                self.refused_while_pending.append((processed, payload))
                continue
            refresh = "not_needed"
            if processed - self.poll_at > timedelta(seconds=60):
                recent = [at for at in self.refreshes if processed - at < timedelta(hours=24)]
                if len(recent) >= 24:
                    self._result(payload, "refused_status_refresh_limit", processed, "refused")
                    continue
                self.refreshes.append(processed)
                self.requests += 1
                self._apply(processed)
                self.poll_at = processed
                refresh = "refreshed"
            target = self.reported_target()
            usable = 20 <= target <= 75
            reason = None
            if payload == "Manual:70":
                if target != 70 and not (self.mode == "Off" and not usable):
                    reason = "refused_target_mismatch"
                elif self.mode == "Manual":
                    reason = "already_in_requested_state"
                elif self.mode != "Off":
                    reason = "refused_mode_mismatch"
            elif self.mode == "Off":
                reason = "already_in_requested_state"
            elif self.mode != "Manual":
                reason = "refused_mode_mismatch"
            elif target != 70:
                reason = "refused_target_mismatch"
            if reason:
                self._result(payload, reason, processed, refresh)
                continue
            wanted = {"Manual:70": "Manual", "off": "Off"}[payload]
            self.posts.append((processed, payload))
            self.requests += 2
            if not self.lose:
                self.pending = (processed + self.apply_delay, wanted)
            self._apply(processed + timedelta(seconds=1))
            self.poll_at = processed + timedelta(seconds=1)
            if self.mode == wanted:
                self._result(payload, "observed_in_status", processed, refresh)
            else:
                self.awaiting = [processed, payload, wanted, 0, refresh]
                self._result(payload, "awaiting_confirmation", processed, refresh)
        if self.awaiting:
            posted, payload, wanted, done, refresh = self.awaiting
            if done < 2 and now >= posted + timedelta(seconds=(60, 300)[done]):
                self.awaiting[3] = done = done + 1
                self.requests += 1
                self._apply(now)
                self.poll_at = now
                self._judge(now)
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
            if self.awaiting:
                self._judge(now)
        if self.awaiting and now >= self.awaiting[0] + timedelta(seconds=360):
            self._finish(now, "not_confirmed_within_limit")

    def _judge(self, now):
        posted, payload, wanted, done, refresh = self.awaiting
        if self.mode == wanted:
            self._finish(now, "observed_in_status")
        elif self.mode != {"Manual": "Off", "Off": "Manual"}[wanted]:
            self._finish(now, "unexpected_state_after_command")
        elif done >= 2:
            self._finish(now, "not_confirmed_within_limit")
        else:
            self._result(payload, "awaiting_confirmation", now, refresh)

    def _finish(self, now, result):
        posted, payload, wanted, done, refresh = self.awaiting
        self.awaiting = None
        self._result(payload, result, now, refresh)

    def _apply(self, at):
        if self.pending and self.pending[0] <= at:
            self.mode = self.pending[1]
            self.pending = None

    def observe(self, now):
        return obs(
            now,
            poll_at=self.poll_at,
            mode=self.mode,
            target_c=self.reported_target(),
            temperature_c=round(self.temperature),
            element="on" if self.element else "off",
            requests_total=self.requests,
            last_command=self.last_command,
            bridge_confirmation_pending=self.awaiting is not None,
            bridge_refreshes_24h=len(
                [at for at in self.refreshes if now - at < timedelta(hours=24)]
            ),
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
    # 0.6.2 + bridge 1.3.11: ends within the bridge's bounded window (~6 min).
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "command_not_confirmed"
    assert controller.history[-1]["status"] == "not_confirmed"


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


def closed_loop(
    start,
    minutes,
    temperature,
    pv=sunny_pv,
    draws=None,
    forecast=True,
    economic=False,
    extra_load=None,
    options=None,
    holiday=None,
):
    """Minute-by-minute: bridge model -> HA-like observation -> advisor ->
    desire -> controller -> MQTT message -> bridge model. Returns the trace."""
    settings, tariffs = c.parse_options(
        {"forecast_enabled": forecast, "native_schedule_periods": "[]", **(options or {})}
    )
    standby = permission_mod.StandbyPermission() if economic else None
    advisor = advisor_mod.Advisor()
    session = plan_mod.SessionTemperature()
    sim = SimBridge(start - timedelta(minutes=29), temperature=temperature)
    controller = enabled(start)
    trace = []
    previous = "unknown"
    for minute in range(minutes):
        now = start + timedelta(minutes=minute)
        sim.tick(now, (draws or {}).get(minute, 0.0))
        house = 0.6 + (3.0 if sim.element else 0.0) + (extra_load(now) if extra_load else 0.0)
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
            holiday=holiday if holiday and now < holiday[1] else None,
        )
        advice = advisor.tick(
            now, m.Plan(state="shadow_wait_for_window"), settings, tariffs, inputs
        )
        previous = advice.heater.state
        change = goals_mod.next_tariff_change(now, tariffs, settings.tariff_clock)
        peak = change[0] if change and change[1].kind == "peak" else None
        away = holiday is not None and holiday[0] <= now < holiday[1]
        peak_now = m.tariff_at(now, tariffs, settings.tariff_clock).kind == "peak"
        if economic and not away:
            soon = peak is not None and now <= peak <= now + timedelta(minutes=35)
            econ = standby.assess(
                now, advice, settings, tariffs, decision_at=peak if soon else None
            )
            desire = plan_mod.desire_from_advice(
                now,
                advice,
                permitted,
                30,
                peak,
                advice.heater.state,
                standby=standby,
                economics=econ,
                reading=reading,
                morning_window=plan_mod.morning_failsafe_window(now, settings, tariffs),
                peak_now=peak_now,
            )
        elif away:
            desire = plan_mod.holiday_desire(
                now, holiday, advice, permitted, 30, peak, advice.heater.state, peak_now
            )
        else:
            desire = plan_mod.desire_from_advice(
                now, advice, permitted, 30, peak, advice.heater.state
            )
        observation = sim.observe(now)
        observation.element, observation.element_confidence = (
            advice.heater.state,
            advice.heater.confidence,
        )
        for effect in controller.step(observation, desire, cfg()):
            if effect.kind == "publish":
                sim.publish(now, effect.payload)
        trace.append(
            (
                now,
                sim.mode,
                sim.element,
                round(sim.temperature, 1),
                desire.action,
                controller.state,
                desire.reason,
            )
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
    # 0.7.0: a shower at 06:30 (preferred 06:00 met, hard deadline 07:00 still
    # ahead) must restart heating at once for the hard deadline.
    start = local(hour=5)
    sim, controller, trace = closed_loop(start, 4 * 60, 50, draws={90: 12.0})  # 06:30, to 38 °C
    posts = [(at.astimezone(m.HOBART).strftime("%H:%M"), payload) for at, payload in sim.posts]
    assert controller.fault is None
    # The comfort start follows the shower within the minute (no poll wait).
    assert posts[0] == ("06:30", "Manual:70"), posts
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
    # Parked OFF reporting no usable setpoint (here 0): resume sends 70 explicitly.
    [start] = publishes(controller.step(obs(now, target_c=0), PERMIT, cfg()))
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


@pytest.mark.parametrize("cmd", ["8", "16"])
def test_real_bridge_polls_off_even_with_an_out_of_range_setpoint(factory, cmd):
    """1.3.8 rejected such an OFF status and backed off while the heater stayed
    OFF; >= 1.3.9 publishes it, flagged unusable. (T3: OFF is Cmd 8 and keeps 70.)"""
    bridge = factory()
    ready(bridge)
    body = {"result": {**STATUS["result"], "Cmd": cmd, "T_SetPoint": "0"}}
    bridge.session.request.side_effect = [response(body=body)]
    values = bridge.poll_status("TEST123")
    assert values["Cmd"] == int(cmd)


@pytest.mark.parametrize("off_code", ["8", "16"])
def test_off_path_on_the_real_bridge_posts_off_and_confirms_cmd_8_or_16(factory, clock, off_code):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=9)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": off_code, "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", ctl.PARK_PAYLOAD))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/off") and write.kwargs["data"] == ""
    assert bridge.confirmed["TEST123"][1]["Cmd"] == int(off_code)
    assert bridge.last_command["result"] == "observed_in_status"


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


@pytest.mark.parametrize("off_setpoint", [0.0, 70.0, 90.0])
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


def test_closed_loop_off_with_a_usable_other_target_never_resumes_silently():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), temperature=45)
    sim.off_setpoint = 40.0  # e.g. a target the owner chose, reported while OFF
    controller = enabled(start)
    run_day(sim, controller, lambda now: PERMIT, start, 120)
    assert sim.posts == [] and sim.mode == "Off"
    assert controller.state == ctl.OWNER_OVERRIDE and controller.reason == "off_target_not_70"


def test_disabled_and_automation_payloads_are_the_only_two_the_controller_can_emit():
    """The controller's command vocabulary is exactly the bridge allowlist."""
    assert {ctl.PERMIT_PAYLOAD, ctl.PARK_PAYLOAD} == {"Manual:70", "off"}
    source = (ROOT_PACKAGE / "controller.py").read_text()
    published = [line for line in source.splitlines() if 'Effect("publish"' in line]
    assert len(published) == 1 and "payload=payload" in published[0]


# --- 0.6.1: bridge 1.3.10 fresh-status command path ----------------------------------------


def report(now, result, payload="Manual:70", seconds=15, refresh="refreshed"):
    return {
        "kind": "MODE",
        "payload": payload,
        "result": result,
        "status_refresh": refresh,
        "at": (now + timedelta(seconds=seconds)).isoformat(),
    }


@pytest.mark.parametrize(
    "result",
    ["already_in_requested_state", "refused_mode_mismatch", "refused_target_mismatch"],
)
def test_bridge_seeing_an_owner_change_pauses_control_without_a_fault(result):
    now = local(hour=11)
    controller = started(now)
    later = now + timedelta(seconds=20)
    mode = "Manual" if result == "already_in_requested_state" else "Schedule"
    effects = controller.step(
        obs(
            later, poll_at=now + timedelta(seconds=14), mode=mode, last_command=report(now, result)
        ),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.OWNER_OVERRIDE and controller.fault is None
    assert controller.reason == "mode_or_target_changed_outside_controller"
    assert "override_mode_or_target_changed_outside_controller" in notices(effects)
    for minute in range(1, 180):
        at = now + timedelta(minutes=minute)
        assert not publishes(controller.step(obs(at, poll_at=at, mode=mode), PERMIT, cfg()))


def test_pre_command_status_is_not_mistaken_for_confirmation():
    """1.3.10 publishes the pre-command read's status before the outcome. If it
    already shows the requested mode, that is an owner change, not success."""
    now = local(hour=11)
    controller = started(now)
    pre = obs(
        now + timedelta(seconds=16),
        poll_at=now + timedelta(seconds=15),
        mode="Manual",
        last_command=report(now, "refreshing_status", refresh="in_progress"),
    )
    controller.step(pre, PERMIT, cfg())
    assert controller.state == ctl.CONFIRMING
    outcome = obs(
        now + timedelta(seconds=17),
        poll_at=now + timedelta(seconds=15),
        mode="Manual",
        last_command=report(now, "already_in_requested_state"),
    )
    controller.step(outcome, PERMIT, cfg())
    assert controller.state == ctl.OWNER_OVERRIDE


def test_refreshed_command_confirms_on_the_bridge_outcome():
    now = local(hour=11)
    controller = started(now)
    for result, state in (
        ("refreshing_status", ctl.CONFIRMING),
        ("submitted_awaiting_status", ctl.CONFIRMING),
        ("observed_in_status", ctl.HEATING_PERMITTED),
    ):
        controller.step(
            obs(
                now + timedelta(seconds=20),
                poll_at=now + timedelta(seconds=16),
                mode="Manual" if result != "refreshing_status" else "Off",
                last_command=report(now, result),
            ),
            PERMIT,
            cfg(),
        )
        assert controller.state == state, result
    assert controller.history[-1]["bridge_result"] == "observed_in_status"


@pytest.mark.parametrize(
    "result",
    [
        "refused_status_refresh_failed",
        "refused_cloud_backoff",
        "refused_cloud_quota_limited",
        "refused_auth_not_ready",
        "refused_status_refresh_too_soon",
        "refused_status_refresh_limit",
        "dropped_command_expired_during_refresh",
        "refused_status_not_fresh",
        "refused_by_policy",
        "refused_some_future_code",
    ],
)
def test_every_bridge_refusal_locks_once_and_is_never_retried(result):
    now = local(hour=11)
    controller = started(now)
    effects = controller.step(
        obs(now + timedelta(seconds=20), last_command=report(now, result)), PERMIT, cfg()
    )
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "bridge_refused_or_dropped"
    assert "fault_bridge_refused_or_dropped" in notices(effects)
    for minute in range(1, 120):
        assert not publishes(controller.step(obs(now + timedelta(minutes=minute)), PERMIT, cfg()))


def test_closed_loop_stale_status_commands_cost_at_most_three_requests_each():
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), temperature=45)
    controller = enabled(start)
    window = (local(hour=11, minute=10), local(hour=14, minute=10))  # between polls

    def desire(now):
        if window[0] <= now < window[1]:
            return PERMIT
        return PARK

    before = sim.requests
    run_day(sim, controller, desire, start, 300)
    payloads = [payload for _, payload in sim.posts]
    assert payloads == ["Manual:70", "off"]
    assert controller.fault is None and controller.state == ctl.PARKED
    # Both commands were sent between polls (no 0.6.0 poll-slot wait) ...
    sent = [at for at, _ in sim.posts]
    assert sent[0] - window[0] < timedelta(minutes=2)
    assert sent[1] - window[1] < timedelta(minutes=2)
    # ... and each cost one pre-command read, one write and one confirmation.
    assert len(sim.refreshes) == 2
    polls = 3 * 10  # at most ten background polls (GET 401 -> refresh -> GET) in 300 min
    assert sim.requests - before <= polls + 2 * 3


def test_daily_command_and_request_budgets_bound_cloud_traffic():
    """Worst case at the default limits: 6 commands, each a pre-command read,
    a write and a confirmation, plus 30-minute polling, stays far inside both
    the controller's request budget and the bridge's 24 refreshes a day."""
    config = ctl.ControllerConfig()
    command_requests = config.max_commands_per_day * 3
    polling = 48 * 3
    assert command_requests + polling <= config.max_requests_per_day
    assert config.max_commands_per_day <= 24


# --- 0.6.2: bridge 1.3.11 bounded confirmation --------------------------------------------


def confirming_permit(now):
    controller = started(now)
    assert controller.state == ctl.CONFIRMING
    return controller


def test_awaiting_confirmation_is_neither_success_nor_failure():
    """T3b: the read right after the POST still showed the old mode."""
    now = local(hour=11)
    controller = confirming_permit(now)
    for minute in (0.5, 1, 3, 5, 6):  # well past the old 5-minute late-poll rule
        at = now + timedelta(minutes=minute)
        controller.step(
            obs(at, poll_at=at, mode="Off", last_command=report(now, "awaiting_confirmation")),
            PERMIT,
            cfg(),
        )
        assert controller.state == ctl.CONFIRMING, minute
        assert controller.fault is None
    at = now + timedelta(minutes=6, seconds=10)
    controller.step(
        obs(at, poll_at=at, mode="Manual", last_command=report(now, "observed_in_status")),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED
    assert controller.history[-1]["status"] == "confirmed"


def test_requested_mode_is_confirmed_only_once_the_bridge_has_judged_it():
    now = local(hour=11)
    controller = confirming_permit(now)
    at = now + timedelta(minutes=1)
    controller.step(
        obs(at, poll_at=at, mode="Manual", last_command=report(now, "awaiting_confirmation")),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.CONFIRMING  # status first, outcome a moment later
    controller.step(
        obs(
            at,
            poll_at=at,
            mode="Manual",
            last_command=report(now, "observed_in_status", seconds=61),
        ),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.HEATING_PERMITTED


def test_resume_is_never_confirmed_at_another_target():
    now = local(hour=11)
    controller = confirming_permit(now)
    at = now + timedelta(minutes=1)
    controller.step(
        obs(
            at,
            poll_at=at,
            mode="Manual",
            target_c=65.0,
            last_command=report(now, "unexpected_state_after_command"),
        ),
        PERMIT,
        cfg(),
    )
    assert controller.state == ctl.OWNER_OVERRIDE
    assert controller.reason == "unexpected_mode_during_confirmation"


def test_not_confirmed_within_the_bridge_window_locks_with_owner_guidance():
    now = local(hour=11)
    controller = confirming_permit(now)
    at = now + timedelta(minutes=6)
    record = {**report(now, "not_confirmed_within_limit"), "observed_mode": "Off"}
    effects = controller.step(obs(at, poll_at=at, mode="Off", last_command=record), PERMIT, cfg())
    assert controller.state == ctl.FAULT_LOCKED and controller.fault == "command_not_confirmed"
    assert "fault_command_not_confirmed" in notices(effects)
    message = next(e.message for e in effects if e.key == "fault_command_not_confirmed")
    assert "not repeated" in message and "Acknowledge" in message
    for minute in range(7, 240):
        later = now + timedelta(minutes=minute)
        assert not publishes(controller.step(obs(later, poll_at=later), PERMIT, cfg()))
    assert controller.acknowledge(now + timedelta(hours=4))
    assert controller.state == ctl.OBSERVING


def test_another_pending_bridge_command_blocks_a_controller_command():
    now = local(hour=11)
    controller = parked_controller(now)
    assert not publishes(controller.step(obs(now, bridge_confirmation_pending=True), PERMIT, cfg()))
    assert "bridge_confirmation_pending" in controller.gate_failures
    assert len(publishes(controller.step(obs(now), PERMIT, cfg()))) == 1


def test_bridge_1_3_10_is_not_commanded_by_0_6_2():
    now = local(hour=11)
    controller = parked_controller(now)
    assert not publishes(
        controller.step(obs(now, bridge_confirmation_followups=None), PERMIT, cfg())
    )
    assert "bridge_1_3_11_required" in controller.gate_failures


@pytest.mark.parametrize("delay", [timedelta(seconds=45), timedelta(minutes=4)])
def test_closed_loop_delayed_cloud_readback_confirms_without_a_second_post(delay):
    start = local(hour=10, minute=50)
    sim = SimBridge(start - timedelta(minutes=29), apply_delay=delay)
    controller = enabled(start)
    run_day(sim, controller, lambda now: PERMIT, start, 30)
    assert [p for _, p in sim.posts] == ["Manual:70"]
    assert controller.state == ctl.HEATING_PERMITTED and controller.fault is None
    assert sim.last_command["result"] == "observed_in_status"
    assert sim.refused_while_pending == []  # the controller never sent another


def test_ha_restart_while_the_bridge_awaits_confirmation_never_resends():
    now = local(hour=11)
    controller = confirming_permit(now)
    restored = ctl.Controller.from_dict(controller.to_dict())
    restored.restored(now + timedelta(minutes=1))
    at = now + timedelta(minutes=2)
    assert not publishes(
        restored.step(
            obs(at, poll_at=at, mode="Off", last_command=report(now, "awaiting_confirmation")),
            PERMIT,
            cfg(),
        )
    )
    assert restored.state == ctl.CONFIRMING
    restored.step(
        obs(
            at,
            poll_at=at,
            mode="Manual",
            last_command=report(now, "observed_in_status", seconds=70),
        ),
        PERMIT,
        cfg(),
    )
    assert restored.state == ctl.HEATING_PERMITTED


# --- 0.7.1 settings safety (audit F1-F3, F11) -------------------------------------


def test_command_topic_must_match_the_mapped_heater():
    expected = ctl.expected_command_topic("thermowatt_TEST123_v314")
    assert expected == TOPIC
    for unknown in (None, "", "other_TEST123_v314", "thermowatt_x_v314", 42):
        assert ctl.expected_command_topic(unknown) is None
    assert cfg(expected_command_topic=TOPIC).missing_commissioning() == []
    assert cfg(expected_command_topic=None).missing_commissioning() == []  # no extra check
    wrong = cfg(command_topic="P/TEST124/CMD/MODE", expected_command_topic=TOPIC)
    assert wrong.missing_commissioning() == ["command_topic_does_not_match_heater"]
    # A mismatching topic is a commissioning gate: nothing is ever published.
    now = local(hour=12)
    controller = parked_controller(now)
    effects = controller.step(obs(now, temperature_c=40), PERMIT, wrong)
    assert not publishes(effects)
    assert "command_topic_does_not_match_heater" in controller.gate_failures


@pytest.mark.parametrize("policy", ["legacy", None, "Automation"])
def test_no_command_unless_the_bridge_policy_is_automation(policy):
    now = local(hour=12)
    controller = parked_controller(now)
    effects = controller.step(
        obs(now, temperature_c=40, bridge_command_policy=policy), PERMIT, cfg()
    )
    assert not publishes(effects)
    assert "bridge_policy_not_automation" in controller.gate_failures
    effects = controller.step(obs(now + timedelta(seconds=30), temperature_c=40), PERMIT, cfg())
    assert publishes(effects)  # the same request goes ahead under "automation"


def test_safety_settings_are_locked_while_control_is_on_and_never_restored():
    settings_mod = importlib.import_module(f"{m.__package__}.settings")
    base = c.saved_options({"sources": dict(c.DEFAULT_SOURCES)})
    assert settings_mod.locked_changes(base, dict(base)) == []
    for key, value in {
        "controller_command_topic": "P/OTHER/CMD/MODE",
        "controller_bridge_qualified": True,
        "controller_max_commands_per_day": 8.0,
        "controller_min_rest_minutes": 45.0,
        "controller_execution_latency_minutes": 10.0,
        "import_positive": True,
        "meter_verified": False,
        "tariff_verified": False,
        "peak_rate": 0.40,
        "feed_in_rate": 0.05,
        "peak_evening_start": "15:00",
        "tariff_clock": "local",
        "status_max_age_minutes": 60.0,
    }.items():
        assert settings_mod.locked_changes(base, {**base, key: value}) == [key], key
    moved = {**base, "sources": {**c.DEFAULT_SOURCES, "grid": "sensor.other_meter"}}
    assert settings_mod.locked_changes(base, moved) == ["sources"]
    # Same value in another numeric type is not a change (60 vs 60.0).
    assert settings_mod.locked_changes(base, {**base, "grid_max_age_seconds": 120}) == []
    # Everyday preferences, notifications and legacy values stay editable.
    for key, value in {
        "target_c": 66.0,
        "morning_preferred_c": 48.0,
        "morning_hard_time": "07:30",
        "controller_notify_service": "mobile_app_phone",
        "forecast_enabled": True,
    }.items():
        assert settings_mod.locked_changes(base, {**base, key: value}) == [], key
    message = settings_mod.locked_message(["controller_command_topic", "sources"])
    assert "Turn off Automatic heater control" in message
    assert "Controller command topic" in message and "Sensor mappings" in message
    # Restore and Undo only ever touch preferences: never a locked key.
    changed = {
        **base,
        "controller_min_heating_minutes": 60.0,
        "controller_max_requests_per_day": 300.0,
        "status_max_age_minutes": 60.0,
        "target_c": 66.0,
    }
    restored = settings_mod.recommended_options(changed)
    assert settings_mod.locked_changes(changed, restored) == []
    assert restored["controller_min_heating_minutes"] == 60.0
    assert restored["controller_max_requests_per_day"] == 300.0
    assert restored["target_c"] == c.DEFAULT_OPTIONS["target_c"]
    assert settings_mod.locked_changes(restored, settings_mod.undo_restore(restored)) == []


def test_operational_setting_validation_and_readable_rejections():
    ok = c.parse_options
    for options in (
        {"controller_notify_service": ""},
        {"controller_notify_service": "mobile_app_pixel_10a"},
        {"controller_min_rest_minutes": 60.0},  # latency 30 + 30
        {"controller_min_rest_minutes": 90.0, "controller_execution_latency_minutes": 60.0},
        {"status_max_age_minutes": 35.0},
        {"forecast_max_age_minutes": 35.0},
        {"peak_rate": 2.0, "off_peak_rate": 0.0},
        {"controller_max_commands_per_day": 5},
    ):
        ok(options)
    for options, code in (
        ({"controller_notify_service": "notify.mobile_app_phone"}, "notify_service_invalid"),
        ({"controller_notify_service": "Mobile App"}, "notify_service_invalid"),
        ({"controller_max_commands_per_day": 5.5}, "whole_number_required"),
        ({"controller_max_requests_per_day": 220.4}, "whole_number_required"),
        ({"controller_min_rest_minutes": 61.0}, "rest_longer_than_latency_reserve"),
        (
            {"controller_min_rest_minutes": 45.0, "controller_execution_latency_minutes": 10.0},
            "rest_longer_than_latency_reserve",
        ),
        ({"status_max_age_minutes": 30.0}, "settings_invalid"),
        ({"forecast_max_age_minutes": 30.0}, "settings_invalid"),
        ({"peak_rate": 2.1}, "tariff_invalid"),
        ({"off_peak_rate": -0.01}, "tariff_invalid"),
        ({"morning_preferred_c": 41.0}, "morning_preferred_below_minimum"),
        (
            {"morning_preferred_time": "07:30", "morning_hard_time": "07:00"},
            "morning_times_order",
        ),
        ({"evening_time": "11:00"}, "afternoon_time_invalid"),
    ):
        with pytest.raises(ValueError) as error:
            ok(options)
        assert error.value.args[0] == code, (options, error.value.args)
        message = c.rejection_message(error.value)
        assert message and message != "The settings are not valid together.", code
    assert "notify." in c.rejection_message(ValueError("notify_service_invalid"))
    assert (
        c.rejection_message(ValueError("something_new")) == "The settings are not valid together."
    )


def test_pause_shadow_planning_does_not_pause_an_active_controller():
    now = local(hour=12)
    settings, tariffs = c.parse_options({"paused": True})
    readings = {
        key: m.Reading(value, now, unit)
        for key, value, unit in [
            ("temperature", 60, "°C"),
            ("target", 70, "°C"),
            ("mode", "Manual", None),
            ("last_poll", now.isoformat(), None),
            ("cloud_health", "ok", None),
            ("grid", 2000, "W"),
        ]
    }
    boot = now - timedelta(hours=1)
    assert m.evaluate(now, boot, readings, settings, tariffs).state == "shadow_paused"
    active = m.evaluate(now, boot, readings, settings, tariffs, controlled=True)
    assert active.state != "shadow_paused"


def test_pricing_setting_changes_reset_economic_permission_evidence(runtime):  # noqa: F811
    instance, _, clock = runtime
    standby = permission_mod.StandbyPermission()
    standby.samples.append((clock[0], 2.5))
    standby.grant_since = clock[0]
    instance.executor = SimpleNamespace(standby=standby, session=plan_mod.SessionTemperature())
    sources = dict(instance.sources)
    # A notification-only change does not reprice anything: evidence kept.
    instance.apply_options(c.saved_options({"controller_notify_service": "mobile_app_x"}), sources)
    assert standby.samples and standby.grant_since == clock[0]
    # A price change does: samples and grant/withdraw timers are rebuilt.
    instance.apply_options(c.saved_options({"peak_rate": 0.40}), sources)
    assert not standby.samples and standby.grant_since is None and standby.last is None
    standby.samples.append((clock[0], 2.5))
    instance.apply_options(c.saved_options({"peak_rate": 0.40, "target_c": 66.0}), sources)
    assert not standby.samples
