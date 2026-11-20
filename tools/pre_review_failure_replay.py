"""Multi-day plan-loss and persistent authentication-failure comparisons."""

import argparse
import json
from pathlib import Path

from final_week_replay import Week, results as replay, m, SERIAL
from conftest import response


def lost(local):
    return local.weekday() == 1 and 75 <= local.hour * 60 + local.minute < 120


class FailureWeek(Week):
    def __init__(self, *args, **kwargs):
        self.auth_failed_at = None
        self.requests_after_auth_failure = self.dropped_plans = self.loss_status_reads = 0
        self.lease_loss_observed = False
        super().__init__(*args, **kwargs)
        original = self.bridge.on_mqtt_message

        def receive(client, userdata, message):
            if message.topic.endswith("/poll_plan") and lost(self.now().astimezone(m.STANDARD)):
                self.dropped_plans += 1
                return  # simulated broker delivery loss; no controller replacement HTTP
            original(client, userdata, message)

        self.bridge.on_mqtt_message = receive

    def cloud(self, method, url, **kwargs):
        local = self.now().astimezone(m.STANDARD)
        if self.auth_failed_at is not None:
            self.requests_after_auth_failure += 1
        if url.endswith("/refresh") and local.weekday() == 6 and local.hour >= 2:
            self.auth_failed_at = self.now()
            self.event("synthetic_refresh_401_operator_recovery_required")
            return response(401)
        if url.endswith("/status") and lost(local):
            self.loss_status_reads += 1
        return super().cloud(method, url, **kwargs)

    def actions(self, local):
        super().actions(local)
        if (
            lost(local)
            and self.bridge.poll_schedule.active
            and not self.bridge.poll_schedule.summary(SERIAL)["active"]
            and not self.lease_loss_observed
            and local.hour * 60 + local.minute >= 79
        ):
            self.lease_loss_observed = True
            self.event("expired_plan_lease_fixed_recovery_observed")

    def run_week(self):
        row = super().run_week()
        row["additional_failures"] = {
            "dropped_plan_frames": self.dropped_plans,
            "expired_lease_observed": self.lease_loss_observed,
            "status_reads_during_plan_loss": self.loss_status_reads,
            "refresh_401_at": self.auth_failed_at.isoformat() if self.auth_failed_at else None,
            "http_after_refresh_rejection": self.requests_after_auth_failure,
            "final_auth_mode": self.bridge.guard.state["mode"],
        }
        return row


def results():
    report = replay(
        [
            ("fixed_30", "fixed_30", False, 60),
            ("fixed_60", "fixed_60", False, 60),
        ],
        week_class=FailureWeek,
    )
    report["schema_version"] = 2
    report["assumptions"]["additional_failures"] = (
        "Tuesday01:15–02:00AEST poll-plan delivery loss; Sunday first refresh at/after02:00 "
        "returns synthetic401 and remains persistently locked without operator recovery. "
        "No auth generation is increased. Counts after this failure are reliability evidence, "
        "not savings obtained by comparing unavailable control. No live account is used."
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(results(), indent=2) + "\n", encoding="utf-8")
