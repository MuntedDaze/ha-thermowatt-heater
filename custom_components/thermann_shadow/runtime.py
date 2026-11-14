"""Read HA states only, on a fixed local timer. Never call services or a transport.

0.9.0: the runtime gathers MEASUREMENTS for the one coordinated policy
(``simple_policy``) and the read-only displays:

* the Thermann reading, target, mode and poll time (bridge entities);
* the GoodWe grid power (signed by the owner's verified convention), PV and
  house load, and the local element estimate (``heater_state``);
* the EMHASS PV and household-load forecasts as net-export slots (``forecast``);
* the tariff calendar.

It does not decide anything: the executor runs the policy every minute and the
controller supervises any command. The 0.4-0.8 planner (goals, strategies,
economic permission) is gone.
"""

import logging
from collections import deque
from datetime import timedelta

from homeassistant.util import dt as dt_util

from .config import DEFAULT_OPTIONS, DEFAULT_PV_AC
from .forecast import build_forecast
from .heater_state import HeaterState, HeaterStateEstimator, base_load
from .model import ELEMENT_KW, Reading, _fresh, _power, number, tariff_at, timestamp
from .settings import BACKUP_KEY, describe
from .thermal import ThermalObserver

# Measured-vs-forecast PV correction uses a short rolling mean, so one passing
# cloud sample cannot discard the whole horizon. Window is deliberately fixed.
PV_AVERAGE_MINUTES = 15
CLOUD_HEALTH = {"ok", "disabled", "auth_locked", "quota_limited", "backoff", "unavailable"}

LOG = logging.getLogger(__name__)


def next_tariff_change(now, tariffs, clock):
    """(time, tariff) of the next change of tariff kind within 8 days, or None."""
    current = tariff_at(now, tariffs, clock)
    at = now.replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 4):
        at += timedelta(minutes=15)
        candidate = tariff_at(at, tariffs, clock)
        if candidate.kind != current.kind:
            while tariff_at(at - timedelta(minutes=1), tariffs, clock).kind != current.kind:
                at -= timedelta(minutes=1)
            return at, candidate
    return None


