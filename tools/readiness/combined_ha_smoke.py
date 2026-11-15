"""Actual combined component + monitoring contracts, only in --network none HA."""

import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace

from homeassistant.helpers.template import Template
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from shadow_ha_checks import start_hass, flush_and_close, report_inputs

sys.path.insert(0, "/workspace")
from energy_monitoring.mapping import load  # noqa: E402
from energy_monitoring.package import build_package  # noqa: E402
from energy_monitoring.dashboard import build_dashboard, referenced_entities, walk_cards  # noqa: E402


def denied(*args, **kwargs):
    raise AssertionError("Combined test attempted external I/O")


def templates(node):
    if isinstance(node, str) and ("{{" in node or "{%" in node):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from templates(value)
    elif isinstance(node, list):
        for value in node:
            yield from templates(value)


async def main():
    socket.socket.connect = socket.socket.connect_ex = denied
    socket.create_connection = socket.getaddrinfo = denied
    with tempfile.TemporaryDirectory() as folder:
        hass = await start_hass(folder, Path("/workspace/custom_components/thermann_shadow"))
        from custom_components.thermann_shadow.config import DEFAULT_SOURCES, DOMAIN

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
        entry = result["result"]
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN][entry.entry_id]
        report_inputs(hass, DEFAULT_SOURCES)
        runtime.update(dt_util.utcnow())
        await runtime.executor.async_step()
        config = load()
        registry = er.async_get(hass)
        known = {
            item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        for key, entity in config["hot_water"].items():
            if entity.startswith("sensor.thermann_shadow_"):
                assert entity in known, (key, entity)
        counts = []
        for meters in (0, 3):
            for circuit in config["circuits"][:meters]:
                circuit["power"] = f"sensor.synthetic_{circuit['key']}"
                hass.states.async_set(circuit["power"], 0, {"unit_of_measurement": "W"})
            built = build_package(config)
            board = build_dashboard(config)
            # No state is invented for missing optional sources: render their
            # unavailable branches against actual HA Template semantics.
            variables = {
                "this": SimpleNamespace(state="0", attributes={}),
                "trigger": SimpleNamespace(id="end", to_state=SimpleNamespace(state="unknown")),
            }
            for text in [*templates(built), *templates(board)]:
                Template(text, hass).async_render(variables, strict=True)
            assert len(board["views"]) == 7
            assert not {"button", "water-heater", "thermostat"} & {
                card["type"] for card in walk_cards(board)
            }
            assert not any(
                e.startswith(("water_heater.", "switch.", "button."))
                for e in referenced_entities(board)
            )
            counts.append({"meters": meters, "templates": len(list(templates(built)))})
        assert runtime.executor.controller.enabled is False
        await flush_and_close(hass)
        print(
            json.dumps(
                {"combined_contract": counts, "real_heater_commands": 0, "external_requests": 0}
            )
        )


asyncio.run(main())
