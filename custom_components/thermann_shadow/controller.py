"""Guarded four-state executor. The ONLY code that may request a
Thermann mode change, and only through the bridge's guarded four-state MQTT
payloads (Thermann Hot Water app >= 1.3.14).

Pure logic: no Home Assistant imports, no I/O. ``executor.py`` builds the
observations, persists the returned state BEFORE publishing, and performs the
returned effects. Every rule here errs towards "do nothing and tell the owner".

Heater states (docs/OPERATING_POLICY.md):
  * OFF       Thermann software OFF (the heater keeps its own protections);
  * BASELINE  Manual 45 °C (overnight, and weekends until the comfort window);
  * NORMAL    Manual 62 °C (required weekday storage, weekend window, Override);
  * STORAGE   Manual 70 °C (optional, qualified surplus solar only).
WHICH state is wanted is decided by ``simple_policy`` (one coordinated policy).
This module decides only WHETHER a change may be sent now (commissioning, the
bridge, freshness, budgets, owner control) and supervises its confirmation.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from .solar import PROTECTIVE_REASONS, SPACING, WITHDRAWAL_REASONS

OFF, BASELINE, STORAGE = "off", "baseline", "storage"  # simple_policy states
NORMAL = "normal_storage"
TARGET_C = {BASELINE: 45.0, NORMAL: 62.0, STORAGE: 70.0}
# Bridge 1.3.13 payload: "<target>@<prior>"; the bridge re-checks <prior> on a
# fresh status and refuses anything else (owner changes are never overwritten).
PAYLOAD_TARGET = {OFF: "off", BASELINE: "Manual:45", NORMAL: "Manual:62", STORAGE: "Manual:70"}
PAYLOAD_PRIOR = {OFF: "off", BASELINE: "45", NORMAL: "62", STORAGE: "70"}
PARK_MODE = "Off"
TOPIC_PREFIX, TOPIC_SUFFIX = "P/", "/CMD/MODE"
REFRESH_SUFFIX = "/refresh"
# Status at most this old is used by the bridge without a pre-command read
# (the bridge allows 60 s; up to ~20 s pass before it takes the command).
BRIDGE_FRESH_SECONDS = 30.0

DISABLED = "disabled"
OBSERVING = "observing"
PARKED = "parked"  # confirmed OFF
BASELINE_ACTIVE = "baseline_45"  # confirmed Manual 45
STORAGE_ACTIVE = "storage_70"  # confirmed Manual 70
NORMAL_ACTIVE = "normal_storage_62"
CHANGE_REQUESTED = "change_requested"  # policy wants another state; a gate blocks it
CONFIRMING = "confirming"  # one command published; waiting for observed status
OWNER_OVERRIDE = "owner_override"
FAULT_LOCKED = "fault_locked"
STATES = (
    DISABLED,
    OBSERVING,
    PARKED,
    BASELINE_ACTIVE,
    STORAGE_ACTIVE,
    NORMAL_ACTIVE,
    CHANGE_REQUESTED,
    CONFIRMING,
    OWNER_OVERRIDE,
    FAULT_LOCKED,
)
STEADY = {PARKED, BASELINE_ACTIVE, NORMAL_ACTIVE, STORAGE_ACTIVE, CHANGE_REQUESTED}
STATE_OF = {PARKED: OFF, BASELINE_ACTIVE: BASELINE, NORMAL_ACTIVE: NORMAL, STORAGE_ACTIVE: STORAGE}
ACTIVE_OF = {value: key for key, value in STATE_OF.items()}
EVENT_PREFIXES = ("fault_", "override_")

FAILURE_PREFIXES = ("dropped_", "refused_", "rejected_")
# Strict allowlist of transient (non-auth, non-quota) bridge read failures that
# prove no heater POST was attempted before entering cloud backoff.
TRANSIENT_REFRESH_ERRORS = frozenset(
    {
        "cloud_success_false",
        "cloud_timeout",
        "cloud_connection_error",
        "cloud_network_error",
        "cloud_invalid_json",
        "cloud_envelope_not_object",
        "cloud_error_nonempty",
        "cloud_result_missing",
        "cloud_result_wrong_type",
        "cloud_backoff",
        "cloud_http_500",
        "cloud_http_502",
        "cloud_http_503",
        "cloud_http_504",
    }
)
# The bridge's FRESH status showed something other than the stated prior state
# (the owner changed it since the last poll): owner control, not a fault.
OWNER_CHANGE_RESULTS = {
    "refused_target_mismatch",
    "refused_mode_mismatch",
    "already_in_requested_state",
}
BRIDGE_IN_PROGRESS_RESULTS = {
    "refreshing_status",
    "submitting",
    "submitted_awaiting_status",
    "awaiting_confirmation",
}
# 0.9.1 (audit C1). OPTIONAL commands start heating that is not needed for hot
# water: a peak-solar start and a weekend/night solar start. They stop at the
# configured daily limit. Every other non-OFF command is ESSENTIAL (the weekday
# normal storage heat, the baseline, the 12hr Override62): optional activity
# can never use up its budget. Essential commands have their own higher cap, so
# a fault that loops is still stopped. OFF is never held back.
OPTIONAL_REASONS = frozenset(
    {
        "peak_solar_qualified",
        "solar_opportunity",
        "weekday_solar_boost",
        "weekday_direct_solar_boost",
    }
)
ESSENTIAL_EXTRA_COMMANDS = 6
COMMAND_WINDOW = timedelta(hours=24)
# Reserve pre-read/POST/two confirmations/possible refresh for two essential
# transitions. This local estimate never grants additional vendor quota.
OPTIONAL_EXIT_REQUEST_RESERVE = 10
# Must match the policy: only justified protective peak OFF bypasses spacing.
SPACING_EXEMPT_REASONS = PROTECTIVE_REASONS
FORECAST_ALERT_AFTER = timedelta(minutes=60)
BRIDGE_NOT_CONFIRMED = "not_confirmed_within_limit"
BRIDGE_UNEXPECTED_STATE = "unexpected_state_after_command"


def bridge_failure(result: object) -> bool:
    return isinstance(result, str) and result.startswith(FAILURE_PREFIXES)


def payload_for(target: str, prior: str) -> str:
    return f"{PAYLOAD_TARGET[target]}@{PAYLOAD_PRIOR[prior]}"


def heater_state(mode: str | None, target_c: float | None) -> str | None:
    """The policy state the heater is observably in, or None (anything else:
    Schedule, Eco, Holiday, Unknown, or Manual at another target)."""
    if mode == PARK_MODE:
        return OFF
    if mode == "Manual" and target_c is not None:
        for state, value in TARGET_C.items():
            if target_c == value:
                return state
    return None


RECOVERY = {
    "command_not_confirmed": "The bridge sent the command once but no status within its confirmation window (about 6 minutes) showed the requested mode. It was not repeated. Check the Thermann app: if it shows the requested mode, the cloud is slow to report it; otherwise the command did not take effect. Set the mode you want in the app, then press Acknowledge fault; automatic control re-inspects the heater first.",
    "command_not_applied": "The heater did not report the requested mode after the MQTT command was published (it may not have been sent or applied). Check the Thermann Hot Water app diagnostics and the Thermann app, set the mode you want if needed, then press Acknowledge fault; automatic control re-inspects the heater before doing anything.",
    "confirmation_timeout": "No status arrived to confirm the last command. Check the Thermann Hot Water app log and cloud health, then the Thermann app. Press Acknowledge fault when the heater state is known.",
    "bridge_refused_or_dropped": "The bridge did not send the command (see last command result). Nothing was changed on the heater. Fix the cause, then Acknowledge fault.",
    "publish_failed": "Home Assistant could not publish the MQTT command. Nothing is known to have reached the heater. Check MQTT, then Acknowledge fault.",
    "intent_unresolved_after_restart": "Home Assistant restarted while a command was unconfirmed and no later status resolved it. Check the Thermann app, then Acknowledge fault.",
    "unexpected_mode_during_confirmation": "The heater reported a mode that was neither the previous nor the requested one. Check the Thermann app. Resume automatic control when you are satisfied.",
    "mode_or_target_changed_outside_controller": "The Thermann mode or target changed without a controller command (for example in the app). Automatic control stays paused until you press Resume automatic control.",
    "unexpected_mode_or_target": "The heater is not OFF or a supported Manual 45/62/70 °C target (for example it is in Schedule, Eco or another Manual target). Automatic control will not touch it. To return to the agreed operating policy, select in the Thermann app the state the policy wants now (Manual 45 °C overnight, Manual 62 °C in the weekday daytime or the weekend comfort window, OFF during a peak; if unsure, any of these is safe because the controller then applies the policy), then press Resume automatic control.",
    "owner_hold": "You placed the heater on hold. Automatic control sends nothing until you press Resume automatic control.",
    "guest_mode_not_applied": "The 12hr Override wants Manual at 62 °C but the controller could not apply it (see the reason and gate failures). Check the Thermann Hot Water app and the Thermann app; you can select the intended temperature in the app yourself.",
}
HOBART = ZoneInfo("Australia/Hobart")
GUEST_HOURS = 12.0
GUEST_ALERT_AFTER = timedelta(minutes=10)
HOLIDAY_MAX_DAYS = 60


@dataclass(frozen=True)
class ControllerConfig:
    command_topic: str = ""
    # Daily limit for OPTIONAL solar starts; essential commands may go
    # ESSENTIAL_EXTRA_COMMANDS beyond it; a park (OFF) is never held back.
    max_commands_per_day: int = 8
    tariff_verified: bool = True
    # Supervised OFF/45/62/70 qualification (bridge 1.3.14+); required for every command.
    four_state_qualified: bool = False
    command_spacing_minutes: float = SPACING.total_seconds() / 60
    element_kw: float = 3.0  # exposure estimate only, never electrical evidence
    solar_cooldown_minutes: float = 10.0
    confirmation_timeout_minutes: float = 65.0
    max_requests_per_day: int = 220
    poll_interval_minutes: float = 30.0
    notification_cooldown_hours: float = 6.0
    expected_command_topic: str | None = None

    def missing_commissioning(self) -> list[str]:
        missing = []
        if not valid_topic(self.command_topic):
            missing.append("command_topic_not_configured")
        elif self.expected_command_topic and self.command_topic != self.expected_command_topic:
            missing.append("command_topic_does_not_match_heater")
        if not self.four_state_qualified:
            missing.append("four_state_commands_not_qualified")
        if not self.tariff_verified:
            missing.append("tariff_contract_not_verified")
        return missing


HEATER_UNIQUE_ID = re.compile(r"^thermowatt_([A-Za-z0-9]{4,40})_v314$")


def expected_command_topic(unique_id: object) -> str | None:
    """The bridge's mode command topic for a heater entity unique ID
    (``thermowatt_<serial>_v314`` -> ``P/<serial>/CMD/MODE``)."""
    if not isinstance(unique_id, str):
        return None
    match = HEATER_UNIQUE_ID.match(unique_id)
    return f"P/{match.group(1)}/CMD/MODE" if match else None


def valid_topic(topic: object) -> bool:
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return False
    if not topic.endswith(TOPIC_SUFFIX):
        return False
    serial = topic[len(TOPIC_PREFIX) : -len(TOPIC_SUFFIX)]
    return 1 <= len(serial) <= 64 and serial.isalnum()


def refresh_topic(command_topic: str) -> str | None:
    """The bridge's guarded on-demand status topic for the same heater."""
    if not valid_topic(command_topic):
        return None
    return command_topic[: -len(TOPIC_SUFFIX)] + REFRESH_SUFFIX


