"""Home Assistant side of the production executor.

* Builds an ``Observation`` from existing HA states only (no cloud requests).
* Asks the planner (``runtime.advice``) for one ``Desire`` per evaluation.
* Runs the pure ``Controller`` state machine.
* Persists controller state BEFORE publishing; a failed save sends nothing.
* Publishes at most the single MQTT message the controller returns, through the
  existing Thermowatt bridge topic. Never retried by this module.

A fresh installation cannot command anything: automatic control is OFF, no
command topic is configured and both commissioning confirmations are false.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .config import DOMAIN
from .control_plan import (
    PEAK_GUARD_MARGIN,
    SessionTemperature,
    desire_from_advice,
    holiday_desire,
    morning_failsafe_window,
)
from .controller import (
    CONFIRMING,
    HEATING_PERMITTED,
    PARK_REQUESTED,
    Controller,
    ControllerConfig,
    Desire,
    Observation,
)
from .goals import next_tariff_change
from .permission import StandbyPermission

LOG = logging.getLogger(__name__)
STORAGE_VERSION = 1
NOTIFY_SERVICE = re.compile(r"^[a-z0-9_]{1,64}$")
VENDOR_MODES = {"Manual", "Schedule", "Eco", "Off", "Holiday", "Unknown"}


def controller_config(options: dict, poll_minutes: float = 30.0) -> ControllerConfig:
    from .config import DEFAULT_OPTIONS

    values = {**DEFAULT_OPTIONS, **options}
    return ControllerConfig(
        command_topic=str(values["controller_command_topic"]).strip(),
        bridge_commands_qualified=values["controller_bridge_qualified"] is True,
        min_heating_minutes=float(values["controller_min_heating_minutes"]),
        min_rest_minutes=float(values["controller_min_rest_minutes"]),
        max_commands_per_day=int(values["controller_max_commands_per_day"]),
        confirmation_timeout_minutes=float(values["controller_confirmation_timeout_minutes"]),
        max_requests_per_day=int(values["controller_max_requests_per_day"]),
        poll_interval_minutes=poll_minutes,
    )


class Executor:
    def __init__(self, hass, entry, runtime) -> None:
        self.hass, self.entry, self.runtime = hass, entry, runtime
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.controller")
        self.controller = Controller()
        self.session = SessionTemperature()
        self.standby = StandbyPermission()
        self.lock = asyncio.Lock()
        self.listeners: set = set()
        self.last_observation: Observation | None = None
        self.save_failed = False
        self._saved: dict | None = None
        self.configure(entry.options)

    # ------------------------------------------------------------------ setup
    def configure(self, options) -> None:
        from .config import DEFAULT_OPTIONS

        values = {**DEFAULT_OPTIONS, **options}
        self.cfg = controller_config(values, self._poll_minutes())
        self.latency_minutes = float(values["controller_execution_latency_minutes"])
        self.notify_service = str(values["controller_notify_service"]).strip()

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self.controller = Controller.from_dict(data)
        self._saved = data if isinstance(data, dict) else None
        self.controller.restored(dt_util.utcnow())
        self.runtime.controller_active = self.controller.enabled

    def _poll_minutes(self) -> float:
        state = self.hass.states.get(self.runtime.sources.get("cloud_health", ""))
        seconds = state.attributes.get("poll_interval_seconds") if state else None
        if isinstance(seconds, (int, float)) and 60 <= seconds <= 7200:
            return seconds / 60
        return 30.0

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def permitted(self) -> bool:
        """Whether Manual (heating permission) is the controller's current state."""
        if self.controller.state in {HEATING_PERMITTED, PARK_REQUESTED}:
            return True
        intent = self.controller.intent or {}
        return self.controller.state == CONFIRMING and intent.get("action") == "park"

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
            await self._save()
        self._notify_listeners()

    async def async_set_holiday(self, which: str, value: datetime | None) -> bool:
        """Owner: set the holiday departure or return (datetime entities)."""
        async with self.lock:
            now = dt_util.utcnow()
            controller = self.controller
            start = (
                dt_util.parse_datetime(controller.holiday_start)
                if controller.holiday_start
                else None
            )
            back = (
                dt_util.parse_datetime(controller.holiday_return)
                if controller.holiday_return
                else None
            )
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
        poll = states.get(sources.get("last_poll", ""))
        if poll is not None and poll.state not in {"unknown", "unavailable", "None"}:
            try:
                obs.poll_at = dt_util.parse_datetime(poll.state)
            except (TypeError, ValueError):
                obs.poll_at = None
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
            followups = attrs.get("command_confirmation_followups_seconds")
            obs.bridge_confirmation_followups = (
                list(followups) if isinstance(followups, list) else None
            )
            pending = attrs.get("command_confirmation_pending")
            obs.bridge_confirmation_pending = pending if isinstance(pending, bool) else None
        obs.bridge_available = (
            mode is not None and mode.state != "unavailable" and obs.cloud_health is not None
        )
        counter = states.get(sources.get("requests", ""))
        if counter is not None:
            obs.requests_total = _int(counter.state)
        advice = self.runtime.advice
        if advice is not None:
            obs.element = advice.heater.state
            obs.element_confidence = advice.heater.confidence
        return obs

    def desire(self, now: datetime):
        change = None
        try:
            change = next_tariff_change(
                now, self.runtime.tariffs, self.runtime.settings.tariff_clock
            )
        except ValueError:
            pass
        peak = change[0] if change and change[1].kind == "peak" else None
        advice = self.runtime.advice
        settings, tariffs = self.runtime.settings, self.runtime.tariffs
        peak_soon = (
            peak is not None
            and now <= peak <= now + timedelta(minutes=self.latency_minutes) + PEAK_GUARD_MARGIN
        )
        economics = self.standby.assess(
            now, advice, settings, tariffs, decision_at=peak if peak_soon else None
        )
        obs = self.last_observation
        controller = self.controller
        if controller.guest_active(now):
            # Guest mode: Manual 70 °C for the whole period, economics relaxed;
            # every controller gate, confirmation and owner rule still applies.
            return Desire("permit", "guest_mode", comfort=True, standby=True)
        if controller.holiday_active(now):
            # Away: no comfort goals and no economic standby permission; the
            # planner prepares only the return goal (cheapest feasible heat)
            # and otherwise keeps the heater parked (OFF keeps antibacterial
            # and frost protection active).
            return holiday_desire(
                now,
                controller.holiday_window(now),
                advice,
                self.permitted(),
                self.latency_minutes,
                peak,
                advice.heater.state if advice else "unknown",
            )
        return desire_from_advice(
            now,
            advice,
            self.permitted(),
            self.latency_minutes,
            peak,
            advice.heater.state if advice else "unknown",
            standby=self.standby,
            economics=economics,
            reading=obs.temperature_c if obs else None,
            morning_window=morning_failsafe_window(now, settings, tariffs),
        )

    async def async_step(self, now: datetime | None = None) -> None:
        async with self.lock:
            now = now or dt_util.utcnow()
            self.cfg = controller_config(self.entry.options, self._poll_minutes())
            obs = self.observe(now)
            self.last_observation = obs
            desire = self.desire(now)
            effects = self.controller.step(obs, desire, self.cfg)
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
            for effect in effects:
                if effect.kind == "notify":
                    await self._notify(effect)
                elif effect.kind == "resolve":
                    self._dismiss(effect.key)
        self._notify_listeners()

    async def _save(self) -> bool:
        """Write only when the controller state changed (no per-minute disk
        writes while idle). An intent is always new state, so it is always
        written before its message is published."""
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
    def values(self) -> dict:
        now = dt_util.utcnow()
        summary = self.controller.summary(now)
        obs = self.last_observation
        last = summary["last_command"] or {}
        desire = summary["desire"] or {}
        return {
            "controller_state": summary["state"],
            "controller_reason": summary["reason"],
            "thermann_mode": obs.mode if obs else None,
            "thermann_target": obs.target_c if obs else None,
            "next_action": desire.get("action"),
            "next_heating_start": _parse(desire.get("next_start")),
            "next_heating_stop": _parse(desire.get("next_stop")),
            "last_command": last.get("payload"),
            "last_command_result": last.get("status"),
            "last_command_time": _parse(last.get("created_at")),
            "commands_last_24h": summary["commands_last_24h"],
            "requests_last_24h": summary["requests_last_24h"],
            "fault": summary["fault"] or "none",
            "operating_mode": summary["operating_mode"],
            "guest_mode_ends": _parse(summary["guest_until"]),
        }

    def details(self) -> dict:
        now = dt_util.utcnow()
        obs = self.last_observation
        return {
            **self.controller.summary(now),
            "commissioning_missing": self.cfg.missing_commissioning(),
            "command_topic_configured": bool(self.cfg.command_topic),
            "permit_payload": "Manual:70 (bridge >= 1.3.9 guarded Manual)",
            "park_payload": "off (Thermann software OFF; antibacterial and frost protection stay active)",
            "execution_latency_reserved_minutes": self.latency_minutes,
            "command_timing": "single_message_bridge_fresh_status_no_retry",
            "planning_temperature": self.session.summary(),
            "permission_economics": self.standby.last.summary() if self.standby.last else None,
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
                "bridge_refreshes_24h": obs.bridge_refreshes_24h if obs else None,
                "bridge_refresh_limit_24h": obs.bridge_refresh_limit if obs else None,
            },
            "recovery_manual": "Official Thermann app: select Manual at 70 °C (hot water now), or turn the heater OFF (parked). "
            "Never reset authentication locks automatically; see the add-on documentation.",
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
