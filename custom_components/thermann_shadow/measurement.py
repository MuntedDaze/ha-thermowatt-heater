"""Circuit measurement and power balance. No inference, services or commands.

Verification is an explicit commissioning record ``entity_id|unit``. Changing
either invalidates it. An HA report time is a receipt time, not proof of the
meter's acquisition time; steady readings must actually be reported regularly.
"""

from dataclasses import dataclass
from datetime import datetime

from .model import Reading, _fresh, number


@dataclass(frozen=True)
class CircuitPower:
    watts: float | None = None
    observed_at: datetime | None = None
    state: str = "unknown"
    quality: str = "missing"

    @property
    def valid(self) -> bool:
        return self.quality == "verified"


def circuit_power(reading: Reading | None, entity, verification, now, boot, max_age=120):
    if reading is None:
        return CircuitPower()
    try:
        _fresh(reading, now, boot, max_age)
        watts = number(reading.value)
        if reading.unit == "kW":
            watts *= 1000
        elif reading.unit != "W":
            return CircuitPower(quality="unit_invalid")
        if not 0 <= watts <= 3800:
            return CircuitPower(quality="power_implausible")
        if 100 < watts < 2000:
            return CircuitPower(watts, reading.observed_at, quality="power_ambiguous")
        if verification != f"{entity}|{reading.unit}":
            return CircuitPower(watts, reading.observed_at, quality="unverified")
        return CircuitPower(
            watts, reading.observed_at, "on" if watts >= 2000 else "off", "verified"
        )
    except (ValueError, TypeError, OverflowError):
        return CircuitPower(quality="stale_or_invalid")


def energy_reading(reading, now, boot, max_age=120):
    """Optional cumulative circuit import, kWh; never a control authority."""
    if reading is None:
        return None
    try:
        _fresh(reading, now, boot, max_age)
        value = number(reading.value)
        if reading.unit == "Wh":
            value /= 1000
        elif reading.unit != "kWh":
            return None
        return value if 0 <= value <= 1e9 else None
    except (ValueError, TypeError, OverflowError):
        return None


def power_balance(grid_import_kw, heater_kw):
    """Signed grid without heater, plus marginal heater grid/PV kW.

    Conservation: G_without = G - H; A = H - G. Never add nominal power.
    This attributes current circuit use, not savings against a 45-degree cycle.
    """
    available = heater_kw - grid_import_kw
    solar = min(heater_kw, max(0.0, available))
    return {
        "grid_without_heater_kw": grid_import_kw - heater_kw,
        "available_before_heater_kw": available,
        "heater_solar_kw": solar,
        "heater_grid_kw": heater_kw - solar,
    }
