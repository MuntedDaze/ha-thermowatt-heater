"""Bounded bridge-owned adaptive scheduling. No HTTP, auth or device commands.

MQTT plans are expiring hints anchored to the bridge's own successful status.
All deadlines run on monotonic time. Restart discards leases/deadlines and
requires the bridge's normal fresh discovery/status. The small journal retains
diagnostic counters, never permission to skip startup inspection or cloud guards.
"""

import json
import math

MIN_INTERVAL = 900
MAX_INTERVAL = 2400
LEASE_SECONDS = 180
REASONS = frozenset(
    {"stable", "heating", "ct_free", "uncertain", "before_decision", "near_completion", "recovery"}
)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class AdaptiveSchedule:
    def __init__(self, enabled, clock, monotonic, path=None, writer=None):
        self.enabled, self.clock, self.monotonic = enabled, clock, monotonic
        self.path, self.writer = path, writer
        self.healthy = True
        self.records = {}
        self.counts = {"accepted": 0, "rejected": 0, "ordinary_reads": 0, "reused_reads": 0}
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
        self.records[serial] = {
            "wall": timestamp,
            "mono": self.monotonic(),
            "fixed": fixed_seconds,
            "issued": None,
            "due": None,
            "lease": 0,
            "reason": "fixed_fallback",
        }

    def clear(self):
        self.records.clear()

    def accept(self, serial, payload):
        record = self.records.get(serial)
        try:
            plan = json.loads(payload)
            if not self.active or record is None or not isinstance(plan, dict):
                raise ValueError
            if (
                set(plan) != {"version", "status_at", "issued_at", "delay_seconds", "reason"}
                or type(plan["version"]) is not int
                or plan["version"] != 1
            ):
                raise ValueError
            if not all(finite(plan[k]) for k in ("status_at", "issued_at", "delay_seconds")):
                raise ValueError
            if not 0 <= self.clock() - plan["issued_at"] <= 30:
                raise ValueError
            if abs(plan["status_at"] - record["wall"]) > 0.01:
                raise ValueError
            if record["issued"] is not None and plan["issued_at"] <= record["issued"]:
                raise ValueError
            if (
                not MIN_INTERVAL <= plan["delay_seconds"] <= MAX_INTERVAL
                or plan["reason"] not in REASONS
            ):
                raise ValueError
            due = record["mono"] + plan["delay_seconds"]
            # The first lease may replace the fixed slot. Later callbacks can
            # advance, never slide a consequential deadline later.
            record["due"] = min(record["due"], due) if record["due"] is not None else due
            record.update(
                issued=plan["issued_at"],
                lease=self.monotonic() + LEASE_SECONDS,
                reason=plan["reason"],
            )
            self.counts["accepted"] += 1
            return True
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.counts["rejected"] += 1
            return False

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
            "counts": dict(self.counts),
        }
