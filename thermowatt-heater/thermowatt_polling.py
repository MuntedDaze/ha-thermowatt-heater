"""Bounded bridge-owned Smart scheduling. No HTTP, auth or device commands.

1.5.0: only the controller's Smart (version 3) plans are accepted; the pre-Smart
version 1/2 plans and the Minimum/fixed_30 plan modes are removed (owner
decision D2, 20 Nov 2026). Without a valid plan the fixed schedule applies.
MQTT plans are expiring hints anchored to the bridge's own successful status.
All deadlines run on monotonic time. Restart discards leases/deadlines and
requires the bridge's normal fresh discovery/status. The small journal retains
diagnostic counters, never permission to skip startup inspection or cloud guards.
"""

import json
import math

MIN_INTERVAL = 900
MAX_INTERVAL = 2400  # longest temperature-relevant (non-quiet) delay
MAX_QUIET_INTERVAL = 28800  # 8 h: confirmed quiet baseline/OFF overnight
LEASE_SECONDS = 180
QUIET_REASONS = {"stable_baseline", "stable_off", "quiet_before_decision"}
REASONS = QUIET_REASONS | {"required_temperature", "before_decision", "uncertain"}
# Home Assistant renders a timestamp sensor's state with whole-second precision
# (``isoformat(timespec="seconds")``), so a controller reading the bridge's
# "Last successful poll" entity echoes floor(observation time). The bridge keeps
# the sub-second wall time of its own read; both forms identify the same read.
EXACT_IDENTITY_TOLERANCE = 0.01
# Safe, enumerable rejection categories (no payload content is ever retained).
REJECTION_CODES = (
    "schedule_inactive",
    "no_current_observation",
    "invalid_payload",
    "version_unsupported",
    "mode_mismatch",
    "fields_invalid",
    "plan_stale_or_future",
    "status_identity_mismatch",
    "plan_not_newer",
    "owner_check_invalid",
    "delay_or_reason_invalid",
)


