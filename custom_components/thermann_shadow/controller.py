"""Production executor state machine. The ONLY code that may request a Thermann
mode change, and only through the Thermowatt bridge's guarded MQTT payloads.

Pure logic: no Home Assistant imports, no I/O. ``executor.py`` builds the
observations, persists the returned state BEFORE publishing, and performs the
returned effects. Every rule here errs towards "do nothing and tell the owner".

Control method (owner decision, revised 12 Nov 2026 after app testing):
  * heating PERMITTED = Manual at 70 °C (the Thermann thermostat decides power);
  * heating PARKED    = Thermann software OFF (mains stays connected, so the
    manufacturer's antibacterial and frost protection remain active).
The empty-Schedule park was withdrawn: with an empty programme the app's
setpoint reverted to 40 °C. No setpoint writes, no Schedule writes, no mains
switching, no fallback heating windows. The native Schedule is not used and
needs no particular configuration.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

APPROVED_TARGET_C = 70.0
# Bridge >= 1.3.10 (automation policy): sends 70 °C explicitly; accepted only
# from OFF whose target is 70 or unusable. The controller never reads Cmd: it
# uses the bridge's vendor mode, which 1.3.10 reports as "Off" for the heater's
# actual OFF code (Cmd 8, seen in T3) and for the older assumed Cmd 16.
PERMIT_PAYLOAD = "Manual:70"
PARK_PAYLOAD = "off"  # bridge: POST /off -> software OFF; accepted only from Manual 70
# Status at most this old is used by the bridge without a pre-command read
# (the bridge allows 60 s; up to ~20 s pass before it takes the command).
BRIDGE_FRESH_SECONDS = 30.0
EXPECTED_MODE = {"permit": "Manual", "park": "Off"}
PARK_MODE = "Off"
TOPIC_PREFIX, TOPIC_SUFFIX = "P/", "/CMD/MODE"

DISABLED = "disabled"
OBSERVING = "observing"
PARKED = "parked"
HEATING_PERMITTED = "heating_permitted"
HEATING_REQUESTED = "heating_requested"  # planner wants heat; waiting for a command slot
PARK_REQUESTED = "park_requested"  # planner wants park; waiting for a command slot
CONFIRMING = "confirming"  # one command published; waiting for observed status
OWNER_OVERRIDE = "owner_override"
FAULT_LOCKED = "fault_locked"
STATES = (
    DISABLED,
    OBSERVING,
    PARKED,
    HEATING_PERMITTED,
    HEATING_REQUESTED,
    PARK_REQUESTED,
    CONFIRMING,
    OWNER_OVERRIDE,
    FAULT_LOCKED,
)
STEADY = {PARKED, HEATING_PERMITTED, HEATING_REQUESTED, PARK_REQUESTED}
EVENT_PREFIXES = ("fault_", "override_")

# Bridge last_command results. Any dropped_/refused_/rejected_ code proves the
# command was NOT applied (1.3.10 adds refresh refusals and failures; unknown
# future codes with these prefixes are treated the same, never as success).
FAILURE_PREFIXES = ("dropped_", "refused_", "rejected_")
# ...but these mean the bridge's FRESH status showed something the controller
# did not expect (the owner changed mode or target since the last poll): that is
# owner control, so control pauses instead of locking with a fault.
OWNER_CHANGE_RESULTS = {
    "refused_target_mismatch",
    "refused_mode_mismatch",
    "already_in_requested_state",
}
# The bridge is still working on the command (1.3.10 publishes the status of its
# pre-command read, and of its confirmation read, BEFORE the final outcome).
# 1.3.11 adds "submitting" (recorded before the POST) and
# "awaiting_confirmation" (a read after the POST still shows the old mode; the
# cloud may report the change late, so the bridge makes bounded follow-ups).
BRIDGE_IN_PROGRESS_RESULTS = {
    "refreshing_status",
    "submitting",
    "submitted_awaiting_status",
    "awaiting_confirmation",
}
# 1.3.11 terminal outcomes that are not refusals.
BRIDGE_NOT_CONFIRMED = "not_confirmed_within_limit"
BRIDGE_UNEXPECTED_STATE = "unexpected_state_after_command"


def bridge_failure(result: object) -> bool:
    return isinstance(result, str) and result.startswith(FAILURE_PREFIXES)


RECOVERY = {
    "command_not_confirmed": "The bridge sent the command once but no status within its confirmation window (about 6 minutes) showed the requested mode. It was not repeated. Check the Thermann app: if it shows the requested mode, the cloud is slow to report it; otherwise the command did not take effect. Set the mode you want in the app, then press Acknowledge fault; automatic control re-inspects the heater first.",
    "command_not_applied": "The heater did not change mode. Check the Thermann app: it should show the mode you expect. Then press Acknowledge fault; automatic control re-inspects the heater before doing anything.",
    "confirmation_timeout": "No status arrived to confirm the last command. Check the Thermowatt add-on log and cloud health, then the Thermann app. Press Acknowledge fault when the heater state is known.",
    "bridge_refused_or_dropped": "The Thermowatt bridge did not send the command (see last command result). Nothing was changed on the heater. Fix the cause, then Acknowledge fault.",
    "publish_failed": "Home Assistant could not publish the MQTT command. Nothing is known to have reached the heater. Check MQTT, then Acknowledge fault.",
    "intent_unresolved_after_restart": "Home Assistant restarted while a command was unconfirmed and no later status resolved it. Check the Thermann app, then Acknowledge fault.",
    "unexpected_mode_during_confirmation": "The heater reported a mode that was neither the previous nor the requested one. Check the Thermann app. Resume automatic control when you are satisfied.",
    "mode_or_target_changed_outside_controller": "The Thermann mode or target changed without a controller command (for example in the app). Automatic control stays paused until you press Resume automatic control.",
    "unexpected_mode_or_target": "The heater is not OFF or in Manual at 70 °C (for example it is in Schedule or Eco). Automatic control will not touch it. In the Thermann app choose Manual at 70 °C or turn it OFF, then press Resume automatic control.",
    "off_target_not_70": "While OFF the heater reports a usable target other than 70 °C. That may be your own setting, so automatic control will not change it. To hand control back, set Manual at 70 °C in the Thermann app (you may then turn it OFF again) and press Resume automatic control.",
    "owner_hold": "You placed the heater on hold. Automatic control sends nothing until you press Resume automatic control.",
    "guest_mode_not_applied": "Guest mode wants Manual at 70 °C but the controller could not apply it (see the reason and gate failures). Check the Thermowatt add-on and the Thermann app; you can select Manual at 70 °C in the app yourself.",
}
GUEST_HOURS = 12.0
GUEST_ALERT_AFTER = timedelta(minutes=10)
HOLIDAY_MAX_DAYS = 60


@dataclass(frozen=True)
class ControllerConfig:
    command_topic: str = ""
    bridge_commands_qualified: bool = False
    hysteresis_c: float = 8.0
    min_heating_minutes: float = 30.0
    min_rest_minutes: float = 30.0
    max_commands_per_day: int = 6
    comfort_reserve_commands: int = 2  # kept for a comfort start + its park
    confirmation_timeout_minutes: float = 65.0
    max_requests_per_day: int = 220
    poll_interval_minutes: float = 30.0
    notification_cooldown_hours: float = 6.0

    def missing_commissioning(self) -> list[str]:
        missing = []
        if not valid_topic(self.command_topic):
            missing.append("command_topic_not_configured")
        if not self.bridge_commands_qualified:
            missing.append("bridge_commands_not_qualified_t3")
        return missing


def valid_topic(topic: object) -> bool:
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return False
    if not topic.endswith(TOPIC_SUFFIX):
        return False
    serial = topic[len(TOPIC_PREFIX) : -len(TOPIC_SUFFIX)]
    return 1 <= len(serial) <= 64 and serial.isalnum()


@dataclass
class Observation:
    """One snapshot of what Home Assistant currently knows. Never assumed."""

    now: datetime
    poll_at: datetime | None = None  # bridge last_successful_poll
    mode: str | None = None  # vendor mode: Manual/Schedule/Eco/Off/Holiday/Unknown
    target_c: float | None = None
    temperature_c: float | None = None
    element: str = "unknown"  # on/off/unknown
    element_confidence: str = "none"
    cloud_health: str | None = None
    auth_mode: str | None = None
    consecutive_failures: int | None = None
    cooldown_seconds: int | None = None
    bridge_available: bool = False
    bridge_commands_enabled: bool | None = None
    last_command: dict | None = None  # bridge >= 1.3.9 diagnostics
    # Bridge >= 1.3.10: bounded pre-command status refresh (None = older bridge).
    bridge_refresh_limit: int | None = None
    bridge_refreshes_24h: int | None = None
    # Bridge >= 1.3.11: bounded confirmation (follow-up schedule; None = older).
    bridge_confirmation_followups: list | None = None
    bridge_confirmation_pending: bool | None = None
    requests_total: int | None = None
    mqtt_ready: bool = False


@dataclass
class Desire:
    """What the planner wants for the coming command interval."""

    action: str  # permit / park / hold
    reason: str
    planner_ok: bool = True
    next_start: datetime | None = None
    next_stop: datetime | None = None
    comfort_risk: str | None = None  # goal kind seriously at risk
    comfort: bool = False  # permit needed for a comfort goal (may use the reserve)
    # 0.7.0: permission kept/granted because heating NOW would be economical,
    # not because heat is needed now (Thermann's thermostat decides; it may
    # not call for heat at all).
    standby: bool = False
    # 0.7.0: economic park during a peak; may bypass the minimum-heating dwell.
    urgent: bool = False


@dataclass
class Intent:
    id: str
    action: str  # permit / park
    payload: str
    topic: str
    created_at: str
    prior_mode: str | None
    poll_at: str | None
    requests_before: int | None
    status: str = "published"  # published/confirmed/not_applied/timeout/ambiguous/publish_failed
    resolved_at: str | None = None
    observed: str | None = None
    bridge_result: str | None = None


@dataclass
class Effect:
    kind: str  # publish / notify / resolve
    key: str = ""
    topic: str = ""
    payload: str = ""
    title: str = ""
    message: str = ""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Controller:
    enabled: bool = False
    hold: bool = False
    state: str = DISABLED
    reason: str = "automatic_control_disabled"
    intent: dict | None = None  # Intent as dict (persisted)
    history: list = field(default_factory=list)  # last 20 resolved intents
    commands: list = field(default_factory=list)  # ISO times of published commands (24 h)
    request_samples: list = field(default_factory=list)  # [ISO poll time, total]
    last_poll_seen: str | None = None
    last_transition_at: str | None = None  # last CONFIRMED mode change (dwell timers)
    inspect_after: str | None = None  # a NEW poll after this time is required to act
    fault: str | None = None
    alerts: dict = field(default_factory=dict)  # key -> ISO time last notified
    active_alerts: list = field(default_factory=list)
    unexplained_since: str | None = None
    last_desire: dict | None = None
    gate_failures: list = field(default_factory=list)
    permitted_off_since: str | None = None
    # 0.7.0 owner modes (persisted with the controller state).
    guest_started: str | None = None
    guest_until: str | None = None
    holiday_start: str | None = None
    holiday_return: str | None = None
    refusal: str | None = None  # why the last owner mode request was refused

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Controller:
        if not isinstance(data, dict):
            return cls()
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        controller = cls(**known)
        if controller.state not in STATES:
            controller.state = OBSERVING
        return controller

    def restored(self, now: datetime) -> None:
        """After an HA restart: never assume the heater is in the last REQUESTED
        state. Re-inspect from a NEW status; an unresolved intent is reconciled
        from observed status only and is never re-sent."""
        self.inspect_after = _iso(now)
        if self.state == CONFIRMING and self.intent:
            self.reason = "reconciling_command_after_restart"
            return
        if self.state in STEADY or self.state == OBSERVING:
            self.state = OBSERVING if self.enabled else DISABLED
            self.reason = "restart_reinspecting_heater"

    # ------------------------------------------------------------------ owner actions
    def set_enabled(self, enabled: bool, now: datetime) -> None:
        self.enabled = enabled
        if not enabled:
            if self.state != CONFIRMING:
                self.state, self.reason = DISABLED, "automatic_control_disabled"
            return
        if self.state in {DISABLED, *STEADY}:
            self.state, self.reason = OBSERVING, "enabled_inspecting_heater"
            self.inspect_after = _iso(now)

    def set_hold(self, now: datetime) -> None:
        self.hold = True
        if self.state != CONFIRMING:
            self.state, self.reason = OWNER_OVERRIDE, "owner_hold"

    def resume(self, now: datetime) -> bool:
        if self.state not in {OWNER_OVERRIDE, OBSERVING} or self.state == CONFIRMING:
            return False
        self.hold = False
        self.state = OBSERVING if self.enabled else DISABLED
        self.reason = "resumed_inspecting_heater"
        self.inspect_after = _iso(now)
        return True

    # ------------------------------------------------------------------ owner modes
    def guest_active(self, now: datetime) -> bool:
        until = _dt(self.guest_until)
        return until is not None and now < until

    def holiday_active(self, now: datetime) -> bool:
        start, back = _dt(self.holiday_start), _dt(self.holiday_return)
        return start is not None and back is not None and start <= now < back

    def holiday_window(self, now: datetime) -> tuple[datetime, datetime] | None:
        start, back = _dt(self.holiday_start), _dt(self.holiday_return)
        if start is None or back is None or now >= back:
            return None
        return start, back

    def operating_mode(self, now: datetime) -> str:
        if not self.enabled:
            return "disabled"
        if self.guest_active(now):
            return "guest"
        if self.holiday_active(now):
            return "holiday"
        return "automatic"

    def _reinspect(self, now: datetime, reason: str) -> None:
        if self.state == CONFIRMING:
            return  # the pending command resolves first; never interrupted
        self.state = OBSERVING if self.enabled else DISABLED
        self.reason = reason
        self.inspect_after = _iso(now)

    def start_guest(self, now: datetime, hours: float = GUEST_HOURS) -> bool:
        """Owner: Manual 70 °C for `hours`, economics relaxed. An explicit owner
        instruction, so it also releases Hold (the heater is re-inspected;
        an app-selected mode other than OFF/Manual 70 still pauses control)."""
        if not self.enabled:
            self.refusal = "automatic_control_is_off"
            return False
        if self.state == FAULT_LOCKED:
            self.refusal = "acknowledge_the_controller_fault_first"
            return False
        if self.holiday_active(now):
            self.refusal = "cancel_holiday_mode_first"
            return False
        self.refusal = None
        self.guest_started, self.guest_until = _iso(now), _iso(now + timedelta(hours=hours))
        if self.hold or self.state == OWNER_OVERRIDE:
            self.hold = False
            self._reinspect(now, "guest_mode_started_reinspecting")
        return True

    def cancel_guest(
        self, now: datetime, reason: str = "guest_mode_cancelled_reinspecting"
    ) -> bool:
        if self.guest_until is None:
            self.refusal = "guest_mode_is_not_active"
            return False
        self.guest_started = self.guest_until = None
        self.refusal = None
        if self.enabled and self.state not in {FAULT_LOCKED, OWNER_OVERRIDE}:
            self._reinspect(now, reason)
        return True

    def set_holiday(self, now: datetime, start: datetime | None, back: datetime | None) -> bool:
        """Owner: away from `start` until `back`. Validated, never silently
        adjusted; a refusal leaves the previous dates unchanged."""
        if start is not None and back is not None:
            if back <= start:
                self.refusal = "return_must_be_after_departure"
                return False
            if back - start > timedelta(days=HOLIDAY_MAX_DAYS):
                self.refusal = "holiday_longer_than_60_days"
                return False
        if back is not None and back <= now:
            self.refusal = "return_must_be_in_the_future"
            return False
        if start is not None and self.guest_active(now) and start <= now:
            self.refusal = "cancel_guest_mode_first"
            return False
        self.refusal = None
        self.holiday_start, self.holiday_return = _iso(start), _iso(back)
        return True

    def cancel_holiday(self, now: datetime) -> bool:
        if self.holiday_start is None and self.holiday_return is None:
            self.refusal = "holiday_mode_is_not_set"
            return False
        self.holiday_start = self.holiday_return = None
        self.refusal = None
        return True

    def _expire_modes(self, now: datetime) -> None:
        until = _dt(self.guest_until)
        if until is not None and now >= until:
            self.cancel_guest(now, "guest_mode_ended_reinspecting")
        back = _dt(self.holiday_return)
        if back is not None and now >= back:
            # Return time reached: normal goals resume (the heater state was
            # never assumed; normal checks continue from observed status).
            self.holiday_start = self.holiday_return = None

    def acknowledge(self, now: datetime) -> bool:
        if self.state != FAULT_LOCKED:
            return False
        self.fault = None
        self.state = OBSERVING if self.enabled else DISABLED
        self.reason = "fault_acknowledged_inspecting_heater"
        self.inspect_after = _iso(now)
        return True

    # ------------------------------------------------------------------ main step
    def step(self, obs: Observation, desire: Desire, cfg: ControllerConfig) -> list[Effect]:
        now = obs.now
        effects: list[Effect] = []
        new_poll = self._ingest_poll(obs)
        self.last_desire = {
            "action": desire.action,
            "reason": desire.reason,
            "planner_ok": desire.planner_ok,
            "next_start": _iso(desire.next_start),
            "next_stop": _iso(desire.next_stop),
        }
        self.commands = [item for item in self.commands if now - _dt(item) <= timedelta(hours=24)]
        self.active_alerts = []
        self._expire_modes(now)
        self._track_unexplained(obs)

        if self.state == CONFIRMING and self.intent:
            self._confirm(obs, cfg, new_poll, effects)
        if self.state == CONFIRMING:
            self._supervise_alerts(obs, desire, cfg, effects)
            return effects
        if not self.enabled:
            self.state, self.reason = DISABLED, "automatic_control_disabled"
            self._supervise_alerts(obs, desire, cfg, effects)
            return effects
        if self.hold and self.state != FAULT_LOCKED:
            self.state, self.reason = OWNER_OVERRIDE, "owner_hold"
        if self.state in {FAULT_LOCKED, OWNER_OVERRIDE}:
            self._supervise_alerts(obs, desire, cfg, effects)
            return effects

        fresh = self._fresh_after_inspection(obs)
        if self.state == OBSERVING:
            if not fresh:
                self.reason = "waiting_for_new_heater_status"
                self._supervise_alerts(obs, desire, cfg, effects)
                return effects
            self._classify(obs, effects)
            if self.state not in STEADY:
                self._supervise_alerts(obs, desire, cfg, effects)
                return effects
        elif fresh and obs.mode is not None:
            self._check_external_change(obs, effects)
            if self.state not in STEADY:
                self._supervise_alerts(obs, desire, cfg, effects)
                return effects

        self._decide(obs, desire, cfg, new_poll, effects)
        self._supervise_alerts(obs, desire, cfg, effects)
        return effects

    # ------------------------------------------------------------------ helpers
    def _track_unexplained(self, obs: Observation) -> None:
        """Heating while parked: antibacterial, protective, frost or a programme
        that is not empty. Detected BEFORE any decision, so no command can be sent
        on the same tick. It is NEVER interrupted; writes wait until it ends."""
        if not self.enabled:
            # Disabled (Stage A): the native programme may legitimately heat.
            self.unexplained_since = None
            return
        parked = self.state in {PARKED, HEATING_REQUESTED, OBSERVING}
        confident = obs.element_confidence in {"verified", "high"}
        if parked and obs.mode == PARK_MODE and obs.element == "on" and confident:
            self.unexplained_since = self.unexplained_since or _iso(obs.now)
        elif obs.element == "off" or obs.mode != PARK_MODE:
            self.unexplained_since = None

    def _ingest_poll(self, obs: Observation) -> bool:
        if obs.poll_at is None:
            return False
        seen = _dt(self.last_poll_seen)
        if seen is not None and obs.poll_at <= seen:
            return False
        self.last_poll_seen = _iso(obs.poll_at)
        if obs.requests_total is not None:
            samples = [
                s for s in self.request_samples if obs.now - _dt(s[0]) <= timedelta(hours=25)
            ]
            if samples and obs.requests_total < samples[-1][1]:
                samples = []  # bridge restart: counter reset, history restarts
            samples.append([_iso(obs.poll_at), obs.requests_total])
            self.request_samples = samples[-60:]
        return True

    def requests_last_24h(self, now: datetime) -> int | None:
        window = [s for s in self.request_samples if now - _dt(s[0]) <= timedelta(hours=24)]
        if len(window) < 2:
            return 0 if window else None
        return window[-1][1] - window[0][1]

    def _fresh_after_inspection(self, obs: Observation) -> bool:
        after = _dt(self.inspect_after)
        if obs.poll_at is None:
            return False
        return after is None or obs.poll_at > after

    def _off_target_ok(self, obs: Observation) -> bool:
        """While OFF: no usable setpoint (absent or outside 20-75 °C, e.g. an
        unreported value), or exactly 70. A usable OTHER value may be the owner's
        own setting and is never silently replaced by Manual:70 (bridge 1.3.9
        refuses it too)."""
        target = obs.target_c
        return target is None or not 20 <= target <= 75 or abs(target - APPROVED_TARGET_C) < 0.01

    def _known_target(self, obs: Observation) -> bool:
        return obs.target_c is not None and abs(obs.target_c - APPROVED_TARGET_C) < 0.01

    def _classify(self, obs: Observation, effects: list[Effect]) -> None:
        self.inspect_after = None
        if obs.mode == PARK_MODE and self._off_target_ok(obs):
            self.state, self.reason = PARKED, "inspected_parked_off"
        elif obs.mode == PARK_MODE:
            self._override("off_target_not_70", obs, effects)
            return
        elif obs.mode == "Manual" and self._known_target(obs):
            self.state, self.reason = HEATING_PERMITTED, "inspected_manual_70"
        else:
            self._override("unexpected_mode_or_target", obs, effects)
            # Dwell timers apply to the controller's OWN confirmed transitions;
            # an inspected state of unknown age imposes none.

    def _check_external_change(self, obs: Observation, effects: list[Effect]) -> None:
        permitted = self.state in {HEATING_PERMITTED, PARK_REQUESTED}
        expected = "Manual" if permitted else PARK_MODE
        if obs.mode == PARK_MODE and not permitted and not self._off_target_ok(obs):
            self._override("off_target_not_70", obs, effects)
        elif obs.mode != expected or (permitted and not self._known_target(obs)):
            self._override("mode_or_target_changed_outside_controller", obs, effects)

    def _override(self, reason: str, obs: Observation, effects: list[Effect]) -> None:
        self.state, self.reason = OWNER_OVERRIDE, reason
        effects.append(
            Effect(
                "notify",
                key=f"override_{reason}",
                title="Hot water: automatic control paused",
                message=f"Observed mode {obs.mode}, target {obs.target_c} °C. {RECOVERY[reason]}",
            )
        )

    def _lock(self, reason: str, detail: str, effects: list[Effect]) -> None:
        self.state, self.reason, self.fault = FAULT_LOCKED, reason, reason
        effects.append(
            Effect(
                "notify",
                key=f"fault_{reason}",
                title="Hot water: controller fault — automatic control locked",
                message=f"{detail} {RECOVERY[reason]}",
            )
        )

    def _confirm(
        self, obs: Observation, cfg: ControllerConfig, new_poll: bool, effects: list[Effect]
    ) -> None:
        intent = self.intent or {}
        published = _dt(intent.get("created_at"))
        expected = EXPECTED_MODE[intent["action"]]
        result = (obs.last_command or {}).get("result")
        result_at = _dt((obs.last_command or {}).get("at"))
        bridge_fresh = (
            result_at is not None
            and published is not None
            and result_at >= published - timedelta(seconds=5)
            and (obs.last_command or {}).get("payload") == intent.get("payload")
        )
        if bridge_fresh:
            intent["bridge_result"] = result
        if bridge_fresh and result in OWNER_CHANGE_RESULTS:
            # The bridge's fresh status (1.3.10 pre-command read) showed the
            # heater already changed, or at another mode/target: owner control.
            # Nothing was written. Checked BEFORE the mode test below, because
            # "already in the requested state" also shows the expected mode.
            self._resolve("external_change", obs, effects)
            self._override("mode_or_target_changed_outside_controller", obs, effects)
            return
        if bridge_fresh and result == BRIDGE_UNEXPECTED_STATE:
            # A fresh read after the POST showed neither the old nor the
            # requested state (for example an app change): owner control.
            self._resolve("ambiguous", obs, effects)
            self._override("unexpected_mode_during_confirmation", obs, effects)
            return
        if bridge_fresh and result == BRIDGE_NOT_CONFIRMED:
            # Sent once, never repeated; no read within the bridge's bounded
            # window confirmed it. Owner action.
            self._resolve("not_confirmed", obs, effects)
            self._lock(
                "command_not_confirmed",
                f"{intent['payload']} was sent once; the heater still reported "
                f"{(obs.last_command or {}).get('observed_mode') or obs.mode}.",
                effects,
            )
            return
        if bridge_fresh and bridge_failure(result):
            self._resolve("not_applied", obs, effects)
            self._lock(
                "bridge_refused_or_dropped",
                f"Last command ({intent['payload']}) result: {result}.",
                effects,
            )
            return
        # The bridge marks the heater unavailable while a command is in flight:
        # no mode means "not yet known", never "changed".
        after_publish = (
            obs.mode is not None
            and obs.poll_at is not None
            and published is not None
            and obs.poll_at > published
        )
        # While the bridge reports this command in progress, a new status is
        # NOT conclusive: it may be the pre-command read (whose outcome, e.g.
        # "already in the requested state", follows a moment later) or a read
        # the cloud has not yet caught up with (1.3.11 awaiting_confirmation).
        # The bridge always ends its bounded window with an outcome; the
        # controller's own timeout is the outer bound.
        in_progress = bridge_fresh and result in BRIDGE_IN_PROGRESS_RESULTS
        late_poll = (
            after_publish and not in_progress and obs.poll_at - published >= timedelta(minutes=5)
        )
        conclusive = after_publish and not in_progress
        target_ok = intent["action"] == "park" or self._known_target(obs)
        if conclusive and obs.mode == expected and target_ok:
            self._resolve("confirmed", obs, effects)
            self.state = HEATING_PERMITTED if intent["action"] == "permit" else PARKED
            self.reason = f"{intent['action']}_confirmed"
            self.last_transition_at = _iso(obs.poll_at)
            self.permitted_off_since = None
            return
        if conclusive and obs.mode not in {expected, intent.get("prior_mode")}:
            self._resolve("ambiguous", obs, effects)
            self._override("unexpected_mode_during_confirmation", obs, effects)
            return
        # The bridge's immediate read may precede the cloud applying the change.
        # A later BACKGROUND poll still showing the prior mode is conclusive.
        if late_poll and obs.mode == intent.get("prior_mode"):
            self._resolve("not_applied", obs, effects)
            self._lock(
                "command_not_applied",
                f"{intent['payload']} was sent but the heater still reports {obs.mode}.",
                effects,
            )
            return
        if published and obs.now - published > timedelta(minutes=cfg.confirmation_timeout_minutes):
            restored = self.reason == "reconciling_command_after_restart"
            self._resolve("timeout", obs, effects)
            self._lock(
                "intent_unresolved_after_restart" if restored else "confirmation_timeout",
                f"{intent['payload']} sent at {intent['created_at']} was never confirmed.",
                effects,
            )
            return
        if self.reason != "reconciling_command_after_restart":
            self.reason = f"confirming_{intent['action']}"

    def _resolve(self, status: str, obs: Observation, effects: list[Effect]) -> None:
        intent = dict(self.intent or {})
        intent.update(status=status, resolved_at=_iso(obs.now), observed=obs.mode)
        self.history = (self.history + [intent])[-20:]
        self.intent = None

    def gates(
        self,
        obs: Observation,
        action: str,
        cfg: ControllerConfig,
        new_poll: bool,
        comfort: bool = False,
        standby: bool = False,
        urgent: bool = False,
    ) -> list[str]:
        """Every reason the controller may NOT publish now (empty = eligible)."""
        failures = list(cfg.missing_commissioning())
        now = obs.now
        if not obs.mqtt_ready:
            failures.append("mqtt_not_ready")
        if not obs.bridge_available:
            failures.append("bridge_unavailable")
        if obs.bridge_commands_enabled is not True:
            failures.append("bridge_commands_disabled_or_unknown")
        if obs.cloud_health != "ok":
            failures.append(f"cloud_health_{obs.cloud_health or 'unknown'}")
        if obs.auth_mode != "authorized":
            failures.append("bridge_auth_not_authorized")
        if obs.consecutive_failures not in (0, None) or (obs.cooldown_seconds or 0) > 0:
            failures.append("bridge_in_backoff")
        if obs.bridge_refresh_limit is None or obs.bridge_confirmation_followups is None:
            # 1.3.9 reports OFF (Cmd 8) as Unknown and cannot refresh status;
            # 1.3.10 ends a command at the first read even when the cloud
            # reports the new mode late (T3b).
            failures.append("bridge_1_3_11_required")
        if obs.bridge_confirmation_pending:
            # Another command (for example one published by hand) still awaits
            # its outcome; the bridge would refuse a new one anyway.
            failures.append("bridge_confirmation_pending")
        if obs.poll_at is None:
            failures.append("no_heater_status")
        else:
            age = (now - obs.poll_at).total_seconds()
            if age > (cfg.poll_interval_minutes + 5) * 60:
                failures.append("heater_status_too_old")
            elif (
                age > BRIDGE_FRESH_SECONDS
                and obs.bridge_refresh_limit is not None
                and (obs.bridge_refreshes_24h or 0) >= obs.bridge_refresh_limit
            ):
                # No refresh left today: wait for a background poll, after
                # which the status is fresh and no refresh is needed.
                failures.append("bridge_refresh_budget_exhausted")
        expected_now = PARK_MODE if action == "permit" else "Manual"
        if obs.mode != expected_now:
            failures.append(f"heater_not_{expected_now.lower()}")
        if action == "park" and not self._known_target(obs):
            failures.append("target_not_70")
        if action == "permit" and not self._off_target_ok(obs):
            failures.append("off_target_not_70")
        since = _dt(self.last_transition_at)
        if since is not None:
            dwell = cfg.min_rest_minutes if action == "permit" else cfg.min_heating_minutes
            thermostat_done = (
                action == "park"
                and obs.element == "off"
                and obs.element_confidence in {"verified", "high"}
            )
            # 0.7.0: an economic park during a peak is not held back by the
            # minimum-heating dwell (that protects against toggling the element,
            # not against peak imports). Minimum REST still limits permits.
            economic_override = action == "park" and urgent
            if (
                now - since < timedelta(minutes=dwell)
                and not thermostat_done
                and not economic_override
            ):
                failures.append("minimum_dwell_not_elapsed")
        if len(self.commands) >= cfg.max_commands_per_day:
            failures.append("daily_command_limit_reached")
        elif (
            action == "permit"
            and not comfort
            and len(self.commands) >= cfg.max_commands_per_day - cfg.comfort_reserve_commands
        ):
            # Economic starts stop early so a comfort start and its park
            # always remain possible within the daily limit.
            failures.append("economic_command_budget_reached")
        used = self.requests_last_24h(now)
        if used is None:
            failures.append("request_accounting_unavailable")
        elif used >= cfg.max_requests_per_day:
            failures.append("daily_cloud_request_budget_reached")
        if self.unexplained_since:
            failures.append("unexplained_heating_in_progress")
        if action == "permit":
            if obs.temperature_c is None:
                failures.append("temperature_unavailable")
            elif obs.temperature_c > APPROVED_TARGET_C - cfg.hysteresis_c and not standby:
                # A standby permission is wanted precisely for LATER reheats
                # (after hot water is used). Any other permit would heat nothing
                # now: the thermostat restarts only below about 62 °C.
                failures.append("thermostat_would_not_call_for_heat")
        return failures

    def _decide(
        self,
        obs: Observation,
        desire: Desire,
        cfg: ControllerConfig,
        new_poll: bool,
        effects: list[Effect],
    ) -> None:
        permitted = self.state in {HEATING_PERMITTED, PARK_REQUESTED}
        action = desire.action
        if (
            action == "hold"
            or (action == "permit" and permitted)
            or (action == "park" and not permitted)
        ):
            self.state = HEATING_PERMITTED if permitted else PARKED
            self.reason = desire.reason
            self.gate_failures = []
            return
        self.state = PARK_REQUESTED if action == "park" else HEATING_REQUESTED
        failures = self.gates(
            obs, action, cfg, new_poll, desire.comfort, desire.standby, desire.urgent
        )
        self.gate_failures = failures
        if failures:
            self.reason = failures[0]
            if failures == ["thermostat_would_not_call_for_heat"]:
                self.state, self.reason = PARKED, "thermostat_would_not_call_for_heat"
            return
        payload = PERMIT_PAYLOAD if action == "permit" else PARK_PAYLOAD
        intent = Intent(
            id=uuid.uuid4().hex,
            action=action,
            payload=payload,
            topic=cfg.command_topic,
            created_at=_iso(obs.now),
            prior_mode=obs.mode,
            poll_at=_iso(obs.poll_at),
            requests_before=obs.requests_total,
        )
        self.intent = asdict(intent)
        self.commands.append(_iso(obs.now))
        self.state, self.reason = CONFIRMING, f"confirming_{action}"
        effects.append(Effect("publish", key=intent.id, topic=cfg.command_topic, payload=payload))

    def publish_failed(self, now: datetime) -> list[Effect]:
        """The executor could not hand the message to MQTT. Never retried."""
        effects: list[Effect] = []
        if self.intent:
            intent = dict(self.intent)
            intent.update(status="publish_failed", resolved_at=_iso(now))
            self.history = (self.history + [intent])[-20:]
            self.intent = None
        self._lock("publish_failed", "The MQTT publish raised an error.", effects)
        return effects

    def _supervise_alerts(
        self, obs: Observation, desire: Desire, cfg: ControllerConfig, effects: list[Effect]
    ) -> None:
        now = obs.now
        if not self.enabled:
            # A disabled controller is silent: no alerts while the native
            # programme and the planner run on their own (installation Stage A).
            for key in list(self.alerts):
                del self.alerts[key]
                effects.append(Effect("resolve", key=key))
            effects[:] = [e for e in effects if e.kind != "notify"]
            return
        alerts: list[tuple[str, str, str]] = []
        managed = True
        if self.unexplained_since:
            alerts.append(
                (
                    "unexplained_heating",
                    "Hot water: protective heating while OFF",
                    "The element is on although the heater is parked OFF. This is expected to be "
                    "the manufacturer's antibacterial cycle or frost protection. It will not be "
                    "interrupted; automatic commands wait until it ends.",
                )
            )
        if (
            self.state == HEATING_PERMITTED
            and obs.element == "off"
            and obs.element_confidence in {"verified", "high"}
        ):
            self.permitted_off_since = self.permitted_off_since or _iso(now)
            since = _dt(self.permitted_off_since)
            if (
                obs.temperature_c is not None
                and obs.temperature_c <= APPROVED_TARGET_C - cfg.hysteresis_c - 2
                and now - since >= timedelta(minutes=15)
            ):
                alerts.append(
                    (
                        "permitted_not_heating",
                        "Hot water: Manual but not heating",
                        f"Manual 70 °C is confirmed and the reading is {obs.temperature_c} °C, but the "
                        "element has been off for 15 minutes. No command is repeated. Check the heater "
                        "and its power supply.",
                    )
                )
        else:
            self.permitted_off_since = None
        if obs.poll_at is None or (now - obs.poll_at) > timedelta(
            minutes=2 * cfg.poll_interval_minutes + 5
        ):
            alerts.append(
                (
                    "status_stale",
                    "Hot water: heater status missing",
                    "No fresh Thermann status for over an hour. Automatic commands are paused. Check "
                    "the Thermowatt add-on and cloud health.",
                )
            )
        if obs.cloud_health not in (None, "ok") and managed:
            alerts.append(
                (
                    "cloud_fault",
                    "Hot water: Thermann cloud problem",
                    f"Bridge cloud health is {obs.cloud_health}. No commands are sent. Authentication "
                    "locks are never reset automatically; see the add-on documentation.",
                )
            )
        if not desire.planner_ok and managed:
            alerts.append(
                (
                    "planner_unavailable",
                    "Hot water: measurements missing",
                    f"The planner cannot decide ({desire.reason}). The controller holds the current mode.",
                )
            )
        started = _dt(self.guest_started)
        if (
            self.guest_active(now)
            and started is not None
            and now - started >= GUEST_ALERT_AFTER
            and self.state not in {HEATING_PERMITTED, CONFIRMING}
        ):
            detail = ", ".join(self.gate_failures) or self.reason
            alerts.append(
                (
                    "guest_mode_not_applied",
                    "Hot water: guest mode not applied",
                    f"Guest mode wants Manual at 70 °C but the controller could not apply it "
                    f"({detail}). {RECOVERY['guest_mode_not_applied']}",
                )
            )
        if desire.comfort_risk and managed:
            alerts.append(
                (
                    f"comfort_risk_{desire.comfort_risk}",
                    "Hot water: comfort deadline at risk",
                    f"The {desire.comfort_risk} hot-water goal is unlikely to be met.",
                )
            )
        cooldown = timedelta(hours=cfg.notification_cooldown_hours)
        # Condition alerts: notify on onset, then at most once per cooldown while
        # the condition persists; "resolve" when it clears.
        for key, title, message in alerts:
            self.active_alerts.append(key)
            last = _dt(self.alerts.get(key))
            if last is None or now - last >= cooldown:
                self.alerts[key] = _iso(now)
                effects.append(Effect("notify", key=key, title=title, message=message))
        for key in list(self.alerts):
            if key not in self.active_alerts and not key.startswith(EVENT_PREFIXES):
                del self.alerts[key]
                effects.append(Effect("resolve", key=key))
        # Fault/override notices are transition events: emitted once per entry,
        # remembered until normal control is restored, then one "restored" notice.
        for effect in effects:
            if effect.kind == "notify" and effect.key.startswith(EVENT_PREFIXES):
                self.alerts[effect.key] = _iso(now)
        events = [key for key in self.alerts if key.startswith(EVENT_PREFIXES)]
        if self.state in STEADY and self.enabled and not self.fault and events:
            for key in events:
                del self.alerts[key]
                effects.append(Effect("resolve", key=key))
            effects.append(
                Effect(
                    "notify",
                    key="control_restored",
                    title="Hot water: automatic control restored",
                    message=f"The controller is operating normally again ({self.state}).",
                )
            )

    # ------------------------------------------------------------------ display
    def guidance(self) -> str:
        return RECOVERY.get(self.fault or self.reason, "")

    def summary(self, now: datetime) -> dict:
        last = self.history[-1] if self.history else None
        return {
            "state": self.state,
            "reason": self.reason,
            "enabled": self.enabled,
            "hold": self.hold,
            "fault": self.fault,
            "recovery_guidance": self.guidance(),
            "pending_intent": self.intent,
            "last_command": last,
            "commands_last_24h": len(self.commands),
            "requests_last_24h": self.requests_last_24h(now),
            "gate_failures": self.gate_failures,
            "active_alerts": self.active_alerts,
            "desire": self.last_desire,
            "last_confirmed_transition": self.last_transition_at,
            "unexplained_heating_since": self.unexplained_since,
            "operating_mode": self.operating_mode(now),
            "guest_until": self.guest_until,
            "holiday_start": self.holiday_start,
            "holiday_return": self.holiday_return,
            "last_mode_refusal": self.refusal,
        }
