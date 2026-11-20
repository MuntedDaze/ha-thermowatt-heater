"""Allowlisted owner diagnostics. Never serialize entries, attributes or HTTP bodies.

This module has no transport or command path. Unknown vendor strings are omitted;
source entities are correlated by a short digest rather than names/serials.
"""

from datetime import UTC, datetime
import hashlib
import json
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .report_codes import INTERNAL_CODES


WHY = {
    "baseline": "Maintain the normal night/weekend temperature.",
    "overnight_baseline": "The native thermostat maintains the overnight target.",
    "peak_park": "Heating is parked for the configured peak electricity period.",
    "peak_lockout": "The selected policy prevents scheduled peak heating.",
    "weekday_storage": "Heat for normal weekday storage before peak.",
    "weekend_daytime_storage": "Measured PV opened the weekend comfort window; normal storage is selected and off-peak grid assistance is allowed.",
    "weekend_storage_no_forecast": "Weekend comfort window is open and no usable forecast is available, so normal storage starts now.",
    "weekend_waiting_for_solar": "Keep the baseline until measured PV opens the weekend window.",
    "weekend_day_ended": "Weekend daytime heating has ended; return to the baseline.",
    "solar_opportunity": "Useful optional solar storage is qualified.",
    "peak_solar_qualified": "Experimental solar heating during peak is qualified by local measurements.",
    "solar_opportunity_import": "Sustained grid import ended optional solar heating.",
    "solar_measurement_unavailable": "Required solar measurements are unavailable; withdraw optional heating.",
    "guest_mode": "The owner's 12-hour comfort override is active.",
    "12hr_override": "The owner's 12-hour comfort override is active.",
    "holiday": "Holiday mode is active.",
    "owner_override": "An owner change or deliberate hold has priority.",
}

# Internal codes only. No arbitrary HA/vendor state strings enter exported text.
CODES = frozenset(
    {
        "normal_storage",
        "Schedule",
        "Eco",
        "Holiday",
        "off",
        "baseline_45",
        "normal_62",
        "storage_70",
        "hold",
        "Manual",
        "Off",
        "disabled",
        "observing",
        "parked",
        "normal_storage_62",
        "change_requested",
        "confirming",
        "owner_override",
        "fault_locked",
        "ok",
        "unknown",
        "unavailable",
        "auth_locked",
        "quota_limited",
        "backoff",
        "authorized",
        "locked",
        "blocked",
        "fresh_cloud_state_for_adoption_required",
        "ready",
        "existing",
        "smart",
        "fixed_30",
        "minimum",
        "local",
        "standard",
        "flat",
        "aurora_93",
        "custom",
        "peak",
        "off_peak",
        "shoulder",
        "ct_free",
        "measured",
        "meter_fault",
        "on",
        "heating",
        "idle",
        "stale",
        "missing",
        "consistent",
        "not_configured",
        "unverified",
        "verified",
        "provisional",
        "fresh",
        "expired",
        "unusable",
        "household_floor",
        "valid",
        "confirmed",
        "submitted",
        "pending",
        "uncertain",
        "cancelled",
        "failed",
        "withheld",
        "submitted_awaiting_status",
        "awaiting_confirmation",
        "refreshing_status",
        "submitting",
        "not_confirmed_within_limit",
        "unexpected_state_after_command",
        "refused_auth_guard",
        "refused_cloud_unavailable",
        "dropped_auth_guard",
        "command_not_confirmed",
        "command_failed",
        "unexpected_heater_state",
        "state_persistence_failed",
        "none",
        "not_due",
        "low",
        "latest_probe_above_warning",
        "STOPPING",
        "ACTIVE",
        "COOLDOWN",
        "WAITING",
        "required_storage",
        "baseline",
        "optional_boost",
        "weekend_comfort",
        "override",
        "holiday",
        "native_thermostat",
        "quiet_overnight",
        "quiet_daytime",
        "quiet_before_decision",
        "before_decision",
        "active_heating",
        "fixed_fallback",
        "no_observation",
        "temperature_unavailable",
        "provisional_range",
        "nominal_only",
        "measured_circuit",
        "inferred",
        "invalid",
        "near_zero_load_floor",
        "load_missing_floor",
        "load_fresh",
        "load_expired_floor",
    }
) | frozenset(WHY)


