"""Deterministic offline tests for cloud_success_false outage, 1-hour backoff,
scheduled heating transitions (22:00 Hobart / 21:00 AEST evening peak -> 45 C
baseline), recovery, failure to recover, notification cooldown preservation,
pre-transition Smart poll lead, honest fault wording, and fail-closed locks.

Uses the real MyThermowattBridge (1.5.1), ShadowRuntime, Executor, and
Controller (0.18.2) with synthetic clocks, mocked HTTP, and realistic Home
Assistant MQTT availability handling. Never touches live Home Assistant or live
Thermowatt cloud services.
"""

from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from conftest import TOKENS, response
from test_controller_0_9_0 import cfg, obs, ready as ready_controller, want
from test_integration_0_9_0 import MON, SERIAL, Rig, drive, hobart
from test_shadow_model import c

CLOUD_SUCCESS_FALSE = {
    "success": False,
    "error": "SYNTHETIC_VENDOR_ERROR_MUST_NOT_LEAK",
}


class AvailabilityRig(Rig):
    """Rig extended with realistic MQTT availability and Smart polling support."""

    def __init__(
        self,
        tmp_path,
        monkeypatch,
        start,
        *,
        mode="Off",
        setpoint=45,
        reading=45.0,
        cloud_polling="smart",
    ):
        self._cloud_polling = cloud_polling
        self.notification_events = []
        self.status_attempts = []
        self.refresh_attempts = []
        super().__init__(
            tmp_path, monkeypatch, start, reading=reading, mode=mode, setpoint=setpoint
        )
        options = {
            **self.entry.options,
            "normal_storage_c": "62",
            "peak_heating_policy": "Never schedule heating during peak",
            "heater_meter_verification": "",
        }
        self.sources.pop("heater_power", None)
        self.entry.options.update(options)
        self.runtime.apply_options(options, self.sources)
        self.executor.configure(options)

    def _stub_home_assistant(self, monkeypatch):
        super()._stub_home_assistant(monkeypatch)
        import sys

        pn = sys.modules["homeassistant.components.persistent_notification"]

        def record_create(hass, message, title, key):
            self.notifications.append(key)
            self.notification_events.append((self.now(), key, title, message))

        pn.async_create = record_create

    def _bridge(self, tmp_path, monkeypatch):
        bridge = super()._bridge(tmp_path, monkeypatch)
        bridge.options["cloud_polling"] = self._cloud_polling
        bridge.smart = self._cloud_polling == "smart"
        bridge.poll_schedule.enabled = bridge.smart
        return bridge

    def ha_mqtt(self, topic, payload, *args, **kwargs):
        if topic == f"P/{SERIAL}/availability":
            if payload == "offline":
                self.report(c.DEFAULT_SOURCES["heater"], "unavailable", {})
                self.report(c.DEFAULT_SOURCES["mode"], "unavailable", {})
            return
        super().ha_mqtt(topic, payload, *args, **kwargs)


def heater_posts(rig):
    return [
        call
        for call in rig.bridge.session.request.call_args_list
        if call.args[0] == "POST" and call.args[1].rsplit("/", 1)[-1] in {"manual", "off"}
    ]


def evaluate(rig):
    rig._meter()
    rig.runtime.update(rig.now())
    drive(rig.executor.async_step(rig.now()))
    return rig.executor.last_decision