@dataclass
class Observation:
    """One snapshot of what Home Assistant currently knows. Never assumed."""

    now: datetime
    poll_at: datetime | None = None  # bridge last_successful_poll
    heater_meter_mapped: bool = False
    heater_meter_quality: str | None = None
    mode: str | None = None  # vendor mode: Manual/Schedule/Eco/Off/Holiday/Unknown
    target_c: float | None = None
    temperature_c: float | None = None
    element: str = "unknown"  # on/off/unknown (local meter estimate)
    element_confidence: str = "none"
    cloud_health: str | None = None
    auth_mode: str | None = None
    consecutive_failures: int | None = None
    cooldown_seconds: int | None = None
    bridge_available: bool = False
    bridge_commands_enabled: bool | None = None
    last_command: dict | None = None
    bridge_refresh_limit: int | None = None
    bridge_refreshes_24h: int | None = None
    bridge_confirmation_pending: bool | None = None
    bridge_command_policy: str | None = None
    bridge_transitions: list | None = None  # 1.3.13 diagnostics
    requests_total: int | None = None
    morning_availability: str | None = None  # legacy diagnostic key
    low_water_assessment: dict | None = None
    mqtt_ready: bool = False
    forecast_available: bool | None = None  # published forecast usable now (None: unknown)
    passive_status_deadline: datetime | None = (
        None  # validated quiet lease; never command authority
    )

    @property
    def heater_state(self) -> str | None:
        return heater_state(self.mode, self.target_c)


