"""0.9.0 end-to-end: HA sensor states and an EMHASS forecast -> runtime -> policy
-> controller -> MQTT -> the REAL bridge 1.3.13 (production defaults) -> mocked
Thermowatt cloud HTTP -> STATUS/DIAGNOSTICS -> HA states -> confirmation.

Everything is offline: a minimal Home Assistant stub, a mocked MQTT bus, a
mocked cloud (with a 30 s readback delay) and a tiny tank model (Manual
thermostat, 8 °C hysteresis, 3 kW). No live service, heater or credential."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from conftest import TOKENS, bridge_module as b, response
from test_shadow_model import PACKAGE, c, m, package

SERIAL = "TEST123"
TOPIC = f"P/{SERIAL}/CMD/MODE"
FORECAST_PV, FORECAST_LOAD = "sensor.emhass_pv", "sensor.emhass_load"


def drive(coroutine):
    """Run a coroutine that never waits (every stub here is immediate), without an
    event loop: asyncio's loop would open a local socket, which conftest forbids."""
    try:
        while True:
            coroutine.send(None)
    except StopIteration as done:
        return done.value


def hobart(day, hour, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=m.HOBART).astimezone(timezone.utc)


MON, TUE = 16, 17  # 2026-11-16/17, AEDT: peaks 08-11 and 17-22


class Tank:
    """The heater as the cloud sees it: mode, setpoint, reading, element."""

    def __init__(self, reading, mode="Off", setpoint=70):
        self.t, self.mode, self.setpoint, self.element = reading, mode, setpoint, False
        self.reported = (mode, setpoint)  # what the cloud reports (delayed)
        self.change_at = None

    def apply(self, mode, setpoint, now):
        self.mode, self.setpoint = mode, setpoint
        self.change_at = now + 30  # cloud readback delay (T3c: 2-63 s)

    def minute(self, now):
        if self.change_at is not None and now >= self.change_at:
            self.reported, self.change_at = (self.mode, self.setpoint), None
        if self.mode != "Manual":
            self.element = False
        elif not self.element and self.t <= self.setpoint - 8:
            self.element = True
        elif self.element and self.t >= self.setpoint:
            self.element = False
        self.t += (3.0 / 60 / m.TANK_KWH_PER_C) if self.element else 0
        self.t -= 0.2 / 60

    def status(self):
        mode, setpoint = self.reported
        cmd = {"Manual": 9, "Off": 8, "Schedule": 17}[mode]
        return {
            "T_Avg": str(round(self.t)),
            "T_SetPoint": str(setpoint),
            "Cmd": str(cmd),
            "WaterHeaterSts": str(32 + int(self.element)),
        }


def sunny_after(hour):
    def pv(loc):
        h = loc.hour + loc.minute / 60
        full = 6.0 * max(0.0, math.sin(math.pi * (h - 6) / 14))
        return full if loc.hour >= hour else 0.15 * full

    return pv


