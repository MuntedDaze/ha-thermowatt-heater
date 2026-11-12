"""0.9.0 three-state controller state machine (pure; no Home Assistant).

OFF / Manual 45 / Manual 70, guarded bridge payloads "<target>@<prior>",
owner protection, gates, confirmation, owner modes and restart. Offline."""

from datetime import datetime, timedelta
import importlib

import pytest

from test_shadow_model import m

ctl = importlib.import_module(f"{m.__package__}.controller")
TOPIC = "P/TEST123/CMD/MODE"
TRANSITIONS = [
    "Manual:45@70",
    "Manual:45@off",
    "Manual:70@45",
    "Manual:70@off",
    "off@45",
    "off@70",
]


def local(year=2026, month=11, day=16, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=m.HOBART).astimezone(m.UTC)


def cfg(**changes):
    values = {"command_topic": TOPIC, "three_state_qualified": True}
    values.update(changes)
    return ctl.ControllerConfig(**values)


def obs(now, mode="Off", target=70.0, poll_age=60, **changes):
    values = dict(
        now=now,
        poll_at=now - timedelta(seconds=poll_age),
        mode=mode,
        target_c=target,
        temperature_c=50.0,
        cloud_health="ok",
        auth_mode="authorized",
        consecutive_failures=0,
        cooldown_seconds=0,
        bridge_available=True,
        bridge_commands_enabled=True,
        bridge_refresh_limit=24,
        bridge_refreshes_24h=0,
        bridge_confirmation_pending=False,
        bridge_command_policy="automation",
        bridge_transitions=list(TRANSITIONS),
        requests_total=100,
        mqtt_ready=True,
    )
    values.update(changes)
    return ctl.Observation(**values)


def want(state, reason="policy"):
    return ctl.Want(state, reason)


def ready(now, mode="Off", target=70.0):
    """An enabled controller that has inspected the heater."""
    c = ctl.Controller()
    c.set_enabled(True, now - timedelta(minutes=5))
    c.request_samples = [[(now - timedelta(hours=1)).isoformat(), 90]]
    c.step(obs(now, mode, target), want("hold"), cfg())
    return c


def publishes(effects):
    return [e.payload for e in effects if e.kind == "publish"]


def notices(effects):
    return [e.key for e in effects if e.kind == "notify"]


# --- commissioning and inspection ---------------------------------------------------------


def test_a_fresh_install_cannot_command():
    missing = ctl.ControllerConfig().missing_commissioning()
    assert missing == ["command_topic_not_configured", "three_state_commands_not_qualified"]
    assert cfg(three_state_qualified=False).missing_commissioning() == [
        "three_state_commands_not_qualified"
    ]
    now = local()
    c = ctl.Controller()
    assert publishes(c.step(obs(now), want("storage"), cfg())) == []
    assert c.state == ctl.DISABLED


@pytest.mark.parametrize(
    ("mode", "target", "state", "heater"),
    [
        ("Off", 70.0, ctl.PARKED, "off"),
        ("Off", 45.0, ctl.PARKED, "off"),  # OFF's retained target is not a setting
        ("Manual", 45.0, ctl.BASELINE_ACTIVE, "baseline"),
        ("Manual", 70.0, ctl.STORAGE_ACTIVE, "storage"),
    ],
)
def test_inspection_recognises_the_three_states(mode, target, state, heater):
    c = ready(local(), mode, target)
    assert (c.state, c.heater) == (state, heater)


@pytest.mark.parametrize(
    ("mode", "target"), [("Manual", 55.0), ("Schedule", 70.0), ("Eco", 45.0), ("Holiday", 70.0)]
)
def test_anything_else_is_the_owners_and_pauses_control(mode, target):
    now = local()
    c = ctl.Controller()
    c.set_enabled(True, now - timedelta(minutes=5))
    effects = c.step(obs(now, mode, target), want("storage"), cfg())
    assert (c.state, c.reason) == (ctl.OWNER_OVERRIDE, "unexpected_mode_or_target")
    assert publishes(effects) == [] and notices(effects)


def test_waits_for_a_status_newer_than_the_inspection_point():
    now = local()
    c = ctl.Controller()
    c.set_enabled(True, now)
    c.step(obs(now, poll_age=60), want("storage"), cfg())
    assert (c.state, c.reason) == (ctl.OBSERVING, "waiting_for_new_heater_status")


