"""Seven-day seasonal Smart/fixed HTTP comparisons through the actual worker.

Uses synthetic HA/MQTT/cloud/tank only. Includes app interventions, heavy draws,
Friday cloud/CT outages, restart, expired leases and rejected authentication.
No network, real account, HA installation or physical heater is used.
"""

import argparse
from datetime import datetime, timedelta
import json
import math
from pathlib import Path

import final_week_replay as base
from pre_review_failure_replay import FailureWeek
from conftest import response


class SmartWeek(FailureWeek):
    daylight = 12
    session_hours = 24
    failure_week = False

    def __init__(self, *args, **kwargs):
        self.token_at = None
        self.expired_status_401 = 0
        super().__init__(*args, **kwargs)
        mode = self.strategy if self.strategy in {"smart", "minimum"} else "existing"
        self.entry.options["polling_mode"] = mode
        if not self.ct:
            from test_existing_installation_upgrade import solar

            self.entry.options["ct_free_solar_verification"] = solar.ct_free_record(
                self.sources["grid"], "W", False, 3
            )
        self.runtime.set_native_reference(self.entry.options)
        self.executor.configure(self.entry.options)
        self.bridge.options["polling_mode"] = mode
        if mode != "existing":
            self.bridge.poll_schedule.smart_mode = mode
            self.bridge.poll_schedule.enabled = True
        self.token_at = self.bridge.token_obtained_at or self.t
        if not self.failure_week:
            # FailureWeek wraps plan delivery; keep it for loss comparisons only.
            self.bridge.on_mqtt_message = (
                base.bridge_module.MyThermowattBridge.on_mqtt_message.__get__(self.bridge)
            )

    def weather(self, local):
        local = local.astimezone(base.m.STANDARD)
        hour = local.hour + local.minute / 60
        dawn = 12 - self.daylight / 2
        clear = (
            5 * max(0, math.sin(math.pi * (hour - dawn) / self.daylight))
            if dawn <= hour <= dawn + self.daylight
            else 0
        )
        if local.weekday() in (1, 6):
            return clear * 0.08
        if local.weekday() == 2:
            return clear * (1 if local.minute % 25 < 12 else 0.08)
        return clear

    def cloud(self, method, url, **kwargs):
        # Model a stated synthetic TTL, rather than claiming a vendor lifetime.
        # Expired ordinary GET follows the real one-refresh/one-retry path.
        if url.endswith("/refresh"):
            self.token_at = self.t
        if (
            url.endswith("/status")
            and self.token_at is not None
            and self.t - self.token_at >= self.session_hours * 3600
        ):
            self.expired_status_401 += 1
            return response(401)
        if self.failure_week:
            return super().cloud(method, url, **kwargs)
        return base.Week.cloud(self, method, url, **kwargs)

    def run_week(self):
        data = super().run_week()
        data["synthetic_session_hours"] = self.session_hours
        data["expired_status_401"] = self.expired_status_401
        return data


def results(seasons=None):
    reports = []
    seasons = seasons or [
        ("summer", (2026, 1, 12), 14, False),
        ("winter", (2026, 7, 13), 10, False),
        ("dst_and_failures", (2026, 9, 28), 12, True),
    ]
    for item in seasons:
        name, date, daylight, failures = item[:4]
        ttl = item[4] if len(item) > 4 else 24
        start = datetime(*date, tzinfo=base.m.STANDARD)
        with base.pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                base,
                "hobart",
                lambda d, h, minute=0, start=start: start
                + timedelta(days=d - 16, hours=h - 1, minutes=minute),
            )
            patch.setattr(SmartWeek, "daylight", daylight)
            patch.setattr(SmartWeek, "failure_week", failures)
            patch.setattr(SmartWeek, "session_hours", ttl)
            report = base.results(
                [(s, s, False, 60) for s in ("fixed_30", "fixed_60", "smart", "minimum")],
                week_class=SmartWeek,
            )
            report["season"] = name
            report["assumptions"]["cloud"] = (
                f"Actual worker HTTP categories; legacy fixed modes use20-minute proactive heuristic. Smart ordinary GET reuses the session with bounded401 refresh/retry; command checks/POST/confirmation retain proactive preparation. Synthetic session{ttl}h, not vendor evidence."
            )
            report["assumptions"]["polling"] = (
                "Smart8h quiet night/90min day; Minimum12h/180min; useful pre-boundary observations; original30min lease-loss fallback. Temperature never promoted to fresh."
            )
            report["assumptions"]["weather"] = (
                f"Synthetic {daylight}-hour solar day; cloudy/patchy days; forecasts can be optimistic. Not measured local meteorology."
            )
            reports.append(report)
    return {"schema": 1, "synthetic": True, "reports": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(results(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