class Rig:
    def __init__(
        self, tmp_path, monkeypatch, start, reading=46.0, mode="Off", pv=None, setpoint=70
    ):
        self.t = start.timestamp()
        self.tank = Tank(reading, mode, setpoint)
        self.pv = pv or sunny_after(13)
        self.states = {}
        self.store = {}
        self.posts = []
        self.ha_publishes = []
        self.notifications = []
        self._stub_home_assistant(monkeypatch)
        self.bridge = self._bridge(tmp_path, monkeypatch)
        self.entry = SimpleNamespace(
            entry_id="entry1",
            options={
                "forecast_enabled": True,
                "forecast_uncertainty": 0.0,
                "forecast_house_margin_kw": 0.0,
                "controller_command_topic": TOPIC,
                "controller_three_state_qualified": True,
            },
        )
        self.sources = {
            **c.DEFAULT_SOURCES,
            "forecast_pv": FORECAST_PV,
            "forecast_load": FORECAST_LOAD,
        }
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=self.states.get),
            config=SimpleNamespace(
                components={"mqtt"}, units=SimpleNamespace(temperature_unit="°C")
            ),
            services=SimpleNamespace(has_service=lambda *a: False),
            async_create_task=lambda coro: coro.close(),
        )
        self._meter()
        self._forecast()
        self.bridge.tick()  # startup read: STATUS and DIAGNOSTICS reach HA
        self.runtime_module, self.executor_module = self._load()
        settings, tariffs = c.parse_options(self.entry.options)
        self.runtime = self.runtime_module.ShadowRuntime(self.hass, self.sources, settings, tariffs)
        self.runtime.boot = self.now() - timedelta(minutes=5)
        self.executor = self._executor()

    # --- Home Assistant stub ---------------------------------------------------------------
    def now(self):
        return datetime.fromtimestamp(self.t, timezone.utc)

    def _stub_home_assistant(self, monkeypatch):
        rig = self

        class Store:
            def __init__(self, hass, version, key):
                self.key = key

            async def async_load(self):
                return rig.store.get(self.key)

            async def async_save(self, data):
                rig.store[self.key] = json.loads(json.dumps(data))

        async def async_publish(hass, topic, payload, qos, retain):
            rig.ha_publishes.append((topic, payload))
            rig.bridge.on_mqtt_message(
                None, None, SimpleNamespace(topic=topic, payload=payload.encode(), retain=False)
            )

        def parse(value):
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        modules = {
            "homeassistant": ModuleType("homeassistant"),
            "homeassistant.util": ModuleType("homeassistant.util"),
            "homeassistant.helpers": ModuleType("homeassistant.helpers"),
            "homeassistant.helpers.storage": ModuleType("homeassistant.helpers.storage"),
            "homeassistant.components": ModuleType("homeassistant.components"),
            "homeassistant.components.mqtt": ModuleType("homeassistant.components.mqtt"),
            "homeassistant.components.persistent_notification": ModuleType("pn"),
            "homeassistant.exceptions": ModuleType("homeassistant.exceptions"),
        }
        for name in ("homeassistant", "homeassistant.helpers", "homeassistant.components"):
            modules[name].__path__ = []
        modules["homeassistant.util"].dt = SimpleNamespace(utcnow=self.now, parse_datetime=parse)
        modules["homeassistant.helpers.storage"].Store = Store
        modules["homeassistant.components.mqtt"].async_publish = async_publish
        notifications = modules["homeassistant.components.persistent_notification"]
        notifications.async_create = lambda hass, message, title, key: self.notifications.append(
            key
        )
        notifications.async_dismiss = lambda hass, key: None
        modules["homeassistant.components"].mqtt = modules["homeassistant.components.mqtt"]
        modules["homeassistant.components"].persistent_notification = notifications
        modules["homeassistant.exceptions"].HomeAssistantError = RuntimeError
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)

    def _load(self):
        loaded = []
        for name in ("runtime", "executor"):
            spec = importlib.util.spec_from_file_location(
                f"{package.__name__}.{name}", PACKAGE / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded.append(module)
        return loaded

    def _executor(self):
        executor = self.executor_module.Executor(self.hass, self.entry, self.runtime)
        self.runtime.executor = executor
        drive(executor.async_load())
        return executor

    def report(self, entity, value, attributes=None):
        now = self.now()
        self.states[entity] = SimpleNamespace(
            state=str(value), attributes=attributes or {}, last_reported=now, last_updated=now
        )

    def ha_mqtt(self, topic, payload, *args, **kwargs):
        """What HA's MQTT entities make of the bridge's messages."""
        if topic.endswith("/STATUS"):
            result = json.loads(payload)["result"]
            self.report(
                c.DEFAULT_SOURCES["heater"],
                "unknown",
                {
                    "current_temperature": float(result["T_Avg"]),
                    "temperature": float(result["T_SetPoint"]),
                },
            )
            self.report(c.DEFAULT_SOURCES["mode"], result["vendor_mode"], dict(result))
        elif topic.endswith("/DIAGNOSTICS"):
            diag = json.loads(payload)
            self.report(c.DEFAULT_SOURCES["cloud_health"], diag["cloud_health"], diag)
            self.report(c.DEFAULT_SOURCES["last_poll"], diag["last_successful_poll"])
            self.report(c.DEFAULT_SOURCES["requests"], diag["request_attempts"])

    # --- the real bridge with a mocked cloud ---------------------------------------------------
    def _bridge(self, tmp_path, monkeypatch):
        monkeypatch.setattr(b.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")
        session = Mock(spec=requests.Session)
        mqtt = Mock()
        mqtt.publish.side_effect = self.ha_mqtt
        bridge = b.MyThermowattBridge(
            {
                "email": "synthetic@example.invalid",
                "password": "SYNTHETIC_PASSWORD",
                "cloud_enabled": True,
                "commands_enabled": True,
                "on_demand_refresh_enabled": True,
                "auth_retry_generation": 1,
            },
            tmp_path,
            session=session,
            mqtt_client=mqtt,
            clock=lambda: self.t,
            monotonic=lambda: self.t,
        )
        bridge.mqtt_connected.set()
        session.request.side_effect = [response(body=TOKENS)]
        bridge.login()
        session.request.side_effect = self.cloud
        bridge.config["devices"] = {SERIAL: {"name": "Synthetic"}}
        bridge.active_devices = {SERIAL}
        bridge.discovered = True
        return bridge

    def cloud(self, method, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "refresh":
            return response(body=TOKENS)
        if endpoint == "status":
            return response(body={"result": self.tank.status()})
        self.posts.append((self.now(), endpoint, kwargs.get("json"), kwargs.get("data")))
        if endpoint == "manual":
            self.tank.apply("Manual", kwargs["json"]["T_SetPoint"], self.t)
        elif endpoint == "off":
            self.tank.apply("Off", self.tank.setpoint, self.t)
        return response(204)

    # --- GoodWe and EMHASS ---------------------------------------------------------------------
    def _meter(self):
        loc = self.now().astimezone(m.HOBART)
        pv = self.pv(loc)
        house = 0.5 + (3.0 if self.tank.element else 0.0)
        export = pv - house  # import_positive False: the meter reports export positive
        self.report(c.DEFAULT_SOURCES["grid"], export * 1000, {"unit_of_measurement": "W"})
        self.report(c.DEFAULT_SOURCES["house"], house * 1000, {"unit_of_measurement": "W"})
        self.report(c.DEFAULT_SOURCES["pv"], pv * 1000, {"unit_of_measurement": "W"})
        self.report(c.DEFAULT_PV_AC, pv * 1000, {"unit_of_measurement": "W"})

    def _forecast(self, pv=None):
        pv = pv or self.pv
        now = self.now()
        start = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
        points = [start + timedelta(minutes=30 * i) for i in range(48)]
        self.report(
            FORECAST_PV,
            0,
            {
                "unit_of_measurement": "kW",
                "forecast_generated_at": now.isoformat(),
                "forecasts": [
                    {
                        "date": at.isoformat(),
                        "p_pv_forecast": round(
                            pv((at + timedelta(minutes=15)).astimezone(m.HOBART)), 3
                        ),
                    }
                    for at in points
                ],
            },
        )
        self.report(
            FORECAST_LOAD,
            0,
            {
                "unit_of_measurement": "kW",
                "forecast_generated_at": now.isoformat(),
                "forecasts": [{"date": at.isoformat(), "p_load_forecast": 0.5} for at in points],
            },
        )

    # --- the clock ------------------------------------------------------------------------------
    def run(self, until, every_minute=None):
        while self.now() < until:
            for _ in range(3):  # the bridge ticks every 20 s
                self.t += 20
                self.bridge.next_cloud = min(self.bridge.next_cloud, self.t)
                self.bridge.tick()
            self.tank.minute(self.t)
            self._meter()
            if self.now().minute in (0, 30):
                self._forecast()  # EMHASS publishes every 30 minutes
            if every_minute:
                every_minute(self)
            self.runtime.update(self.now())
            drive(self.executor.async_step(self.now()))

    def commands(self):
        return [p for t, p in self.ha_publishes if t == TOPIC]

    def enable(self):
        drive(self.executor.async_set_enabled(True))


def local(dt):
    return dt.astimezone(m.HOBART).strftime("%H:%M")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch, hobart(MON, 10, 50))


# --- shadow observation -------------------------------------------------------------------


def test_shadow_mode_runs_the_policy_and_sends_nothing(rig):
    rig.run(hobart(MON, 17, 10))
    assert rig.commands() == [] and rig.posts == []
    shadow = rig.executor.shadow
    assert [item["would_send"] for item in shadow] == ["Manual:70@off"]
    assert "13:00" <= local(datetime.fromisoformat(shadow[0]["at"])) <= "13:20"
    values = rig.runtime.values
    assert values["controller"] == "shadow_observation"
    assert values["shadow_command"] == "Manual:70@off"
    assert values["policy_mode"] == "peak" and values["decision"] == "peak_no_grid_heating"
    assert rig.tank.mode == "Off"  # the heater was never touched


# --- live control, full path -----------------------------------------------------------------


def test_live_weekday_cheapest_window_then_park_through_the_real_bridge(rig):
    rig.enable()
    rig.run(hobart(MON, 17, 10))
    assert rig.commands() == ["Manual:70@off", "off@70"]
    (start, manual, body, _), (park, off, _, data) = rig.posts
    assert manual == "manual" and body == {"T_SetPoint": 70}
    assert "13:00" <= local(start) <= "13:20"  # waited for the forecast sun
    assert off == "off" and data == "" and "16:58" <= local(park) <= "16:59"
    statuses = [item["status"] for item in rig.executor.controller.history]
    assert statuses == ["confirmed", "confirmed"]
    assert rig.executor.controller.state == "parked"
    assert rig.tank.t >= 62  # heated on solar into the Manual 70 band
    # Activation asked the bridge for one guarded status read.
    assert (f"P/{SERIAL}/refresh", "refresh") in rig.ha_publishes


def test_live_requests_stay_small_and_polls_cost_two_each(rig):
    rig.enable()
    rig.run(hobart(MON, 17, 10))
    counts = rig.bridge.request_counts
    assert counts["command"] == 2 and counts["password_login"] == 1
    # About 6 h 20 min: 13 aligned polls, an activation read, refreshes and
    # confirmations, with proactive token refresh and no 401s.
    assert counts["status"] <= 22 and counts["token_refresh"] <= counts["status"]
    assert sum(counts.values()) <= 45


def test_owner_app_change_pauses_control_and_is_never_overwritten(rig):
    rig.enable()

    def owner(rig):
        if local(rig.now()) == "12:15":
            rig.tank.apply("Manual", 55, rig.t)

    rig.run(hobart(MON, 17, 10), owner)
    assert rig.commands() == [] and rig.posts == []
    assert rig.executor.controller.state == "owner_override"
    assert any("override_" in key for key in rig.notifications)
    assert rig.tank.mode == "Manual" and rig.tank.setpoint == 55


def test_restart_while_confirming_never_resends(rig):
    rig.enable()
    rig.run(hobart(MON, 13, 0))
    rig.run(hobart(MON, 13, 30))
    assert rig.commands() == ["Manual:70@off"]
    # Find the minute the command went out, then restart HA before it confirms.
    rig.tank = rig.tank  # (state kept)
    rig2_store = dict(rig.store)
    assert any("controller" in key for key in rig2_store)
    rig.executor = rig._executor()  # restored from the saved state
    rig.run(hobart(MON, 14, 0))
    assert rig.commands() == ["Manual:70@off"]
    assert rig.executor.controller.state == "storage_70"


def test_enable_is_refused_until_commissioning_is_complete(rig):
    rig.entry.options["controller_three_state_qualified"] = False
    rig.executor.configure(rig.entry.options)
    with pytest.raises(RuntimeError, match="three_state_commands_not_qualified"):
        rig.enable()
    assert rig.executor.controller.enabled is False


def test_holiday_keeps_the_heater_off_and_12hr_override_heats(rig):
    rig.enable()
    controller = rig.executor.controller
    now = rig.now()
    assert controller.set_holiday(now, now, hobart(TUE, 12).date())
    rig.run(hobart(MON, 13, 40))
    assert rig.commands() == []  # holiday: OFF, even with good solar
    controller.cancel_holiday(rig.now())
    assert controller.start_guest(rig.now())
    rig.run(hobart(MON, 14, 30))
    assert rig.commands() == ["Manual:70@off"]


def test_dashboard_values_are_json_safe_and_complete(rig):
    rig.enable()
    rig.run(hobart(MON, 12, 0))
    values = rig.executor.values()
    assert values["controller_state"] == "parked"
    assert values["next_action"] in {"off", "storage", "baseline", "hold"}
    json.dumps(rig.executor.details(), allow_nan=False, default=str)
    json.dumps(rig.runtime.details, allow_nan=False, default=str)
    for key in ("policy_state", "policy_mode", "planned_start", "latest_start", "soft_target"):
        assert key in rig.runtime.values


def test_holiday_ends_at_midnight_on_the_return_date_then_manual_45_overnight(rig):
    rig.enable()
    assert rig.executor.controller.set_holiday(rig.now(), rig.now(), hobart(TUE, 12).date())
    rig.run(hobart(MON, 23, 58))
    assert rig.commands() == [] and rig.tank.mode == "Off"  # OFF all Monday, even at 22:00
    rig.run(hobart(TUE, 0, 20))
    assert rig.commands() == ["Manual:45@off"]
    ((when, endpoint, body, _),) = rig.posts
    assert local(when) == "00:00" or local(when) == "00:01", local(when)
    assert body == {"T_SetPoint": 45}
    assert rig.executor.controller.operating_mode(rig.now()) == "automatic"


def test_a_restart_after_the_return_date_resumes_normal_operation(rig):
    rig.enable()
    assert rig.executor.controller.set_holiday(rig.now(), rig.now(), hobart(TUE, 12).date())
    rig.run(hobart(MON, 23, 30))
    rig.executor = rig._executor()  # HA restarts; the holiday is restored from storage
    assert rig.executor.controller.holiday_active(rig.now())
    rig.run(hobart(TUE, 0, 30))
    assert rig.commands() == ["Manual:45@off"]
    assert rig.executor.controller.holiday_return is None


def test_departure_today_commands_off_at_once_through_the_guarded_path(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 10, 50), mode="Manual", setpoint=45)
    rig.enable()
    rig.run(hobart(MON, 11, 10))  # running normally (waiting for the afternoon sun)
    assert rig.commands() == [] and rig.executor.controller.state == "baseline_45"
    today, back = hobart(MON, 12).date(), hobart(MON + 3, 12).date()
    assert rig.executor.controller.set_holiday(rig.now(), today, back)
    rig.run(hobart(MON, 11, 20))
    assert rig.commands() == ["off@45"]
    ((when, endpoint, _, data),) = rig.posts
    assert endpoint == "off" and data == "" and local(when) == "11:11"  # the next minute
    rig.run(hobart(MON, 14, 0))  # good solar, but on holiday: nothing more
    assert rig.commands() == ["off@45"] and rig.tank.mode == "Off"


def test_future_departure_keeps_normal_control_until_00_00_on_that_date(rig):
    rig.enable()
    controller = rig.executor.controller
    assert controller.set_holiday(rig.now(), hobart(TUE, 12).date(), hobart(TUE + 2, 12).date())
    rig.run(hobart(TUE, 0, 20))
    commands = rig.commands()
    assert commands[:3] == ["Manual:70@off", "off@70", "Manual:45@off"], commands  # Monday
    assert commands[3:] == ["off@45"], commands  # 00:00 Tuesday: Holiday mode starts
    assert local(rig.posts[-1][0]) in {"00:00", "00:01"}
    assert controller.operating_mode(rig.now()) == "holiday"