# --- transitions -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "target", "wanted", "payload", "confirm"),
    [
        ("Off", 70.0, "storage", "Manual:70@off", ("Manual", 70.0)),
        ("Off", 70.0, "baseline", "Manual:45@off", ("Manual", 45.0)),
        ("Manual", 45.0, "storage", "Manual:70@45", ("Manual", 70.0)),
        ("Manual", 45.0, "off", "off@45", ("Off", 45.0)),
        ("Manual", 70.0, "baseline", "Manual:45@70", ("Manual", 45.0)),
        ("Manual", 70.0, "off", "off@70", ("Off", 70.0)),
    ],
)
def test_each_transition_is_one_guarded_command_then_confirmed(
    mode, target, wanted, payload, confirm
):
    now = local()
    c = ready(now, mode, target)
    effects = c.step(obs(now + timedelta(minutes=1), mode, target), want(wanted), cfg())
    assert publishes(effects) == [payload]
    assert c.state == ctl.CONFIRMING and c.intent["target"] == wanted
    # Nothing more while confirming.
    later = now + timedelta(minutes=2)
    assert publishes(c.step(obs(later, mode, target, poll_age=200), want(wanted), cfg())) == []
    done = now + timedelta(minutes=3)
    c.step(obs(done, *confirm, poll_age=0), want(wanted), cfg())
    assert c.heater == wanted and c.state == ctl.ACTIVE_OF[wanted]
    assert c.history[-1]["status"] == "confirmed"


def test_no_command_when_the_wanted_state_is_active_or_held():
    now = local()
    c = ready(now, "Manual", 45.0)
    for state in ("baseline", "hold"):
        assert publishes(c.step(obs(now, "Manual", 45.0), want(state), cfg())) == []
    assert c.state == ctl.BASELINE_ACTIVE


def test_bridge_refusal_of_the_prior_state_is_owner_control_not_a_fault():
    now = local()
    c = ready(now)
    c.step(obs(now + timedelta(minutes=1)), want("storage"), cfg())
    bridge = {
        "payload": "Manual:70@off",
        "result": "refused_mode_mismatch",
        "at": (now + timedelta(minutes=1, seconds=10)).isoformat(),
    }
    effects = c.step(
        obs(now + timedelta(minutes=2), "Manual", 55.0, poll_age=30, last_command=bridge),
        want("storage"),
        cfg(),
    )
    assert (c.state, c.reason) == (ctl.OWNER_OVERRIDE, "mode_or_target_changed_outside_controller")
    assert c.fault is None and "override_mode_or_target_changed_outside_controller" in notices(
        effects
    )


@pytest.mark.parametrize(
    ("result", "state"),
    [
        ("not_confirmed_within_limit", ctl.FAULT_LOCKED),
        ("refused_by_policy", ctl.FAULT_LOCKED),
        ("unexpected_state_after_command", ctl.OWNER_OVERRIDE),
    ],
)
def test_bridge_outcomes_lock_or_pause_and_nothing_is_resent(result, state):
    now = local()
    c = ready(now)
    c.step(obs(now + timedelta(minutes=1)), want("storage"), cfg())
    bridge = {
        "payload": "Manual:70@off",
        "result": result,
        "at": (now + timedelta(minutes=7)).isoformat(),
    }
    effects = c.step(
        obs(now + timedelta(minutes=7), poll_age=10, last_command=bridge), want("storage"), cfg()
    )
    assert c.state == state and publishes(effects) == []
    for minute in range(8, 30):
        later = obs(now + timedelta(minutes=minute), poll_age=10, last_command=bridge)
        assert publishes(c.step(later, want("storage"), cfg())) == []


def test_in_progress_bridge_results_are_not_conclusive():
    now = local()
    c = ready(now)
    c.step(obs(now + timedelta(minutes=1)), want("storage"), cfg())
    bridge = {
        "payload": "Manual:70@off",
        "result": "submitted_awaiting_status",
        "at": (now + timedelta(minutes=1, seconds=5)).isoformat(),
    }
    c.step(obs(now + timedelta(minutes=2), poll_age=0, last_command=bridge), want("storage"), cfg())
    assert c.state == ctl.CONFIRMING


# --- gates ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "gate"),
    [
        ({"bridge_transitions": None}, "bridge_1_3_13_required"),
        ({"bridge_transitions": ["off@70"]}, "bridge_1_3_13_required"),
        ({"bridge_confirmation_pending": True}, "bridge_confirmation_pending"),
        ({"bridge_command_policy": "legacy"}, "bridge_policy_not_automation"),
        ({"cloud_health": "backoff"}, "cloud_health_backoff"),
        ({"bridge_commands_enabled": False}, "bridge_commands_disabled_or_unknown"),
        ({"mqtt_ready": False}, "mqtt_not_ready"),
        ({"poll_age": 40 * 60}, "heater_status_too_old"),
    ],
)
def test_each_gate_blocks_the_command(change, gate):
    now = local()
    c = ready(now)
    poll_age = change.pop("poll_age", 60)
    later = now + timedelta(minutes=1)
    effects = c.step(obs(later, poll_age=poll_age, **change), want("storage"), cfg())
    assert publishes(effects) == []
    assert c.state == ctl.CHANGE_REQUESTED and gate in c.gate_failures
    assert c.heater == "off"


def test_the_daily_backstop_never_holds_back_a_park():
    now = local()
    c = ready(now, "Manual", 70.0)
    c.commands = [(now - timedelta(minutes=30 + i)).isoformat() for i in range(8)]
    assert publishes(c.step(obs(now, "Manual", 70.0), want("off"), cfg())) == ["off@70"]
    d = ready(now)
    d.commands = list(c.commands)
    assert publishes(d.step(obs(now), want("storage"), cfg())) == []
    assert "daily_command_limit_reached" in d.gate_failures


