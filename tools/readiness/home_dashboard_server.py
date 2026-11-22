"""Disposable real Home Assistant frontend serving the generated Home dashboard (CI only).

Loopback only inside --network none. No integration is loaded: every entity is a synthetic state
that the browser test changes through a test-only view, and service calls are RECORDED (never run)
so the test can prove which command a tap would send.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import shutil
import socket
import sys

from homeassistant import bootstrap, loader
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, ServiceRegistry

ROOT = Path("/workspace")
CONFIG = Path("/tmp/home-ui")
PRIVATE = Path("/private")
CALLS: list[dict] = []
_connect = socket.socket.connect


def loopback_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
        raise AssertionError("UI test denied a non-loopback connection")
    return _connect(sock, address)


async def record_service(self, domain, service, service_data=None, *args, **kwargs):
    CALLS.append(
        {"service": f"{domain}.{service}", "data": service_data, "target": kwargs.get("target")}
    )
    print(
        json.dumps({"recorded_call": f"{domain}.{service}", "data": str(service_data)}), flush=True
    )
    return None


def seed(hass):
    """Realistic synthetic states for every entity the dashboard uses (nothing here is a device)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import build_home_dashboard as build

    now = datetime.now(timezone.utc)
    later = (now + timedelta(minutes=25)).isoformat()
    earlier = (now - timedelta(minutes=5)).isoformat()
    power = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
    values = {
        "sensor.goodwe_inverter_pv_power": ("4123", power),
        "sensor.goodwe_inverter_house_consumption": ("1200", power),
        "sensor.goodwe_inverter_meter_active_power": ("2923", power),
        "sensor.goodwe_inverter_today_s_pv_generation": (
            "12.4",
            {"unit_of_measurement": "kWh", "device_class": "energy"},
        ),
        "sensor.thermann_shadow_bottom_temperature": ("52.44", {"unit_of_measurement": "°C"}),
        "sensor.thermann_shadow_status_age": ("7", {"unit_of_measurement": "min"}),
        "sensor.thermann_shadow_thermann_mode": ("Manual", {}),
        "sensor.thermann_shadow_thermann_target": ("62", {"unit_of_measurement": "°C"}),
        "sensor.thermann_shadow_desired_thermostat_temperature": (
            "62",
            {"unit_of_measurement": "°C"},
        ),
        "sensor.thermann_shadow_hot_water_operating_mode": ("automatic", {}),
        "sensor.thermann_shadow_current_tariff": ("off_peak", {}),
        "sensor.thermann_shadow_solar_boost_status": ("idle", {}),
        "sensor.thermann_shadow_next_intended_action": ("wait_for_off_peak", {}),
        "sensor.thermann_shadow_next_cloud_poll": (later, {}),
        "sensor.home_last_successful_poll": (earlier, {}),
        "sensor.thermann_shadow_guest_mode_ends": ("unknown", {}),
        "sensor.thermann_shadow_automatic_control_state": ("observing", {}),
        "sensor.thermann_shadow_cloud_health": ("ok", {}),
        "sensor.thermann_shadow_controller_fault": ("none", {}),
        "sensor.tapo_smart_controller_electricity_tariff_status": ("off_peak", {}),
        "sensor.tapo_smart_controller_active_health_warnings": ("0", {}),
        "binary_sensor.tapo_smart_controller_controller_health_problem": ("off", {}),
        "binary_sensor.tapo_smart_controller_simulation_mode_active": ("off", {}),
        "sensor.home_energy_status": ("collecting_first_day", {}),
        "sensor.tapo_smart_controller_garage_door_position": ("Closed", {}),
        "sensor.tapo_smart_controller_garage_door_status": (
            "closed",
            {"summary": "Closed — closed-position contact is made"},
        ),
        "sensor.tapo_smart_controller_front_door_lock_status": (
            "lock_integration_unavailable",
            {"summary": "Closed — lock status not available through Home Assistant"},
        ),
        "binary_sensor.tapo_smart_controller_front_door_open": ("off", {"device_class": "door"}),
        "weather.home": ("sunny", {"temperature": 18.5, "temperature_unit": "°C", "humidity": 60}),
        "light.dining_room_light": (
            "on",
            {
                "brightness": 140,
                "supported_color_modes": ["brightness"],
                "color_mode": "brightness",
            },
        ),
        "light.living_room_light": (
            "off",
            {"supported_color_modes": ["brightness"], "color_mode": None},
        ),
    }
    for custom in (True, False):
        _, ent = build.build_dashboard(custom=custom)
        for entity_id in ent.used:
            if entity_id in values:
                continue
            if entity_id.startswith(("switch.", "binary_sensor.")):
                values[entity_id] = ("off", {"summary": "Off — normal"})
            else:
                values[entity_id] = ("55", {})
    for entity_id, (state, attrs) in values.items():
        hass.states.async_set(entity_id, state, attrs)
    return sorted(values)


