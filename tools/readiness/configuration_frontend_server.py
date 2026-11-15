"""Disposable real HA frontend, loopback only inside --network none CI.

No bridge, MQTT, vendor credentials or live network. Synthetic local browser auth
is written to a private bind mount, never logged or uploaded as an artifact.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import socket
import sys

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant, ServiceRegistry

ROOT = Path("/workspace")
CONFIG = Path("/tmp/thermann-ui")
PRIVATE = Path("/private")
_connect = socket.socket.connect


def loopback_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
        raise AssertionError("UI test denied a non-loopback connection")
    return _connect(sock, address)


async def deny_service(*args, **kwargs):
    raise AssertionError("UI tests must not issue service commands")


async def main():
    socket.socket.connect = loopback_connect
    ServiceRegistry.async_call = deny_service
    CONFIG.mkdir()
    shutil.copytree(ROOT / "custom_components", CONFIG / "custom_components")
    sys.path.insert(0, str(CONFIG))
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
    hass = HomeAssistant(str(CONFIG))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    assert await bootstrap.async_from_config_dict(
        {
            "homeassistant": {
                "name": "Isolated settings preview",
                "time_zone": "Australia/Hobart",
                "latitude": -42.88,
                "longitude": 147.33,
                "elevation": 0,
                "unit_system": "metric",
                "country": "AU",
            },
            "http": {"server_host": ["127.0.0.1"], "server_port": 8123},
            "frontend": {},
        },
        hass,
    )
    from custom_components.thermann_shadow.config import CLOUD_SOURCES, DEFAULT_OPTIONS
    from configuration_ha_checks import check_configuration

    sources = {
        k: f"{'water_heater' if k == 'heater' else 'sensor'}.synthetic_{k}" for k in CLOUD_SOURCES
    }
    flow = await hass.config_entries.flow.async_init("thermann_shadow", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], sources)
    assert result["type"] == "create_entry", result
    entry = result["result"]
    options = {
        **DEFAULT_OPTIONS,
        "sources": sources,
        "extension_preserved": {"future": 1},
        "restore_backup": {"forecast_uncertainty": 0.3},
    }
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    checks = await check_configuration(hass, entry)
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
    (PRIVATE / "browser.json").write_text(json.dumps({"auth": auth, "entry_id": entry.entry_id}))
    print(json.dumps({"ready": True, "flow_checks": checks}), flush=True)
    await asyncio.Event().wait()


logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
