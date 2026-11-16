"""Homeowner labels/help and bounded diagnostic heartbeat, never control logic."""

from datetime import timedelta

STATE_LABELS = {
    "circuit_measurement_mode": {
        "ct_free": "No circuit meter",
        "measured": "Circuit meter available",
        "meter_fault": "Circuit meter unavailable",
    },
    "current_tariff": {"peak": "Peak", "off_peak": "Off-peak", "shoulder": "Shoulder"},
    "next_tariff_kind": {"peak": "Peak", "off_peak": "Off-peak", "shoulder": "Shoulder"},
    "heater_element_state": {"on": "Likely heating", "off": "Likely idle", "unknown": "Unverified"},
    "heater_meter_state": {
        "on": "Measured heating",
        "off": "Measured idle",
        "unknown": "Unverified",
    },
    "solar_session_status": {
        "WAITING": "Waiting",
        "ACTIVE": "Active",
        "STOPPING": "OFF unconfirmed",
        "COOLDOWN": "Waiting to restart",
    },
    "boost_eligibility": {"eligible": "Available", "unavailable": "Not available"},
    "morning_availability": {
        "not_due": "No check due",
        "unverified": "Reading unavailable",
        "low": "Bottom temperature low",
        "latest_probe_above_warning": "Latest probe above warning level",
    },
    "cloud_health": {
        "ok": "Connected",
        "disabled": "Cloud access disabled",
        "auth_locked": "Authentication locked",
        "quota_limited": "Request limit reached",
        "backoff": "Waiting after a failure",
        "unavailable": "Connection unavailable",
        "unrecognised": "Waiting for bridge status",
    },
    "next_action": {
        "off": "OFF",
        "baseline": "Baseline temperature",
        "normal_storage": "Normal storage",
        "storage": "Solar storage",
        "hold": "Wait / keep owner control",
    },
}


HELP = {
    "temperature": (
        "Latest bottom temperature",
        "Latest cloud-reported bottom probe, in °C. It does not measure all hot water. Check the observation age.",
    ),
    "controller": (
        "Heating plan details",
        "Read-only planning diagnostics. Automatic control and all command safeguards are separate.",
    ),
    "controller_state": (
        "Automatic heating status",
        "Controller supervision state. A requested mode is not a confirmed heater state.",
    ),
    "controller_reason": (
        "Why heating is waiting",
        "Technical blocking reason; Copy diagnostic report explains the current plan and safeguards.",
    ),
    "policy_state": (
        "Requested heater mode",
        "Policy's intended mode, subject to owner holds, faults and confirmed exact-prior commands.",
    ),
    "controller_telemetry": (
        "Why Thermowatt made this decision",
        "Significant planning events and their measured evidence; no direct heater controls.",
    ),
    "fault": (
        "Heating control problem",
        "Acknowledge only after checking the official app. Acknowledgement re-inspects; uncertain commands are never replayed.",
    ),
    "cloud_poll_interval": (
        "Time between cloud checks",
        "Seconds between scheduled observations. Command checks/confirmation can add requests.",
    ),
    "boost_eligibility": (
        "Solar heating availability",
        "Optional extra storage needs useful heat, sustained measured surplus, permission, economics and budgets.",
    ),
    "boost_reason": (
        "Why solar heating is waiting",
        "The current optional-boost qualification or rejection reason, not a physical heating measurement.",
    ),
    "morning_availability": (
        "Hot-water availability assessment",
        "Fresh bottom probe below the chosen warning threshold before either peak. Unknown/stale is not measured cold.",
    ),
    "heater_element_state": (
        "Estimated heating element activity",
        "Inferred activity is not physical verification. Only a commissioned dedicated circuit meter can measure element power.",
    ),
    "forecast_load_quality": (
        "Forecast reliability",
        "Forecasts are planning estimates. Missing or implausibly low load uses a conservative household floor.",
    ),
    "controller_evaluated_at": (
        "Controller heartbeat",
        "Completed local evaluation, published at most 15 minutes apart or on a supervision change. Exact latest completion is in the diagnostic report. This does not trigger a cloud request.",
    ),
    "heater_meter_state": (
        "Measured hot-water circuit activity",
        "Unavailable without a commissioned dedicated circuit meter. Cloud OFF is not proof of zero electrical power.",
    ),
    "next_cloud_poll": (
        "Next useful cloud check",
        "Bridge-owned schedule; confirmation, failures and safety gates can change it.",
    ),
    "expected_completion": (
        "Estimated heating completion",
        "A conservative range/nominal planning estimate, not guaranteed hot-water quantity. See prediction confidence.",
    ),
    "current_price_aud": (
        "Current electricity usage price",
        "Australian dollars per kWh. Configure prices using cents/kWh in Electricity Tariffs.",
    ),
    "learned_heating_rate": (
        "Measured heating performance",
        "Learned from clean dedicated-meter cycles only. CT-free estimates remain nominal; learning permission stays separate.",
    ),
}


class Heartbeat:
    """Publish genuine completed timestamps, not an every-minute activity stream.

    Internal evaluations and the exact diagnostic timestamp remain untouched.
    The existing 30-minute external watchdog still has at least 15 minutes of
    normal headroom and detects a stopped controller no later than before.
    """

    def __init__(self):
        self.at = None
        self.key = None

    def value(self, completed, key):
        if completed is not None and (
            self.at is None
            or key != self.key
            or completed < self.at
            or completed - self.at >= timedelta(minutes=15)
        ):
            self.at, self.key = completed, key
        return self.at
