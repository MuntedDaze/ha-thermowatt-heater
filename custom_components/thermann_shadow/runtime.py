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
from datetime import datetime, timedelta
import math

from homeassistant.util import dt as dt_util

from .config import DEFAULT_OPTIONS
from .forecast import build_forecast
from .comfort import pre_peak_availability
from .heater_state import HeaterState, HeaterStateEstimator, base_load
from .model import Reading, _fresh, _power, number, tariff_at, timestamp
from .measurement import CircuitPower, circuit_power, energy_reading, power_balance
from .performance import MeasuredHistory
from .learning import evaluate, planning
from .settings import BACKUP_KEY, describe, _DUAL_PROTECTED
from .thermal import ThermalObserver

# Measured-vs-forecast PV correction uses a short rolling mean, so one passing
# cloud sample cannot discard the whole horizon. Window is deliberately fixed.
PV_AVERAGE_MINUTES = 15
CLOUD_HEALTH = {"ok", "disabled", "auth_locked", "quota_limited", "backoff", "unavailable"}

LOG = logging.getLogger(__name__)


def background_poll_due(now, seconds, health, schedule):
    if (
        health != "ok"
        or schedule != "clock_aligned"
        or type(seconds) not in (int, float)
        or not math.isfinite(seconds)
        or not 60 <= seconds <= 7200
    ):
        return None
    return datetime.fromtimestamp((math.floor(now.timestamp() / seconds) + 1) * seconds, now.tzinfo)


