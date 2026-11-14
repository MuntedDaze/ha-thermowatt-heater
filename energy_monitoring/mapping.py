"""Load and validate ``entity_map.yaml``. Pure Python: no Home Assistant imports."""

from pathlib import Path
import re

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_MAP = HERE / "entity_map.yaml"
ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
KEY = re.compile(r"^[a-z][a-z0-9_]*$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_CIRCUITS = 3
# Keys that would collide with the package's own sensor names.
RESERVED_KEYS = frozenset(
    {"grid", "grid_import", "grid_export", "solar", "house", "tracked", "untracked", "tariff"}
)
RATE_KEYS = ("peak_rate", "off_peak_rate", "feed_in_rate", "daily_supply_charge")


def minutes(clock: str) -> int:
    """``HH:MM`` as minutes after midnight; an end of ``00:00`` means 24:00."""
    return int(clock[:2]) * 60 + int(clock[3:])


def _entity(value, where: str, required: bool = False) -> str:
    value = "" if value is None else str(value).strip()
    if not value:
        if required:
            raise ValueError(f"{where}: an entity ID is required")
        return ""
    if not ENTITY_ID.match(value):
        raise ValueError(f"{where}: {value!r} is not an entity ID")
    return value


def validate(raw: dict) -> dict:
    """Return a normalised copy; raise ``ValueError`` naming the first problem."""
    if raw.get("version") != 1:
        raise ValueError("version: only version 1 is supported")
    grid, solar, house = raw.get("grid") or {}, raw.get("solar") or {}, raw.get("house") or {}
    result = {
        "version": 1,
        "currency": str(raw.get("currency") or "AUD"),
        "grid": {
            "power": _entity(grid.get("power"), "grid.power", True),
            "export_positive": bool(grid.get("export_positive", True)),
            "import_energy": _entity(grid.get("import_energy"), "grid.import_energy", True),
            "export_energy": _entity(grid.get("export_energy"), "grid.export_energy", True),
        },
        "solar": {
            "power": _entity(solar.get("power"), "solar.power", True),
            "energy": _entity(solar.get("energy"), "solar.energy", True),
            "forecast_power": _entity(solar.get("forecast_power"), "solar.forecast_power"),
            "zero_when_unavailable": bool(solar.get("zero_when_unavailable", False)),
        },
        "house": {"power": _entity(house.get("power"), "house.power", True)},
    }

    tariff = raw.get("tariff") or {}
    clock = tariff.get("clock", "standard")
    if clock not in ("standard", "local"):
        raise ValueError("tariff.clock: must be 'standard' or 'local'")
    offset = tariff.get("utc_offset_hours", 10)
    if not isinstance(offset, (int, float)) or isinstance(offset, bool) or not -12 <= offset <= 14:
        raise ValueError("tariff.utc_offset_hours: must be between -12 and 14")
    windows = []
    for index, window in enumerate(tariff.get("peak_windows") or []):
        where = f"tariff.peak_windows[{index}]"
        days = window.get("days")
        if not days or any(day not in range(7) for day in days):
            raise ValueError(f"{where}.days: use 0 (Monday) to 6 (Sunday)")
        start, end = str(window.get("start", "")), str(window.get("end", ""))
        if not CLOCK.match(start) or not CLOCK.match(end):
            raise ValueError(f"{where}: start and end must be HH:MM")
        first, last = minutes(start), minutes(end) or 1440
        if first >= last:
            raise ValueError(f"{where}: must end after it starts, on the same day")
        windows.append({"days": sorted(set(days)), "start": first, "end": last})
    result["tariff"] = {"clock": clock, "utc_offset_hours": offset, "peak_windows": windows}
    for key in RATE_KEYS:
        result["tariff"][f"{key}_entity"] = _entity(
            tariff.get(f"{key}_entity"), f"tariff.{key}_entity"
        )

    circuits, keys = [], set()
    for index, circuit in enumerate(raw.get("circuits") or []):
        where = f"circuits[{index}]"
        key = str(circuit.get("key", ""))
        if not KEY.match(key) or key in RESERVED_KEYS or key in keys:
            raise ValueError(f"{where}.key: {key!r} is missing, reserved or duplicated")
        keys.add(key)
        role = circuit.get("role", "circuit")
        if role not in ("circuit", "hot_water"):
            raise ValueError(f"{where}.role: must be 'circuit' or 'hot_water'")
        power = _entity(circuit.get("power"), f"{where}.power")
        energy = _entity(circuit.get("energy"), f"{where}.energy")
        if energy and not power:
            raise ValueError(f"{where}: an energy entity needs a power entity as well")
        threshold = circuit.get("element_on_watts", 1000)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold <= 0:
            raise ValueError(f"{where}.element_on_watts: must be a positive number")
        circuits.append(
            {
                "key": key,
                "name": str(circuit.get("name") or key.replace("_", " ").capitalize()),
                "role": role,
                "power": power,
                "energy": energy,
                "element_on_watts": threshold,
            }
        )
    if len(circuits) > MAX_CIRCUITS:
        raise ValueError(f"circuits: at most {MAX_CIRCUITS} are supported")
    if sum(circuit["role"] == "hot_water" for circuit in circuits) > 1:
        raise ValueError("circuits: only one circuit can have role hot_water")
    result["circuits"] = circuits

    appliances = []
    for index, appliance in enumerate(raw.get("appliances") or []):
        where = f"appliances[{index}]"
        key = str(appliance.get("key", ""))
        if not KEY.match(key) or key in RESERVED_KEYS or key in keys:
            raise ValueError(f"{where}.key: {key!r} is missing, reserved or duplicated")
        keys.add(key)
        parent = str(appliance.get("circuit") or "")
        if parent and parent not in {circuit["key"] for circuit in circuits}:
            raise ValueError(f"{where}.circuit: {parent!r} is not a circuit key")
        appliances.append(
            {
                "key": key,
                "name": str(appliance.get("name") or key.replace("_", " ").capitalize()),
                "power": _entity(appliance.get("power"), f"{where}.power"),
                "energy": _entity(appliance.get("energy"), f"{where}.energy"),
                "circuit": parent,
            }
        )
    result["appliances"] = appliances

    result["hot_water"] = {
        str(key): _entity(value, f"hot_water.{key}")
        for key, value in (raw.get("hot_water") or {}).items()
    }
    freshness = raw.get("freshness_seconds") or {}
    result["freshness_seconds"] = {
        group: int(freshness.get(group, default))
        for group, default in (("core", 300), ("circuits", 300), ("appliances", 1800))
    }
    if any(value < 0 for value in result["freshness_seconds"].values()):
        raise ValueError("freshness_seconds: values cannot be negative")
    return result


def load(path: Path = DEFAULT_MAP) -> dict:
    return validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def circuit_power(circuit: dict) -> str:
    """The package's normalised power sensor for a mapped circuit."""
    return f"sensor.em_{circuit['key']}_power"


def circuit_energy(circuit: dict) -> str:
    return f"sensor.em_{circuit['key']}_energy"


def active_circuits(config: dict) -> list[dict]:
    return [circuit for circuit in config["circuits"] if circuit["power"]]


def hot_water_circuit(config: dict) -> dict | None:
    return next(
        (circuit for circuit in active_circuits(config) if circuit["role"] == "hot_water"), None
    )


def is_overlapping(config: dict, appliance: dict) -> bool:
    """A plug downstream of a circuit whose CT is installed is already counted there."""
    return appliance["circuit"] in {circuit["key"] for circuit in active_circuits(config)}


def tracked_sources(config: dict) -> list[dict]:
    """Non-overlapping measured loads: every mapped CT circuit, plus each smart
    plug that is not downstream of one. Their sum never counts a load twice."""
    sources = [
        {
            "key": circuit["key"],
            "name": circuit["name"],
            "kind": "circuit",
            "power": circuit_power(circuit),
            "energy": circuit_energy(circuit),
        }
        for circuit in active_circuits(config)
    ]
    sources += [
        {**appliance, "kind": "appliance"}
        for appliance in config["appliances"]
        if appliance["power"] and not is_overlapping(config, appliance)
    ]
    return sources


def rate_entity(config: dict, key: str) -> str:
    return config["tariff"][f"{key}_entity"] or f"input_number.em_{key}"
