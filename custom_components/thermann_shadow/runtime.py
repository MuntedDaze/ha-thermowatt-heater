"""Read HA states only, on a fixed local timer. Never call services or a transport."""

from dataclasses import asdict

from homeassistant.util import dt as dt_util

from .model import Plan, Reading, evaluate, number
from .config import DEFAULT_OPTIONS
from .native import parse_native, permitted_minutes, scheduled_permission


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
        self.set_native_reference({})

    def set_native_reference(self, options):
        self.native_options = {**DEFAULT_OPTIONS, **options}
        self.native_periods = parse_native(self.native_options["native_schedule_periods"])

    def _reading(self, key, attribute=None):
        state = self.hass.states.get(self.sources[key])
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
        self.plan = evaluate(
            now, self.boot, readings, self.settings, self.tariffs, intervention=self.intervention
        )
        self.values = asdict(self.plan)
        self.values["controller"] = self.plan.state
        health = readings.get("cloud_health", Reading("unavailable", now)).value
        self.values["cloud_health"] = (
            health
            if health
            in {"ok", "disabled", "auth_locked", "quota_limited", "backoff", "unavailable"}
            else "unrecognised"
        )
        for key in ("temperature", "target", "pv", "house", "grid"):
            reading = readings.get(key) if key in readings else self._reading(key)
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
        self.plan.warnings.extend(
            [
                "schedule_permission_is_not_element_power",
                "t_comfort_not_assumed_in_manual_or_off",
                "native_programme_is_primary_comfort_fallback",
            ]
        )
        if not self.native_options["native_schedule_clock_verified"]:
            self.plan.warnings.append("native_schedule_times_approximate_clock_unverified")
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
            "morning_comfort_time": "07:00 Australia/Hobart",
            "evening_comfort_time": "16:00 Australia/Hobart",
            "estimate_basis": "uniform_315L_3kW_scenario_not_measured_reserve",
            "comparison_basis": "same_modelled_energy_at_current_rate_not_native_schedule_savings",
            "reasons": self.plan.reasons,
            "warnings": self.plan.warnings,
            "windows": self.plan.windows,
            "native_schedule_reference": self.native_options["native_schedule_periods"],
            "native_schedule_clock": self.native_options["native_schedule_clock"],
            "t_comfort_setting_is_reference_only": True,
            "native_permitted_minutes_before_comfort_deadline": native_minutes,
            "native_window_capacity_is_not_measured_energy": True,
            "sources": self.sources,
        }
        for listener in tuple(self.listeners):
            listener()

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)