def code(value):
    return value if isinstance(value, str) and value in CODES | INTERNAL_CODES else "unreported"


# Bridge 1.4.1 scheduling/refresh categories: closed sets, never free text.
POLLING_CODES = frozenset(
    {
        "adaptive",
        "fixed_fallback",
        "fixed",
        "disabled",
        "journal_unavailable",
        "existing",
        "smart",
        "fixed_30",
        "minimum",
        "stable",
        "heating",
        "ct_free",
        "uncertain",
        "before_decision",
        "near_completion",
        "recovery",
        "stable_baseline",
        "stable_off",
        "required_temperature",
        "quiet_before_decision",
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
        "fixed_30_invalid",
        "delay_or_reason_invalid",
        "queued",
        "accepted_for_read",
        "reconnect_read_scheduled",
    }
    | {
        prefix + reason
        for prefix in ("refused_", "dropped_")
        for reason in (
            "invalid_payload",
            "disabled",
            "bridge_offline",
            "awaiting_discovery",
            "authentication_not_ready",
            "accounting_incomplete",
            "backoff_or_quota",
            "unknown_heater",
            "min_spacing",
        )
    }
)


def polling_code(value):
    return value if isinstance(value, str) and value in POLLING_CODES else "unreported"


def code_counts(value):
    """A {category: count} map restricted to known categories."""
    if not isinstance(value, dict):
        return None
    return {
        key: count
        for key, count in value.items()
        if key in POLLING_CODES and type(count) is int and count >= 0
    }


def outcome(value, key):
    if not isinstance(value, dict):
        return None
    at = numeric(value.get("at"))
    return {
        key: polling_code(value.get(key)),
        "at": datetime.fromtimestamp(at, UTC).isoformat() if at is not None else None,
    }


def numeric(value):
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    return value if type(value) in (int, float) and math.isfinite(value) else None


def stamp(value):
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return at.isoformat() if at.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def command(value):
    """Export a transition's meaning, never its topic, identifier or raw payload."""
    value = value if isinstance(value, dict) else {}
    return {
        **{k: code(value.get(k)) for k in ("prior", "target", "status", "reason")},
        **{
            k: stamp(value.get(k))
            for k in ("created_at", "sent_at", "confirmed_at", "resolved_at", "since")
        },
    }


def event(value):
    return {
        "at": stamp(value.get("at")),
        **{k: code(value.get(k)) for k in ("state", "reason", "wanted", "cloud", "command")},
        "bottom_c": numeric(value.get("bottom_c")),
        "grid_import_kw": numeric(value.get("grid_import_kw")),
        "gate": code(value.get("gate")) if value.get("gate") is not None else None,
        "commands_24h": numeric(value.get("commands_24h")),
        "boost_eligible": value.get("boost_eligible")
        if type(value.get("boost_eligible")) is bool
        else None,
        "boost_reason": code(value.get("boost_reason")),
    }


