"""Deterministic offline tests for cloud_success_false outage, 1-hour backoff,
scheduled heating transitions (22:00 Hobart / 21:00 AEST evening peak -> 45 C
baseline), recovery, failure to recover, notification deduplication, and Smart
mode token-refresh behaviour.

Uses the real MyThermowattBridge (1.5.0), ShadowRuntime, Executor, and
Controller (0.18.1) with synthetic clocks, mocked HTTP, and realistic Home
Assistant MQTT availability handling. Never touches live Home Assistant or live
Thermowatt cloud services.
"""

from datetime import timedelta
from types import SimpleNamespace

from conftest import TOKENS, response
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


def test_race_status_poll_failure_drains_published_command_and_locks_on_recovery(
    tmp_path, monkeypatch
):
    """Exact live-incident Race A: at 22:00 Hobart the controller publishes
    Manual:45@off (intent=published, state=confirming) while the bridge's
    status poll fails with cloud_success_false and _offline() silently drains
    the command queue. At 23:00 recovery the bridge recovers to Off, but the
    controller locks into fault_locked (command_not_applied) instead of
    automatically applying 45 C until the owner acknowledges the fault."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    recovery_at = outage_at + timedelta(seconds=3600)

    # At 22:00:00, controller evaluates while bridge still looks healthy and
    # publishes Manual:45@off into the bridge queue.
    rig.t = outage_at.timestamp()
    evaluate(rig)
    controller = rig.executor.controller
    assert rig.commands() == ["Manual:45@off"]
    assert controller.state == "confirming"
    assert controller.intent is not None
    assert controller.intent["status"] == "published"
    assert controller.heater == "off"
    assert rig.bridge.commands.qsize() == 1

    # Simultaneously, the bridge's scheduled 22:00 status poll fails with
    # cloud_success_false before processing the queued command: tick() enters
    # _offline() (silently draining self.commands) and starts a 3,600 s backoff.
    def fail_then_recover(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < recovery_at:
            rig.status_attempts.append(rig.now())
            return response(body=CLOUD_SUCCESS_FALSE)
        if endpoint == "status":
            rig.status_attempts.append(rig.now())
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = fail_then_recover
    # Simulate the in-flight status_poll failure path in tick().
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    # Put command back after poll starts by triggering poll_status via tick when
    # poll_due fails during discovery/status before or after command drain:
    # Pop the command temporarily, run the failing poll_status, or inject it
    # right before _offline() runs during the HTTP GET.
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
    rig.bridge.tick()

    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1
    assert rig.bridge.next_cloud == outage_at.timestamp() + 3600
    assert rig.bridge.commands.empty()  # silently drained by _offline()
    assert rig.bridge.last_command is None  # bridge never recorded a refusal
    assert rig.bridge.pending is None
    assert not heater_posts(rig)
    assert rig.tank.mode == "Off"

    # Throughout the 1-hour backoff, intent stays published & unconfirmed.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert controller.state == "confirming"
    assert controller.intent is not None
    assert controller.intent["status"] == "published"
    assert controller.heater == "off"
    assert len(rig.status_attempts) == 1
    assert not heater_posts(rig)

    # At 23:00:00 the cloud recovers and bridge polls Off.
    # Current behaviour: controller hits late_poll (>= 7 min) and locks into
    # fault_locked (command_not_applied) instead of auto-recovering.
    advance(rig, recovery_at + timedelta(minutes=2))
    assert rig.bridge.cloud_health == "ok"
    assert rig.bridge.failures == 0
    assert controller.state == "fault_locked"
    assert controller.fault == "command_not_applied"
    assert controller.intent is None
    assert controller.history[-1]["status"] == "not_applied"
    assert rig.tank.mode == "Off"
    assert not heater_posts(rig)

    # Manual owner acknowledgement restores automatic control on the next fresh poll.
    assert drive(rig.executor.async_owner_action("acknowledge"))
    assert controller.state == "observing"
    # Advance to the next scheduled status read + confirmation.
    advance(rig, recovery_at + timedelta(minutes=35))
    assert rig.commands() == ["Manual:45@off", "Manual:45@off"]
    assert len(heater_posts(rig)) == 1
    assert controller.state == "baseline_45"
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 45


def test_race_command_queued_during_backoff_expires_at_recovery_and_locks(tmp_path, monkeypatch):
    """Exact live-incident Race B: bridge enters 3,600 s backoff on
    cloud_success_false at 22:00:00, and controller's Manual:45@off arrives
    over MQTT right after _offline() (before HA ingests cloud_health=backoff).
    The command sits untouched in bridge.commands for 60 minutes, keeping
    controller in confirming/published, then expires as
    dropped_command_older_than_30s at 23:00 and locks into fault_locked."""
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

    # Snapshot healthy HA states just before bridge publishes backoff, then run
    # the failing bridge status poll, then evaluate controller on the pre-backoff
    # snapshot (simulating MQTT propagation lag).
    rig.t = outage_at.timestamp()
    pre_backoff_states = dict(rig.states)
    rig.bridge.next_poll = rig.t
    rig.bridge.next_background[SERIAL] = rig.t
    rig.bridge.next_cloud = rig.t
    rig.bridge.tick()
    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.next_cloud == outage_at.timestamp() + 3600

    post_backoff_states = dict(rig.states)
    rig.states.clear()
    rig.states.update(pre_backoff_states)
    evaluate(rig)  # controller publishes Manual:45@off while bridge is already in backoff
    rig.states.clear()
    rig.states.update(post_backoff_states)

    controller = rig.executor.controller
    assert rig.commands() == ["Manual:45@off"]
    assert controller.state == "confirming"
    assert controller.intent["status"] == "published"
    assert rig.bridge.commands.qsize() == 1
    assert rig.bridge.last_command is None

    # Command stays unread during the entire 3,600 s backoff.
    advance(rig, recovery_at - timedelta(seconds=1))
    assert controller.state == "confirming"
    assert controller.intent["status"] == "published"
    assert rig.bridge.commands.qsize() == 1
    assert len(rig.status_attempts) == 1
    assert not heater_posts(rig)

    # At 23:00:00, bridge wakes, pops the 3,600 s old command, drops it as
    # dropped_command_older_than_30s, then succeeds on status_poll (Off).
    advance(rig, recovery_at + timedelta(minutes=2))
    assert rig.bridge.cloud_health == "ok"
    assert rig.bridge.last_command["result"] == "dropped_command_older_than_30s"
    assert controller.state == "fault_locked"
    assert controller.fault == "bridge_refused_or_dropped"
    assert controller.intent is None
    assert not heater_posts(rig)
    assert rig.tank.mode == "Off"


def test_pre_command_status_refresh_cloud_success_false_enters_1h_backoff_and_locks(
    tmp_path, monkeypatch
):
    """If Manual:45@off triggers a pre-command status refresh (> 60 s old status)
    and that refresh receives cloud_success_false, bridge refuses the command
    with zero POST, enters 3,600 s backoff, and controller locks cleanly."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 50), cloud_polling="smart")
    transition_at = hobart(MON, 22, 0)
    rig.t = transition_at.timestamp()  # prior poll is 90 s old (> 60 s bridge limit)
    rig.bridge.token_obtained_at = rig.t
    rig.bridge.session.request.side_effect = [response(body=CLOUD_SUCCESS_FALSE)]

    evaluate(rig)
    assert rig.commands() == ["Manual:45@off"]
    rig.bridge.tick()

    assert rig.bridge.cloud_health == "backoff"
    assert rig.bridge.last_error == "cloud_success_false"
    assert rig.bridge.failures == 1
    assert rig.bridge.next_cloud == transition_at.timestamp() + 3600
    assert rig.bridge.last_command["result"] == "refused_status_refresh_failed"
    assert rig.bridge.last_command["error"] == "cloud_success_false"
    assert rig.bridge.pending is None
    assert not heater_posts(rig)

    # Next controller evaluation immediately resolves the refusal -> fault_locked.
    rig.t += 60
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.state == "fault_locked"
    assert controller.fault == "bridge_refused_or_dropped"
    assert controller.intent is None
    assert controller.history[-1]["status"] == "not_applied"


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


