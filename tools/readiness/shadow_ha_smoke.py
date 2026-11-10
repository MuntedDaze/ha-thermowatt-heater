"""Run inside the official HA Core image with --network none, never on owner HA."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM

ROOT = Path("/workspace")


def denied(*args, **kwargs):
    raise AssertionError("Shadow integration attempted external I/O or a service call")


async def main():
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "custom_components/thermann_shadow"
        shutil.copytree(ROOT / "custom_components/thermann_shadow", target)
        sys.path.insert(0, folder)
        hass = HomeAssistant(folder)
        await hass.config.async_set_time_zone("Australia/Hobart")
        hass.config.units = METRIC_SYSTEM
        # No connection, DNS, or Home Assistant service calls are allowed.
        socket.socket.connect = denied
        socket.socket.connect_ex = denied
        socket.create_connection = denied
        socket.getaddrinfo = denied
        type(hass.services).async_call = denied
        assert await async_setup_component(hass, "sensor", {})
        result = await hass.config_entries.flow.async_init(
            "thermann_shadow", context={"source": "user"}
        )
        assert result["type"] == "form"
        from custom_components.thermann_shadow.config import DEFAULT_SOURCES, DOMAIN
        from custom_components.thermann_shadow.model import Reading, evaluate

        result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
        assert result["type"] == "create_entry", result
        entry = result["result"]
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert runtime.plan.state == "shadow_blocked"
        now = dt_util.utcnow()
        values = {
            "heater": ("unknown", {"current_temperature": 63, "temperature": 70}),
            "mode": ("Schedule", {}),
            "last_poll": (now.isoformat(), {}),
            "cloud_health": ("ok", {}),
            "requests": (4, {"accounting_complete": True, "accounting_persistent": True}),
            "grid": (1501, {"unit_of_measurement": "W"}),
            "pv": (2322, {"unit_of_measurement": "W"}),
            "house": (821, {"unit_of_measurement": "W"}),
            "import_energy": (1234, {"unit_of_measurement": "kWh"}),
            "export_energy": (5678, {"unit_of_measurement": "kWh"}),
        }
        for key, (state, attrs) in values.items():
            hass.states.async_set(DEFAULT_SOURCES[key], state, attrs)
        now = dt_util.utcnow()
        runtime.update(now)
        assert runtime.plan.state == "shadow_awaiting_validation"
        assert runtime.values["temperature"] == 63
        assert runtime.values["target"] == 70
        assert runtime.values["measured_net_export_kw"] == 1.501
        assert runtime.values["pv"] == 2.322
        assert runtime.values["requests_since_start"] == 0
        assert runtime.plan.estimated_cost_aud is None
        assert runtime.details["additional_cloud_requests"] == 0
        assert runtime.details["control_capable"] is False
        assert runtime.details["observed_refresh_pattern_attempts_per_day"] == 144
        # Real config/options flows reject bad tariffs; owner can edit mappings.
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
        assert flow["step_id"] == "settings"
        bad = {"tariff_periods": "[]"}
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], bad)
        assert flow["errors"]["base"] == "invalid_settings"
        # Explicit synthetic-only qualified settings exercise planning on real HA states.
        runtime.settings = replace(runtime.settings, meter_verified=True, tariff_verified=True)
        runtime.update(now)
        assert runtime.plan.state != "shadow_blocked"
        hass.states.async_set(
            DEFAULT_SOURCES["requests"],
            7,
            {"accounting_complete": True, "accounting_persistent": True},
        )
        runtime.update(dt_util.utcnow())
        assert runtime.values["requests_since_start"] == 3
        hass.states.async_set(DEFAULT_SOURCES["requests"], 1)
        runtime.update(dt_util.utcnow())
        assert "request_counter_reset_history_incomplete" in runtime.plan.warnings
        hass.states.async_set(DEFAULT_SOURCES["mode"], "Manual")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_native_intervention"
        hass.states.async_set(DEFAULT_SOURCES["mode"], "Schedule")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_native_intervention"  # latched for review
        runtime.intervention = False
        hass.states.async_set(DEFAULT_SOURCES["cloud_health"], "quota_limited")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_blocked"
        # A fresh HA report of old retained cloud data is not a new poll after restart.
        fresh = {
            key: Reading(value, now, "°C" if key in {"target", "temperature"} else "W")
            for key, value in {
                "temperature": 63,
                "target": 70,
                "mode": "Schedule",
                "cloud_health": "ok",
                "last_poll": (now - timedelta(hours=1)).isoformat(),
                "grid": 1501,
            }.items()
        }
        assert (
            evaluate(now, runtime.boot, fresh, runtime.settings, runtime.tariffs).state
            == "shadow_blocked"
        )
        controller = hass.states.get("sensor.thermann_shadow_controller")
        assert controller is not None
        assert controller.attributes["control_capable"] is False
        sensor_ids = [
            state.entity_id
            for state in hass.states.async_all("sensor")
            if state.entity_id.startswith("sensor.thermann_shadow_")
        ]
        assert len(sensor_ids) == 24, sensor_ids
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not runtime.listeners
        await hass.async_stop()
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "real_ha_config_flow": "PASS",
                    "sensor_count": len(sensor_ids),
                    "unknown_water_heater_attributes": "PASS",
                    "request_replay_accounting": "PASS",
                    "manual_intervention_latch": "PASS",
                    "clean_unload": "PASS",
                    "live_cloud_requests": 0,
                    "service_calls": 0,
                    "heater_commands": 0,
                }
            )
        )


asyncio.run(main())
