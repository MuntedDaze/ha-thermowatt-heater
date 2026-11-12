"""User-facing names (0.8.0) without changing any identity.

The integration is shown as **Thermann Controller**; its domain stays
``thermann_shadow`` and every entity ID keeps the ``thermann_shadow_`` prefix,
for existing installs (the entity registry keeps IDs) and fresh installs alike
(each entity requests its historical ID instead of deriving one from the new
device name). Renamed entities request the ID of their former name, so
automations, dashboards and history keep working.

Pure module: no Home Assistant imports (the device info is built by callers).
"""

import re

ENTITY_PREFIX = "thermann_shadow"
DEVICE_NAME = "Thermann Controller"
MANUFACTURER = "Unofficial community project (not a Thermann product)"
MODEL = "Hot water controller"
ENTRY_TITLE = "Thermann Controller"
OLD_ENTRY_TITLES = frozenset({"Thermann Shadow"})

# Display name now -> the name the entity ID was first derived from.
LEGACY_NAMES = {
    "Start 12hr Override": "Start guest mode (12 h)",
    "Cancel 12hr Override": "Cancel guest mode",
    "12hr Override ends": "Guest mode ends",
    "Weekend afternoon ready time": "Afternoon comfort preference",
}


def slug(value: str) -> str:
    """HA's slugify for the ASCII names used here."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def object_id(name: str) -> str:
    return f"{ENTITY_PREFIX}_{slug(LEGACY_NAMES.get(name, name))}"


def entity_id(domain: str, name: str) -> str:
    return f"{domain}.{object_id(name)}"


def device_info_fields(domain: str, entry_id: str) -> dict:
    return {
        "identifiers": {(domain, entry_id)},
        "name": DEVICE_NAME,
        "manufacturer": MANUFACTURER,
        "model": MODEL,
    }