def build(runtime, now, ha_version="unknown"):
    """Collect only explicitly typed, useful fields; no recursive raw-data copying."""
    executor = runtime.executor
    ctl = executor.controller
    obs = executor.last_observation
    values = runtime.values
    opts = runtime.native_options
    decision = executor.last_decision
    plan = decision.plan if decision else {}
    summary = ctl.summary(now)
    health = runtime.hass.states.get(runtime.sources.get("cloud_health", ""))
    attrs = health.attributes if health else {}
    try:
        zone = ZoneInfo(opts["time_zone"]).key
    except (KeyError, ValueError, ZoneInfoNotFoundError):
        zone = "unknown"
    measurements = {}
    for key in ("grid", "pv", "pv_ac", "house", "heater_power", "heater_energy"):
        reading = runtime._reading(key)
        source = runtime.sources.get(key)
        measurements[key] = {
            "source_reference": hashlib.sha256(source.encode()).hexdigest()[:10]
            if isinstance(source, str) and source
            else None,
            "mapped": bool(source),
            "value": numeric(reading.value) if reading else None,
            "unit": reading.unit
            if reading and reading.unit in {"W", "kW", "Wh", "kWh", "MWh"}
            else None,
            "reported_at": stamp(reading.observed_at) if reading else None,
            "restored": bool(reading.restored) if reading else None,
            "fresh_kw": runtime._kw(key, now) if key != "heater_energy" else None,
        }
    counts = attrs.get("request_categories", {})
    counts = counts if isinstance(counts, dict) else {}
    schedule = attrs.get("adaptive_polling")
    schedule = schedule if isinstance(schedule, dict) else {}
    refresh = attrs.get("on_demand_refresh_activity")
    refresh = refresh if isinstance(refresh, dict) else {}
    report = {
        "schema": 1,
        "versions": {
            "controller": "0.17.1",
            "bridge": attrs.get("bridge_version")
            if attrs.get("bridge_version") in {"1.3.17", "1.4.0", "1.4.1"}
            else "unreported",
            "home_assistant": ha_version
            if isinstance(ha_version, str)
            and len(ha_version) < 20
            and all(c in "0123456789.abrcdev-" for c in ha_version)
            else "unreported",
        },
        "generated_at": stamp(now),
        "time_zone": zone,
        "heater": {
            "mode": code(obs.mode if obs else None),
            "target_c": numeric(obs.target_c) if obs else None,
            "last_bottom_c": numeric(obs.temperature_c) if obs else None,
            "observed_at": stamp(obs.poll_at) if obs else None,
            "age_minutes": (now - obs.poll_at).total_seconds() / 60
            if obs and obs.poll_at
            else None,
            "physical_element": code(values.get("heater_meter_state")),
            "measurement_mode": code(values.get("circuit_measurement_mode")),
            "note": "Cloud mode/target and the bottom probe do not prove element ON/OFF, whole-tank temperature or water hygiene.",
        },
        "controller": {
            "automatic": bool(ctl.enabled),
            "state": code(ctl.state),
            "reason": code(decision.reason) if decision else "unreported",
            "explanation": WHY.get(
                decision.reason, code(decision.reason).replace("_", " ").capitalize() + "."
            )
            if decision
            else "Waiting for an observation.",
            "fault": code(ctl.fault or "none"),
            "alerts": [code(v) for v in ctl.active_alerts],
            "gates": [code(v) for v in ctl.gate_failures],
            "override_until": stamp(ctl.guest_until),
            "override_target_c": numeric(ctl.guest_target_c),
            "last_evaluated_at": stamp(executor.last_evaluated_at),
            "ct_free_permission_configured": bool(opts.get("ct_free_solar_verification")),
        },
        "plan": {
            **{
                k: stamp(plan.get(k))
                for k in ("best_start", "latest_start", "soft_target", "next_peak")
            },
            **{
                k: numeric(plan.get(k))
                for k in ("desired_target_c", "heating_hours", "planned_heat_kwh")
            },
            "wanted": code(decision.state) if decision else "unreported",
            "role": code(plan.get("heating_role")),
            "boost_reason": code(plan.get("boost_reason")),
        },
        "preferences": {
            k: opts.get(k) if type(opts.get(k)) is bool else numeric(opts.get(k))
            for k in (
                "baseline_c",
                "normal_storage_c",
                "solar_boost_c",
                "optional_solar_boost",
                "weekend_solar_heating",
                "weekend_pv_start_kw",
                "solar_cooldown_minutes",
                "low_water_warning_c",
                "off_peak_rate",
                "peak_rate",
                "shoulder_rate",
                "feed_in_rate",
                "meter_verified",
                "controller_four_state_qualified",
                "learning_hardware_qualified",
                "tariff_verified",
            )
        },
        "tariff": {
            "profile": code(opts.get("tariff_profile")),
            "clock": code(opts.get("tariff_clock")),
            "current": code(values.get("current_tariff")),
            "price_aud_kwh": numeric(values.get("current_price_aud")),
            "next_change": stamp(values.get("next_tariff_change")),
            "next_kind": code(values.get("next_tariff_kind")),
            "peak_solar_allowed": opts.get("peak_heating_policy") == "Verified solar-only heating",
        },
        "measurements": measurements,
        "forecast": {
            "age_minutes": numeric(values.get("forecast_age_minutes")),
            "quality": code(values.get("forecast_load_quality")),
            "net_surplus_kw": numeric(values.get("forecast_net_surplus_kw")),
        },
        "commands": {
            "last": command(summary.get("last_command")),
            "pending": command(summary.get("pending_intent"))
            if summary.get("pending_intent")
            else None,
            "protective_exit": command(summary.get("protective_exit"))
            if summary.get("protective_exit")
            else None,
            "count_24h": numeric(summary.get("commands_last_24h")),
            "parked_off_restore_since": stamp(summary.get("parked_off_restore_since")),
        },
        "cloud": {
            "health": code(obs.cloud_health) if obs else "unreported",
            "authentication": code(obs.auth_mode) if obs else "unreported",
            "last_status_success": stamp(obs.poll_at) if obs else None,
            "requests_24h": numeric(summary.get("requests_last_24h")),
            "requests_since_start": numeric(attrs.get("request_attempts")),
            "remaining_request_budget": max(
                0, executor.cfg.max_requests_per_day - summary["requests_last_24h"]
            )
            if summary.get("requests_last_24h") is not None
            else None,
            "operations": {
                k: numeric(counts.get(k))
                for k in (
                    "status",
                    "command_refresh",
                    "confirmation",
                    "command",
                    "token_refresh",
                    "password_login",
                    "discovery",
                )
            },
        },
        "polling": {
            # One polling configuration (D2): the app's option is the choice;
            # Smart selected but "fixed_fallback" means no plan is in force.
            "bridge_preference": polling_code(attrs.get("polling_preference")),
            "actual_mode": polling_code(attrs.get("polling_mode")),
            "actual_reason": polling_code(attrs.get("polling_reason")),
            "plans_accepted": numeric(schedule.get("counts", {}).get("accepted"))
            if isinstance(schedule.get("counts"), dict)
            else None,
            "plans_rejected": numeric(schedule.get("counts", {}).get("rejected"))
            if isinstance(schedule.get("counts"), dict)
            else None,
            "rejection_reasons_since_bridge_start": code_counts(schedule.get("rejection_reasons")),
            "last_rejection": outcome(schedule.get("last_rejection"), "reason"),
            "last_acceptance": outcome(schedule.get("last_acceptance"), "reason"),
            "on_demand_refresh_enabled": attrs.get("on_demand_refresh_enabled")
            if isinstance(attrs.get("on_demand_refresh_enabled"), bool)
            else None,
            "refresh_outcomes_since_bridge_start": code_counts(refresh.get("outcomes")),
            "last_refresh": outcome(refresh.get("last"), "result"),
            "next_observation": stamp(values.get("next_cloud_poll")),
            "interval_seconds": numeric(values.get("cloud_poll_interval")),
            "note": "Quiet Smart nights can delay detecting an app change up to 8 hours (experimental minimum: 12 hours). Every command still checks its exact prior and confirms.",
        },
        "events": [
            event(v)
            for v in list(getattr(runtime, "owner_events", ()))[-200:]
            if isinstance(v, dict)
        ],
        "privacy": "Source names, account/device identifiers, MQTT addresses and raw responses are omitted. Review before sharing; HA's download wrapper can include its own system metadata.",
    }
    return report


def text_report(report):
    return (
        "Thermowatt diagnostic report\nCopy all of this report; no heater command is sent.\n\n"
        + json.dumps(report, indent=2, ensure_ascii=False)
    )
