"""Read HA states only, on a fixed local timer. Never call services or a transport."""

from dataclasses import asdict
from collections import deque
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .model import Plan, Reading, evaluate, number, _fresh, _power
from .config import DEFAULT_OPTIONS
from .native import parse_native, permitted_minutes, scheduled_permission
from .forecast import build_forecast
from .cycles import CyclePolicy
from .decision import decide
from .settings import BACKUP_KEY, describe

# Measured-vs-forecast PV correction uses a short rolling mean, so one passing
# cloud sample cannot discard the whole horizon. Window is deliberately fixed.
PV_AVERAGE_MINUTES = 15


class ShadowRuntime:
    def __init__(self, hass, sources, settings, tariffs):
        self.hass = hass
        self.sources = sources
        self.settings = settings
        self.tariffs = tariffs
        self.boot = dt_util.utcnow()
        self.plan = Plan(reasons=["awaiting_post_restart_inputs"])
        self.values = {}
        self.details = {}
        self.listeners = set()
        self.last_native = None
        self.intervention = False
        self.first_count = None
        self.last_count = None
        self.count_started = None
        self.solar_samples = deque(maxlen=121)
        self.pv_samples = deque(maxlen=64)  # (observed_at, kW), fresh distinct reports
        self.cycle = CyclePolicy()
        self.set_native_reference({})

    def set_native_reference(self, options):
        self.native_options = {**DEFAULT_OPTIONS, **options}
        self.native_periods = parse_native(self.native_options["native_schedule_periods"])

    def apply_options(self, options, sources):
        from .config import parse_options

        settings, tariffs = parse_options(options)
        changed_mapping = dict(sources) != dict(self.sources)
        if changed_mapping or settings != self.settings or tariffs != self.tariffs:
            self.cycle = CyclePolicy()
            self.solar_samples.clear()
            self.pv_samples.clear()
        if changed_mapping:
            self.boot = dt_util.utcnow()
            self.last_native = None
        self.sources, self.settings, self.tariffs = sources, settings, tariffs
        self.set_native_reference(options)
        self.update(dt_util.utcnow())

    def _reading(self, key, attribute=None):
        entity_id = self.sources.get(key)
        if not isinstance(entity_id, str):
            return None
        state = self.hass.states.get(entity_id)
        # Schedule is deliberately Unknown on the water_heater entity. Its
        # numeric attributes remain useful; mode comes from the vendor sensor.
        if (
            state is None
            or state.state == "unavailable"
            or (attribute is None and state.state == "unknown")
        ):
            return None
        unit = state.attributes.get("unit_of_measurement")
        if key == "heater":
            unit = self.hass.config.units.temperature_unit
        return Reading(
            state.attributes.get(attribute) if attribute else state.state,
            state.last_reported,
            unit,
            bool(state.attributes.get("restored", False)),
        )

    def update(self, now):
        readings = {}
        for key in ("grid", "mode", "last_poll", "cloud_health"):
            if reading := self._reading(key):
                readings[key] = reading
        for key, attribute in (("temperature", "current_temperature"), ("target", "temperature")):
            if reading := self._reading("heater", attribute):
                readings[key] = reading
        # New mode/target on a new cloud sample is an owner/native intervention,
        # never an invitation to acquire control. Latch until configuration review.
        native = tuple(
            readings[key].value if key in readings else None for key in ("mode", "target")
        )
        try:
            native = (native[0], number(native[1]))
        except (ValueError, TypeError, OverflowError):
            native = (None, None)
        if all(item is not None for item in native):
            if self.last_native is not None and self.last_native != native:
                self.intervention = True
            self.last_native = native
        solar_confirmed = False
        try:
            grid = readings["grid"]
            _fresh(grid, now, self.boot, self.settings.grid_max_age_seconds)
            export = _power(grid) * (-1 if self.settings.import_positive else 1)
            if (
                not self.settings.meter_verified
                or export < self.settings.min_solar_kw + self.settings.export_headroom_kw
            ):
                self.solar_samples.clear()
            else:
                if self.solar_samples and (
                    grid.observed_at < self.solar_samples[-1]
                    or (grid.observed_at - self.solar_samples[-1]).total_seconds()
                    > self.settings.grid_max_age_seconds
                ):
                    self.solar_samples.clear()
                if not self.solar_samples or grid.observed_at > self.solar_samples[-1]:
                    self.solar_samples.append(grid.observed_at)
                solar_confirmed = (
                    self.solar_samples[-1] - self.solar_samples[0]
                ).total_seconds() >= self.settings.solar_hold_minutes * 60
        except (KeyError, ValueError, TypeError, OverflowError):
            self.solar_samples.clear()
        measured_pv = None
        try:
            pv = self._reading("pv")
            if pv:
                _fresh(pv, now, self.boot, self.settings.grid_max_age_seconds)
                value = _power(pv)
                if value < 0:
                    raise ValueError("pv_negative")
                if not self.pv_samples or pv.observed_at > self.pv_samples[-1][0]:
                    self.pv_samples.append((pv.observed_at, value))
        except (ValueError, TypeError, OverflowError):
            pass
        while self.pv_samples and now - self.pv_samples[0][0] > timedelta(
            minutes=PV_AVERAGE_MINUTES
        ):
            self.pv_samples.popleft()
        if self.pv_samples and now - self.pv_samples[-1][0] <= timedelta(
            seconds=self.settings.grid_max_age_seconds
        ):
            measured_pv = sum(value for _, value in self.pv_samples) / len(self.pv_samples)
        self.forecast = build_forecast(
            now,
            self.boot,
            self.settings,
            self.hass.states.get(self.sources.get("forecast_pv", "")),
            self.hass.states.get(self.sources.get("forecast_load", "")),
            measured_pv,
        )
        self.forecast.measured_pv_average_kw = (
            None if measured_pv is None else round(measured_pv, 3)
        )
        self.plan = evaluate(
            now,
            self.boot,
            readings,
            self.settings,
            self.tariffs,
            forecast=self.forecast.slots,
            intervention=self.intervention,
            solar_confirmed=solar_confirmed,
        )
        self.plan.warnings.extend(self.forecast.warnings)
        cycle = self.cycle.step(
            now,
            self.plan,
            self.settings,
            self.tariffs,
            self.forecast.slots,
            readings["grid"].observed_at if "grid" in readings else None,
        )
        solar_benefit = cycle["benefit_vs_grid_alternative_aud"]
        if (
            not self.forecast.slots
            and solar_benefit is not None
            and 0 < solar_benefit < self.settings.switching_benefit_aud
            and (self.plan.net_export_kw or 0) - self.settings.export_headroom_kw
            >= self.settings.min_solar_kw
        ):
            # Honest limitation, not a silent default change: without a forecast,
            # only solar_window_minutes of measured surplus is credited, which can
            # cap the benefit below the owner's switching threshold.
            self.plan.warnings.append("measured_only_solar_benefit_below_switching_threshold")
        code, label, explanation = decide(
            self.plan,
            cycle,
            self.cycle.active,
            self.settings.forecast_enabled,
            self.forecast.source,
            self.settings,
        )
        self.values = asdict(self.plan)
        self.values.update(
            {
                "recommendation": label,
                "decision": code,
                "simulated_cycle_state": cycle["state"],
                "simulated_cycle_count": self.cycle.starts,
                "simulated_stop_count": self.cycle.stops,
                "suppressed_switching_episodes": self.cycle.suppressed_edges,
                "simulated_cost_aud": cycle["simulated_cost_aud_session"],
                "benefit_of_now_aud": cycle["benefit_of_now_aud"],
                "continuing_cost_aud": cycle["continuing_cost_aud"],
                "later_cost_aud": cycle["later_cost_aud"],
                "forecast_net_surplus_kw": self.forecast.slots[0].export_kw
                if self.forecast.slots
                else None,
                "forecast_age_minutes": self.forecast.age_minutes,
                "forecast_usable_solar_kwh": _usable_solar(
                    self.forecast.slots, now, self.plan.deadline, self.settings
                ),
                "deadline_countdown_minutes": max(
                    0, round((self.plan.deadline - now).total_seconds() / 60)
                )
                if self.plan.deadline
                else None,
                "completion_time": datetime.fromisoformat(cycle["estimated_completion"])
                if cycle["estimated_completion"]
                else None,
            }
        )
        self.values["controller"] = self.plan.state
        self.values["morning_threshold_c"] = self.settings.morning_threshold_c
        self.values["storage_target_c"] = self.settings.target_c
        health = readings.get("cloud_health", Reading("unavailable", now)).value
        self.values["cloud_health"] = (
            health
            if health
            in {"ok", "disabled", "auth_locked", "quota_limited", "backoff", "unavailable"}
            else "unrecognised"
        )
        for key in ("temperature", "target", "pv", "house", "grid"):
            reading = (
                readings.get(key)
                if key in {"temperature", "target", "grid"}
                else self._reading(key)
            )
            value = None
            try:
                max_age = (
                    self.settings.status_max_age_minutes * 60
                    if key in {"temperature", "target"}
                    else self.settings.grid_max_age_seconds
                )
                if (
                    reading
                    and not reading.restored
                    and reading.observed_at >= self.boot
                    and 0 <= (now - reading.observed_at).total_seconds() <= max_age
                ):
                    value = number(reading.value)
                    if key in {"pv", "house", "grid"}:
                        value = (
                            value / 1000
                            if reading.unit == "W"
                            else value
                            if reading.unit == "kW"
                            else None
                        )
                    if key in {"temperature", "target"} and reading.unit != "°C":
                        value = None
            except (ValueError, TypeError, OverflowError):
                pass
            self.values[key] = value
        # Signed raw grid is displayed unchanged. Derived export/import explicitly
        # uses the owner's editable, provisionally identified sign convention.
        grid = self.values.get("grid")
        self.values["measured_net_export_kw"] = (
            None if grid is None else grid * (-1 if self.settings.import_positive else 1)
        )
        net = self.values["measured_net_export_kw"]
        self.values["measured_import_kw"] = None if net is None else max(0, -net)
        self.values["measured_export_kw"] = None if net is None else max(0, net)
        self.values["requests_since_start"] = None
        self.values["observed_requests_per_hour"] = None
        count_reading = self._reading("requests")
        count_warning = None
        if count_reading and not count_reading.restored:
            try:
                count = number(count_reading.value)
                if (
                    count < 0
                    or count != int(count)
                    or not 0 <= (now - count_reading.observed_at).total_seconds() <= 300
                ):
                    raise ValueError
                if self.last_count is not None and count < self.last_count:
                    self.first_count = self.count_started = None
                    count_warning = "request_counter_reset_history_incomplete"
                if self.first_count is None:
                    self.first_count, self.count_started = count, now
                self.last_count = count
                self.values["requests_since_start"] = count - self.first_count
                hours = (now - self.count_started).total_seconds() / 3600
                if hours >= 0.5:
                    self.values["observed_requests_per_hour"] = round(
                        (count - self.first_count) / hours, 2
                    )
            except (ValueError, TypeError, OverflowError):
                count_warning = "request_accounting_unavailable"
        else:
            count_warning = "request_accounting_unavailable"
        if count_warning:
            self.plan.warnings.append(count_warning)
        self.values["native_schedule_window"] = (
            scheduled_permission(
                now, self.native_periods, self.native_options["native_schedule_clock"]
            )
            if readings.get("mode") and readings["mode"].value == "Schedule"
            else "unknown_not_schedule"
        )
        self.values["t_comfort_reference_c"] = self.native_options["t_comfort_reference_c"]
        temperature = self.values.get("temperature")
        if (
            self.values["native_schedule_window"] == "within_reported_window"
            and temperature is not None
            and temperature < self.settings.expected_native_target_c - 8
        ):
            # The native thermostat may already be calling for heat, so the
            # measured grid can include the REAL 3 kW element. The planner does not
            # de-embed an unverified load: solar economics are then understated.
            self.plan.warnings.append("measured_grid_may_already_include_native_element_load")
        self.plan.warnings.extend(
            [
                "schedule_permission_is_not_element_power",
                "t_comfort_not_assumed_in_manual_or_off",
                "native_programme_is_primary_comfort_fallback",
            ]
        )
        if not self.native_options["native_schedule_clock_verified"]:
            self.plan.warnings.append("native_schedule_times_approximate_clock_unverified")
        from .native import clock_check_required

        clock_check = clock_check_required(now, self.native_options["native_clock_check_date"])
        self.values["device_clock_check"] = (
            "check_required"
            if clock_check or not self.native_options["native_schedule_clock_verified"]
            else "checked_this_dst_period"
        )
        if self.values["device_clock_check"] == "check_required":
            self.plan.warnings.append("check_thermann_clock_manual_dst_adjustment_required")
        if self.native_options["t_comfort_reference_c"] == 10:
            self.plan.warnings.append("t_comfort_10C_not_practical_hot_water_reserve")
        else:
            self.plan.warnings.append("higher_t_comfort_can_heat_outside_schedule_including_peak")
        native_minutes = None
        if self.plan.comfort_deadline is not None:
            native_minutes = permitted_minutes(
                now,
                self.plan.comfort_deadline,
                self.native_periods,
                self.native_options["native_schedule_clock"],
            )
            if (
                self.plan.modelled_heating_minutes is not None
                and native_minutes < self.plan.modelled_heating_minutes
            ):
                self.plan.warnings.append(
                    "reported_native_windows_may_not_fit_depleted_tank_scenario"
                )
        counter = self.hass.states.get(self.sources["requests"])
        categories = {}
        if counter is not None:
            raw = counter.attributes.get("request_categories", {})
            if isinstance(raw, dict):
                categories = {
                    key: raw[key]
                    for key in (
                        "password_login",
                        "token_refresh",
                        "discovery",
                        "status",
                        "command",
                        "confirmation",
                    )
                    if type(raw.get(key)) is int and 0 <= raw[key] < 2**63
                }
            if (
                counter.attributes.get("accounting_complete") is not True
                or counter.attributes.get("accounting_persistent") is not True
            ):
                self.plan.warnings.append("request_accounting_incomplete_or_unverified")
        self.details = {
            "shadow_mode": True,
            "control_capable": False,
            "additional_cloud_requests": 0,
            "nominal_status_cycles_per_day": 48,
            "observed_refresh_pattern_attempts_per_day": 144,
            "request_estimates_are_not_vendor_quota_or_upper_bound": True,
            "request_counter_basis": "local_lifetime_attempts_excludes_official_app",
            "request_categories_local_lifetime": categories,
            "controller_observation_started": self.boot.isoformat(),
            "grid_sign": "import_positive" if self.settings.import_positive else "export_positive",
            "meter_sign_load_test_verified": self.settings.meter_verified,
            "tariff_contract_verified": self.settings.tariff_verified,
            "tariff_clock": self.settings.tariff_clock,
            "morning_comfort_time": self.settings.morning.isoformat() + " Australia/Hobart",
            "evening_comfort_time": self.settings.evening.isoformat()
            + " nominal; weekday storage deadline follows actual peak",
            "planning_goal": self.plan.deadline_kind,
            "morning_threshold_is_not_a_setpoint": True,
            "manual_recovery_risk_accepted_by_owner": True,
            "estimate_basis": "uniform_315L_3kW_scenario_not_measured_reserve",
            "comparison_basis": "same_modelled_energy_at_current_rate_not_native_schedule_savings",
            "reasons": self.plan.reasons,
            "warnings": self.plan.warnings,
            "windows": self.plan.windows,
            "native_schedule_reference": self.native_options["native_schedule_periods"],
            "native_schedule_clock": self.native_options["native_schedule_clock"],
            "native_clock_reference_date": self.native_options["native_clock_check_date"],
            "device_clock_not_read_by_api": True,
            "solar_hold_satisfied": solar_confirmed,
            "local_evaluation_seconds": 60,
            "t_comfort_setting_is_reference_only": True,
            "native_permitted_minutes_before_comfort_deadline": native_minutes,
            "native_window_capacity_is_not_measured_energy": True,
            "sources": dict(self.sources),
            "cycle": cycle,
            "decision": code,
            "decision_explanation": explanation,
            "forecast": {
                "source": self.forecast.source,
                "age_minutes": self.forecast.age_minutes,
                "pv_error_kw": self.forecast.pv_error_kw,
                "pv_correction_now": self.forecast.correction,
                "pv_correction_fades_to_none_after_hours": self.forecast.correction_hours,
                "measured_pv_average_kw": self.forecast.measured_pv_average_kw,
                "load_basis": self.forecast.load_basis,
                "intervals": len(self.forecast.slots),
            },
            "advanced_form_settings": {
                key: describe(key, self.native_options[key])
                for key in ("tariff_periods", "native_schedule_periods")
            },
            "restore_undo_available": isinstance(self.native_options.get(BACKUP_KEY), dict),
        }
        for listener in tuple(self.listeners):
            listener()

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)


def _usable_solar(slots, now, deadline, settings):
    """Forecast surplus the full 3 kW element could absorb before the deadline (kWh)."""
    if not slots or deadline is None:
        return None
    total = 0.0
    for item in slots:
        start, end = max(item.start, now), min(item.end, deadline)
        if end > start:
            usable = min(3.0, max(0.0, item.export_kw - settings.export_headroom_kw))
            total += usable * (end - start).total_seconds() / 3600
    return round(total, 3)