def next_tariff_change(now, tariffs, clock, zone="Australia/Hobart"):
    """(time, tariff) of the next change of tariff kind within 8 days, or None."""
    current = tariff_at(now, tariffs, clock, zone)
    at = now.replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 4):
        at += timedelta(minutes=15)
        candidate = tariff_at(at, tariffs, clock, zone)
        if (candidate.kind, candidate.rate) != (current.kind, current.rate):
            while (
                tariff_at(at - timedelta(minutes=1), tariffs, clock, zone).kind,
                tariff_at(at - timedelta(minutes=1), tariffs, clock, zone).rate,
            ) != (current.kind, current.rate):
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
        self.grid_observed_at = None
        self.grid_value_missing = False
        self.circuit = CircuitPower()
        self.circuit_energy_kwh = None
        self.power_budget = None
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
        self.history = MeasuredHistory(settings.tank_litres, settings.element_kw)
        self.history_store = None
        self.history_persistent = False
        self.completion = {}
        self.telemetry = None
        self._event_key = None
        self.owner_events = deque(maxlen=200)
        self.owner_event_store = None
        self.solar_input_loss_pending = False

    def set_native_reference(self, options):
        self.native_options = {**DEFAULT_OPTIONS, **options}
        self.history.configure(
            self.settings.tank_litres,
            self.settings.element_kw,
            self.native_options["heater_meter_verification"],
        )

    def apply_options(self, options, sources):
        from .config import parse_options

        settings, tariffs = parse_options(options)
        changed_mapping = dict(sources) != dict(self.sources)
        verification_changed = (
            options.get("heater_meter_verification", "")
            != self.native_options["heater_meter_verification"]
        )
        reset_needed = (
            changed_mapping
            or any(
                options.get(key, DEFAULT_OPTIONS[key]) != self.native_options[key]
                for key in _DUAL_PROTECTED
            )
            or verification_changed
            or settings != self.settings
            or tariffs != self.tariffs
            or any(
                options.get(key, DEFAULT_OPTIONS[key]) != self.native_options[key]
                for key in ("optional_heat_margin_aud_per_kwh", "pause_min_saving_aud")
            )
        )
        if reset_needed:
            self.pv_samples.clear()
            self.history.last = self.history.anchor = self.history.candidate = None
            self.history.cycle = None
            self.history.dirty = True
            self.estimator.reset()
        if changed_mapping:
            self.boot = dt_util.utcnow()
        self.sources, self.settings, self.tariffs = sources, settings, tariffs
        self.history.configure(settings.tank_litres, settings.element_kw)
        self.set_native_reference(options)
        if self.executor is not None and reset_needed:
            # New policy must see the new tariff/settings, not the previous ones.
            self.executor.reset_policy()
        self.update(dt_util.utcnow())

    def learning(self, now, target):
        metrics = evaluate(
            list(self.history.sessions),
            target,
            self.settings.tank_litres,
            self.settings.element_kw,
            self.history.meter_identity,
            now,
        )
        rate, basis = planning(
            metrics,
            self.native_options["learned_planning_enabled"],
            self.native_options["learning_hardware_qualified"],
            self.circuit.valid,
            self.history_persistent,
        )
        return {
            **metrics,
            "planning_rate_c_per_hour": rate,
            "planning_basis": basis,
            "affects_control": basis == "learned_conservative_lower_bound",
        }

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

    def capture_input_report(self, event, now):
        """Preserve intervening real reports even if queued evaluations coalesce.

        No decision, command or HTTP here. Only actual signed measurements are
        sampled. Raw callbacks may reset CT qualification, never grant CT credit.
        """
        entity = event.data.get("entity_id")
        key = next(
            (k for k in ("pv", "grid", "heater_power") if self.sources.get(k) == entity), None
        )
        if key is None or self.executor is None:
            return
        state = event.data.get("new_state")
        kw = None
        at = state.last_reported if state else None
        if state:
            try:
                reading = Reading(
                    state.state,
                    at,
                    state.attributes.get("unit_of_measurement"),
                    bool(state.attributes.get("restored", False)),
                )
                _fresh(reading, now, self.boot, self.settings.grid_max_age_seconds)
                if not reading.restored:
                    kw = _power(reading)
            except (ValueError, TypeError, OverflowError):
                pass
        if key == "pv":
            self.executor.policy.add_pv(at, kw)
        elif key == "heater_power":
            reading = (
                Reading(
                    state.state,
                    at,
                    state.attributes.get("unit_of_measurement"),
                    bool(state.attributes.get("restored", False)),
                )
                if state
                else None
            )
            circuit = circuit_power(
                reading,
                self.sources.get("heater_power"),
                self.native_options["heater_meter_verification"],
                now,
                self.boot,
                self.settings.grid_max_age_seconds,
                nominal_kw=self.settings.element_kw,
            )
            if not circuit.valid:
                self._solar_input_loss()
            else:
                grid = self._reading("grid")
                try:
                    if grid is None or grid.restored or not self.settings.meter_verified:
                        raise ValueError("unverified_grid")
                    _fresh(grid, now, self.boot, self.settings.grid_max_age_seconds)
                    signed = _power(grid) * (1 if self.settings.import_positive else -1)
                    if abs((circuit.observed_at - grid.observed_at).total_seconds()) > 60:
                        raise ValueError("unpaired_meter")
                    storage = self.executor.controller.heater in {"normal_storage", "storage"}
                    measured = circuit.watts / 1000 if storage and circuit.state == "on" else 0
                    if measured - signed < self.executor.policy.s.peak_start_kw:
                        reset = max(circuit.observed_at, grid.observed_at)
                        self.executor.policy.surplus_reset_at = max(
                            self.executor.policy.surplus_reset_at or reset, reset
                        )
                except (ValueError, TypeError, OverflowError):
                    self._solar_input_loss()
        elif not self.settings.meter_verified:
            self._solar_input_loss()
        elif kw is None:
            # 0.16.2: a valueless report is unmeasured time. Before any optional
            # session it pauses (never satisfies) qualification instead of
            # erasing genuine votes; during one it keeps the latched loss.
            if self._optional_active():
                self._solar_input_loss()
            else:
                self.executor.policy.note_missing()
        else:
            signed = kw if self.settings.import_positive else -kw
            policy = self.executor.policy
            if signed <= policy.s.peak_import_tolerance_kw:
                policy.import_reset_at = max(policy.import_reset_at or at, at)
            if self.sources.get("heater_power"):
                # Only decide() may grant positive CT votes, using its current
                # paired evidence at min(grid_time, circuit_time). A queued
                # newer0W CT observation must be able to defeat an older ON.
                circuit = circuit_power(
                    self._reading("heater_power"),
                    self.sources.get("heater_power"),
                    self.native_options["heater_meter_verification"],
                    now,
                    self.boot,
                    self.settings.grid_max_age_seconds,
                    nominal_kw=self.settings.element_kw,
                )
                if not circuit.valid or abs((circuit.observed_at - at).total_seconds()) > 60:
                    self._solar_input_loss()
                    return
                storage = self.executor.controller.heater in {"normal_storage", "storage"}
                measured = circuit.watts / 1000 if storage and circuit.state == "on" else 0
                if measured - signed < policy.s.peak_start_kw:
                    policy.surplus_reset_at = max(policy.surplus_reset_at or at, at)
            else:
                from .solar import ct_free_record

                unit = state.attributes.get("unit_of_measurement")
                record = ct_free_record(
                    entity, unit, self.settings.import_positive, self.settings.element_kw
                )
                if (
                    self.native_options["heater_meter_verification"]
                    or not record
                    or record != self.native_options["ct_free_solar_verification"]
                    or -signed > self.settings.pv_ac_limit_kw * 1.10
                ):
                    self._solar_input_loss()
                    return
                policy.add_meter(at, signed, heater_kw=0)

    def _solar_input_loss(self):
        """Retain a transient loss until the sole controller records/resolves it."""
        self.executor.policy.samples.clear()
        if self._optional_active():
            self.solar_input_loss_pending = True

    def _optional_active(self):
        """An optional solar session, or an unresolved optional start, exists."""
        from .controller import OPTIONAL_REASONS

        controller = self.executor.controller
        return bool(
            controller.solar_session_active
            or (
                controller.intent
                and controller.intent.get("reason") in OPTIONAL_REASONS
                and controller.intent.get("target") != "off"
            )
        )

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
        grid_reading = self._reading("grid")
        self.grid_observed_at = (
            grid_reading.observed_at if self.grid_import_kw is not None else None
        )
        # A current report that carries no value (GoodWe "unavailable"/"unknown")
        # is a missing measurement, not a below-threshold one. It never votes;
        # the policy's existing gap and freshness limits still expire evidence.
        raw = self.hass.states.get(self.sources.get("grid") or "")
        reported = getattr(raw, "last_reported", None)
        self.grid_value_missing = bool(
            grid is None
            and settings.meter_verified
            and raw is not None
            and not raw.attributes.get("restored", False)
            and isinstance(reported, datetime)
            and self.boot <= reported <= now
            and (now - reported).total_seconds() <= settings.grid_max_age_seconds
        )
        if not settings.meter_verified:
            self.warnings.append("meter_direction_not_verified_no_measured_solar_used")
        pv_ac_now = None
        pv_ac_entity = self.sources.get("pv_ac")
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
        self.circuit = circuit_power(
            self._reading("heater_power"),
            self.sources.get("heater_power"),
            self.native_options["heater_meter_verification"],
            now,
            self.boot,
            settings.grid_max_age_seconds,
            nominal_kw=settings.element_kw,
        )
        self.circuit_energy_kwh = energy_reading(
            self._reading("heater_energy"), now, self.boot, settings.grid_max_age_seconds
        )
        if self.sources.get("heater_energy") == "sensor.em_hot_water_energy":
            self.circuit_energy_kwh = None
        if self.sources.get("heater_power") and not self.circuit.valid:
            self.warnings.append(
                "heater_meter_invalid_optional_heat_blocked_check_raw_report_cadence"
            )
        paired = (
            self.circuit.valid
            and self.grid_observed_at is not None
            and abs((self.circuit.observed_at - self.grid_observed_at).total_seconds()) <= 60
        )
        self.power_budget = (
            power_balance(self.grid_import_kw, self.circuit.watts / 1000) if paired else None
        )
        status_raw = mode_state.attributes.get("WaterHeaterSts") if mode_state else None
        self.heater = self.estimator.update(
            now,
            house_kw,
            status_raw,
            self.poll_at if status_ok else None,
            mode == "Manual",
            None,  # aggregate estimator is diagnostic only; CT is a separate authority
        )
        command_key = self.executor.controller.last_command_at() if self.executor else None
        self.history.update(
            self.circuit,
            temperature,
            self.poll_at if status_ok else None,
            mode,
            target,
            command_key,
            settings.grid_max_age_seconds,
        )
        energy_source = self._reading("heater_energy")
        if energy_source and self.circuit_energy_kwh is not None:
            identity = f"{self.sources.get('heater_energy')}|{energy_source.unit}"
            self.history.counter_update(
                energy_source.observed_at, self.circuit_energy_kwh, identity
            )
        self.completion = self.history.completion(
            now, temperature if mode == "Manual" else None, self.poll_at, target, self.circuit
        )
        if self.history_store is not None and self.history.should_save(now):
            self.hass.async_create_task(self._save_history())

        # EMHASS forecasts as net-export slots.
        self.forecast = build_forecast(
            now,
            self.boot,
            settings,
            self.hass.states.get(self.sources.get("forecast_pv", "")),
            self.hass.states.get(self.sources.get("forecast_load", "")),
            measured_pv,
            measured_house=house_kw,
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
            )
            if self.thermal_store is not None and self.thermal.should_save(now):
                self.hass.async_create_task(self.thermal_store.async_save(self.thermal.to_dict()))
        except Exception:  # noqa: BLE001 - diagnostics must never disturb control
            LOG.debug("Thermal observer update failed.")

        self._display(now, temperature, target, grid, export_kw, house_kw, pv_ac_now, status_ok)
        for listener in tuple(self.listeners):
            listener()

    async def _save_history(self):
        try:
            await self.history_store.async_save(self.history.to_dict())
            self.history_persistent = True
        except Exception:  # noqa: BLE001 - diagnostic failure must not disrupt guards
            self.history_persistent = False
            LOG.warning("Measured heating history could not be saved.")

    def record_event(self, now, obs, decision):
        """One event per semantic change; existing input sensors retain raw data."""
        last = self.executor.controller.intent or (
            self.executor.controller.history[-1] if self.executor.controller.history else {}
        )
        key = (
            obs.mode,
            obs.target_c,
            obs.poll_at,
            self.circuit.state,
            self.circuit.quality,
            self.values.get("current_tariff"),
            decision.reason,
            decision.plan.get("desired_target_c"),
            decision.plan.get("heating_role"),
            decision.plan.get("boost_eligible"),
            decision.plan.get("boost_reason"),
            last.get("id"),
            last.get("status"),
            self.executor.controller.state,
            self.executor.controller.reason
            if self.executor.controller.state == "change_requested"
            else None,
            self.executor.poll_shadow.last_would_poll,
        )
        if key == self._event_key:
            return
        self._event_key = key
        from .report import event

        self.owner_events.append(
            event(
                {
                    "at": now,
                    "state": self.executor.controller.state,
                    "reason": decision.reason,
                    "wanted": decision.state,
                    "cloud": obs.cloud_health,
                    "command": last.get("status"),
                    "boost_eligible": decision.plan.get("boost_eligible"),
                    "boost_reason": decision.plan.get("boost_reason"),
                    "bottom_c": obs.temperature_c,
                    "grid_import_kw": self.grid_import_kw,
                    # 0.16.2: which command gate held a wanted change, and the
                    # rolling count that optional starts are measured against.
                    "gate": self.executor.controller.reason
                    if self.executor.controller.state == "change_requested"
                    else None,
                    "commands_24h": self.executor.controller.commands_in_window(now),
                }
            )
        )
        if self.owner_event_store:
            try:
                self.owner_event_store.async_delay_save(
                    lambda: {"events": list(self.owner_events)}, 30
                )
            except Exception:  # noqa: BLE001 - diagnostic logging cannot block supervision
                LOG.warning("Owner diagnostic history could not be scheduled for saving.")
        self.telemetry = {
            "schema_version": 2,
            "at": now.isoformat(),
            "power": {
                "watts": self.circuit.watts,
                "state": self.circuit.state,
                "quality": self.circuit.quality,
                "observed_at": self.circuit.observed_at.isoformat()
                if self.circuit.observed_at
                else None,
            },
            "energy": {
                "circuit_kwh": self.circuit_energy_kwh,
                "integrated_covered_kwh": round(self.history.integrated_kwh, 6),
                "covered_seconds": self.history.covered_seconds,
                "gaps": self.history.gaps,
                "counter_epochs": self.history.counter_epochs,
            },
            "thermann": {
                "temperature_c": obs.temperature_c,
                "target_c": obs.target_c,
                "mode": obs.mode,
                "observed_at": obs.poll_at.isoformat() if obs.poll_at else None,
                "time_basis": "bridge_receipt_not_device_acquisition",
                "status_raw": self.heater.status_raw,
            },
            "site": {
                "grid_import_kw": self.grid_import_kw,
                "pv_ac_kw": self.values.get("measured_pv_ac_kw"),
                "budget": self.power_budget,
                "grid_observed_at": self.grid_observed_at.isoformat()
                if self.grid_observed_at
                else None,
            },
            "tariff": {
                "kind": self.values.get("current_tariff"),
                "rate_aud_kwh": self.values.get("current_price_aud"),
                "clock": self.settings.tariff_clock,
                "feed_in_aud_kwh": self.settings.feed_in_rate,
            },
            "forecast": self.details.get("forecast"),
            "controller": {
                "state": self.executor.controller.state,
                "reason": decision.reason,
                "wanted": decision.state,
                "operating_mode": self.executor.controller.operating_mode(now),
                "last_command": dict(last),
            },
            "completion": dict(self.completion),
            "heating_plan": {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in decision.plan.items()
            },
            "calibration": self.history.calibration(obs.target_c),
            "learning": self.learning(now, int(self.native_options["normal_storage_c"])),
            "polling": self.executor.poll_shadow.summary(),
        }

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
            storage_target_c=float(self.native_options["normal_storage_c"]),
            normal_storage_target_c=float(self.native_options["normal_storage_c"]),
            baseline_target_c=float(self.native_options["baseline_c"]),
            tariff_verification="verified" if self.settings.tariff_verified else "unverified",
            feed_in_rate_aud=self.settings.feed_in_rate,
            solar_boost_target_c=float(self.native_options["solar_boost_c"]),
            peak_heating_policy=self.native_options["peak_heating_policy"],
            optional_boost_enabled="on" if self.native_options["optional_solar_boost"] else "off",
            circuit_measurement_mode="ct_free"
            if not self.sources.get("heater_power")
            else "measured"
            if self.circuit.valid
            else "meter_fault",
            heater_measured_w=self.circuit.watts if self.circuit.valid else None,
            heater_meter_state=self.circuit.state,
            heater_meter_quality=self.circuit.quality,
            heater_energy_kwh=self.circuit_energy_kwh,
            heater_raw_w=self.circuit.watts,
            expected_completion=datetime.fromisoformat(self.completion["latest"])
            if self.completion.get("latest")
            else None,
            nominal_heating_minutes=self.completion.get("nominal_continuous_minutes"),
            prediction_confidence="provisional_range"
            if self.completion.get("latest")
            else "unknown",
        )
        calibration = self.history.calibration(target)
        learned = self.learning(now, int(self.native_options["normal_storage_c"]))
        values.update(
            learning_status=learned["planning_basis"],
            learning_sessions=learned["sessions"],
            prediction_error=learned["heldout_mae_minutes"],
            planning_heating_rate=learned["planning_rate_c_per_hour"],
        )
        values["learned_heating_rate"] = (
            calibration["on_kw"] / calibration["kwh_per_c"] if calibration["ready"] else None
        )
        base, _ = base_load(house_kw, self.heater)
        values["base_load_kw"] = None if base is None else round(base, 3)
        health = self._reading("cloud_health")
        values["cloud_health"] = (
            health.value if health and health.value in CLOUD_HEALTH else "unrecognised"
        )
        cloud = self.hass.states.get(self.sources.get("cloud_health", ""))
        attrs = cloud.attributes if cloud else {}
        seconds = attrs.get("poll_interval_seconds")
        values["next_cloud_poll"] = (
            background_poll_due(now, seconds, values["cloud_health"], attrs.get("poll_schedule"))
            if status_ok
            else None
        )
        values["cloud_poll_interval"] = seconds if values["next_cloud_poll"] is not None else None
        schedule = attrs.get("adaptive_polling")
        values["adaptive_polling_status"] = (
            attrs.get("polling_mode", "fixed") + ":" + attrs.get("polling_reason", "clock_aligned")
        )
        if isinstance(schedule, dict) and schedule.get("enabled"):
            try:
                due = datetime.fromisoformat(attrs["next_scheduled_poll"])
                values["next_cloud_poll"] = (
                    due if due.tzinfo and due >= now and values["cloud_health"] == "ok" else None
                )
            except (ValueError, TypeError, KeyError):
                values["next_cloud_poll"] = None
            values["cloud_poll_interval"] = (
                schedule.get("interval_seconds") if values["next_cloud_poll"] else None
            )

        try:
            current = tariff_at(
                now, self.tariffs, self.settings.tariff_clock, self.settings.time_zone
            )
            change = next_tariff_change(
                now, self.tariffs, self.settings.tariff_clock, self.settings.time_zone
            )
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
        values["forecast_load_quality"] = self.forecast.load_quality if self.forecast else None
        comfort = pre_peak_availability(
            now,
            temperature,
            self.poll_at,
            values.get("next_tariff_change") if values.get("next_tariff_kind") == "peak" else None,
            threshold=self.native_options["low_water_warning_c"],
            lead_minutes=self.native_options["pre_peak_observation_minutes"],
            max_age_minutes=self.settings.status_max_age_minutes,
            boot=self.boot,
        )
        values["morning_availability"] = comfort["state"]
        self._requests(now)
        executor = self.executor
        policy = executor.policy_values() if executor is not None else {}
        values.update(policy)
        values["controller"] = (
            "automatic_control" if self.controller_active else "shadow_observation"
        )
        self.details = {
            "morning_availability": comfort,
            "circuit_measurement": {
                "watts": self.circuit.watts,
                "state": self.circuit.state,
                "quality": self.circuit.quality,
                "observed_at": self.circuit.observed_at.isoformat()
                if self.circuit.observed_at
                else None,
                "budget": self.power_budget,
                "aggregate_inference": "diagnostic_only",
            },
            "shadow_mode": not self.controller_active,
            "controller_active": self.controller_active,
            "policy": "four_state_dual_storage (docs/dual-storage)",
            "additional_cloud_requests": 0,
            "local_evaluation_seconds": 60,
            "grid_sign": "import_positive" if self.settings.import_positive else "export_positive",
            "meter_sign_load_test_verified": self.settings.meter_verified,
            "tariff_contract_verified": self.settings.tariff_verified,
            "tariff_clock": self.settings.tariff_clock,
            "time_zone": self.settings.time_zone,
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
                "load_quality": self.forecast.load_quality if self.forecast else None,
                "load_floor_kw": self.forecast.load_floor_kw if self.forecast else None,
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