def test_publish_failure_locks_and_is_never_retried():
    now = local()
    c = ready(now)
    c.step(obs(now), want("storage"), cfg())
    effects = c.publish_failed(now)
    assert c.state == ctl.FAULT_LOCKED and c.intent is None
    assert "fault_publish_failed" in notices(effects)


# --- owner control --------------------------------------------------------------------------------


def test_an_app_change_while_steady_pauses_until_resume():
    now = local()
    c = ready(now, "Manual", 45.0)
    later = now + timedelta(minutes=30)
    effects = c.step(obs(later, "Manual", 70.0, poll_age=10), want("baseline"), cfg())
    assert c.state == ctl.OWNER_OVERRIDE and publishes(effects) == []
    assert c.resume(later)
    c.step(obs(later + timedelta(minutes=30), "Manual", 70.0, poll_age=10), want("hold"), cfg())
    assert c.state == ctl.STORAGE_ACTIVE


def test_hold_sends_nothing_until_resumed():
    now = local()
    c = ready(now)
    c.set_hold(now)
    assert publishes(c.step(obs(now), want("storage"), cfg())) == []
    assert c.state == ctl.OWNER_OVERRIDE


def test_guest_mode_needs_control_and_ends_after_twelve_hours():
    now = local()
    c = ctl.Controller()
    assert not c.start_guest(now) and c.refusal == "automatic_control_is_off"
    c = ready(now)
    assert c.start_guest(now) and c.guest_active(now + timedelta(hours=11))
    c.step(obs(now + timedelta(hours=12, minutes=1)), want("hold"), cfg())
    assert not c.guest_active(now + timedelta(hours=12, minutes=1))


def test_holiday_dates_are_validated_and_never_adjusted():
    now = local()
    c = ready(now)
    assert not c.set_holiday(now, now + timedelta(days=2), now + timedelta(days=1))
    assert c.refusal == "return_must_be_after_departure"
    assert not c.set_holiday(now, now, now + timedelta(days=61))
    assert c.set_holiday(now, now, now + timedelta(days=3)) and c.holiday_active(now)


def test_guest_not_applied_is_reported():
    now = local()
    c = ready(now)
    c.start_guest(now)
    c.step(obs(now + timedelta(minutes=11), cloud_health="backoff"), want("storage"), cfg())
    assert "guest_mode_not_applied" in c.active_alerts


# --- persistence and restart ----------------------------------------------------------------------


def test_restart_while_confirming_reconciles_and_never_resends():
    now = local()
    c = ready(now)
    c.step(obs(now), want("storage"), cfg())
    restored = ctl.Controller.from_dict(c.to_dict())
    restored.restored(now + timedelta(minutes=1))
    assert restored.state == ctl.CONFIRMING
    effects = restored.step(obs(now + timedelta(minutes=2), poll_age=200), want("storage"), cfg())
    assert publishes(effects) == []


def test_restart_in_a_steady_state_reinspects_first():
    now = local()
    c = ready(now, "Manual", 45.0)
    restored = ctl.Controller.from_dict(c.to_dict())
    restored.restored(now)
    assert restored.state == ctl.OBSERVING
    assert publishes(restored.step(obs(now, "Manual", 45.0), want("storage"), cfg())) == []


def test_a_0_8_state_with_a_pending_permit_is_reconciled_not_resent():
    old = {
        "enabled": True,
        "state": "confirming",
        "reason": "confirming_permit",
        "intent": {"id": "x", "action": "permit", "payload": "Manual:70", "topic": TOPIC},
        "commands": [],
        "permitted_off_since": None,  # a removed 0.8 field is ignored
    }
    c = ctl.Controller.from_dict(old)
    assert c.intent is None and c.state == ctl.OBSERVING
    assert c.history[-1]["payload"] == "Manual:70"


@pytest.mark.parametrize(
    ("unique_id", "topic"),
    [("thermowatt_TEST123_v314", TOPIC), ("other", None), (None, None)],
)
def test_expected_topic_and_refresh_topic(unique_id, topic):
    assert ctl.expected_command_topic(unique_id) == topic
    assert ctl.refresh_topic(TOPIC) == "P/TEST123/refresh"
    assert ctl.refresh_topic("bad") is None


def test_controller_module_has_no_home_assistant_or_network_imports():
    source = open(ctl.__file__, encoding="utf-8").read()
    for name in ("homeassistant", "requests", "socket", "paho"):
        assert f"import {name}" not in source and f"from {name}" not in source


def test_the_controller_enforces_the_spacing_itself():
    now = local()
    c = ready(now, "Manual", 70.0)
    c.commands = [(now - timedelta(minutes=14)).isoformat()]
    assert publishes(c.step(obs(now, "Manual", 70.0), want("off"), cfg())) == []
    assert "command_spacing" in c.gate_failures
    c.commands = [(now - timedelta(minutes=15)).isoformat()]
    assert publishes(c.step(obs(now, "Manual", 70.0), want("off"), cfg())) == ["off@70"]
