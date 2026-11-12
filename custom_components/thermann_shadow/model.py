"""Deterministic shadow scenarios. No I/O, actuation, quota resets or HA dependency.

The uniform-tank model is NOT a usable-water reserve or hygiene measurement.
Plans are advisory counterfactuals while native Schedule retains all ownership.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

HOBART = ZoneInfo("Australia/Hobart")
STANDARD = timezone(timedelta(hours=10))
UTC = timezone.utc
TANK_KWH_PER_C = 315 * 4.186 / 3600
ELEMENT_KW = 3.0


@dataclass(frozen=True)
class Reading:
    value: object
    observed_at: datetime
    unit: str | None = None
    restored: bool = False


@dataclass(frozen=True)
class Tariff:
    days: tuple[int, ...]
    start: int  # wall minutes, inclusive; overnight periods belong to start day
    end: int  # exclusive; equal start/end means 24 hours
    rate: float  # AUD/kWh; no vendor tariff is assumed
    kind: str


@dataclass(frozen=True)
class Forecast:
    start: datetime
    end: datetime
    export_kw: float  # forecast NET export, after household load; never PV alone


@dataclass(frozen=True)
class Settings:
    meter_verified: bool = False
    tariff_verified: bool = False
    paused: bool = False
    import_positive: bool = True
    tariff_clock: str = "local"
    target_c: float = 70.0  # model target only; never a heater setpoint
    morning_threshold_c: float = 42.0  # HARD morning minimum; NEVER a storage setpoint
    morning_preferred_c: float = 45.0  # preferred morning reserve (soft); NEVER a setpoint
    expected_native_target_c: float = 70.0
    margin_minutes: float = 30.0
    feed_in_rate: float = 0.08
    export_headroom_kw: float = 0.3
    status_max_age_minutes: float = 45.0
    grid_max_age_seconds: float = 120.0
    solar_hold_minutes: float = 10.0
    solar_window_minutes: float = 15.0
    min_solar_kw: float = 0.1
    switching_benefit_aud: float = 0.10
    solar_loss_minutes: float = 20.0
    minimum_cycle_minutes: float = 30.0
    minimum_gap_minutes: float = 30.0
    forecast_enabled: bool = False
    forecast_uncertainty: float = 0.25
    forecast_max_age_minutes: float = 120.0
    forecast_house_margin_kw: float = 0.3
    expected_morning_draw_c: float = 10.0  # owner assumption, not a measurement
    standing_loss_c_per_hour: float = 0.2  # owner assumption, not a measurement
    wait_benefit_aud_per_kwh: float = 0.05
    pv_ac_limit_kw: float = 5.0  # one GoodWe GW5000 inverter, shared by both arrays
    base_load_source: str = "measured_only"
    shower_time_enabled: bool = False
    # Household times used when a day has no peak (weekends); the weekday
    # deadlines follow the tariff's actual peak starts (fixed AEST).
    morning: time = time(8)
    evening: time = time(16)
    shower_time: time = time(7)
    # 0.7.0 morning comfort, EVERY day (Hobart local): at least the morning
    # threshold by the preferred time; the hard deadline is never abandoned
    # when the preferred time is missed.
    morning_preferred: time = time(6)
    morning_hard: time = time(7)


@dataclass
class Plan:
    state: str = "shadow_blocked"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(
        default_factory=lambda: [
            "shadow_only_no_commands",
            "bottom_sensor_not_whole_tank_reserve",
            "thermal_model_unqualified",
            "hygiene_and_native_fallback_unverified",
            "cloud_read_time_not_device_sample_time",
            "native_schedule_still_controls_heater",
            "thermostat_hysteresis_can_prevent_heating",
        ]
    )
    deadline: datetime | None = None
    comfort_deadline: datetime | None = None
    peak_start: datetime | None = None
    deadline_kind: str | None = None
    planned_start: datetime | None = None
    latest_start: datetime | None = None
    grid_fallback_start: datetime | None = None
    planning_target_c: float | None = None
    current_tariff: str | None = None
    current_price_aud: float | None = None
    recommended_energy_source: str | None = None
    mixed_model_energy_kwh: float | None = None
    modelled_heating_minutes: float | None = None
    estimated_import_kwh: float | None = None
    estimated_solar_kwh: float | None = None
    unmet_model_energy_kwh: float | None = None
    estimated_cost_aud: float | None = None
    comparison_cost_difference_aud: float | None = None
    net_export_kw: float | None = None
    status_age_minutes: float | None = None
    windows: list[dict[str, str | float]] = field(default_factory=list)


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        raise ValueError("number_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("number_invalid")
    return result


def aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_invalid")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not aware(result):
        raise ValueError("timestamp_invalid")
    return result.astimezone(UTC)


_TARIFF_CACHE: dict[tuple[float, int, str], tuple[tuple[Tariff, ...], Tariff]] = {}


def tariff_at(at: datetime, tariffs: tuple[Tariff, ...], clock: str) -> Tariff:
    # Tariffs change on wall-minute boundaries only: memoise per UTC minute and
    # tariff-table identity (the cached entry holds the table, so ids stay valid).
    key = (at.timestamp() // 60, id(tariffs), clock)
    hit = _TARIFF_CACHE.get(key)
    if hit is not None and hit[0] is tariffs:
        return hit[1]
    result = _tariff_at_minute(at, tariffs, clock)
    if len(_TARIFF_CACHE) >= 50000:
        _TARIFF_CACHE.clear()
    _TARIFF_CACHE[key] = (tariffs, result)
    return result


def _tariff_at_minute(at: datetime, tariffs: tuple[Tariff, ...], clock: str) -> Tariff:
    local = at.astimezone(HOBART if clock == "local" else STANDARD)
    minute = local.hour * 60 + local.minute
    matches = []
    for item in tariffs:
        today = local.weekday() in item.days
        previous = (local.weekday() - 1) % 7 in item.days
        if (
            (item.start < item.end and today and item.start <= minute < item.end)
            or (
                item.start > item.end
                and ((today and minute >= item.start) or (previous and minute < item.end))
            )
            or (item.start == item.end and today)
        ):
            matches.append(item)
    if len(matches) != 1:
        raise ValueError("tariff_gap_or_overlap")
    return matches[0]


def validate_tariffs(tariffs: tuple[Tariff, ...], clock: str) -> None:
    if clock not in {"local", "standard"} or not 1 <= len(tariffs) <= 32:
        raise ValueError("tariff_invalid")
    for item in tariffs:
        if (
            not item.days
            or any(type(day) is not int or not 0 <= day <= 6 for day in item.days)
            or len(set(item.days)) != len(item.days)
            or not 0 <= item.start < 1440
            or not 0 <= item.end < 1440
            or not math.isfinite(item.rate)
            or not -5 <= item.rate <= 10
            or item.kind not in {"off_peak", "shoulder", "peak"}
        ):
            raise ValueError("tariff_invalid")
    # A whole local week, outside DST, proves minute coverage including overnight
    # weekday/weekend boundaries. Runtime UTC iteration also covers both DST folds.
    start = datetime(2026, 6, 1, tzinfo=HOBART if clock == "local" else STANDARD)
    for minute in range(7 * 1440):
        tariff_at(start + timedelta(minutes=minute), tariffs, clock)


def _fresh(reading: Reading, now: datetime, boot: datetime, seconds: float) -> None:
    if (
        reading.restored
        or not aware(reading.observed_at)
        or reading.observed_at < boot
        or not 0 <= (now - reading.observed_at).total_seconds() <= seconds
    ):
        raise ValueError("input_stale_or_restored")


def _present(reading: Reading) -> None:
    if reading.restored or not aware(reading.observed_at):
        raise ValueError("input_stale_or_restored")


def _power(reading: Reading) -> float:
    if reading.unit not in {"W", "kW"}:
        raise ValueError("grid_power_unit_invalid")
    result = number(reading.value) / (1000 if reading.unit == "W" else 1)
    if abs(result) > 30:
        raise ValueError("grid_power_out_of_range")
    return result


def _deadline(
    now: datetime, settings: Settings, tariffs: tuple[Tariff, ...]
) -> tuple[datetime, str, datetime, datetime | None]:
    local = now.astimezone(HOBART)
    candidates = []
    for day in (local.date(), local.date() + timedelta(days=1)):
        morning = datetime.combine(day, settings.morning, HOBART).astimezone(UTC)
        evening = datetime.combine(day, settings.evening, HOBART).astimezone(UTC)
        # Tariff deadline is independent of the household's nominal 16:00 time.
        start = datetime.combine(day, time(12), HOBART).astimezone(UTC)
        peak = None
        for step in range(12 * 60) if settings.tariff_verified else ():
            instant = start + timedelta(minutes=step)
            if instant.astimezone(HOBART).date() != day:
                break
            if tariff_at(instant, tariffs, settings.tariff_clock).kind == "peak":
                evening = instant
                peak = instant
                break
        comfort_evening = datetime.combine(day, settings.evening, HOBART).astimezone(UTC)
        candidates.extend(
            [
                (morning, "morning_0700", morning, None),
                (evening, "afternoon_peak" if peak else "afternoon_comfort", comfort_evening, peak),
            ]
        )
    return min(item for item in candidates if item[0] > now)


def validate_settings(settings: Settings) -> None:
    if (
        any(
            type(getattr(settings, key)) is not bool
            for key in (
                "paused",
                "meter_verified",
                "tariff_verified",
                "import_positive",
                "forecast_enabled",
                "shower_time_enabled",
            )
        )
        or settings.tariff_clock not in {"local", "standard"}
        or settings.base_load_source not in {"measured_only", "measured_then_published"}
        or not 0 <= settings.expected_morning_draw_c <= 40
        or not 0 <= settings.standing_loss_c_per_hour <= 2
        or not 0 <= settings.wait_benefit_aud_per_kwh <= 0.5
        or not 1 <= settings.pv_ac_limit_kw <= 30
        or not isinstance(settings.shower_time, time)
        or settings.shower_time.tzinfo is not None
        or not time(0) <= settings.shower_time <= time(11, 59)
        or not 65 <= settings.target_c <= 70
        or not 30 <= settings.morning_threshold_c <= 60
        or not settings.morning_threshold_c <= settings.morning_preferred_c <= 60
        or not 20 <= settings.expected_native_target_c <= 75
        or not 0 <= settings.margin_minutes <= 120
        or not 30 <= settings.status_max_age_minutes <= 90
        or not 30 <= settings.grid_max_age_seconds <= 300
        or not 0 <= settings.export_headroom_kw <= 3
        or not 0 <= settings.feed_in_rate <= 2
        or not 5 <= settings.solar_hold_minutes <= 30
        or not 5 <= settings.solar_window_minutes <= 30
        or not 0 <= settings.min_solar_kw <= 3
        or not 0 <= settings.switching_benefit_aud <= 5
        or not 0 <= settings.solar_loss_minutes <= 120
        or not 0 <= settings.minimum_cycle_minutes <= 180
        or not 0 <= settings.minimum_gap_minutes <= 180
        or not 0 <= settings.forecast_uncertainty <= 0.9
        or not 15 <= settings.forecast_max_age_minutes <= 360
        or not 0 <= settings.forecast_house_margin_kw <= 5
        or not isinstance(settings.morning, time)
        or settings.morning.tzinfo is not None
        or not isinstance(settings.evening, time)
        or settings.evening.tzinfo is not None
        or not time(0) <= settings.morning <= time(11, 59)
        or any(
            not isinstance(value, time) or value.tzinfo is not None
            for value in (settings.morning_preferred, settings.morning_hard)
        )
        or not time(0) <= settings.morning_preferred <= settings.morning_hard <= time(11, 59)
        or not time(12) <= settings.evening <= time(23, 59)
    ):
        raise ValueError("settings_invalid")


def evaluate(
    now: datetime,
    boot: datetime,
    readings: dict[str, Reading],
    settings: Settings,
    tariffs: tuple[Tariff, ...],
    forecast: tuple[Forecast, ...] = (),
    intervention: bool = False,
    solar_confirmed: bool = False,
    controlled: bool = False,
) -> Plan:
    """Local planning only. Never enact a window or request a cloud update.

    ``controlled``: the production controller is active. It supervises the
    heater mode itself (Manual 70 / OFF are its own states; anything else is
    owner override), so the shadow-era "native Schedule expected" check and
    the intervention latch must not gate the planner then."""
    plan = Plan()
    if not aware(now) or not aware(boot):
        plan.reasons.append("clock_invalid")
        return plan
    if settings.paused:
        plan.state = "shadow_paused"
        plan.reasons.append("owner_paused")
        return plan
    try:
        validate_settings(settings)
        # Cloud-derived readings come from ONE bridge STATUS publish. HA's MQTT
        # entities do not rewrite state for identical payloads, so entity report
        # times say nothing about freshness (Stage 1 F1). The bridge's poll
        # timestamp is the evidence: readings are valid while that poll is fresh.
        # A retained status re-delivered after an HA restart keeps its real poll
        # time, so it is neither rejected nor made to look newer than it is.
        for key in ("temperature", "target", "mode", "cloud_health", "last_poll"):
            _present(readings[key])
        poll_at = timestamp(readings["last_poll"].value)
        plan.status_age_minutes = (now - poll_at).total_seconds() / 60
        if not 0 <= plan.status_age_minutes <= settings.status_max_age_minutes:
            raise ValueError("status_stale_or_pre_restart")
        if readings["cloud_health"].value != "ok":
            raise ValueError("cloud_not_healthy")
        temperature = number(readings["temperature"].value)
        target = number(readings["target"].value)
        if readings["temperature"].unit != "°C" or readings["target"].unit != "°C":
            raise ValueError("temperature_unit_invalid")
        if not 0 <= temperature <= 100 or not 20 <= target <= 75:
            raise ValueError("temperature_out_of_range")
        if not controlled and (
            readings["mode"].value != "Schedule"
            or target != settings.expected_native_target_c
            or intervention
        ):
            plan.state = "shadow_native_intervention"
            plan.reasons.append("native_mode_or_target_changed_review_required")
            return plan
        if "grid" in readings:
            grid = readings["grid"]
            _fresh(grid, now, boot, settings.grid_max_age_seconds)
            export = _power(grid) * (-1 if settings.import_positive else 1)
        else:
            imported, exported = readings["grid_import"], readings["grid_export"]
            for reading in (imported, exported):
                _fresh(reading, now, boot, settings.grid_max_age_seconds)
                if _power(reading) < 0:
                    raise ValueError("split_grid_power_negative")
            export = _power(exported) - _power(imported)
        plan.net_export_kw = round(export, 3)
        from .goals import upcoming_goals

        goal = upcoming_goals(now, settings, tariffs)[0]
        plan.deadline = goal.deadline
        plan.deadline_kind = (
            "morning"
            if goal.kind == "morning"
            else ("afternoon_peak" if goal.peak_start else "afternoon_comfort")
        )
        plan.comfort_deadline = goal.deadline
        plan.peak_start = goal.peak_start
        plan.planning_target_c = goal.target_c
        active_tariff = tariff_at(now, tariffs, settings.tariff_clock)
        if settings.tariff_verified:
            plan.current_tariff, plan.current_price_aud = active_tariff.kind, active_tariff.rate
        energy = max(0.0, plan.planning_target_c - temperature) * TANK_KWH_PER_C
        required = energy + (ELEMENT_KW * settings.margin_minutes / 60 if energy else 0)
        plan.mixed_model_energy_kwh = round(energy, 3)
        plan.modelled_heating_minutes = round(required / ELEMENT_KW * 60, 1)
        plan.latest_start = (
            plan.deadline - timedelta(hours=required / ELEMENT_KW) if required else None
        )
        if not settings.meter_verified or not settings.tariff_verified:
            plan.state = "shadow_awaiting_validation"
            plan.reasons.append("verify_meter_sign_units_and_tariff")
            return plan
        if len(forecast) > 576:
            raise ValueError("forecast_invalid")
        previous_end = now
        for item in forecast:
            if (
                not aware(item.start)
                or not aware(item.end)
                or item.start < previous_end
                or item.end <= item.start
                or item.end > now + timedelta(hours=48)
                or not math.isfinite(item.export_kw)
                or not 0 <= item.export_kw <= 30
            ):
                raise ValueError("forecast_invalid")
            previous_end = item.end
        if not forecast:
            plan.warnings.append("no_net_surplus_forecast_current_export_not_extrapolated")
        plan.warnings.append("bottom_temperature_used_directly_planning_estimate_only")
        plan.warnings.append("morning_threshold_is_comfort_criterion_not_storage_setpoint")
        if (
            plan.deadline_kind != "morning"
            and settings.target_c - 8 < temperature < settings.target_c
        ):
            plan.warnings.append("within_thermostat_hysteresis_no_forced_heating_verified")
        if required == 0:
            plan.state = "shadow_no_modelled_topup"
            plan.reasons.append(
                "morning_threshold_met_no_morning_heat_required"
                if plan.deadline_kind == "morning"
                else "storage_target_met_no_topup_required"
            )
            plan.recommended_energy_source = "none"
            plan.estimated_import_kwh = plan.estimated_solar_kwh = plan.unmet_model_energy_kwh = 0
            plan.estimated_cost_aud = plan.comparison_cost_difference_aud = 0
            return plan
        slots = []
        cursor = now.astimezone(UTC)
        current_rate = tariff_at(cursor, tariffs, settings.tariff_clock).rate
        while cursor < plan.deadline:
            # Split at every wall-minute boundary, including unusual tariff
            # boundaries. Never charge a whole slot at its initial tariff.
            end = min(cursor.replace(second=0, microsecond=0) + timedelta(minutes=1), plan.deadline)
            for item in forecast:
                if cursor < item.start < end:
                    end = item.start
                if cursor < item.end < end:
                    end = item.end
            tariff = tariff_at(cursor, tariffs, settings.tariff_clock)
            # Only a bounded recent-export scenario, never a whole-day forecast.
            surplus = (
                max(0.0, export - settings.export_headroom_kw)
                if solar_confirmed
                and cursor < now + timedelta(minutes=settings.solar_window_minutes)
                else 0.0
            )
            for item in forecast:
                if item.start <= cursor and item.end >= end:
                    # Headroom is for MEASURED surplus; forecasts carry their own
                    # uncertainty and household margin (no double deduction).
                    surplus = max(0.0, item.export_kw)
                    break
            # Element is a full 3 kW load; fraction describes its energy source,
            # never variable element power or a modulated command.
            solar_fraction = min(1.0, surplus / ELEMENT_KW)
            unit_cost = tariff.rate * (1 - solar_fraction) + settings.feed_in_rate * solar_fraction
            capacity = ELEMENT_KW * (end - cursor).total_seconds() / 3600
            slots.append(
                (solar_fraction < 1, unit_cost, cursor, end, capacity, solar_fraction, tariff.kind)
            )
            cursor = end
        # Reserve a full off-peak fallback independently of any future forecast.
        # Latest-first on equal prices leaves time for solar without missing duty.
        backup_remaining = required
        backup_start = now
        for slot in reversed(slots):
            if slot[6] != "off_peak":
                continue
            amount = min(backup_remaining, slot[4])
            backup_start = slot[3] - timedelta(hours=amount / ELEMENT_KW)
            backup_remaining -= amount
            if backup_remaining <= 1e-8:
                break
        plan.grid_fallback_start = (
            backup_start
            if backup_remaining <= 1e-8
            else max(now, plan.deadline - timedelta(hours=required / ELEMENT_KW))
        )
        force_now = now >= plan.grid_fallback_start
        if backup_remaining > 1e-8:
            plan.warnings.append("insufficient_off_peak_time_comfort_priority")
        if export >= ELEMENT_KW + settings.export_headroom_kw and not solar_confirmed:
            plan.warnings.append("solar_export_hold_not_yet_satisfied")
        if solar_confirmed:
            plan.warnings.append("recent_export_window_is_assumption_not_forecast")
        remaining, imported_kwh, solar_kwh, cost = required, 0.0, 0.0, 0.0
        selected = []
        ordered = (
            sorted(slots, key=lambda slot: slot[2])
            if force_now
            else sorted(
                slots,
                key=lambda slot: (
                    slot[1],
                    slot[2].timestamp() if slot[5] > 0 else -slot[2].timestamp(),
                ),
            )
        )
        for _, unit_cost, start, end, capacity, fraction, kind in ordered:
            amount = min(remaining, capacity)
            if amount <= 1e-8:
                break
            if not force_now and fraction < 1:
                start = end - timedelta(hours=amount / ELEMENT_KW)
                finish = end
            else:
                finish = start + (end - start) * (amount / capacity)
            selected.append((start, finish, fraction, kind))
            solar_kwh += amount * fraction
            imported_kwh += amount * (1 - fraction)
            cost += amount * unit_cost
            remaining -= amount
        for start, end, fraction, kind in sorted(selected):
            source = "net_solar" if fraction == 1 else "mixed" if fraction else kind
            if (
                plan.windows
                and plan.windows[-1]["end"] == start.isoformat()
                and plan.windows[-1]["source"] == source
            ):
                plan.windows[-1]["end"] = end.isoformat()
            else:
                plan.windows.append(
                    {"start": start.isoformat(), "end": end.isoformat(), "source": source}
                )
        plan.planned_start = min((item[0] for item in selected), default=None)
        plan.estimated_import_kwh = round(imported_kwh, 3)
        plan.estimated_solar_kwh = round(solar_kwh, 3)
        plan.estimated_cost_aud = round(cost, 3)
        plan.unmet_model_energy_kwh = round(max(0.0, remaining), 3)
        plan.recommended_energy_source = (
            "net_solar" if imported_kwh < 1e-8 else "mixed" if solar_kwh > 1e-8 else "grid"
        )
        # Unserved energy is a shortfall, never a saving.
        plan.comparison_cost_difference_aud = round((required - remaining) * current_rate - cost, 3)
        if remaining > 1e-8:
            plan.state = "shadow_shortfall"
            plan.reasons.append("insufficient_modelled_heating_time_before_deadline")
            plan.warnings.append("comfort_at_risk_native_or_owner_action_required")
        elif plan.planned_start == now:
            plan.state = (
                "shadow_solar_opportunity"
                if export >= ELEMENT_KW + settings.export_headroom_kw
                else "shadow_heat_now"
            )
            plan.reasons.append("full_3kW_heating_window_now_no_command_sent")
        else:
            plan.state = "shadow_wait_for_window"
            plan.reasons.append("solar_first_then_lowest_cost_slots_before_deadline")
        plan.warnings.append("hypothetical_windows_not_executable_schedule")
    except KeyError:
        plan.reasons.append("required_mapping_missing")
    except (ValueError, TypeError, OverflowError) as error:
        # Fixed categories only; do not return raw HA states or exception strings.
        safe_codes = {
            "clock_invalid",
            "settings_invalid",
            "input_stale_or_restored",
            "status_stale_or_pre_restart",
            "cloud_not_healthy",
            "temperature_unit_invalid",
            "temperature_out_of_range",
            "grid_power_unit_invalid",
            "grid_power_out_of_range",
            "split_grid_power_negative",
            "forecast_invalid",
            "tariff_gap_or_overlap",
            "timestamp_invalid",
            "number_invalid",
        }
        code = error.args[0] if error.args and isinstance(error.args[0], str) else None
        plan.reasons.append(code if code in safe_codes else "input_or_configuration_invalid")
    return plan
