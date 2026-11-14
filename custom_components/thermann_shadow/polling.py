"""One bounded advisory scheduler; never performs or requests a cloud read.

Actual fixed polling, token refresh, backoff and command confirmations remain
entirely bridge-owned. This comparison is conditioned on actual observations,
not a claim about unseen owner changes or token expiry on a different schedule.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class PollContext:
    now: datetime
    status_at: datetime | None
    heating: bool | None
    command_at: datetime | None = None
    confirming: bool = False
    uncertain: bool = False
    decision_at: datetime | None = None
    completion_at: datetime | None = None
    cloud_ready: bool = True
    desired_target_c: int | None = None
    reported_target_c: int | None = None


class PollingShadow:
    def __init__(self, enabled=False, heating_minutes=60, stable_minutes=90):
        if not 15 <= heating_minutes <= 60 or not 30 <= stable_minutes <= 90:
            raise ValueError("polling_bounds_invalid")
        self.enabled = enabled
        self.heating_minutes, self.stable_minutes = heating_minutes, stable_minutes
        self.virtual_at = self.next_due = self.last_would_poll = None
        self.actual_seen = self.command_seen = None
        self.actual_statuses = self.would_polls = self.blocked = 0
        self.reused_confirmations = 0
        self.reason = "disabled" if not enabled else "awaiting_status"
        self._blocked_until = None
        self.desired_target_c = self.reported_target_c = None

    def observe(self, c: PollContext):
        self.desired_target_c, self.reported_target_c = c.desired_target_c, c.reported_target_c
        status = c.status_at if c.status_at and c.status_at <= c.now else None
        new_status = status is not None and (self.actual_seen is None or status > self.actual_seen)
        if new_status:
            self.actual_seen = status
            self.actual_statuses += 1
        if not self.enabled:
            return False
        if self._blocked_until is not None and c.now < self._blocked_until:
            return False
        if self.virtual_at is None:
            self.virtual_at = status or c.now
        if c.command_at and c.command_at <= c.now and c.command_at != self.command_seen:
            self.command_seen = c.command_at
            # Pre-command and bounded confirmation reads stay with the bridge.
            # Reuse their actual successful status instead of inventing a GET.
        if (
            new_status
            and self.command_seen
            and self.command_seen < status
            and status - self.command_seen <= timedelta(minutes=7)
            and status > self.virtual_at
        ):
            self.virtual_at, self.next_due = status, None
            self.reused_confirmations += 1
        bound = self.heating_minutes if c.heating is True else self.stable_minutes
        due, reason = (
            self.virtual_at + timedelta(minutes=bound),
            "heating_cap" if c.heating else "stable_cap",
        )
        if c.uncertain or c.heating is None or status is None:
            due, reason = min(due, self.virtual_at + timedelta(minutes=15)), "uncertain_or_recovery"
        for when, why in ((c.decision_at, "before_decision"), (c.completion_at, "near_completion")):
            if when and c.now <= when and when - timedelta(minutes=10) < due:
                target = c.desired_target_c if why == "before_decision" else c.reported_target_c
                if target in (62, 70):
                    why += "_normal_62" if target == 62 else "_boost_70"
                due, reason = (
                    max(self.virtual_at + timedelta(minutes=5), when - timedelta(minutes=10)),
                    why,
                )
        # A stream of sensor callbacks cannot slide an existing deadline later.
        if self.next_due is None or due < self.next_due:
            self.next_due, self.reason = due, reason
        if c.now < self.next_due:
            return False
        if not c.cloud_ready or c.confirming:
            self.blocked += 1
            self.reason = (
                "existing_bridge_guards" if not c.cloud_ready else "bridge_owned_confirmation"
            )
            self.next_due = c.now + timedelta(minutes=5)
            self._blocked_until = self.next_due
            return False
        self.would_polls += 1
        self.last_would_poll = self.virtual_at = c.now
        self.next_due = None
        return True

    def summary(self):
        return {
            "enabled": self.enabled,
            "actual_schedule": "fixed_bridge_unchanged",
            "comparison_basis": "actual_fixed_observations_not_closed_loop",
            "heating_max_minutes": self.heating_minutes,
            "stable_max_minutes": self.stable_minutes,
            "reason": self.reason,
            "desired_target_c": self.desired_target_c,
            "reported_target_c": self.reported_target_c,
            "next_due": self.next_due.isoformat() if self.next_due else None,
            "last_would_poll": self.last_would_poll.isoformat() if self.last_would_poll else None,
            "would_status_reads": self.would_polls,
            "actual_observed_statuses": self.actual_statuses,
            "reused_command_statuses": self.reused_confirmations,
            "blocked_evaluations": self.blocked,
            "extra_cloud_requests": 0,
            "unobserved_event_detection_delay": "unknown_without_independent_event_truth",
        }
