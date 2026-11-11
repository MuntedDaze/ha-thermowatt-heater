"""Read HA states only, on a fixed local timer. Never call services or a transport."""

from dataclasses import asdict
from collections import deque
from datetime import timedelta

from homeassistant.util import dt as dt_util

from .model import Plan, Reading, evaluate, number, timestamp, _fresh, _power
from .config import DEFAULT_OPTIONS, DEFAULT_PV_AC
from .native import parse_native, permitted_minutes, scheduled_permission
from .forecast import build_forecast
from .advisor import Advisor, TickInputs
from .goals import next_tariff_change
from .model import TANK_KWH_PER_C, tariff_at
from .settings import BACKUP_KEY, describe

# Measured-vs-forecast PV correction uses a short rolling mean, so one passing
# cloud sample cannot discard the whole horizon. Window is deliberately fixed.
PV_AVERAGE_MINUTES = 15
GATED = {
    "shadow_blocked",
    "shadow_paused",
    "shadow_native_intervention",
    "shadow_awaiting_validation",
}


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
        self.advisor = Advisor()
        self.advice = None
        self._status_ok = False
        self.set_native_reference({})

    def set_native_reference(self, options):
        self.native_options = {**DEFAULT_OPTIONS, **options}
        self.native_periods = parse_native(self.native_options["native_schedule_periods"])

    def apply_options(self, options, sources):
        from .config import parse_options

        settings, tariffs = parse_options(options)
        changed_mapping = dict(sources) != dict(self.sources)
        if changed_mapping or settings != self.settings or tariffs != self.tariffs:
            self.advisor.reset()
            self.solar_samples.clear()
            self.pv_samples.clear()
        if changed_mapping:
            self.boot = dt_util.utcnow()
            self.last_native = None
        self.sources, self.settings, self.tariffs = sources, settings, tariffs
        self.set_native_reference(options)
        self.update(dt_util.utcnow())

    def _reading(self, key, attribute=None, entity_id=None):
        entity_id = entity_id or self.sources.get(key)
        if not isinstance(entity_id, str) or not entity_id:
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
        # AC-side inverter output: consistent with the AC meter and GoodWe house
        # load. The DC "pv" mapping stays display-only (Stage 1 F6).
        measured_pv = pv_ac_now = None
        pv_ac_entity = self.sources.get("pv_ac") or DEFAULT_PV_AC
        try:
            pv = self._reading("pv_ac", entity_id=pv_ac_entity)
            if pv:
                _fresh(pv, now, self.boot, self.settings.grid_max_age_seconds)
                value = _power(pv)
                if value < 0:
                    raise ValueError("pv_negative")
                pv_ac_now = value
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
        poll_at = None
        try:
            poll_at = timestamp(readings["last_poll"].value)
        except (KeyError, ValueError, TypeError):
            pass
        status_ok = (
            poll_at is not None
            and 0 <= (now - poll_at).total_seconds() <= self.settings.status_max_age_minutes * 60
        )
        self._status_ok = status_ok
        temperature = None
        if status_ok and "temperature" in readings:
            try:
                temperature = number(readings["temperature"].value)
            except (ValueError, TypeError):
                temperature = None
        export_kw = self.plan.net_export_kw
        house_kw = self._kw("house", now)
        if house_kw is None and pv_ac_now is not None and export_kw is not None:
            house_kw = max(0.0, pv_ac_now - export_kw)
        mode_state = self.hass.states.get(self.sources.get("mode", ""))
        status_raw = mode_state.attributes.get("WaterHeaterSts") if mode_state else None
        heater_power = self._kw("heater_power", now) if self.sources.get("heater_power") else None
        inputs = TickInputs(
            temperature=temperature,
            house_kw=house_kw,
            pv_ac_kw=pv_ac_now,
            export_kw=export_kw,
            status_raw=status_raw,
            status_at=poll_at if status_ok else None,
            in_window=lambda at: scheduled_permission(
                at, self.native_periods, self.native_options["native_schedule_clock"]
            )
            == "within_reported_window",
            heater_power_kw=heater_power,
            native_periods=self.native_periods,
            native_clock=self.native_options["native_schedule_clock"],
            pv_series=self.forecast.pv_series,
            load_series=self.forecast.load_series,
            forecast_available=bool(self.forecast.pv_series),
        )
        advice = self.advisor.tick(now, self.plan, self.settings, self.tariffs, inputs)
        self.advice = advice
        self._apply_advice(now, advice, pv_ac_now)
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
                cloud = key in {"temperature", "target"}
                if (
                    reading
                    and not reading.restored
                    and (
                        self._status_ok
                        if cloud
                        else reading.observed_at >= self.boot
                        and 0 <= (now - reading.observed_at).total_seconds() <= max_age
                    )
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
            "weekend_morning_time": self.settings.morning.isoformat() + " Australia/Hobart",
            "weekend_afternoon_time": self.settings.evening.isoformat() + " Australia/Hobart",
            "weekday_deadlines": "start of the actual morning/evening peak (fixed AEST tariff)",
            "shower_time": self.settings.shower_time.isoformat()
            if self.settings.shower_time_enabled
            else None,
            "planning_goal": self.plan.deadline_kind,
            "morning_threshold_is_not_a_setpoint": True,
            "manual_recovery_risk_accepted_by_owner": True,
            "estimate_basis": "uniform_315L_3kW_scenario_not_measured_reserve",
            "comparison_basis": "incremental_cost_vs_not_heating_same_energy_all_plans",
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
            **self._advice_details(),
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

    def _kw(self, key, now):
        reading = self._reading(key)
        try:
            if reading:
                _fresh(reading, now, self.boot, self.settings.grid_max_age_seconds)
                value = _power(reading)
                return value if value >= 0 else None
        except (ValueError, TypeError, OverflowError):
            pass
        return None

    def _apply_advice(self, now, advice, pv_ac_now):
        """Map the advice onto existing sensor keys (stable unique IDs) and new ones."""
        result = advice.assessment
        best = result.plans.get("best_overall") if result else None
        plan = self.plan
        if (
            plan.state not in GATED
            and not advice.meter_suspect
            and advice.code not in {"data_unavailable"}
        ):
            plan.state = "shadow_advising"
            plan.reasons = [advice.code]
            plan.windows = []
            if result:
                first = result.requirements[0] if result.requirements else None
                plan.mixed_model_energy_kwh = round(first[1], 3) if first else None
                plan.modelled_heating_minutes = (
                    round(first[1] / 3 * 60 + self.settings.margin_minutes, 1)
                    if first and first[1] > 0
                    else 0.0
                )
                fallback = result.fallback
                plan.grid_fallback_start = min(fallback.values()) if fallback else None
                plan.latest_start = fallback.get(first[0].kind) if first else None
                target = best or result.plans.get("heat_now_continuous")
                plan.planned_start = target.start if target else None
                plan.estimated_cost_aud = round(target.cost_aud, 3) if target else 0
                plan.estimated_solar_kwh = round(target.solar_kwh, 3) if target else 0
                plan.estimated_import_kwh = round(target.import_kwh, 3) if target else 0
                now_plan = result.plans.get("heat_now_continuous")
                plan.unmet_model_energy_kwh = round(now_plan.shortfall_kwh, 3) if now_plan else 0
                if target and target.energy_kwh:
                    share = target.solar_kwh / target.energy_kwh
                    plan.recommended_energy_source = (
                        "net_solar" if share > 0.99 else "mixed" if share > 0.01 else "grid"
                    )
                    plan.comparison_cost_difference_aud = round(
                        target.energy_kwh * min(item.rate for item in self.tariffs)
                        - target.cost_aud,
                        3,
                    )
                else:
                    plan.recommended_energy_source = "none"
                    plan.comparison_cost_difference_aud = 0
                plan.windows = [
                    {"start": a.isoformat(), "end": b.isoformat(), "source": "hypothetical_plan"}
                    for a, b in (target.blocks if target else [])
                ]
        elif plan.state not in GATED:
            plan.state = "shadow_blocked"
            plan.reasons = [
                "meter_reading_suspect" if advice.meter_suspect else "heater_status_unavailable"
            ]
        self.values = asdict(plan)
        readiness = advice.readiness
        change = current = None
        try:
            change = next_tariff_change(now, self.tariffs, self.settings.tariff_clock)
            current = tariff_at(now, self.tariffs, self.settings.tariff_clock)
        except ValueError:
            pass
        goals = {goal.kind: goal for goal in reversed(advice.goals)}
        pv_forecast_now = None
        for start, end, value in self.forecast.pv_series:
            if start <= now < end:
                pv_forecast_now = value
        forecast_surplus = (
            max(0.0, pv_forecast_now - advice.base_p50_kw)
            if pv_forecast_now is not None and advice.base_p50_kw is not None
            else None
        )
        if best is not None and best.start is not None:
            state = "hypothetical_heating_now" if best.start <= now else "hypothetical_waiting"
        elif result is not None:
            state = (
                "not_needed"
                if advice.code in {"no_heating_needed", "native_heating_economical"}
                and not result.plans
                else "hypothetical_heating_now"
            )
        else:
            state = "suspended"
        native = advice.native or {}
        saving = result.saving_by_waiting_aud if result else None
        self.values.update(
            {
                "recommendation": advice.label,
                "decision": advice.code,
                "simulated_cycle_state": state,
                "benefit_of_now_aud": -saving if saving is not None else None,
                "continuing_cost_aud": result.heat_now_cost_aud if result else None,
                "later_cost_aud": result.best_cost_aud if result else None,
                "forecast_net_surplus_kw": round(forecast_surplus, 3)
                if forecast_surplus is not None
                else None,
                "forecast_age_minutes": self.forecast.age_minutes,
                "forecast_usable_solar_kwh": round(best.solar_kwh, 3) if best else None,
                "deadline_countdown_minutes": max(
                    0, round((plan.deadline - now).total_seconds() / 60)
                )
                if plan.deadline
                else None,
                "completion_time": best.end if best else None,
                "heater_element_state": advice.heater.state,
                "heater_state_confidence": advice.heater.confidence,
                "base_load_kw": round(advice.base_p50_kw, 3)
                if advice.base_p50_kw is not None
                else None,
                "measured_pv_ac_kw": round(pv_ac_now, 3) if pv_ac_now is not None else None,
                "current_solar_surplus_kw": advice.surplus_now_kw,
                "next_tariff_change": change[0] if change else None,
                "next_tariff_kind": change[1].kind if change else None,
                "current_tariff_rate_aud": current.rate if current else None,
                "morning_ready_deadline": goals["morning"].deadline if "morning" in goals else None,
                "afternoon_ready_deadline": goals["afternoon"].deadline
                if "afternoon" in goals
                else None,
                "morning_readiness": readiness.get("morning", {}).get("status"),
                "afternoon_readiness": readiness.get("afternoon", {}).get("status"),
                "waiting_saving_aud": saving,
                "decision_confidence": advice.confidence,
                "native_predicted_cost_aud": native.get("predicted_cost_aud"),
                "schedule_advisor_suggestion": (advice.schedule or {}).get(
                    "cheapest_meeting_goals"
                ),
                "native_vs_best_plan_aud": round(
                    native["predicted_cost_aud"] - result.best_cost_aud, 3
                )
                if native and result and result.best_cost_aud is not None
                else None,
            }
        )

    def _advice_details(self):
        advice = self.advice
        if advice is None:
            return {}
        result = advice.assessment
        heater = advice.heater
        return {
            "decision": advice.code,
            "decision_explanation": advice.explanation,
            "decision_confidence": advice.confidence,
            "decision_pending_change_to": advice.pending_code,
            "economic_decision": advice.economic_code,
            "physical_state_applied_without_stabiliser_delay": True,
            "hypothetical_surplus_kw": {
                "value": advice.surplus_now_kw,
                "bounds": list(advice.surplus_bounds_kw) if advice.surplus_bounds_kw else None,
                "basis": advice.surplus_basis,
                "meaning": "PV AC minus base load: what the heater could use if it were off; not measured export",
            },
            "native_thermostat_satisfied": advice.satisfied,
            "heat_now_cost_range_aud": list(result.heat_now_cost_range_aud)
            if result and result.heat_now_cost_range_aud
            else None,
            "heater_state": {
                "state": heater.state,
                "confidence": heater.confidence,
                "basis": heater.basis,
                "status_bit0": heater.status_bit,
                "status_raw": heater.status_raw,
                "status_semantics": "empirical_32_33_correlation_not_manufacturer_contract",
                "last_load_step": heater.last_step,
                "last_load_step_at": heater.last_step_at.isoformat()
                if heater.last_step_at
                else None,
            },
            "load": {
                "base_low_kw": advice.base_low_kw,
                "base_high_kw": advice.base_high_kw,
                "base_p50_kw": advice.base_p50_kw,
                "meter_suspect_pre_commissioning_signature": advice.meter_suspect,
                "basis": "house_load_minus_3kW_when_element_on",
            },
            "goals": [
                {
                    "kind": goal.kind,
                    "deadline": goal.deadline.isoformat(),
                    "target_c": goal.target_c,
                    "basis": goal.basis,
                }
                for goal in advice.goals
            ],
            "readiness": {
                kind: {**item, "deadline": item["deadline"].isoformat()}
                for kind, item in advice.readiness.items()
            },
            "strategies": {name: plan.summary() for name, plan in result.plans.items()}
            if result
            else {},
            "requirements_kwh": [
                {"goal": goal.kind, "kwh": round(kwh, 3), "deg_c": round(kwh / TANK_KWH_PER_C, 1)}
                for goal, kwh in result.requirements
            ]
            if result
            else [],
            "fallback_starts": {kind: at.isoformat() for kind, at in result.fallback.items()}
            if result
            else {},
            "strategy_warnings": result.warnings if result else [],
            "native_outlook": advice.native,
            "schedule_advisor": advice.schedule,
        }

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)