@dataclass
class Want:
    """What the policy wants now (from ``simple_policy.Decision``)."""

    state: str  # OFF / BASELINE / STORAGE, or "hold"
    reason: str
    layer: int = 5
    plan: dict = field(default_factory=dict)


@dataclass
class Intent:
    id: str
    target: str  # OFF / BASELINE / STORAGE
    prior: str
    payload: str
    topic: str
    created_at: str
    prior_mode: str | None
    poll_at: str | None
    requests_before: int | None
    reason: str = ""
    status: str = "published"
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


def hobart_midnight(day: date | datetime, zone: str = "Australia/Hobart") -> datetime:
    """Holiday dates take effect at 00:00 Hobart local: a departure of 10
    November starts Holiday mode at 00:00 on 10 November (so today's date
    starts it at once), and a return of 14 November ends it at 00:00 on 14
    November. A datetime is reduced to its Hobart date."""
    if isinstance(day, datetime):
        day = day.astimezone(ZoneInfo(zone)).date()
    return datetime.combine(day, time(0), ZoneInfo(zone))


@dataclass
class Controller:
    time_zone: str = "Australia/Hobart"
    enabled: bool = False
    hold: bool = False
    state: str = DISABLED
    reason: str = "automatic_control_disabled"
    heater: str | None = None  # confirmed policy state while steady
    intent: dict | None = None  # Intent as dict (persisted)
    history: list = field(default_factory=list)  # last 20 resolved intents
    commands: list = field(default_factory=list)  # ISO times of published commands (24 h)
    request_samples: list = field(default_factory=list)  # [ISO poll time, total]
    request_counter_last: int | None = None
    request_counter_offset: int = 0
    last_poll_seen: str | None = None
    last_transition_at: str | None = None
    inspect_after: str | None = None  # a NEW poll after this time is required to act
    fault: str | None = None
    alerts: dict = field(default_factory=dict)
    alert_cooldowns: dict = field(default_factory=dict)
    active_alerts: list = field(default_factory=list)
    last_want: dict | None = None
    gate_failures: list = field(default_factory=list)
    storage_idle_since: str | None = None
    guest_started: str | None = None
    guest_until: str | None = None
    guest_target_c: int = 62  # active pre-0.16 overrides retain their original target
    weekend_heat_date: str | None = None
    weekend_end_date: str | None = None
    holiday_start: str | None = None
    holiday_return: str | None = None
    refusal: str | None = None
    forecast_missing_since: str | None = None
    heater_meter_missing_since: str | None = None
    last_observed_heater: str | None = None
    parked_off_restore_since: str | None = None
    protective_exit: dict | None = None
    optional_cooldown_until: str | None = None
    solar_session_active: bool = False

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Controller:
        """Loads 0.9.0 state; 0.8.x and older state keeps only what still means
        the same thing, and an old pending intent is reconciled, never re-sent."""
        if not isinstance(data, dict):
            return cls()
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        controller = cls(**known)
        if data.get("guest_until") and "guest_target_c" not in data:
            controller.guest_target_c = 70  # preserve an active legacy instruction/expiry
        if controller.guest_target_c not in (62, 70):
            controller.guest_target_c = 62
        if controller.state not in STATES:
            controller.state = OBSERVING
        # 0.7-0.8 stored dates AND times; 0.9.0 keeps each Hobart date (00:00).
        for key in ("holiday_start", "holiday_return"):
            value = getattr(controller, key)
            if value and "time_zone" not in data:
                setattr(
                    controller,
                    key,
                    _iso(hobart_midnight(datetime.fromisoformat(value), controller.time_zone)),
                )
        intent = controller.intent
        if intent is not None and (not isinstance(intent, dict) or "target" not in intent):
            # A 0.8.x permit/park intent: its outcome is decided by the next
            # status (re-inspection), never by re-sending anything.
            controller.history = (controller.history + [dict(intent or {})])[-20:]
            controller.intent = None
            if controller.state == CONFIRMING:
                controller.state = OBSERVING
        return controller

    def restored(self, now: datetime) -> None:
        """After an HA restart: never assume the heater is in the last REQUESTED
        state. Re-inspect from a NEW status; an unresolved intent is reconciled
        from observed status only and is never re-sent."""
        self.solar_session_active = False  # local qualification history was interrupted
        if (seen := _dt(self.last_poll_seen)) is not None and seen > now:
            self.last_poll_seen = None
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
            self.solar_session_active = False
            if self.state != CONFIRMING:
                self.state, self.reason = DISABLED, "automatic_control_disabled"
            return
        if self.state in {DISABLED, *STEADY}:
            self.state, self.reason = OBSERVING, "enabled_inspecting_heater"
            self.inspect_after = _iso(now)

    def set_hold(self, now: datetime) -> None:
        self.hold = True
        self.solar_session_active = False
        if self.state != CONFIRMING:
            self.state, self.reason = OWNER_OVERRIDE, "owner_hold"

    def resume(self, now: datetime) -> bool:
        if self.state not in {OWNER_OVERRIDE, OBSERVING}:
            return False
        self.hold = False
        self.state = OBSERVING if self.enabled else DISABLED
        self.reason = "resumed_inspecting_heater"
        self.inspect_after = _iso(now)
        return True

    def acknowledge(self, now: datetime) -> bool:
        if self.state != FAULT_LOCKED:
            return False
        self.fault = None
        self.state = OBSERVING if self.enabled else DISABLED
        self.reason = "fault_acknowledged_inspecting_heater"
        self.inspect_after = _iso(now)
        return True

    # ------------------------------------------------------------------ owner modes
    def guest_active(self, now: datetime) -> bool:
        until = _dt(self.guest_until)
        return until is not None and now < until

    def holiday_active(self, now: datetime) -> bool:
        start, back = _dt(self.holiday_start), _dt(self.holiday_return)
        return start is not None and back is not None and start <= now < back

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
        """Owner: Manual 62 °C for ``hours`` (the 12hr Override). An explicit
        owner instruction, so it also releases Hold (the heater is re-inspected
        first; an app-selected other mode still pauses control)."""
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
        self.guest_target_c = 62
        # The owner's explicit Override supersedes a pending solar protective
        # exit (audit M1, 20 Nov 2026). Otherwise it stayed latched for 12 h:
        # a false "protective OFF unconfirmed" alert, phantom exposure, and an
        # OFF instead of the policy's state when the Override expired. If the
        # Override ends or is cancelled inside a peak, the policy requests the
        # peak OFF again and the exit re-latches from the observed state.
        self.protective_exit = None
        self.solar_session_active = False
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
        # 0.9.1 (audit M1): a steady controller knows the heater state (every
        # status is checked against it), so the policy resumes at once. Waiting
        # for a new poll left Manual 70 °C on peak grid for up to 30 minutes.
        if self.enabled and self.state not in {FAULT_LOCKED, OWNER_OVERRIDE, *STEADY}:
            self._reinspect(now, reason)
        return True

    def holiday_start_date(self) -> date | None:
        start = _dt(self.holiday_start)
        return start.astimezone(ZoneInfo(self.time_zone)).date() if start else None

    def holiday_return_date(self) -> date | None:
        back = _dt(self.holiday_return)
        return back.astimezone(ZoneInfo(self.time_zone)).date() if back else None

    def set_holiday(
        self, now: datetime, start: date | datetime | None, back: date | datetime | None
    ) -> bool:
        """Owner: away from the departure DATE ``start`` until the return DATE
        ``back``. Both take effect at 00:00 Hobart local, so a departure of
        today starts Holiday mode at once. Validated, never silently
        adjusted; a refusal leaves the previous dates unchanged."""
        if start is not None:
            start = hobart_midnight(start, self.time_zone)
        if back is not None:
            back = hobart_midnight(back, self.time_zone)
        if back is not None and back <= now:
            self.refusal = "return_must_be_in_the_future"
            return False
        if start is not None and back is not None:
            if back <= start:
                self.refusal = "return_must_be_after_departure"
                return False
            if back - start > timedelta(days=HOLIDAY_MAX_DAYS):
                self.refusal = "holiday_longer_than_60_days"
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
            self.holiday_start = self.holiday_return = None

    # ------------------------------------------------------------------ main step
    def last_command_at(self) -> datetime | None:
        return _dt(self.commands[-1]) if self.commands else None

    def commands_in_window(self, now: datetime) -> int:
        """Commands in the rolling half-open window (now - 24 h, now].

        Peak boundaries recur at the same clock time daily, so yesterday's
        boundary command must expire at today's boundary decision rather than
        one tick later (0.16.2). The policy and the gate use this same count.
        """
        return sum(1 for item in self.commands if now - _dt(item) < COMMAND_WINDOW)

    def step(self, obs: Observation, want: Want, cfg: ControllerConfig) -> list[Effect]:
        now = obs.now
        effects: list[Effect] = []
        new_poll = self._ingest_poll(obs)
        # A genuine uncontrolled mode/target invalidates older OFF evidence.
        # Unavailable entities have no mode and retain the last observation.
        if new_poll and obs.mode is not None:
            self.last_observed_heater = obs.heater_state
        self.last_want = {
            "state": want.state,
            "reason": want.reason,
            "layer": want.layer,
            "best_start": _iso(want.plan.get("best_start")),
            "latest_start": _iso(want.plan.get("latest_start")),
            "soft_target": _iso(want.plan.get("soft_target")),
        }
        self.commands = [item for item in self.commands if now - _dt(item) < COMMAND_WINDOW]
        self.active_alerts = []
        self._expire_modes(now)

        # A required-storage hold outside peak is no longer an optional solar
        # session. Do not carry an old morning permission into a later peak.
        if (
            self.intent is None
            and want.plan.get("mode") != "peak"
            and want.reason
            not in (
                OPTIONAL_REASONS | {"solar_opportunity_continues", "weekday_solar_boost_continues"}
            )
        ):
            self.solar_session_active = False

        # Preserve the exit independently of the original transaction. Sun
        # returning must not erase a withdrawal while START is unconfirmed.
        if (
            self.enabled
            and not self.hold
            and not self.guest_active(now)
            and self.state != OWNER_OVERRIDE
            and want.state == OFF
            and want.reason in PROTECTIVE_REASONS
            and (self.heater in (NORMAL, STORAGE) or self.intent)
        ):
            if self.protective_exit is None:
                self.protective_exit = {"since": _iso(now), "reason": want.reason}
            price = want.plan.get("current_import_price_aud")
            if isinstance(price, (int, float)) and 0 <= price <= 10:
                self.protective_exit["price_aud_per_kwh"] = max(
                    price, self.protective_exit.get("price_aud_per_kwh", 0)
                )

        if self.state == CONFIRMING and self.intent:
            self._confirm(obs, cfg, new_poll, effects)
        if (
            self.protective_exit
            and obs.heater_state == OFF
            and obs.poll_at is not None
            and obs.poll_at <= now
            and obs.poll_at >= _dt(self.protective_exit["since"])
            and obs.bridge_confirmation_pending is False
            and obs.bridge_available
            and obs.cloud_health == "ok"
            and obs.auth_mode == "authorized"
            and self.intent is None
        ):
            self.protective_exit = None
            self.optional_cooldown_until = _iso(now + timedelta(minutes=cfg.solar_cooldown_minutes))
            self.solar_session_active = False
        if self.state == CONFIRMING:
            self._supervise_alerts(obs, want, cfg, effects)
            return effects
        if not self.enabled:
            self.state, self.reason, self.heater = DISABLED, "automatic_control_disabled", None
            self._supervise_alerts(obs, want, cfg, effects)
            return effects
        if self.hold and self.state != FAULT_LOCKED:
            self.state, self.reason = OWNER_OVERRIDE, "owner_hold"
        if self.state in {FAULT_LOCKED, OWNER_OVERRIDE}:
            self._supervise_alerts(obs, want, cfg, effects)
            return effects

        fresh = self._fresh_after_inspection(obs)
        if self.state == OBSERVING:
            if not fresh:
                self.reason = "waiting_for_new_heater_status"
                self._supervise_alerts(obs, want, cfg, effects)
                return effects
            self._classify(obs, effects)
            if self.state not in STEADY:
                self._supervise_alerts(obs, want, cfg, effects)
                return effects
        elif fresh and obs.mode is not None:
            self._check_external_change(obs, effects)
            if self.state not in STEADY:
                self._supervise_alerts(obs, want, cfg, effects)
                return effects

        if self.protective_exit and not self.guest_active(now):
            want = Want(OFF, self.protective_exit["reason"], 4, want.plan)
        self._decide(obs, want, cfg, effects)
        self._supervise_alerts(obs, want, cfg, effects)
        return effects

    # ------------------------------------------------------------------ helpers
    def _ingest_poll(self, obs: Observation) -> bool:
        # Diagnostics may arrive without a new temperature/status poll. Keep
        # command and refresh usage visible too, including bridge counter reset.
        if obs.requests_total is not None and obs.requests_total >= 0:
            previous = self.request_counter_last
            if previous is None and self.request_samples:
                # 0.14.0 stored raw counters only. Its final sample is also the
                # reset anchor on the first upgrade observation.
                previous = max(0, self.request_samples[-1][1] - self.request_counter_offset)
            if previous is not None and obs.requests_total < previous:
                self.request_counter_offset += previous
            self.request_counter_last = obs.requests_total
            total = self.request_counter_offset + obs.requests_total
            samples = [
                s for s in self.request_samples if obs.now - _dt(s[0]) <= timedelta(hours=25)
            ]
            if not samples or total != samples[-1][1]:
                samples.append([_iso(obs.now), total])
            self.request_samples = samples[-4096:]
        if obs.poll_at is None or obs.poll_at > obs.now:
            return False
        seen = _dt(self.last_poll_seen)
        if seen is not None and obs.poll_at <= seen:
            return False
        self.last_poll_seen = _iso(obs.poll_at)
        return True

    def requests_last_24h(self, now: datetime) -> int | None:
        cutoff = now - timedelta(hours=24)
        # Include the last boundary anchor; dropping it hides the first delta.
        before = [s for s in self.request_samples if _dt(s[0]) <= cutoff]
        window = ([before[-1]] if before else []) + [
            s for s in self.request_samples if cutoff < _dt(s[0]) <= now
        ]
        if len(window) < 2:
            return 0 if window else None
        used = window[-1][1] - window[0][1]
        return used if used >= 0 else None

    def _fresh_after_inspection(self, obs: Observation) -> bool:
        after = _dt(self.inspect_after)
        if obs.poll_at is None or obs.poll_at > obs.now:
            return False
        return after is None or obs.poll_at > after

    def _settle(self, state: str, reason: str) -> None:
        self.heater = state
        self.state, self.reason = ACTIVE_OF[state], reason

    def _classify(self, obs: Observation, effects: list[Effect]) -> None:
        self.inspect_after = None
        observed = obs.heater_state
        if observed is None:
            self._override("unexpected_mode_or_target", obs, effects)
            return
        self._settle(observed, f"inspected_{observed}")

    def _check_external_change(self, obs: Observation, effects: list[Effect]) -> None:
        if obs.heater_state != self.heater:
            self._override("mode_or_target_changed_outside_controller", obs, effects)

    def _override(self, reason: str, obs: Observation, effects: list[Effect]) -> None:
        self.solar_session_active = False
        self.state, self.reason, self.heater = OWNER_OVERRIDE, reason, None
        effects.append(
            Effect(
                "notify",
                key=f"override_{reason}",
                title="Hot water: automatic control paused",
                message=f"Observed mode {obs.mode}, target {obs.target_c} °C. {RECOVERY[reason]}",
            )
        )

    def _lock(self, reason: str, detail: str, effects: list[Effect]) -> None:
        self.solar_session_active = False
        self.state, self.reason, self.fault, self.heater = FAULT_LOCKED, reason, reason, None
        effects.append(
            Effect(
                "notify",
                key=f"fault_{reason}",
                title="Hot water: controller fault — automatic control locked",
                message=f"{detail} {RECOVERY[reason]}",
            )
        )

    @staticmethod
    def _transient_backoff_refusal(obs: Observation, last: dict) -> bool:
        """True only when the bridge explicitly proves no POST was attempted due
        to a transient (non-auth, non-quota) cloud backoff or pre-command read failure."""
        if (
            obs.bridge_confirmation_pending is not False
            or obs.auth_mode != "authorized"
            or obs.cloud_health in {"auth_locked", "quota_limited"}
        ):
            return False
        result = last.get("result")
        if result == "refused_cloud_backoff":
            return True
        if result == "refused_status_refresh_failed":
            return last.get("error") in TRANSIENT_REFRESH_ERRORS
        return False

    def _confirm(
        self, obs: Observation, cfg: ControllerConfig, new_poll: bool, effects: list[Effect]
    ) -> None:
        intent = self.intent or {}
        published = _dt(intent.get("created_at"))
        target = intent["target"]
        last = obs.last_command or {}
        result, result_at = last.get("result"), _dt(last.get("at"))
        bridge_fresh = (
            result_at is not None
            and published is not None
            and result_at >= published - timedelta(seconds=5)
            and result_at <= obs.now
            and last.get("payload") == intent.get("payload")
        )
        if bridge_fresh:
            intent["bridge_result"] = result
        if bridge_fresh and result in OWNER_CHANGE_RESULTS:
            # The bridge's fresh status was not the stated prior state: the
            # owner changed the heater since the last poll. Nothing was written.
            self._resolve("external_change", obs)
            self._override("mode_or_target_changed_outside_controller", obs, effects)
            return
        if bridge_fresh and result == BRIDGE_UNEXPECTED_STATE:
            self._resolve("ambiguous", obs)
            self._override("unexpected_mode_during_confirmation", obs, effects)
            return
        if bridge_fresh and result == BRIDGE_NOT_CONFIRMED:
            self._resolve("not_confirmed", obs)
            self._lock(
                "command_not_confirmed",
                f"{intent['payload']} was sent once; the heater still reported "
                f"{last.get('observed_mode') or obs.mode}.",
                effects,
            )
            return
        if bridge_fresh and bridge_failure(result):
            if self._transient_backoff_refusal(obs, last):
                restored = self.reason == "reconciling_command_after_restart"
                self._resolve("deferred_cloud_backoff", obs)
                if restored or self.heater is None:
                    self.state = OBSERVING if self.enabled else DISABLED
                    self.reason = "deferred_cloud_backoff_reinspecting"
                    self.inspect_after = _iso(obs.now)
                else:
                    self.state = CHANGE_REQUESTED
                    self.reason = "deferred_cloud_backoff"
                    self.gate_failures = ["bridge_in_backoff"]
                return
            self._resolve("not_applied", obs)
            self._lock(
                "bridge_refused_or_dropped",
                f"Last command ({intent['payload']}) result: {result}.",
                effects,
            )
            return
        after_publish = (
            obs.mode is not None
            and obs.poll_at is not None
            and published is not None
            and obs.poll_at > published
            and obs.poll_at <= obs.now
        )
        in_progress = bridge_fresh and result in BRIDGE_IN_PROGRESS_RESULTS
        conclusive = after_publish and not in_progress
        observed = obs.heater_state
        if conclusive and observed == target:
            if intent.get("reason") in WITHDRAWAL_REASONS:
                self.optional_cooldown_until = _iso(
                    obs.now + timedelta(minutes=cfg.solar_cooldown_minutes)
                )
            self.solar_session_active = (
                self.enabled
                and not self.hold
                and target != OFF
                and intent.get("reason") in OPTIONAL_REASONS
            )
            self._resolve("confirmed", obs)
            self._settle(target, f"{target}_confirmed")
            self.last_transition_at = _iso(obs.poll_at)
            return
        if conclusive and observed != intent.get("prior"):
            self._resolve("ambiguous", obs)
            self._override("unexpected_mode_during_confirmation", obs, effects)
            return
        late_poll = conclusive and obs.poll_at - published >= timedelta(minutes=7)
        if late_poll and observed == intent.get("prior"):
            # The bridge's window (6 min) has passed and a later poll still shows
            # the prior state.
            self._resolve("not_applied", obs)
            self._lock(
                "command_not_applied",
                f"{intent['payload']} was published to MQTT, but a later status poll still "
                f"reports {obs.mode} (the bridge did not confirm sending or applying it).",
                effects,
            )
            return
        if published and obs.now - published > timedelta(minutes=cfg.confirmation_timeout_minutes):
            restored = self.reason == "reconciling_command_after_restart"
            self._resolve("timeout", obs)
            self._lock(
                "intent_unresolved_after_restart" if restored else "confirmation_timeout",
                f"{intent['payload']} published at {intent['created_at']} was never confirmed.",
                effects,
            )
            return
        if self.reason != "reconciling_command_after_restart":
            self.reason = f"confirming_{target}"

    def _resolve(self, status: str, obs: Observation) -> None:
        intent = dict(self.intent or {})
        intent.update(status=status, resolved_at=_iso(obs.now), observed=obs.mode)
        self.history = (self.history + [intent])[-20:]
        self.intent = None

    def gates(
        self,
        obs: Observation,
        target: str,
        cfg: ControllerConfig,
        payload: str = "",
        reason: str = "",
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
        if obs.bridge_command_policy != "automation":
            failures.append("bridge_policy_not_automation")
        if obs.cloud_health != "ok":
            failures.append(f"cloud_health_{obs.cloud_health or 'unknown'}")
        if obs.auth_mode != "authorized":
            failures.append("bridge_auth_not_authorized")
        if obs.consecutive_failures not in (0, None) or (obs.cooldown_seconds or 0) > 0:
            failures.append("bridge_in_backoff")
        if not isinstance(obs.bridge_transitions, list) or payload not in obs.bridge_transitions:
            failures.append("bridge_1_3_13_required")
        if obs.bridge_confirmation_pending:
            failures.append("bridge_confirmation_pending")
        elif obs.bridge_confirmation_pending is not False:
            failures.append("bridge_confirmation_state_unknown")
        if obs.poll_at is None:
            failures.append("no_heater_status")
        else:
            age = (now - obs.poll_at).total_seconds()
            if age < 0:
                failures.append("heater_status_in_future")
            elif age > (cfg.poll_interval_minutes + 5) * 60:
                failures.append("heater_status_too_old")
            elif (
                age > BRIDGE_FRESH_SECONDS
                and obs.bridge_refresh_limit is not None
                and (obs.bridge_refreshes_24h or 0) >= obs.bridge_refresh_limit
            ):
                failures.append("bridge_refresh_budget_exhausted")
        if obs.heater_state != self.heater:
            failures.append("heater_not_in_confirmed_state")
        last = self.last_command_at()
        spacing_exempt = target == OFF and reason in SPACING_EXEMPT_REASONS
        if (
            not spacing_exempt
            and last is not None
            and now - last < timedelta(minutes=cfg.command_spacing_minutes)
        ):
            # The policy applies the same rule; this is the backstop.
            failures.append("command_spacing")
        if target != OFF:
            # A park (OFF) is never held back by either limit.
            sent = len(self.commands)
            if reason in OPTIONAL_REASONS:
                if sent >= cfg.max_commands_per_day:
                    failures.append("daily_command_limit_reached")
            elif sent >= cfg.max_commands_per_day + ESSENTIAL_EXTRA_COMMANDS:
                failures.append("daily_essential_command_limit_reached")
        used = self.requests_last_24h(now)
        if used is None:
            failures.append("request_accounting_unavailable")
        elif used >= cfg.max_requests_per_day and target != OFF:
            failures.append("daily_cloud_request_budget_reached")
        elif (
            used is not None
            and reason in OPTIONAL_REASONS
            and target != OFF
            and used + OPTIONAL_EXIT_REQUEST_RESERVE > cfg.max_requests_per_day
        ):
            failures.append("optional_exit_request_reserve")
        if target != OFF and reason in OPTIONAL_REASONS:
            if self.protective_exit:
                failures.append("protective_exit_unresolved")
            until = _dt(self.optional_cooldown_until)
            if until is not None and now < until:
                failures.append("solar_withdrawal_cooldown")
        return failures

    def solar_adoption_ready(self, obs: Observation, cfg: ControllerConfig) -> bool:
        """No command: recent exact observed state and capacity to protectively exit."""
        current = self.heater
        return bool(
            self.enabled
            and self.state in STEADY
            and current in (NORMAL, STORAGE)
            and not self.hold
            and not self.fault
            and not self.intent
            and not self.protective_exit
            and obs.poll_at is not None
            and 0 <= (obs.now - obs.poll_at).total_seconds() <= BRIDGE_FRESH_SECONDS
            and obs.heater_state == current
            and not self.gates(obs, OFF, cfg, payload_for(OFF, current), "peak_lockout")
        )

    def _decide(
        self, obs: Observation, want: Want, cfg: ControllerConfig, effects: list[Effect]
    ) -> None:
        current = self.heater
        if (
            want.state == current
            and want.plan.get("adopt_solar_session") is True
            and self.solar_adoption_ready(obs, cfg)
        ):
            # Permission to continue an already observed target, not a heater
            # command or a new command confirmation. Restart clears permission.
            self.solar_session_active = True
        if want.state == "hold" or want.state == current or current is None:
            self.state = ACTIVE_OF[current] if current else OBSERVING
            self.reason = want.reason
            self.gate_failures = []
            return
        payload = payload_for(want.state, current)
        failures = self.gates(obs, want.state, cfg, payload, want.reason)
        self.gate_failures = failures
        if failures:
            self.state, self.reason = CHANGE_REQUESTED, failures[0]
            return
        intent = Intent(
            id=uuid.uuid4().hex,
            target=want.state,
            prior=current,
            payload=payload,
            topic=cfg.command_topic,
            created_at=_iso(obs.now),
            prior_mode=obs.mode,
            poll_at=_iso(obs.poll_at),
            requests_before=obs.requests_total,
            reason=want.reason,
        )
        self.intent = asdict(intent)
        self.commands.append(_iso(obs.now))
        self.state, self.reason = CONFIRMING, f"confirming_{want.state}"
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
        self, obs: Observation, want: Want, cfg: ControllerConfig, effects: list[Effect]
    ) -> None:
        now = obs.now
        if not self.enabled:
            self.parked_off_restore_since = None
            for key in list(self.alerts):
                del self.alerts[key]
                effects.append(Effect("resolve", key=key))
            self.alert_cooldowns.clear()
            effects[:] = [e for e in effects if e.kind != "notify"]
            return
        alerts: list[tuple[str, str, str]] = []
        water = obs.low_water_assessment or {}
        if water.get("state") == "low" and not self.holiday_active(now):
            alerts.append(
                (
                    "pre_peak_low_hot_water",
                    "Hot water may be running low",
                    f"The bottom tank sensor is reading {water['reading_c']:g}°C before the evening peak "
                    f"(observed {water['observed_at']}). There may be less hot water available than usual. "
                    "This does not measure every litre in the tank or automatically authorise peak heating. "
                    "Check the selected mode and cloud status; use the owner override if you want normal comfort storage.",
                )
            )
        if self.protective_exit:
            alerts.append(
                (
                    "protective_exit_unresolved",
                    "Hot water: protective OFF is not confirmed",
                    "Solar permission was withdrawn at "
                    + self.protective_exit["since"]
                    + ". A previous command or command safeguard is blocking confirmed OFF. "
                    "Electrical consumption remains unknown without a verified circuit meter. "
                    "Check the controller fault/gates and the Thermann app; use the documented "
                    "manual recovery if remote control cannot complete. No command is replayed.",
                )
            )
        # Last OBSERVED software state is retained through unavailable entities
        # and restart. This is a reliability warning, never an element-state
        # assertion or permission to bypass peak/owner/confirmation guards.
        needs_restore = (
            self.last_observed_heater == OFF
            and (
                want.state in TARGET_C
                or (
                    want.state == "hold"
                    and want.reason in {"command_spacing", "cloud_or_freshness_gate"}
                    and want.plan.get("wanted") in TARGET_C
                )
                or (
                    self.heater is None
                    and want.state == "hold"
                    and want.reason == "heater_state_not_controlled"
                    and want.plan.get("unconfirmed_restore_target_c") in TARGET_C.values()
                )
            )
            and not self.hold
            and self.state != OWNER_OVERRIDE
        )
        if needs_restore:
            since = _dt(self.parked_off_restore_since)
            if since is None or since > now:
                self.parked_off_restore_since = _iso(now)
                since = now
            if now - since >= timedelta(minutes=30):
                alerts.append(
                    (
                        "parked_off_cannot_restore",
                        "Hot water: parked OFF, cannot restore heat",
                        "The last observed heater state was software OFF and a permitted heating target "
                        "has been wanted for 30 minutes without confirmed restoration. Hot water may run out. "
                        "Check cloud/authentication/controller faults and the Thermann app. No command or lock "
                        "is automatically retried or reset. If the app is unavailable, follow the manufacturer's "
                        "local-control instructions or contact qualified support; never bypass electrical protection. "
                        "Strict peak lockout needs working control to restore heat. This warning does not authorise peak heating.",
                    )
                )
        else:
            self.parked_off_restore_since = None
        if want.reason == "peak_lockout" and (self.heater != OFF or self.state == CONFIRMING):
            alerts.append(
                (
                    "peak_lockout_unverified",
                    "Hot water: peak lockout not yet confirmed",
                    "Routine peak heating is locked out, but software OFF has not been confirmed. "
                    "Cloud failures or an in-flight command may delay it. No command is blindly repeated. "
                    "Software OFF never proves zero electrical power; native protections and owner intervention remain independent.",
                )
            )
        if obs.heater_meter_mapped and obs.heater_meter_quality not in ("verified", "unverified"):
            since = _dt(self.heater_meter_missing_since)
            if since is None or since > now:
                self.heater_meter_missing_since = _iso(now)
                since = now
            if now - since >= timedelta(minutes=5):
                alerts.append(
                    (
                        "heater_meter_unavailable",
                        "Hot water: raw circuit meter unavailable",
                        f"Circuit power is {obs.heater_meter_quality or 'unknown'}. Optional solar heat is blocked; "
                        "essential off-peak heat retains its normal guards. Check the raw meter entity, sign, units "
                        "and last_reported cadence, including steady 0 W. Repeated evaluations do not prove liveness.",
                    )
                )
        else:
            self.heater_meter_missing_since = None
        if (
            self.state in {STORAGE_ACTIVE, NORMAL_ACTIVE}
            and self.heater in TARGET_C
            and obs.poll_at is not None
            and 0 <= (now - obs.poll_at).total_seconds() <= (cfg.poll_interval_minutes + 5) * 60
            and obs.element == "off"
            and obs.element_confidence in {"verified", "high"}
        ):
            self.storage_idle_since = self.storage_idle_since or _iso(now)
            since = _dt(self.storage_idle_since)
            if (
                obs.temperature_c is not None
                and obs.temperature_c <= TARGET_C[self.heater] - 8 - 2
                and now - since >= timedelta(minutes=15)
            ):
                alerts.append(
                    (
                        "storage_not_heating",
                        "Hot water: Manual target confirmed but not heating",
                        f"Manual {TARGET_C[self.heater]} °C is confirmed and the reading is {obs.temperature_c} °C, but "
                        "the element has been off for 15 minutes. No command is repeated. Check "
                        "the heater and its power supply.",
                    )
                )
        else:
            self.storage_idle_since = None
        passive_ok = (
            obs.passive_status_deadline is not None
            and obs.poll_at is not None
            and obs.poll_at <= now <= obs.passive_status_deadline
            and obs.passive_status_deadline - obs.poll_at <= timedelta(hours=12, minutes=5)
        )
        if not passive_ok and (
            obs.poll_at is None
            or not timedelta(0)
            <= now - obs.poll_at
            <= timedelta(minutes=2 * cfg.poll_interval_minutes + 5)
        ):
            alerts.append(
                (
                    "status_stale",
                    "Hot water: heater status missing",
                    "Thermann status is missing, future-dated or beyond the configured freshness window. "
                    "Automatic commands require a valid status. "
                    "Check the Thermann Hot Water app and cloud health.",
                )
            )
        if obs.cloud_health not in (None, "ok"):
            alerts.append(
                (
                    "cloud_fault",
                    "Hot water: Thermann cloud problem",
                    f"Bridge cloud health is {obs.cloud_health}. No commands are sent. "
                    "Authentication locks are never reset automatically; see the app "
                    "documentation.",
                )
            )
        if obs.forecast_available is False:
            self.forecast_missing_since = self.forecast_missing_since or _iso(now)
            if now - _dt(self.forecast_missing_since) >= FORECAST_ALERT_AFTER:
                alerts.append(
                    (
                        "forecast_unavailable",
                        "Hot water: EMHASS forecast unavailable",
                        "No usable published PV and household-load forecast for over an hour. "
                        "No future solar is assumed: weekday 62 storage starts by its latest "
                        "start and the weekend window starts 62 at once when it opens. "
                        "Check the EMHASS forecast sensors and 'Use published forecasts'.",
                    )
                )
        else:
            self.forecast_missing_since = None
        started = _dt(self.guest_started)
        if (
            self.guest_active(now)
            and started is not None
            and now - started >= GUEST_ALERT_AFTER
            and self.state
            not in {
                ACTIVE_OF["normal_storage" if self.guest_target_c == 62 else STORAGE],
                CONFIRMING,
            }
        ):
            detail = ", ".join(self.gate_failures) or self.reason
            alerts.append(
                (
                    "guest_mode_not_applied",
                    "Hot water: 12hr Override not applied",
                    f"The 12hr Override wants Manual at {self.guest_target_c} °C but the controller could not "
                    f"apply it ({detail}). {RECOVERY['guest_mode_not_applied']}",
                )
            )
        cooldown = timedelta(hours=cfg.notification_cooldown_hours)
        for key, title, message in alerts:
            self.active_alerts.append(key)
            last = _dt(self.alert_cooldowns.get(key) or self.alerts.get(key))
            if last is None or now - last >= cooldown:
                stamp = _iso(now)
                self.alerts[key] = stamp
                self.alert_cooldowns[key] = stamp
                effects.append(Effect("notify", key=key, title=title, message=message))
        for key in list(self.alerts):
            if key not in self.active_alerts and not key.startswith(EVENT_PREFIXES):
                del self.alerts[key]
                effects.append(Effect("resolve", key=key))
        for key in list(self.alert_cooldowns):
            recorded = _dt(self.alert_cooldowns.get(key))
            if key not in self.alerts and (recorded is None or now - recorded >= cooldown):
                del self.alert_cooldowns[key]
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
            "override_target_c": self.guest_target_c if self.guest_active(now) else None,
            "legacy_override": self.guest_active(now) and self.guest_target_c == 70,
            "state": self.state,
            "reason": self.reason,
            "enabled": self.enabled,
            "hold": self.hold,
            "heater": self.heater,
            "fault": self.fault,
            "recovery_guidance": self.guidance(),
            "pending_intent": self.intent,
            "last_command": last,
            "commands_last_24h": len(self.commands),
            "requests_last_24h": self.requests_last_24h(now),
            "gate_failures": self.gate_failures,
            "active_alerts": self.active_alerts,
            "want": self.last_want,
            "last_confirmed_transition": self.last_transition_at,
            "operating_mode": self.operating_mode(now),
            "guest_until": self.guest_until,
            "holiday_start": self.holiday_start,
            "holiday_return": self.holiday_return,
            "last_mode_refusal": self.refusal,
            "last_observed_heater": self.last_observed_heater,
            "parked_off_restore_since": self.parked_off_restore_since,
            "protective_exit": self.protective_exit,
            "optional_cooldown_until": self.optional_cooldown_until,
            "solar_session_active": self.solar_session_active,
            "protective_exit_wait_seconds": max(
                0, (now - _dt(self.protective_exit["since"])).total_seconds()
            )
            if self.protective_exit
            else 0,
        }
