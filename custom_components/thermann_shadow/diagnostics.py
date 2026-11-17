"""Home Assistant's authenticated, read-only diagnostics download."""

from homeassistant.const import __version__
from homeassistant.util import dt as dt_util

from .config import DOMAIN
from .report import build


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    return build(runtime, dt_util.utcnow(), __version__) if runtime else {"state": "not_loaded"}