async def main():
    socket.socket.connect = loopback_connect
    ServiceRegistry.async_call = record_service
    CONFIG.mkdir()
    (CONFIG / "www" / "thermowatt").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "homeowner/www/thermowatt-power-flow-card.js",
        CONFIG / "www/thermowatt/thermowatt-power-flow-card.js",
    )
    # The demo integration provides a weather entity that supports daily forecasts. Only this test
    # copy of the dashboard points at it; the committed dashboard uses weather.home (Open-Meteo).
    dashboard = (ROOT / "homeowner/home.yaml").read_text(encoding="utf-8")
    (CONFIG / "home.yaml").write_text(
        dashboard.replace("weather.home", "weather.demo_weather_south"), encoding="utf-8"
    )
    storage = CONFIG / ".storage"
    storage.mkdir()
    (storage / "onboarding").write_text(
        json.dumps(
            {
                "version": 4,
                "key": "onboarding",
                "data": {"done": ["user", "core_config", "integration", "analytics"]},
            }
        )
    )
    (storage / "lovelace_resources").write_text(
        json.dumps(
            {
                "version": 1,
                "minor_version": 1,
                "key": "lovelace_resources",
                "data": {
                    "items": [
                        {
                            "id": "thermowatt_power_flow",
                            "url": "/local/thermowatt/thermowatt-power-flow-card.js",
                            "type": "module",
                        }
                    ]
                },
            }
        )
    )
    hass = HomeAssistant(str(CONFIG))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    assert await bootstrap.async_from_config_dict(
        {
            "homeassistant": {
                "name": "Isolated Home dashboard preview",
                "time_zone": "Australia/Hobart",
                "latitude": -42.88,
                "longitude": 147.33,
                "elevation": 0,
                "unit_system": "metric",
                "country": "AU",
            },
            "http": {"server_host": ["127.0.0.1"], "server_port": 8123},
            "frontend": {},
            "recorder": {"db_url": "sqlite:///:memory:"},
            "history": {},
            "demo": {},
            "lovelace": {
                "dashboards": {
                    "home-test": {
                        "mode": "yaml",
                        "title": "Home",
                        "show_in_sidebar": True,
                        "filename": "home.yaml",
                    }
                }
            },
        },
        hass,
    )
    seeded = seed(hass)

    class StateView(HomeAssistantView):
        url = "/api/home_ui_state"
        name = "api:home_ui_state"

        async def post(self, request):
            body = await request.json()
            hass.states.async_set(body["entity_id"], body["state"], body.get("attributes", {}))
            return self.json({"ok": True})

    class CallsView(HomeAssistantView):
        url = "/api/home_ui_calls"
        name = "api:home_ui_calls"

        async def get(self, request):
            return self.json(list(CALLS))

        async def delete(self, request):
            CALLS.clear()
            return self.json({"ok": True})

    hass.http.register_view(StateView)
    hass.http.register_view(CallsView)
    user = await hass.auth.async_create_user("Synthetic UI reviewer", group_ids=["system-admin"])
    refresh = await hass.auth.async_create_refresh_token(user, client_id="http://127.0.0.1:8123/")
    access = hass.auth.async_create_access_token(refresh)
    auth = {
        "hassUrl": "http://127.0.0.1:8123",
        "clientId": "http://127.0.0.1:8123/",
        "access_token": access,
        "refresh_token": refresh.token,
        "token_type": "Bearer",
        "expires_in": 1800,
        "expires": int(datetime.now(timezone.utc).timestamp() * 1000) + 1800000,
    }
    await hass.async_start()
    (PRIVATE / "browser.json").write_text(json.dumps({"auth": auth}))
    print(json.dumps({"ready": True, "seeded": len(seeded)}), flush=True)
    await asyncio.Event().wait()


logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
