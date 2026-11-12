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
from datetime import datetime

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .config import DOMAIN
from .controller import (
    CONFIRMING,
    Controller,
    ControllerConfig,
    Observation,
    Want,
    expected_command_topic,
    heater_state,
    payload_for,
    refresh_topic,
)
from .simple_policy import HOLD, PolicySettings, SimplePolicy, Snapshot

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
    )


class Executor:
    def __init__(self, hass, entry, runtime) -> None:
        self.hass, self.entry, self.runtime = hass, entry, runtime
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.controller")
        self.controller = Controller()
        self.lock = asyncio.Lock()
        self.listeners: set = set()
        self.last_observation: Observation | None = None
        self.last_decision = None
        self.shadow: list[dict] = []  # would-be commands while control is OFF
        self.save_failed = False
        self._saved: dict | None = None
        self._refresh_wanted = False
        self.reset_policy()
        self.configure(entry.options)

    # ------------------------------------------------------------------ setup
    def configure(self, options) -> None:
        from .config import DEFAULT_OPTIONS

        values = {**DEFAULT_OPTIONS, **options}
        self.cfg = controller_config(values, self._poll_minutes(), self._expected_topic())
        self.notify_service = str(values["controller_notify_service"]).strip()

    def reset_policy(self) -> None:
        settings = self.runtime.settings
        self.policy = SimplePolicy(
            PolicySettings(feed_in_rate=settings.feed_in_rate, tariff_clock=settings.tariff_clock),
            self.runtime.tariffs,
        )

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self.controller = Controller.from_dict(data)
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
        """Owner: the holiday departure (a datetime) or the return DATE."""
        async with self.lock:
            now = dt_util.utcnow()
            controller = self.controller
            start = dt_util.parse_datetime(controller.holiday_start or "") or None
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
        obs.element = self.runtime.heater.state
        obs.element_confidence = self.runtime.heater.confidence
        return obs

    def decide(self, now: datetime, obs: Observation):
        """One policy decision from the measurements (never a request)."""
        runtime, controller = self.runtime, self.controller
        grid = runtime.grid_import_kw
        if grid is not None:
            element = {"on": True, "off": False}.get(runtime.heater.state)
            self.policy.add_meter(now, grid, element)
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
        forecast = runtime.forecast.slots if runtime.forecast is not None else ()
        snapshot = Snapshot(
            now=now,
            heater_state=state,
            reading_c=runtime.temperature_c,
            reading_at=runtime.poll_at,
            forecast=tuple(forecast),
            last_command_at=last,
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
        if self.shadow and self.shadow[-1]["would_send"] == payload:
            # The heater is not changed in shadow mode, so the same wish recurs
            # after every spacing interval: recorded once.
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
        self._notify_listeners()

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