def advance(rig, until, step_seconds=20):
    """Advance synthetic wall/monotonic clocks honestly without bypassing backoff."""
    while rig.now() < until:
        next_t = min(until.timestamp(), rig.t + step_seconds)
        prev_minute = int(rig.t // 60)
        rig.t = next_t
        prev_poll = rig.bridge.last_success.get(SERIAL)
        rig.bridge.tick()
        new_poll = rig.bridge.last_success.get(SERIAL)
        if int(rig.t // 60) > prev_minute:
            rig.tank.minute(rig.t)
            evaluate(rig)
        elif new_poll != prev_poll:
            # Matches __init__.py::new_poll evaluating immediately on new last_poll.
            evaluate(rig)


def make_evening_peak_rig(tmp_path, monkeypatch, poll_at, *, cloud_polling="smart"):
    """Start during evening peak (17:00-22:00 Hobart AEDT) with confirmed Off
    observed at ``poll_at`` so the bridge's real 30-minute schedule fires at
    ``poll_at + 30 min`` without overriding scheduler internals."""
    rig = AvailabilityRig(
        tmp_path,
        monkeypatch,
        poll_at - timedelta(seconds=30),
        mode="Off",
        setpoint=45,
        reading=45.0,
        cloud_polling=cloud_polling,
    )
    rig.enable()
    rig.t = poll_at.timestamp()
    rig.bridge.token_obtained_at = rig.t
    rig.bridge.poll_status(SERIAL)
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.state == "parked"
    assert controller.heater == "off"
    assert controller.last_observed_heater == "off"
    assert rig.commands() == []
    rig.bridge.session.request.reset_mock()
    return rig


def test_outage_before_transition_clean_backoff_and_automatic_recovery(
    tmp_path, monkeypatch, caplog
):
    """Clean outage before 22:00 Hobart: controller holds in change_requested,
    bridge respects the 3,600 s backoff with zero extra calls, and both recover
    automatically to confirmed Manual 45 C when cloud succeeds at +1 hour."""
    caplog.set_level("INFO")
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 28), cloud_polling="smart")
    outage_at = hobart(MON, 21, 58)
    recovery_at = outage_at + timedelta(seconds=3600)

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud

    # Poll at 21:58:00 (2 minutes before the 22:00 transition) via real schedule.
    rig.t = outage_at.timestamp()
    rig.bridge.tick()
    evaluate(rig)

    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1
    assert rig.bridge.guard.state["mode"] == "authorized"
    assert rig.bridge.next_poll == outage_at.timestamp() + 3600
    assert rig.bridge.next_cloud == outage_at.timestamp() + 3600
    assert "SYNTHETIC_VENDOR_ERROR_MUST_NOT_LEAK" not in caplog.text

    # Cross 22:00 Hobart (evening peak ends -> policy wants baseline 45 C).
    advance(rig, hobart(MON, 22, 5))
    controller = rig.executor.controller
    assert controller.state == "change_requested"
    assert controller.intent is None
    assert controller.heater == "off"
    assert rig.commands() == []
    assert not heater_posts(rig)
    assert len(rig.status_attempts) == 1

    # Advance through the entire 1-hour cooldown up to 1 second before expiry.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert len(rig.status_attempts) == 1  # zero extra cloud calls during 3,600 s backoff
    assert rig.commands() == []
    assert controller.state == "change_requested"
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 1
    assert rig.notifications.count("thermann_shadow_parked_off_cannot_restore") == 1

    # Cross the 3,600 s recovery boundary; bridge recovers and controller restores 45 C.
    advance(rig, recovery_at + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert rig.bridge.failures == 0
    assert rig.commands() == ["Manual:45@off"]
    assert len(heater_posts(rig)) == 1
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45
    assert controller.state == "baseline_45"
    assert controller.heater == "baseline"
    assert controller.fault is None
    assert controller.intent is None
    assert "parked_off_cannot_restore" not in controller.active_alerts
    assert "cloud_fault" not in controller.active_alerts


def test_race_a_in_flight_status_poll_failure_defers_and_auto_recovers_at_1h(tmp_path, monkeypatch):
    """Fix #1 + #2 (confirmed 25 Nov 2026 live incident Race A): at 22:00 Hobart
    the controller publishes Manual:45@off while the bridge's status poll fails
    with cloud_success_false. _offline() now records refused_cloud_backoff
    instead of silently draining the queue; controller defers cleanly without
    locking, fires parked_off_cannot_restore at 30 min with zero retries, and
    automatically restores Manual 45 C at 23:00 recovery."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    recovery_at = outage_at + timedelta(seconds=3600)

    rig.t = outage_at.timestamp()
    evaluate(rig)
    controller = rig.executor.controller
    assert rig.commands() == ["Manual:45@off"]
    assert controller.state == "confirming"
    assert controller.intent["status"] == "published"
    queued_cmd = rig.bridge.commands.get_nowait()

    def in_flight_status_fail(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            # Command arrives over MQTT while GET /status is in flight.
            rig.bridge.commands.put_nowait(queued_cmd)
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = in_flight_status_fail
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()

    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1
    assert rig.bridge.next_cloud == outage_at.timestamp() + 3600
    assert rig.bridge.commands.empty()
    assert rig.bridge.last_command["result"] == "refused_cloud_backoff"
    assert rig.bridge.last_command["error"] == "cloud_success_false"
    assert rig.bridge.pending is None
    assert not heater_posts(rig)
    assert rig.tank.mode == "Off"

    # Next controller evaluation resolves the proven-never-sent refusal without locking.
    rig.t += 60
    evaluate(rig)
    assert controller.fault is None
    assert controller.intent is None
    assert controller.heater == "off"
    assert controller.history[-1]["status"] == "deferred_cloud_backoff"
    assert controller.parked_off_restore_since == outage_at.isoformat()

    # Throughout the 1-hour backoff: zero extra cloud calls, zero extra commands,
    # and parked_off_cannot_restore still alerts at 30 minutes.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert controller.state == "change_requested"
    assert controller.fault is None
    assert len(rig.status_attempts) == 1
    assert rig.commands() == ["Manual:45@off"]
    assert not heater_posts(rig)
    assert rig.notifications.count("thermann_shadow_parked_off_cannot_restore") == 1

    # At 23:00:00 cloud recovers -> bridge polls Off -> controller automatically
    # sends Manual:45@off, reuses fresh status, and confirms Manual 45 C.
    advance(rig, recovery_at + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert rig.bridge.failures == 0
    assert rig.commands() == ["Manual:45@off", "Manual:45@off"]
    assert len(heater_posts(rig)) == 1
    assert controller.state == "baseline_45"
    assert controller.heater == "baseline"
    assert controller.fault is None
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45
    assert "parked_off_cannot_restore" not in controller.active_alerts


def test_race_b_command_queued_during_backoff_refused_immediately_and_auto_recovers(
    tmp_path, monkeypatch
):
    """Fix #1 + #2 (Race B): Manual:45@off arrives right after bridge enters
    3,600 s backoff. tick() immediately drains it with refused_cloud_backoff
    (0 HTTP requests), controller defers without locking, and automatically
    restores Manual 45 C at 23:00 recovery."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    recovery_at = outage_at + timedelta(seconds=3600)

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud

    rig.t = outage_at.timestamp()
    pre_backoff_states = dict(rig.states)
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    assert rig.bridge.cloud_health == "backoff"

    # Simulate MQTT lag: controller evaluates on pre-backoff states and publishes.
    post_backoff_states = dict(rig.states)
    rig.states.clear()
    rig.states.update(pre_backoff_states)
    evaluate(rig)
    rig.states.clear()
    rig.states.update(post_backoff_states)

    controller = rig.executor.controller
    assert rig.commands() == ["Manual:45@off"]
    assert controller.state == "confirming"
    assert rig.bridge.commands.qsize() == 1

    # Bridge's next tick drains the queued command immediately with refused_cloud_backoff.
    rig.t += 1
    rig.bridge.tick()
    assert rig.bridge.commands.empty()
    assert rig.bridge.last_command["result"] == "refused_cloud_backoff"
    assert rig.bridge.last_command["error"] == "cloud_success_false"
    assert len(rig.status_attempts) == 1

    rig.t += 59
    evaluate(rig)
    assert controller.fault is None
    assert controller.intent is None
    assert controller.history[-1]["status"] == "deferred_cloud_backoff"

    # Zero requests during backoff; automatic recovery at 23:00.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert len(rig.status_attempts) == 1
    assert not heater_posts(rig)

    advance(rig, recovery_at + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert len(heater_posts(rig)) == 1
    assert controller.state == "baseline_45"
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45


def test_pre_command_status_refresh_cloud_success_false_defers_and_auto_recovers(
    tmp_path, monkeypatch
):
    """Fix #2: if Manual:45@off triggers a pre-command status refresh that gets
    transient cloud_success_false (non-auth, non-quota), bridge enters 3,600 s
    backoff with refused_status_refresh_failed, controller defers safely, and
    automatically restores Manual 45 C at +1 h recovery."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 50), cloud_polling="smart")
    transition_at = hobart(MON, 22, 0)
    recovery_at = transition_at + timedelta(seconds=3600)
    rig.t = transition_at.timestamp()
    rig.bridge.token_obtained_at = rig.t

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud

    evaluate(rig)
    assert rig.commands() == ["Manual:45@off"]
    rig.bridge.tick()

    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1
    assert rig.bridge.next_cloud == recovery_at.timestamp()
    assert rig.bridge.last_command["result"] == "refused_status_refresh_failed"
    assert rig.bridge.last_command["error"] == "cloud_success_false"
    assert rig.bridge.pending is None
    assert not heater_posts(rig)

    rig.t += 60
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.fault is None
    assert controller.intent is None
    assert controller.heater == "off"
    assert controller.history[-1]["status"] == "deferred_cloud_backoff"

    advance(rig, recovery_at + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert len(heater_posts(rig)) == 1
    assert controller.state == "baseline_45"
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45


@pytest.mark.parametrize(
    "bridge_result,error,cloud_health,auth_mode",
    [
        ("refused_status_refresh_failed", "cloud_daily_limit", "quota_limited", "authorized"),
        ("refused_status_refresh_failed", "cloud_http_429", "quota_limited", "authorized"),
        ("refused_status_refresh_failed", "cloud_http_401", "auth_locked", "blocked"),
        ("refused_status_refresh_failed", "cloud_http_403", "auth_locked", "blocked"),
        ("refused_status_refresh_failed", "cloud_error_unclassified", "backoff", "authorized"),
        ("refused_status_refresh_failed", None, "backoff", "authorized"),
        ("refused_auth_not_ready", "auth_http_401", "auth_locked", "blocked"),
        ("refused_cloud_quota_limited", "cloud_daily_limit", "quota_limited", "authorized"),
        ("refused_cloud_backoff", "cloud_daily_limit", "quota_limited", "authorized"),
        ("refused_by_policy", None, "ok", "authorized"),
        ("dropped_command_older_than_30s", None, "ok", "authorized"),
        ("rejected_by_cloud", "command_rejected", "backoff", "authorized"),
    ],
)
def test_non_transient_or_auth_quota_refusals_still_fail_closed_to_fault_locked(
    bridge_result, error, cloud_health, auth_mode
):
    """Fix #2 fail-closed invariant: auth, quota, policy, dropped, rejected, and
    unclassified errors ALWAYS lock into fault_locked."""
    now = hobart(MON, 22, 0)
    controller = ready_controller(now, "Off", 45.0)
    controller.step(obs(now + timedelta(minutes=1)), want("baseline"), cfg())
    assert controller.state == "confirming"
    last = {
        "payload": "Manual:45@off",
        "result": bridge_result,
        "at": (now + timedelta(minutes=1, seconds=5)).isoformat(),
    }
    if error is not None:
        last["error"] = error
    controller.step(
        obs(
            now + timedelta(minutes=2),
            poll_age=120,
            cloud_health=cloud_health,
            auth_mode=auth_mode,
            last_command=last,
        ),
        want("baseline"),
        cfg(),
    )
    assert controller.state == "fault_locked"
    assert controller.fault == "bridge_refused_or_dropped"


def test_fault_notifications_say_published_not_sent_when_bridge_never_confirmed():
    """Honest fault wording: late_poll (command_not_applied) and
    confirmation_timeout must not falsely claim the command 'was sent'."""
    now = hobart(MON, 22, 0)
    c_late = ready_controller(now, "Off", 45.0)
    c_late.step(obs(now), want("baseline"), cfg())
    effects = c_late.step(
        obs(now + timedelta(minutes=10), mode="Off", poll_age=0), want("baseline"), cfg()
    )
    assert c_late.state == "fault_locked" and c_late.fault == "command_not_applied"
    notice = next(e for e in effects if e.kind == "notify" and e.key == "fault_command_not_applied")
    assert "published to MQTT" in notice.message
    assert "was sent" not in notice.message

    c_timeout = ready_controller(now, "Off", 45.0)
    c_timeout.step(obs(now), want("baseline"), cfg())
    timeout_effects = c_timeout.step(
        obs(now + timedelta(minutes=66), mode="Off", poll_age=4000), want("baseline"), cfg()
    )
    assert c_timeout.state == "fault_locked" and c_timeout.fault == "confirmation_timeout"
    t_notice = next(
        e for e in timeout_effects if e.kind == "notify" and e.key == "fault_confirmation_timeout"
    )
    assert "published at" in t_notice.message
    assert "sent at" not in t_notice.message


def test_smart_poll_plan_leads_evening_peak_end_by_30s_to_prevent_boundary_race(
    tmp_path, monkeypatch
):
    """Fix #3: Smart polling schedules its pre-transition read 30 s before
    22:00:00 (at 21:59:30), so a healthy read stays <= 60 s fresh through 22:00
    (0 extra pre-command GETs) and a failing read reports backoff before 22:00."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    poll_plans = [
        json.loads(payload) for topic, payload in rig.ha_publishes if topic.endswith("/poll_plan")
    ]
    assert poll_plans
    latest = poll_plans[-1]
    assert latest["status_at"] == hobart(MON, 21, 30).timestamp()
    # 21:30:00 -> 21:59:30 = 1,770 seconds (30 s lead before 22:00:00 peak end).
    assert latest["delay_seconds"] == 1770
    assert latest["reason"] == "before_decision"

    # Let the real Smart schedule run across 21:59:30 -> 22:00:00 on a healthy cloud:
    # the 21:59:30 status is reused by Manual:45@off with ZERO extra pre-command GET!
    rig.bridge.session.request.reset_mock()
    advance(rig, hobart(MON, 22, 3))
    assert rig.executor.controller.state == "baseline_45"
    assert len(heater_posts(rig)) == 1
    assert rig.bridge.usage.counts["command_refresh"] == 0


def test_failure_to_recover_at_1h_doubles_backoff_and_recovers_later_from_change_requested(
    tmp_path, monkeypatch
):
    """Failure to recover at +1 h (second cloud_success_false) doubles backoff
    to 7,200 s (2 h) without locking AuthGuard or spamming notifications.
    When cloud recovers at +3 h total, change_requested restores 45 C."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 28), cloud_polling="smart")
    outage_at = hobart(MON, 21, 58)
    first_retry = outage_at + timedelta(seconds=3600)
    second_retry = first_retry + timedelta(seconds=7200)  # T + 3 hours

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < second_retry:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud

    rig.t = outage_at.timestamp()
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    evaluate(rig)
    assert rig.bridge.failures == 1
    assert rig.bridge.next_cloud == first_retry.timestamp()

    # First retry at +1 hour fails again -> backoff doubles to 7,200 s.
    advance(rig, first_retry + timedelta(minutes=2))
    assert rig.bridge.failures == 2
    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.guard.state["mode"] == "authorized"
    assert rig.bridge.next_cloud == second_retry.timestamp()
    assert len(rig.status_attempts) == 2
    assert rig.executor.controller.state == "change_requested"

    # Zero requests during the 2-hour backoff and zero duplicate notifications.
    advance(rig, second_retry - timedelta(seconds=1))
    assert len(rig.status_attempts) == 2
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 1
    assert rig.notifications.count("thermann_shadow_parked_off_cannot_restore") == 1
    assert rig.notifications.count("thermann_shadow_status_stale") == 1

    # Cloud finally recovers at +3 hours -> automatic restoration to 45 C.
    advance(rig, second_retry + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert rig.bridge.failures == 0
    assert rig.commands() == ["Manual:45@off"]
    assert len(heater_posts(rig)) == 1
    assert rig.executor.controller.state == "baseline_45"
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45


def test_failure_to_recover_with_no_bridge_reply_still_hits_65m_confirmation_timeout(
    tmp_path, monkeypatch
):
    """If an MQTT command never reaches the bridge at all (e.g. broker drop) and
    the +1 h recovery poll fails (2 h backoff), the 65-minute confirmation
    timeout still fails closed to fault_locked even after cloud later recovers."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    first_retry = outage_at + timedelta(seconds=3600)
    second_retry = first_retry + timedelta(seconds=7200)

    rig.t = outage_at.timestamp()
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.state == "confirming"
    # Simulate broker dropping the MQTT publish before the bridge ever receives it.
    rig.bridge.commands.get_nowait()

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < second_retry:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()

    advance(rig, outage_at + timedelta(minutes=64))
    assert rig.bridge.failures == 2
    assert controller.state == "confirming"
    assert controller.intent["status"] == "published"

    advance(rig, outage_at + timedelta(minutes=66))
    assert controller.state == "fault_locked"
    assert controller.fault == "confirmation_timeout"
    assert controller.intent is None
    assert controller.history[-1]["status"] == "timeout"

    advance(rig, second_retry + timedelta(minutes=5))
    assert rig.bridge.cloud_health == "ok"
    assert controller.state == "fault_locked"
    assert not heater_posts(rig)
    assert rig.tank.mode == "Off"


def test_notifications_preserve_6h_cooldown_across_brief_unavailable_gap(tmp_path, monkeypatch):
    """Fix #5: consecutive failures in backoff emit cloud_fault once per 6 h
    cooldown, AND a brief cloud_health='unavailable' gap no longer erases the
    cooldown or re-fires cloud_fault until the 6 h cooldown actually expires."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 28), cloud_polling="smart")
    outage_at = hobart(MON, 21, 58)
    rig.bridge.session.request.side_effect = lambda m, u, **k: response(body=CLOUD_SUCCESS_FALSE)

    rig.t = outage_at.timestamp()
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    evaluate(rig)
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 1

    # Continuous backoff across 2+ hours (including second failure at +1 h): still 1.
    advance(rig, outage_at + timedelta(hours=2))
    assert rig.bridge.failures == 2
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 1

    # Simulate a brief unavailable tick on sensor.home_cloud_health, then backoff again.
    saved_health = rig.states[c.DEFAULT_SOURCES["cloud_health"]]
    rig.t += 60
    rig.report(c.DEFAULT_SOURCES["cloud_health"], "unavailable", {})
    evaluate(rig)
    assert "cloud_fault" not in rig.executor.controller.alerts
    assert "cloud_fault" in rig.executor.controller.alert_cooldowns

    rig.t += 60
    rig.states[c.DEFAULT_SOURCES["cloud_health"]] = SimpleNamespace(
        state=saved_health.state,
        attributes=saved_health.attributes,
        last_reported=rig.now(),
        last_updated=rig.now(),
    )
    evaluate(rig)
    # Cooldown preserved: still only 1 notification within 6 hours.
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 1

    # After the 6-hour cooldown expires, cloud_fault notifies again.
    rig.t = (outage_at + timedelta(hours=6, minutes=1)).timestamp()
    rig.states[c.DEFAULT_SOURCES["cloud_health"]] = SimpleNamespace(
        state=saved_health.state,
        attributes=saved_health.attributes,
        last_reported=rig.now(),
        last_updated=rig.now(),
    )
    evaluate(rig)
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 2


def test_smart_mode_ordinary_get_does_not_proactively_refresh_on_cloud_success_false(
    tmp_path, monkeypatch
):
    """Auth/token behaviour unchanged: in bridge 1.5.0 Smart mode, ordinary
    GET /status keeps bounded_reactive_refresh without extra /refresh calls on
    HTTP 200 success:false."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 28), cloud_polling="smart")
    outage_at = hobart(MON, 21, 58)
    recovery_at = outage_at + timedelta(seconds=3600)

    rig.bridge.token_obtained_at = outage_at.timestamp() - 3600
    endpoints = []

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        endpoints.append((method, endpoint))
        if endpoint == "refresh":
            return response(body=TOKENS)
        return response(body=CLOUD_SUCCESS_FALSE)

    rig.bridge.session.request.side_effect = cloud

    rig.t = outage_at.timestamp()
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    assert endpoints == [("GET", "status")]
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1

    rig.t = recovery_at.timestamp()
    rig.bridge.tick()
    assert endpoints == [("GET", "status"), ("GET", "status")]
    assert rig.bridge.failures == 2
    assert rig.bridge.guard.state["mode"] == "authorized"


def test_ha_restart_during_deferred_cloud_backoff_reinspects_and_auto_recovers(
    tmp_path, monkeypatch
):
    """Independent safety check: if HA restarts while a command is confirming and
    then observes refused_cloud_backoff, it never replays the command immediately,
    enters observing (requiring a genuinely NEW post-restart poll), keeps
    parked_off_restore_since continuous, and automatically restores 45 C once
    the 1-hour backoff expires."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    recovery_at = outage_at + timedelta(seconds=3600)

    rig.t = outage_at.timestamp()
    evaluate(rig)
    assert rig.commands() == ["Manual:45@off"]
    queued_cmd = rig.bridge.commands.get_nowait()

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            rig.bridge.commands.put_nowait(queued_cmd)
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    assert rig.bridge.last_command["result"] == "refused_cloud_backoff"
    assert not heater_posts(rig)

    # Simulate Home Assistant restarting before processing the refusal.
    rig.t += 120
    rig.executor = rig._executor()
    controller = rig.executor.controller
    assert controller.state == "confirming"
    assert controller.reason == "reconciling_command_after_restart"

    evaluate(rig)
    assert controller.state == "observing"
    assert controller.fault is None
    assert controller.intent is None
    assert controller.history[-1]["status"] == "deferred_cloud_backoff"
    assert controller.parked_off_restore_since == outage_at.isoformat()
    assert rig.commands() == ["Manual:45@off"]  # never replayed across restart

    # Stays safely observing through the 1-hour backoff and alerts at 30 minutes.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert controller.state == "observing"
    assert rig.commands() == ["Manual:45@off"]
    assert not heater_posts(rig)
    assert rig.notifications.count("thermann_shadow_parked_off_cannot_restore") == 1

    # Fresh post-restart poll at 23:00 classifies Off and restores Manual 45 C.
    advance(rig, recovery_at + timedelta(minutes=3))
    assert rig.bridge.cloud_health == "ok"
    assert len(heater_posts(rig)) == 1
    assert controller.state == "baseline_45"
    assert controller.fault is None
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45
