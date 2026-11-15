"""Home Assistant side of the production executor (0.9.0).

Every minute (and on each new bridge status):

* builds an ``Observation`` from existing HA states only (no cloud requests);
* feeds the local GoodWe sample and the Thermann reading to ONE coordinated
  policy (``simple_policy``) together with the EMHASS forecast and the tariff;
* runs the pure ``Controller`` state machine on the policy's wanted state;
* persists controller state BEFORE publishing; a failed save sends nothing;
* publishes at most the single MQTT message the controller returns, through
  the bridge's guarded three-state topic. Never retried by this module.

Shadow observation: while automatic control is OFF (the default) the same
policy runs on the observed heater state and records the command it WOULD send
(respecting the same 15-minute spacing). Nothing is published.

A fresh installation cannot command anything: automatic control is OFF, no
command topic is configured and the three-state qualification is false.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, time

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .config import DOMAIN
from .controller import (
    CONFIRMING,
    STEADY,
    Controller,
    ControllerConfig,
    Observation,
    Want,
    expected_command_topic,
    heater_state,
    payload_for,
    refresh_topic,
)
from zoneinfo import ZoneInfo
from .polling import PollContext, PollingShadow
from .adaptive import make_plan, event_plan
from .simple_policy import HOLD, STORAGE, PolicySettings, SimplePolicy, Snapshot

LOG = logging.getLogger(__name__)
STORAGE_VERSION = 1
NOTIFY_SERVICE = re.compile(r"^[a-z0-9_]{1,64}$")
VENDOR_MODES = {"Manual", "Schedule", "Eco", "Off", "Holiday", "Unknown"}
SHADOW_LOG_LENGTH = 30


def controller_config(
    options: dict, poll_minutes: float = 30.0, expected_topic: str | None = None
) -> ControllerConfig:
    from .config import DEFAULT_OPTIONS

    values = {**DEFAULT_OPTIONS, **options}
    return ControllerConfig(
        command_topic=str(values["controller_command_topic"]).strip(),
        bridge_commands_qualified=values["controller_bridge_qualified"] is True,
        three_state_qualified=values["controller_three_state_qualified"] is True,
        max_commands_per_day=int(values["controller_max_commands_per_day"]),
        confirmation_timeout_minutes=float(values["controller_confirmation_timeout_minutes"]),
        max_requests_per_day=int(values["controller_max_requests_per_day"]),
        poll_interval_minutes=poll_minutes,
        expected_command_topic=expected_topic,
        published_forecasts_enabled=values["forecast_enabled"] is True,
        tariff_verified=values["tariff_verified"] is True,
        requires_four_states=True,
        four_state_qualified=values["controller_four_state_qualified"] is True,
    )


class Executor:
    def __init__(self, hass, entry, runtime) -> None:
        self.hass, self.entry, self.runtime = hass, entry, runtime
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.controller")
        self.controller = Controller()
        self.last_evaluated_at = None  # not restored; only a completed evaluation updates it
        self.lock = asyncio.Lock()
        self.listeners: set = set()
        self.last_observation: Observation | None = None
        self.last_decision = None
        self.shadow: list[dict] = []  # would-be commands while control is OFF
        self.save_failed = False
        self._saved: dict | None = None
        self._refresh_wanted = False
        self._last_poll_plan_at = None
        self.poll_shadow = PollingShadow()
        self.reset_policy()
        self.configure(entry.options)

    # ------------------------------------------------------------------ setup
    def configure(self, options) -> None:
        from .config import DEFAULT_OPTIONS

        values = {**DEFAULT_OPTIONS, **options}
        self.controller.time_zone = self.runtime.settings.time_zone
        self.cfg = controller_config(values, self._poll_minutes(), self._expected_topic())
        economic_change = any(
            values[key] != self.runtime.native_options[key]
            for key in ("optional_heat_margin_aud_per_kwh", "pause_min_saving_aud")
        )
        economic_change = economic_change or any(
            values[key] != self.runtime.native_options[key]
            for key in (
                "baseline_c",
                "normal_storage_c",
                "solar_boost_c",
                "tank_litres",
                "element_kw",
                "completion_margin_minutes",
                "optional_solar_boost",
                "peak_heating_policy",
                "boost_useful_fraction",
                "boost_min_saving_aud",
            )
        )
        self.runtime.set_native_reference(options)
        if economic_change:
            self.reset_policy()
        shadow_settings = (
            values["adaptive_polling_shadow"],
            values["adaptive_poll_heating_minutes"],
            values["adaptive_poll_stable_minutes"],
        )
        if shadow_settings != (
            self.poll_shadow.enabled,
            self.poll_shadow.heating_minutes,
            self.poll_shadow.stable_minutes,
        ):
            self.poll_shadow = PollingShadow(*shadow_settings)
        self.notify_service = str(values["controller_notify_service"]).strip()

    def reset_policy(self) -> None:
        settings = self.runtime.settings
        self.policy = SimplePolicy(
            PolicySettings(
                baseline_c=int(self.runtime.native_options["baseline_c"]),
                normal_c=int(self.runtime.native_options["normal_storage_c"]),
                storage_c=int(self.runtime.native_options["solar_boost_c"]),
                boost_enabled=self.runtime.native_options["optional_solar_boost"],
                peak_policy=self.runtime.native_options["peak_heating_policy"],
                element_kw=float(self.runtime.native_options["element_kw"]),
                kwh_per_c=float(self.runtime.native_options["tank_litres"]) * 4.186 / 3600,
                peak_start_kw=float(self.runtime.native_options["element_kw"])
                + settings.export_headroom_kw,
                soft_target_margin=timedelta(
                    minutes=float(self.runtime.native_options["completion_margin_minutes"])
                ),
                boost_useful_fraction=float(self.runtime.native_options["boost_useful_fraction"]),
                boost_min_saving=float(self.runtime.native_options["boost_min_saving_aud"]),
                feed_in_rate=settings.feed_in_rate,
                tariff_clock=settings.tariff_clock,
                time_zone=settings.time_zone,
                daytime_start=time.fromisoformat(self.runtime.native_options["daytime_start"]),
                storage_ready=time.fromisoformat(self.runtime.native_options["storage_ready_time"]),
                baseline_start=time.fromisoformat(self.runtime.native_options["baseline_start"]),
                optional_heat_margin=self.runtime.native_options[
                    "optional_heat_margin_aud_per_kwh"
                ],
                pause_min_saving=self.runtime.native_options["pause_min_saving_aud"],
            ),
            self.runtime.tariffs,
        )

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self.controller = Controller.from_dict(data)
        self.controller.time_zone = self.runtime.settings.time_zone
        self._saved = data if isinstance(data, dict) else None
        self.controller.restored(dt_util.utcnow())
        self.runtime.controller_active = self.controller.enabled
        # Restart: one guarded on-demand status read, so the first decision does
        # not wait for the next poll (the bridge ignores it unless enabled).
        self._refresh_wanted = self.controller.enabled

    def _expected_topic(self) -> str | None:
        """Command topic of the MAPPED heater, from its entity registry entry."""
        try:
            from homeassistant.helpers import entity_registry as er

            entry = er.async_get(self.hass).async_get(self.runtime.sources.get("heater", ""))
        except Exception:  # noqa: BLE001 - no registry: no extra check
            return None
        return expected_command_topic(entry.unique_id if entry else None)

    def _poll_minutes(self) -> float:
        state = self.hass.states.get(self.runtime.sources.get("cloud_health", ""))
        seconds = state.attributes.get("poll_interval_seconds") if state else None
        if isinstance(seconds, (int, float)) and 60 <= seconds <= 7200:
            return seconds / 60
        return 30.0

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    # ------------------------------------------------------------------ owner actions
    async def async_set_enabled(self, enabled: bool) -> None:
        missing = self.cfg.missing_commissioning()
        if enabled and missing:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(
                "Automatic control cannot be enabled until commissioning is complete: "
                + ", ".join(missing)
                + ". Nothing was changed."
            )
        async with self.lock:
            self.controller.set_enabled(enabled, dt_util.utcnow())
            self.runtime.controller_active = enabled
            self._refresh_wanted = enabled  # activation: one guarded status read
            await self._save()
        self._notify_listeners()

    async def async_set_holiday(self, which: str, value) -> bool:
        """Owner: the holiday departure or return DATE (date entities)."""
        async with self.lock:
            now = dt_util.utcnow()
            controller = self.controller
            start = controller.holiday_start_date()
            back = controller.holiday_return_date()
            if which == "start":
                start = value
            else:
                back = value
            done = controller.set_holiday(now, start, back)
            await self._save()
        self._notify_listeners()
        return done

    async def async_owner_action(self, action: str) -> bool:
        async with self.lock:
            now = dt_util.utcnow()
            done = {
                "hold": lambda: (self.controller.set_hold(now), True)[1],
                "resume": lambda: self.controller.resume(now),
                "acknowledge": lambda: self.controller.acknowledge(now),
                "guest_start": lambda: self.controller.start_guest(now),
                "guest_cancel": lambda: self.controller.cancel_guest(now),
                "holiday_cancel": lambda: self.controller.cancel_holiday(now),
            }[action]()
            await self._save()
        self._notify_listeners()
        return done

    # ------------------------------------------------------------------ evaluation
    def observe(self, now: datetime) -> Observation:
        states, sources = self.hass.states, self.runtime.sources
        obs = Observation(now=now, mqtt_ready="mqtt" in self.hass.config.components)
        obs.poll_at = self.runtime.poll_at
        obs.heater_meter_mapped = bool(self.runtime.sources.get("heater_power"))
        obs.heater_meter_quality = self.runtime.circuit.quality
        mode = states.get(sources.get("mode", ""))
        if mode is not None and mode.state in VENDOR_MODES:
            obs.mode = mode.state
        heater = states.get(sources.get("heater", ""))
        if heater is not None and heater.state != "unavailable":
            obs.target_c = _number(heater.attributes.get("temperature"))
            obs.temperature_c = _number(heater.attributes.get("current_temperature"))
        health = states.get(sources.get("cloud_health", ""))
        if health is not None and health.state != "unavailable":
            attrs = health.attributes
            obs.cloud_health = health.state
            obs.auth_mode = attrs.get("auth_guard_mode")
            obs.consecutive_failures = _int(attrs.get("consecutive_failures"))
            obs.cooldown_seconds = _int(attrs.get("cooldown_remaining_seconds"))
            flag = attrs.get("commands_enabled")
            obs.bridge_commands_enabled = flag if isinstance(flag, bool) else None
            last = attrs.get("last_command")
            obs.last_command = dict(last) if isinstance(last, dict) else None
            obs.bridge_refresh_limit = _int(attrs.get("command_status_refresh_limit_24h"))
            obs.bridge_refreshes_24h = _int(attrs.get("command_status_refreshes_24h"))
            pending = attrs.get("command_confirmation_pending")
            obs.bridge_confirmation_pending = pending if isinstance(pending, bool) else None
            policy = attrs.get("command_policy")
            obs.bridge_command_policy = policy if isinstance(policy, str) else None
            transitions = attrs.get("command_transitions")
            obs.bridge_transitions = list(transitions) if isinstance(transitions, list) else None
        obs.bridge_available = (
            mode is not None and mode.state != "unavailable" and obs.cloud_health is not None
        )
        counter = states.get(sources.get("requests", ""))
        if counter is not None:
            obs.requests_total = _int(counter.state)
        obs.element = self.runtime.circuit.state
        obs.element_confidence = "verified" if self.runtime.circuit.valid else "none"
        forecast = self.runtime.forecast
        obs.forecast_available = (
            bool(forecast is not None and forecast.slots)
            if self.runtime.settings.forecast_enabled
            else None
        )
        if health is not None:
            self._quiet_deadline(obs, health.attributes.get("adaptive_polling"))
        return obs

    def _quiet_state(self, obs, decision):
        controller = self.controller
        if (
            not controller.enabled
            or controller.state not in STEADY
            or controller.hold
            or controller.intent
            or decision is None
            or decision.command
            or decision.state != obs.heater_state
            or obs.heater_state != controller.heater
            or (obs.heater_meter_mapped and obs.heater_meter_quality != "verified")
        ):
            return None
        if decision.reason == "baseline":
            # A reported cold baseline is a useful progress observation, even
            # though CT-free operation cannot prove the element energised.
            if (
                obs.temperature_c is None
                or obs.temperature_c < self.policy.s.baseline_c - self.policy.s.hysteresis_c
            ):
                return None
            return "baseline"
        if (
            decision.state == "off"
            and decision.plan.get("mode") == "peak"
            and self.runtime.native_options["peak_heating_policy"]
            == "Never schedule heating during peak"
        ):
            return "off"
        return None

    def _quiet_deadline(self, obs, schedule):
        """Only suppress a passive-age alert; never grants command/temperature authority."""
        if (
            not self.runtime.native_options["event_aware_polling_enabled"]
            or not self.runtime.native_options["adaptive_polling_enabled"]
            or not self._quiet_state(obs, self.last_decision)
            or obs.cloud_health != "ok"
            or obs.auth_mode != "authorized"
            or not isinstance(schedule, dict)
            or schedule.get("active") is not True
            or schedule.get("plan_version") != 2
            or schedule.get("reason") not in ("stable_baseline", "stable_off")
            or obs.poll_at is None
            or obs.poll_at > obs.now
        ):
            return
        owner = schedule.get("owner_check_seconds")
        next_at = schedule.get("next_at")
        maximum = self.runtime.native_options["owner_change_check_minutes"] * 60
        if (
            type(owner) is not int
            or not 1800 <= owner <= min(5400, maximum)
            or type(next_at) not in (int, float)
            or not obs.poll_at.timestamp() <= next_at <= obs.poll_at.timestamp() + owner + 1
        ):
            return
        obs.passive_status_deadline = obs.poll_at + timedelta(seconds=owner + 300)

    def _event_decision_at(self, now, decision, decision_at):
        """Observe at the real policy transition, allowing the strict prior to be reused."""
        moments = []
        boundary = self.runtime.values.get("next_tariff_change")
        if boundary is not None:
            moments.append(
                boundary - self.policy.s.peak_lead
                if self.runtime.values.get("next_tariff_kind") == "peak"
                else boundary
            )
        # Flat/no-afternoon-peak service windows also have known local transitions.
        zone = ZoneInfo(self.runtime.settings.time_zone)
        today = now.astimezone(zone).date()
        for day in (today, today + timedelta(days=1)):
            if day.weekday() < 5:
                for clock in (self.policy.s.daytime_start, self.policy.s.baseline_start):
                    when = datetime.combine(day, clock, zone)
                    if when >= now and self.policy._kind(when) != "peak":
                        moments.append(when)
        # Retain actual start/pause/override decisions, but use the adjusted peak
        # boundary above rather than the old ten-minute advance fetch.
        if decision_at is not None and decision_at != boundary:
            moments.append(decision_at)
        if decision.command:
            moments.append(now)
        # A verified full-solar opportunity can make a new probe consequential.
        if (
            self.runtime.temperature_c is None
            and self.runtime.power_budget is not None
            and self.runtime.native_options["optional_solar_boost"]
            and self.policy.sustained(
                now, self.policy.s.qualify, lambda x: x[2] >= self.policy.s.peak_start_kw
            )
        ):
            moments.append(now)
        return min((at for at in moments if at >= now), default=None)

    def decide(self, now: datetime, obs: Observation):
        """One policy decision from the measurements (never a request)."""
        runtime, controller = self.runtime, self.controller
        if controller.enabled:
            # While a command awaits confirmation the policy plans from the
            # state it requested (found by the end-to-end test: planning from
            # the old state wanted it back and bypassed the spacing).
            intent = controller.intent if controller.state == CONFIRMING else None
            state = intent["target"] if intent else controller.heater
            last = controller.last_command_at()
        else:
            state = heater_state(obs.mode, obs.target_c)
            last = _dt(self.shadow[-1]["at"]) if self.shadow else None
        grid = runtime.grid_import_kw
        if grid is not None:
            # Physical budget always uses measured watts. Optional upgrades from
            # baseline still require raw export: existing baseline heat is not a
            # new discretionary solar purchase. Never credit aggregate inference.
            watts = (
                runtime.circuit.watts
                if runtime.power_budget is not None and state in (STORAGE, "normal_storage")
                else 0.0
            )
            at = runtime.grid_observed_at
            if runtime.power_budget is not None:
                at = min(at, runtime.circuit.observed_at)
            if at is not None:
                self.policy.add_meter(at, grid, heater_kw=watts / 1000)
        else:
            self.policy.samples.clear()  # a loss breaks qualification continuity
        if runtime.power_budget is None:
            self.policy.samples.clear()
        forecast = runtime.forecast.slots if runtime.forecast is not None else ()
        snapshot = Snapshot(
            now=now,
            heater_state=state,
            reading_c=runtime.temperature_c,
            reading_at=runtime.poll_at,
            learned_rates={
                target: info["planning_rate_c_per_hour"]
                for target in (45, 62, 70)
                if (info := runtime.learning(now, target))["affects_control"]
            },
            required_export_kw=max(0, -grid) if grid is not None else None,
            forecast=tuple(forecast),
            last_command_at=last,
            heater_meter_valid=runtime.power_budget is not None,
            optional_allowed=(
                not controller.enabled
                or (
                    len(controller.commands) < self.cfg.max_commands_per_day
                    and controller.requests_last_24h(now) is not None
                    and controller.requests_last_24h(now) + 10 <= self.cfg.max_requests_per_day
                )
            ),
            measured_element_kw=runtime.circuit.watts / 1000
            if runtime.circuit.valid and runtime.circuit.state == "on"
            else None,
            owner_override=controller.enabled
            and (controller.hold or controller.state == "owner_override"),
            holiday=controller.holiday_active(now),
            override_12h=controller.guest_active(now),
        )
        decision = self.policy.decide(snapshot)
        self.last_decision = decision
        return decision, state

    def _record_shadow(self, now: datetime, decision, state) -> None:
        if self.controller.enabled:
            return
        if decision.command is None or state is None or decision.state == HOLD:
            return
        payload = payload_for(decision.state, state)
        if (
            self.shadow
            and self.shadow[-1]["would_send"] == payload
            and _dt(self.shadow[-1]["at"])
            .astimezone(ZoneInfo(self.runtime.settings.time_zone))
            .date()
            == now.astimezone(ZoneInfo(self.runtime.settings.time_zone)).date()
        ):
            # The heater is not changed in shadow mode, so the same wish recurs
            # after every spacing interval: recorded once a (Hobart) day. The
            # next day's command is recorded again (0.9.1, audit M7), so each
            # day's park is visible.
            return
        self.shadow = (
            self.shadow
            + [
                {
                    "at": now.isoformat(),
                    "would_send": payload,
                    "reason": decision.reason,
                    "layer": decision.layer,
                }
            ]
        )[-SHADOW_LOG_LENGTH:]

    async def async_step(self, now: datetime | None = None) -> None:
        async with self.lock:
            now = now or dt_util.utcnow()
            self.cfg = controller_config(
                self.entry.options, self._poll_minutes(), self._expected_topic()
            )
            obs = self.observe(now)
            self.last_observation = obs
            decision, state = self.decide(now, obs)
            self._record_shadow(now, decision, state)
            want = Want(decision.state, decision.reason, decision.layer, dict(decision.plan))
            effects = self.controller.step(obs, want, self.cfg)
            self.runtime.controller_active = self.controller.enabled
            if not await self._save():
                # Never publish an intent that is not persisted (restart safety).
                effects = [e for e in effects if e.kind != "publish"]
                if self.controller.intent:
                    effects += self.controller.publish_failed(now)
            for effect in [e for e in effects if e.kind == "publish"]:
                try:
                    from homeassistant.components import mqtt

                    await mqtt.async_publish(self.hass, effect.topic, effect.payload, 1, False)
                    LOG.info("Controller published %s (intent %s).", effect.payload, effect.key)
                except Exception:  # noqa: BLE001 - any failure is a fault; never retried
                    LOG.warning("Controller MQTT publish failed; automatic control locked.")
                    effects += self.controller.publish_failed(now)
                    await self._save()
            if self._refresh_wanted and self.controller.enabled:
                await self._request_refresh()
            for effect in effects:
                if effect.kind == "notify":
                    await self._notify(effect)
                elif effect.kind == "resolve":
                    self._dismiss(effect.key)
            actions = [
                self.runtime.values.get("next_tariff_change"),
                decision.plan.get("best_start"),
                decision.plan.get("latest_start"),
                decision.plan.get("next_baseline"),
                now if decision.command and self.controller.enabled else None,
            ]
            actions = [at for at in actions if at is not None and at >= now]
            self.poll_shadow.observe(
                PollContext(
                    now=now,
                    status_at=obs.poll_at,
                    heating=(self.runtime.circuit.state == "on")
                    if self.runtime.circuit.valid
                    else None,
                    command_at=self.controller.last_command_at(),
                    confirming=self.controller.state == CONFIRMING,
                    uncertain=self.runtime.temperature_c is None,
                    decision_at=min(actions) if actions else None,
                    completion_at=_dt(self.runtime.completion.get("earliest")),
                    cloud_ready=obs.cloud_health == "ok"
                    and obs.auth_mode == "authorized"
                    and not obs.cooldown_seconds,
                    desired_target_c=decision.plan.get("desired_target_c"),
                    reported_target_c=obs.target_c if obs.mode == "Manual" else None,
                )
            )
            # An already-selected storage target needs no new start decision.
            # Keep the old shadow comparison intact, but do not spend real GETs
            # on its hypothetical latest-start or zero-benefit pause window.
            storing = (self.policy.setpoint(state) or 0) >= int(
                self.runtime.native_options["normal_storage_c"]
            )
            actual_actions = [
                self.runtime.values.get("next_tariff_change"),
                decision.plan.get("next_baseline"),
            ]
            if self.controller.enabled:
                actual_actions += [now] if decision.command else []
                if not storing:
                    actual_actions += [
                        decision.plan.get("best_start"),
                        decision.plan.get("latest_start"),
                    ]
            actual_actions = [when for when in actual_actions if when is not None and when >= now]
            await self._publish_poll_plan(
                now, obs, decision, min(actual_actions) if actual_actions else None
            )
            self.runtime.record_event(now, obs, decision)
            self.last_evaluated_at = now
        self._notify_listeners()

    async def _publish_poll_plan(self, now, obs, decision, decision_at):
        if not self.runtime.native_options["adaptive_polling_enabled"]:
            return
        if self.controller.state == CONFIRMING:
            return  # the bridge owns the existing confirmation read sequence
        if (
            self._last_poll_plan_at is not None
            and 0 <= (now - self._last_poll_plan_at).total_seconds() < 60
        ):
            return
        topic = refresh_topic(self.cfg.command_topic)
        if topic is None or obs.cloud_health != "ok" or obs.auth_mode != "authorized":
            return
        health = self.hass.states.get(self.runtime.sources.get("cloud_health", ""))
        versions = health.attributes.get("adaptive_plan_versions", []) if health else []
        wants_event_aware = self.runtime.native_options["event_aware_polling_enabled"]
        event_aware = (
            wants_event_aware
            and isinstance(versions, list)
            and any(type(v) is int and v == 2 for v in versions)
        )
        if wants_event_aware and not event_aware:
            return  # no v2 qualification/capability: expire into fixed fallback
        if event_aware:
            plan = event_plan(
                now,
                obs.poll_at,
                stable_state=self._quiet_state(obs, decision),
                temperature_valid=self.runtime.temperature_c is not None,
                decision_at=self._event_decision_at(now, decision, decision_at),
                owner_check_minutes=self.runtime.native_options["owner_change_check_minutes"],
                status_max_minutes=self.runtime.settings.status_max_age_minutes,
            )
        else:
            plan = make_plan(
                now,
                obs.poll_at,
                heating=self.runtime.circuit.state == "on",
                has_ct=self.runtime.circuit.valid,
                temperature_valid=self.runtime.temperature_c is not None,
                decision_at=decision_at,
                completion_at=_dt(self.runtime.completion.get("earliest")),
                status_max_minutes=self.runtime.settings.status_max_age_minutes,
            )
        if plan is None:
            return
        self._last_poll_plan_at = now
        try:
            from homeassistant.components import mqtt
            import json

            await mqtt.async_publish(
                self.hass, topic.removesuffix("refresh") + "poll_plan", json.dumps(plan), 0, False
            )
        except Exception:  # noqa: BLE001 - no fallback HTTP or retry; bridge lease expires
            LOG.debug("Adaptive plan unavailable; bridge fixed fallback remains.")

    async def _request_refresh(self) -> None:
        """At activation or restart: ask the bridge for ONE guarded status read
        (its own spacing, authentication, backoff and quota gates still apply,
        and it ignores the request unless on-demand refresh is enabled)."""
        self._refresh_wanted = False
        topic = refresh_topic(self.cfg.command_topic)
        if topic is None:
            return
        try:
            from homeassistant.components import mqtt

            await mqtt.async_publish(self.hass, topic, "refresh", 0, False)
        except Exception:  # noqa: BLE001 - a status request is never essential
            LOG.debug("On-demand status request could not be published.")

    async def _save(self) -> bool:
        """Write only when the controller state changed. An intent is always new
        state, so it is always written before its message is published."""
        data = self.controller.to_dict()
        if data == self._saved and not self.save_failed:
            return True
        try:
            await self.store.async_save(data)
            self._saved = data
            self.save_failed = False
            return True
        except Exception:  # noqa: BLE001
            LOG.warning("Controller state could not be saved; no command will be sent.")
            self.save_failed = True
            return False

    # ------------------------------------------------------------------ notifications
    async def _notify(self, effect) -> None:
        from homeassistant.components import persistent_notification

        try:
            persistent_notification.async_create(
                self.hass, effect.message, effect.title, f"{DOMAIN}_{effect.key}"
            )
        except Exception:  # noqa: BLE001 - a notification never breaks control
            LOG.warning("Home Assistant notification could not be created.")
        if self.notify_service and NOTIFY_SERVICE.match(self.notify_service):
            if self.hass.services.has_service("notify", self.notify_service):
                try:
                    await self.hass.services.async_call(
                        "notify",
                        self.notify_service,
                        {"title": effect.title, "message": effect.message},
                        blocking=False,
                    )
                except Exception:  # noqa: BLE001
                    LOG.warning("Owner notification service failed.")

    def _dismiss(self, key: str) -> None:
        from homeassistant.components import persistent_notification

        try:
            persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_{key}")
        except Exception:  # noqa: BLE001
            LOG.debug("Notification dismiss failed.")

    def _notify_listeners(self) -> None:
        for listener in tuple(self.listeners):
            listener()

    # ------------------------------------------------------------------ display
    def policy_values(self) -> dict:
        """Read-only policy sensors (runtime display)."""
        decision = self.last_decision
        plan = decision.plan if decision else {}
        return {
            "policy_state": decision.state if decision else None,
            "decision": decision.reason if decision else None,
            "policy_mode": plan.get("mode"),
            "planned_start": plan.get("best_start"),
            "latest_start": plan.get("latest_start"),
            "soft_target": plan.get("soft_target"),
            "peak_start": plan.get("next_peak"),
            "heating_hours_needed": plan.get("heating_hours"),
            "target_reached": None if not plan else ("yes" if plan.get("target_reached") else "no"),
            "measured_surplus_kw": None
            if plan.get("measured_kw") is None
            else round(plan["measured_kw"], 2),
            "shadow_command": self.shadow[-1]["would_send"] if self.shadow else None,
            "desired_temperature": plan.get("desired_target_c"),
            "heating_requirement": plan.get("heating_role"),
            "boost_eligibility": "eligible" if plan.get("boost_eligible") else "unavailable",
            "boost_reason": plan.get("boost_reason"),
            "planned_heat_kwh": plan.get("planned_heat_kwh"),
        }

    def plan_details(self) -> dict:
        decision = self.last_decision
        if decision is None:
            return {}
        plan = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in decision.plan.items()
        }
        return {
            "state": decision.state,
            "reason": decision.reason,
            "layer": decision.layer,
            "command_now": decision.command,
            "plan": plan,
            "shadow_log": list(self.shadow),
        }

    def values(self) -> dict:
        now = dt_util.utcnow()
        summary = self.controller.summary(now)
        obs = self.last_observation
        last = summary["last_command"] or {}
        want = summary["want"] or {}
        decision = self.last_decision
        return {
            "controller_state": summary["state"],
            "controller_reason": summary["reason"],
            "controller_evaluated_at": self.last_evaluated_at,
            "thermann_mode": obs.mode if obs else None,
            "thermann_target": obs.target_c if obs else None,
            "next_action": want.get("state") or (decision.state if decision else None),
            "next_heating_start": _parse(want.get("best_start")),
            "next_heating_stop": _parse(want.get("soft_target")),
            "last_command": last.get("payload"),
            "last_command_result": last.get("status"),
            "last_command_time": _parse(last.get("created_at")),
            "commands_last_24h": summary["commands_last_24h"],
            "requests_last_24h": summary["requests_last_24h"],
            "fault": summary["fault"] or "none",
            "parked_off_restore_since": _parse(summary["parked_off_restore_since"]),
            "operating_mode": summary["operating_mode"],
            "guest_mode_ends": _parse(summary["guest_until"]),
            "desired_temperature": decision.plan.get("desired_target_c") if decision else None,
            "heating_requirement": decision.plan.get("heating_role") if decision else None,
            "boost_eligibility": "eligible"
            if decision and decision.plan.get("boost_eligible")
            else "unavailable",
            "boost_reason": decision.plan.get("boost_reason") if decision else None,
            "planned_heat_kwh": decision.plan.get("planned_heat_kwh") if decision else None,
            "request_budget_remaining": max(
                0, self.cfg.max_requests_per_day - summary["requests_last_24h"]
            )
            if summary["requests_last_24h"] is not None
            else None,
            "next_adaptive_poll": self.poll_shadow.next_due,
            "adaptive_poll_interval": (
                self.poll_shadow.next_due - self.poll_shadow.virtual_at
            ).total_seconds()
            if self.poll_shadow.enabled
            and self.poll_shadow.next_due
            and self.poll_shadow.virtual_at
            else None,
        }

    def details(self) -> dict:
        now = dt_util.utcnow()
        obs = self.last_observation
        return {
            **self.controller.summary(now),
            "commissioning_missing": self.cfg.missing_commissioning(),
            "command_topic_configured": bool(self.cfg.command_topic),
            "payloads": "<target>@<prior>: off / Manual:45 / Manual:70 (bridge 1.3.13)",
            "command_timing": "single_message_bridge_fresh_status_no_retry",
            "policy_decision": self.plan_details(),
            "state_saved": not self.save_failed,
            "observation": {
                "poll_at": obs.poll_at.isoformat() if obs and obs.poll_at else None,
                "mode": obs.mode if obs else None,
                "target_c": obs.target_c if obs else None,
                "temperature_c": obs.temperature_c if obs else None,
                "element": obs.element if obs else None,
                "element_confidence": obs.element_confidence if obs else None,
                "cloud_health": obs.cloud_health if obs else None,
                "bridge_commands_enabled": obs.bridge_commands_enabled if obs else None,
                "bridge_last_command": obs.last_command if obs else None,
                "bridge_transitions": obs.bridge_transitions if obs else None,
            },
            "recovery_manual": "Official Thermann app: select Manual at 70 °C (hot water now), "
            "Manual 45 °C, or turn the heater OFF. Never reset authentication locks "
            "automatically; see the app documentation.",
            "confirming": self.controller.state == CONFIRMING,
        }


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _int(value):
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse(value):
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else None