class Rejected(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class AdaptiveSchedule:
    def __init__(
        self,
        enabled,
        clock,
        monotonic,
        path=None,
        writer=None,
    ):
        self.enabled, self.clock, self.monotonic = enabled, clock, monotonic
        self.path, self.writer = path, writer
        self.healthy = True
        self.records = {}
        self.counts = {"accepted": 0, "rejected": 0, "ordinary_reads": 0, "reused_reads": 0}
        # Diagnostics since this bridge start only; never persisted, so the
        # version-1 journal (and a rollback to 1.4.0) is unchanged.
        self.rejections = {}
        self.last_rejection = None
        self.last_acceptance = None
        if path is not None and path.exists():
            try:
                if path.stat().st_size > 4096:
                    raise ValueError
                data = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or data.get("version") != 1
                    or set(data["counts"]) != set(self.counts)
                ):
                    raise ValueError
                if any(type(v) is not int or not 0 <= v < 2**63 for v in data["counts"].values()):
                    raise ValueError
                self.counts = data["counts"]
            except (ValueError, TypeError, KeyError, OSError):
                self.healthy = False  # fixed fallback, never a silent learned deadline

    @property
    def active(self):
        return self.enabled and self.healthy

    def save(self):
        if self.path is not None and self.writer is not None:
            try:
                self.writer(self.path, {"version": 1, "counts": self.counts})
            except OSError:
                self.healthy = False

    def observed(self, serial, timestamp, fixed_seconds):
        previous = self.records.get(serial)
        # Two reads inside one wall-clock second cannot be told apart by a
        # second-precision echo; then only an exact echo identifies the newer.
        ambiguous = previous is not None and math.floor(previous["wall"]) == math.floor(timestamp)
        self.records[serial] = {
            "second_ambiguous": ambiguous,
            "wall": timestamp,
            "mono": self.monotonic(),
            "fixed": fixed_seconds,
            "issued": None,
            "due": None,
            "lease": 0,
            "reason": "fixed_fallback",
            "version": None,
            "owner_limit": None,
        }

    def clear(self):
        self.records.clear()

    def identity_offset(self, record, status_at):
        """Seconds by which ``status_at`` precedes this record's read, or None
        when the plan was made for a different observation.

        Exact (sub-second) echoes match as before. A whole-second echo matches
        only floor(read time), and only when no other read of this heater fell
        in the same second. This is identity only: freshness and deadlines stay
        anchored to the bridge's own monotonic read time.
        """
        offset = record["wall"] - status_at
        if abs(offset) <= EXACT_IDENTITY_TOLERANCE:
            return 0.0
        if (
            not record.get("second_ambiguous")
            and float(status_at).is_integer()
            and status_at == math.floor(record["wall"])
        ):
            return offset  # 0.01 < offset < 1
        return None

    def _reject(self, code):
        self.counts["rejected"] += 1
        self.rejections[code] = self.rejections.get(code, 0) + 1
        self.last_rejection = {"reason": code, "at": int(self.clock())}
        return False

    def accept(self, serial, payload):
        record = self.records.get(serial)
        try:
            if not self.active:
                raise Rejected("schedule_inactive")
            if record is None:
                raise Rejected("no_current_observation")
            try:
                plan = json.loads(payload)
            except (ValueError, UnicodeError):
                raise Rejected("invalid_payload") from None
            if not isinstance(plan, dict):
                raise Rejected("invalid_payload")
            if plan.get("version") != 3 or type(plan.get("version")) is not int:
                raise Rejected("version_unsupported")
            if plan.get("polling_mode") != "smart":
                raise Rejected("mode_mismatch")
            keys = {
                "version",
                "status_at",
                "issued_at",
                "delay_seconds",
                "reason",
                "owner_check_seconds",
                "polling_mode",
            }
            if set(plan) != keys:
                raise Rejected("fields_invalid")
            if not all(finite(plan[k]) for k in ("status_at", "issued_at", "delay_seconds")):
                raise Rejected("fields_invalid")
            if not 0 <= self.clock() - plan["issued_at"] <= 30:
                raise Rejected("plan_stale_or_future")
            offset = self.identity_offset(record, plan["status_at"])
            if offset is None:
                raise Rejected("status_identity_mismatch")
            if record["issued"] is not None and plan["issued_at"] <= record["issued"]:
                raise Rejected("plan_not_newer")
            owner_limit = plan["owner_check_seconds"]
            if type(owner_limit) is not int or not 1800 <= owner_limit <= MAX_QUIET_INTERVAL:
                raise Rejected("owner_check_invalid")
            limit = (
                owner_limit if plan["reason"] in QUIET_REASONS else min(MAX_INTERVAL, owner_limit)
            )
            if not MIN_INTERVAL <= plan["delay_seconds"] <= limit or plan["reason"] not in REASONS:
                raise Rejected("delay_or_reason_invalid")
            # The controller measured its delay from status_at. For a whole-
            # second echo that is up to one second before the bridge's read, so
            # the deadline lands where the controller intended: never later.
            due = record["mono"] - offset + plan["delay_seconds"]
            # The first lease may replace the fixed slot. Later callbacks can
            # advance, never slide a consequential deadline later.
            record["due"] = min(record["due"], due) if record["due"] is not None else due
            record.update(
                issued=plan["issued_at"],
                lease=self.monotonic() + LEASE_SECONDS,
                reason=plan["reason"],
                version=3,
                owner_limit=owner_limit,
            )
            self.counts["accepted"] += 1
            self.last_acceptance = {"reason": plan["reason"], "at": int(self.clock())}
            return True
        except Rejected as error:
            return self._reject(error.code)
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            return self._reject("invalid_payload")

    def deadline(self, serial):
        r = self.records.get(serial)
        if not self.active or r is None:
            return None
        if r["due"] is not None and self.monotonic() <= r["lease"]:
            return r["due"]
        return r["mono"] + r["fixed"]

    def summary(self, serial):
        due = self.deadline(serial)
        r = self.records.get(serial)
        leased = due is not None and r["due"] is not None and self.monotonic() <= r["lease"]
        return {
            "enabled": self.enabled,
            "active": bool(leased),
            "reason": r["reason"]
            if leased
            else "fixed_fallback"
            if self.active
            else "disabled"
            if not self.enabled
            else "journal_unavailable",
            "next_at": self.clock() + max(0, due - self.monotonic()) if due is not None else None,
            "interval_seconds": max(0, due - r["mono"]) if due is not None else None,
            "lease_remaining_seconds": max(0, r["lease"] - self.monotonic()) if leased else 0,
            "plan_version": r["version"] if leased else None,
            "owner_check_seconds": r["owner_limit"] if leased else None,
            "counts": dict(self.counts),
            # Since this bridge start: safe category -> count, and latest outcomes.
            "rejection_reasons": dict(self.rejections),
            "last_rejection": dict(self.last_rejection) if self.last_rejection else None,
            "last_acceptance": dict(self.last_acceptance) if self.last_acceptance else None,
        }