def test_failure_to_recover_while_confirming_hits_65m_confirmation_timeout_and_stays_locked(
    tmp_path, monkeypatch
):
    """If an intent is published/confirming (Race A) and the +1 h recovery poll
    also fails (2 h backoff), the 65-minute confirmation timeout fires at +65 m
    and locks the controller even after cloud eventually recovers at +3 h."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 30), cloud_polling="smart")
    outage_at = hobart(MON, 22, 0)
    first_retry = outage_at + timedelta(seconds=3600)
    second_retry = first_retry + timedelta(seconds=7200)

    rig.t = outage_at.timestamp()
    evaluate(rig)
    controller = rig.executor.controller
    assert controller.state == "confirming"
    queued_cmd = rig.bridge.commands.get_nowait()

    def cloud(method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status" and rig.now() < second_retry:
            rig.status_attempts.append(rig.now())
            if len(rig.status_attempts) == 1:
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

    # At +1 h (23:00), retry fails again -> 7,200 s backoff; still confirming at 23:04.
    advance(rig, outage_at + timedelta(minutes=64))
    assert rig.bridge.failures == 2
    assert controller.state == "confirming"
    assert controller.intent["status"] == "published"

    # Past 65 minutes (confirmation_timeout_minutes = 65.0) -> fault_locked.
    advance(rig, outage_at + timedelta(minutes=66))
    assert controller.state == "fault_locked"
    assert controller.fault == "confirmation_timeout"
    assert controller.intent is None
    assert controller.history[-1]["status"] == "timeout"

    # Even after cloud recovers at +3 h, controller remains fault_locked with zero POSTs.
    advance(rig, second_retry + timedelta(minutes=5))
    assert rig.bridge.cloud_health == "ok"
    assert controller.state == "fault_locked"
    assert controller.fault == "confirmation_timeout"
    assert not heater_posts(rig)
    assert rig.tank.mode == "Off"


def test_notifications_no_spam_on_backoff_but_unavailable_gap_resets_cooldown(
    tmp_path, monkeypatch
):
    """Consecutive failures in continuous backoff emit cloud_fault once per 6 h
    cooldown; however, a brief cloud_health='unavailable' gap clears self.alerts
    and immediately re-notifies when backoff returns."""
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

    rig.t += 60
    rig.states[c.DEFAULT_SOURCES["cloud_health"]] = SimpleNamespace(
        state=saved_health.state,
        attributes=saved_health.attributes,
        last_reported=rig.now(),
        last_updated=rig.now(),
    )
    evaluate(rig)
    # Current behaviour: cooldown was erased by the 1-minute unavailable gap.
    assert rig.notifications.count("thermann_shadow_cloud_fault") == 2


def test_smart_mode_ordinary_get_does_not_proactively_refresh_on_cloud_success_false(
    tmp_path, monkeypatch
):
    """In bridge 1.5.0 Smart mode, ordinary GET /status skips proactive 20-min
    token refresh (ordinary_smart_get checks self.smart, not poll_schedule.active).
    If the vendor ever returns HTTP 200 success:false for a stale session, neither
    the initial poll nor the 1-hour recovery poll refreshes the token."""
    rig = make_evening_peak_rig(tmp_path, monkeypatch, hobart(MON, 21, 28), cloud_polling="smart")
    outage_at = hobart(MON, 21, 58)
    recovery_at = outage_at + timedelta(seconds=3600)

    # Age the access token well past PROACTIVE_REFRESH_AGE (1200 s).
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

    # Advance 1 hour to the recovery poll (fixed fallback timing, but self.smart
    # is still True): still sends GET /status without refreshing the 2-hour-old token.
    rig.t = recovery_at.timestamp()
    rig.bridge.tick()
    assert endpoints == [("GET", "status"), ("GET", "status")]
    assert rig.bridge.failures == 2
    assert rig.bridge.guard.state["mode"] == "authorized"