class ShadowRuntime:
    def __init__(self, hass, sources, settings, tariffs):
        self.hass = hass
        self.sources = sources
        self.settings = settings
        self.tariffs = tariffs
        self.boot = dt_util.utcnow()
        self.values = {}
        self.details = {}
        self.listeners = set()
        self.first_count = None
        self.last_count = None
        self.count_started = None
        self.pv_samples = deque(maxlen=64)  # (observed_at, kW), fresh distinct reports
        self.estimator = HeaterStateEstimator()
        self.heater = HeaterState()
        self.forecast = None
        self.grid_import_kw = None  # signed: import positive; None when stale/unverified
        self.heater_power_kw = None  # fresh, plausibly metered local circuit power
        self.temperature_c = None
        self.poll_at = None
        self.warnings = []
        # Set by the Executor (it publishes; this module never does).
        self.controller_active = False
        self.executor = None
        # 0.7.0 read-only thermal observer (diagnostics; never affects control).
        self.thermal = ThermalObserver()
        self.thermal_store = None
        self.native_options = dict(DEFAULT_OPTIONS)

    def set_native_reference(self, options):
        self.native_options = {**DEFAULT_OPTIONS, **options}

    def apply_options(self, options, sources):
        from .config import parse_options

        settings, tariffs = parse_options(options)
        changed_mapping = dict(sources) != dict(self.sources)
        if changed_mapping or settings != self.settings or tariffs != self.tariffs:
            self.pv_samples.clear()
            self.estimator.reset()
            if self.executor is not None:
                # Meter evidence was gathered under the old mapping or sign.
                self.executor.reset_policy()
        if changed_mapping:
            self.boot = dt_util.utcnow()
        self.sources, self.settings, self.tariffs = sources, settings, tariffs
        self.set_native_reference(options)
        self.update(dt_util.utcnow())

    def _reading(self, key, attribute=None, entity_id=None):
        entity_id = entity_id or self.sources.get(key)
        if not isinstance(entity_id, str) or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
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

    def _kw(self, key, now, entity_id=None):
        reading = self._reading(key, entity_id=entity_id)
        try:
            if reading and not reading.restored:
                _fresh(reading, now, self.boot, self.settings.grid_max_age_seconds)
                return _power(reading)
        except (ValueError, TypeError, OverflowError):
            pass
        return None

    # ------------------------------------------------------------------ the tick
    def update(self, now):
        settings = self.settings
        self.warnings = []
        # Thermann status (bridge entities).
        poll = self._reading("last_poll")
        try:
            self.poll_at = timestamp(poll.value) if poll else None
        except (ValueError, TypeError):
            self.poll_at = None
        status_ok = (
            self.poll_at is not None
            and 0 <= (now - self.poll_at).total_seconds() <= settings.status_max_age_minutes * 60
        )
        temperature = target = None
        for key, attribute in (("temperature", "current_temperature"), ("target", "temperature")):
            reading = self._reading("heater", attribute)
            try:
                value = number(reading.value) if reading and status_ok else None
                if reading and reading.unit != "°C":
                    value = None
            except (ValueError, TypeError, OverflowError):
                value = None
            if key == "temperature":
                temperature = value
            else:
                target = value
        self.temperature_c = temperature
        mode_state = self.hass.states.get(self.sources.get("mode", ""))
        mode = mode_state.state if mode_state else None

        # GoodWe meter (local, about every minute). Signed import only when the
        # owner has verified the meter's direction; otherwise no solar evidence.
        grid = self._kw("grid", now)
        export_kw = None if grid is None else grid * (-1 if settings.import_positive else 1)
        self.grid_import_kw = (
            None if export_kw is None or not settings.meter_verified else -export_kw
        )
        if not settings.meter_verified:
            self.warnings.append("meter_direction_not_verified_no_measured_solar_used")
        pv_ac_now = None
        pv_ac_entity = self.sources.get("pv_ac") or DEFAULT_PV_AC
        value = self._kw("pv_ac", now, entity_id=pv_ac_entity)
        if value is not None and value >= 0:
            pv_ac_now = value
            reading = self._reading("pv_ac", entity_id=pv_ac_entity)
            if reading and (not self.pv_samples or reading.observed_at > self.pv_samples[-1][0]):
                self.pv_samples.append((reading.observed_at, value))
        while self.pv_samples and now - self.pv_samples[0][0] > timedelta(
            minutes=PV_AVERAGE_MINUTES
        ):
            self.pv_samples.popleft()
        measured_pv = (
            sum(item for _, item in self.pv_samples) / len(self.pv_samples)
            if self.pv_samples
            and now - self.pv_samples[-1][0] <= timedelta(seconds=settings.grid_max_age_seconds)
            else None
        )
        house_kw = self._kw("house", now)
        if house_kw is None and pv_ac_now is not None and export_kw is not None:
            house_kw = max(0.0, pv_ac_now - export_kw)
        heater_mapped = bool(self.sources.get("heater_power"))
        heater_power = self._kw("heater_power", now) if heater_mapped else None
        if heater_power is not None and not 0 <= heater_power <= ELEMENT_KW * 1.4:
            heater_power = None  # backwards CT polarity or shared/incorrect circuit
            self.warnings.append("heater_power_implausible_check_ct_circuit")
        elif heater_mapped and heater_power is None:
            self.warnings.append("heater_power_stale_or_unavailable")
        self.heater_power_kw = heater_power
        status_raw = mode_state.attributes.get("WaterHeaterSts") if mode_state else None
        self.heater = self.estimator.update(
            now,
            house_kw,
            status_raw,
            self.poll_at if status_ok else None,
            mode == "Manual",
            heater_power,
        )

        # EMHASS forecasts as net-export slots.
        self.forecast = build_forecast(
            now,
            self.boot,
            settings,
            self.hass.states.get(self.sources.get("forecast_pv", "")),
            self.hass.states.get(self.sources.get("forecast_load", "")),
            measured_pv,
        )
        self.forecast.measured_pv_average_kw = (
            None if measured_pv is None else round(measured_pv, 3)
        )
        self.warnings.extend(self.forecast.warnings)

        try:
            self.thermal.update(
                now,
                temperature,
                self.poll_at if status_ok else None,
                self.heater.state,
                self.heater.confidence,
                mode,
                heater_power_kw=self.heater_power_kw,
                meter_configured=heater_mapped,
            )
            if self.thermal_store is not None and self.thermal.should_save(now):
                self.hass.async_create_task(self.thermal_store.async_save(self.thermal.to_dict()))
        except Exception:  # noqa: BLE001 - diagnostics must never disturb control
            LOG.debug("Thermal observer update failed.")

        self._display(now, temperature, target, grid, export_kw, house_kw, pv_ac_now, status_ok)
        for listener in tuple(self.listeners):
            listener()

    # ------------------------------------------------------------------ displays
    def forecast_export_now(self, now):
        for slot in self.forecast.slots if self.forecast else ():
            if slot.start <= now < slot.end:
                return slot.export_kw
        return None

    def _display(self, now, temperature, target, grid, export_kw, house_kw, pv_ac_now, status_ok):
        values = self.values
        pv = self._kw("pv", now)
        values.update(
            temperature=temperature,
            target=target,
            pv=pv,
            house=house_kw,
            grid=grid,
            measured_net_export_kw=export_kw,
            measured_import_kw=None if export_kw is None else max(0.0, -export_kw),
            measured_export_kw=None if export_kw is None else max(0.0, export_kw),
            measured_pv_ac_kw=None if pv_ac_now is None else round(pv_ac_now, 3),
            status_age_minutes=round((now - self.poll_at).total_seconds() / 60, 1)
            if self.poll_at
            else None,
            heater_element_state=self.heater.state,
            heater_state_confidence=self.heater.confidence,
            heater_power_kw=None
            if self.heater_power_kw is None
            else round(self.heater_power_kw, 3),
            heater_power_source_ready=None
            if not self.sources.get("heater_power")
            else self.heater_power_kw is not None,
            storage_target_c=70,
        )
        base, _ = base_load(house_kw, self.heater)
        values["base_load_kw"] = None if base is None else round(base, 3)
        health = self._reading("cloud_health")
        values["cloud_health"] = (
            health.value if health and health.value in CLOUD_HEALTH else "unrecognised"
        )
        try:
            current = tariff_at(now, self.tariffs, self.settings.tariff_clock)
            change = next_tariff_change(now, self.tariffs, self.settings.tariff_clock)
        except ValueError:
            current = change = None
        values.update(
            current_tariff=current.kind if current else None,
            current_price_aud=current.rate if current else None,
            current_tariff_rate_aud=current.rate if current else None,
            next_tariff_change=change[0] if change else None,
            next_tariff_kind=change[1].kind if change else None,
        )
        export_now = self.forecast_export_now(now)
        values["forecast_net_surplus_kw"] = (
            None if export_now is None else round(max(0.0, export_now), 3)
        )
        values["forecast_age_minutes"] = self.forecast.age_minutes if self.forecast else None
        self._requests(now)
        executor = self.executor
        policy = executor.policy_values() if executor is not None else {}
        values.update(policy)
        values["controller"] = (
            "automatic_control" if self.controller_active else "shadow_observation"
        )
        self.details = {
            "shadow_mode": not self.controller_active,
            "controller_active": self.controller_active,
            "policy": "simplified_three_state (SIMPLIFIED_STRATEGY.md)",
            "additional_cloud_requests": 0,
            "local_evaluation_seconds": 60,
            "grid_sign": "import_positive" if self.settings.import_positive else "export_positive",
            "meter_sign_load_test_verified": self.settings.meter_verified,
            "heater_power_source": self.sources.get("heater_power") or None,
            "heater_power_kw": self.heater_power_kw,
            "heater_power_source_ready": None
            if not self.sources.get("heater_power")
            else self.heater_power_kw is not None,
            "tariff_contract_verified": self.settings.tariff_verified,
            "tariff_clock": self.settings.tariff_clock,
            "status_fresh": status_ok,
            "warnings": list(self.warnings),
            "sources": dict(self.sources),
            "heater_state": {
                "state": self.heater.state,
                "confidence": self.heater.confidence,
                "basis": self.heater.basis,
                "status_bit0": self.heater.status_bit,
                "status_raw": self.heater.status_raw,
                "status_semantics": "empirical_32_33_correlation_not_manufacturer_contract",
            },
            "forecast": {
                "source": self.forecast.source if self.forecast else None,
                "age_minutes": self.forecast.age_minutes if self.forecast else None,
                "pv_error_kw": self.forecast.pv_error_kw if self.forecast else None,
                "measured_pv_average_kw": self.forecast.measured_pv_average_kw
                if self.forecast
                else None,
                "load_basis": self.forecast.load_basis if self.forecast else None,
                "intervals": len(self.forecast.slots) if self.forecast else 0,
            },
            "policy_plan": executor.plan_details() if executor is not None else None,
            "advanced_form_settings": {
                key: describe(key, self.native_options[key]) for key in ("tariff_periods",)
            },
            "restore_undo_available": isinstance(self.native_options.get(BACKUP_KEY), dict),
        }

    def _requests(self, now):
        values = self.values
        values["requests_since_start"] = values["observed_requests_per_hour"] = None
        reading = self._reading("requests")
        if not reading or reading.restored:
            self.warnings.append("request_accounting_unavailable")
            return
        try:
            count = number(reading.value)
            if (
                count < 0
                or count != int(count)
                or not 0 <= (now - reading.observed_at).total_seconds() <= 300
            ):
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            self.warnings.append("request_accounting_unavailable")
            return
        if self.last_count is not None and count < self.last_count:
            self.first_count = self.count_started = None
            self.warnings.append("request_counter_reset_history_incomplete")
        if self.first_count is None:
            self.first_count, self.count_started = count, now
        self.last_count = count
        values["requests_since_start"] = count - self.first_count
        hours = (now - self.count_started).total_seconds() / 3600
        if hours >= 0.5:
            values["observed_requests_per_hour"] = round((count - self.first_count) / hours, 2)

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)
