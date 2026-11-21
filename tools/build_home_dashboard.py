"""Unified Home dashboard generator (canonical source: homeowner/home_mapping.yaml + this file).

Writes, reproducibly:
  homeowner/home.yaml                    dashboard using the Thermowatt power-flow custom card
  homeowner/home_no_custom_card.yaml     the same dashboard with a native power-flow fallback
  homeowner/home_energy_package.yaml     optional HA package (kW sensors, daily energy, self-consumption)

It never modifies the existing Thermowatt or Tapo dashboards. ``--check`` fails if any output is stale,
``--report`` prints every entity the dashboard uses and the mappings still to be completed.
"""

import argparse
import importlib
import json
from pathlib import Path
import re
import sys
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_homeowner_home")
package.__path__ = [str(ROOT / "custom_components/thermann_shadow")]
sys.modules[package.__name__] = package
naming = importlib.import_module(f"{package.__name__}.naming")
integration_config = importlib.import_module(f"{package.__name__}.config")

MAPPING = ROOT / "homeowner/home_mapping.yaml"
TAPO_CONTRACT = ROOT / "homeowner/tapo_entity_contract.json"
OUTPUTS = {
    "home": ROOT / "homeowner/home.yaml",
    "native": ROOT / "homeowner/home_no_custom_card.yaml",
    "package": ROOT / "homeowner/home_energy_package.yaml",
}
CARD_RESOURCE = "/local/thermowatt/thermowatt-power-flow-card.js"
IDLE_KW = 0.005  # 5 W: below this a flow is idle, not import/export
TAPO_SETTINGS_PATH = "/config/integrations/integration/tapo_smart_controller"
THERMOWATT_SETTINGS_PATH = "/config/integrations/integration/thermann_shadow"


# ------------------------------------------------------------------ mapping + contracts
def load_mapping():
    return yaml.safe_load(MAPPING.read_text(encoding="utf-8"))


def load_tapo_contract():
    return json.loads(TAPO_CONTRACT.read_text(encoding="utf-8"))["entities"]


def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


class Entities:
    """Resolves every entity once and records where it came from (for --report and tests)."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.contract = load_tapo_contract()
        self.used = {}  # entity_id -> source
        self.thermowatt_names = {}  # entity_id -> display name it was derived from
        self.unresolved = []

    def thermowatt(self, domain, name):
        eid = naming.entity_id(domain, name)
        self.used[eid] = "thermann_shadow"
        self.thermowatt_names[eid] = name
        return eid

    def tapo(self, domain, bathroom_or_name, suffix=None):
        label = bathroom_or_name if suffix is None else f"{bathroom_or_name} {suffix}"
        eid = f"{domain}.tapo_smart_controller_{slug(label)}"
        if eid not in self.contract:
            raise KeyError(f"{eid} is not in the Tapo entity contract")
        self.used[eid] = "tapo_smart_controller"
        return eid

    def mapped(self, group, key=None):
        node = self.mapping[group] if key is None else self.mapping[group][key]
        entity = node["entity"] if isinstance(node, dict) else node
        if not entity:
            self.unresolved.append(f"{group}{'.' + key if key else ''}")
            return None
        self.used[entity] = "home_mapping"
        return entity

    def energy(self, key):
        eid = self.mapping["energy"][key]["entity"]
        self.used[eid] = "home_mapping"
        return eid


# ------------------------------------------------------------------ small card helpers
def heading(text, icon=None):
    card = {"type": "heading", "heading": text, "heading_style": "title"}
    if icon:
        card["icon"] = icon
    return card


def note(text):
    return {"type": "markdown", "content": text}


def tile(entity, name=None, icon=None, color=None, content=None, tap=None, hide_state=False):
    card = {"type": "tile", "entity": entity}
    if name:
        card["name"] = name
    if icon:
        card["icon"] = icon
    if color:
        card["color"] = color
    if content:
        card["state_content"] = content
    if hide_state:
        card["hide_state"] = True
    action = tap or {"action": "more-info"}
    card["tap_action"] = action
    card["icon_tap_action"] = action
    card["hold_action"] = {"action": "none"}
    card["vertical"] = False
    return card


def press(button_id, question):
    return {
        "action": "perform-action",
        "perform_action": "button.press",
        "target": {"entity_id": button_id},
        "confirmation": {"text": question},
    }


def call(service, entity, question=None):
    action = {
        "action": "perform-action",
        "perform_action": service,
        "target": {"entity_id": entity},
    }
    if question:
        action["confirmation"] = {"text": question}
    return action


def when(entity, state=None, not_states=()):
    conditions = []
    if state is not None:
        conditions.append({"condition": "state", "entity": entity, "state": state})
    for other in not_states:
        conditions.append({"condition": "state", "entity": entity, "state_not": other})
    return conditions


def conditional(conditions, card):
    return {"type": "conditional", "conditions": conditions, "card": card}


def section(*cards, span=None):
    out = {"type": "grid", "cards": list(cards)}
    if span:
        out["column_span"] = span
    return out


def mapping_needed(what, key):
    return note(
        f"**{what}: mapping needed.** Set `{key}` in `homeowner/home_mapping.yaml` to the real "
        "entity ID (Developer Tools -> States), then run `python tools/build_home_dashboard.py`. "
        "Nothing is guessed."
    )


def sensor_row(ent, name):
    return {"entity": ent, "name": name}


# ------------------------------------------------------------------ energy
def package_ids():
    """Entity IDs created by home_energy_package.yaml (object ids fixed by their names)."""
    return {
        "solar_kw": "sensor.home_solar_power_kw",
        "house_kw": "sensor.home_house_power_kw",
        "import_kw": "sensor.home_grid_import_kw",
        "export_kw": "sensor.home_grid_export_kw",
        "grid_state": "sensor.home_grid_state",
        "import_today": "sensor.home_grid_import_today",
        "export_today": "sensor.home_grid_export_today",
        "consumption_today": "sensor.home_consumption_today",
        "used_today": "sensor.home_solar_used_directly_today",
        "selfcons_today": "sensor.home_self_consumption_today",
    }


def power_flow_card(ent, custom):
    if custom:
        return {
            "type": "custom:thermowatt-power-flow-card",
            "solar_entity": ent.energy("solar_power"),
            "house_entity": ent.energy("house_power"),
            "grid_entity": ent.energy("grid_power"),
            "grid_export_positive": bool(ent.mapping["energy"]["grid_export_positive"]),
        }
    ids = package_ids()
    for key in ("solar_kw", "house_kw", "grid_state", "import_kw", "export_kw"):
        ent.used[ids[key]] = "home_energy_package"
    return {
        "type": "grid",
        "columns": 2,
        "square": False,
        "cards": [
            tile(ids["solar_kw"], "Solar", "mdi:solar-power", "green"),
            tile(ids["house_kw"], "House", "mdi:home-lightning-bolt", "blue"),
            tile(ids["grid_state"], "Grid", "mdi:transmission-tower", "orange"),
            tile(ids["import_kw"], "Importing", "mdi:transmission-tower-import", "orange"),
            tile(ids["export_kw"], "Exporting", "mdi:transmission-tower-export", "green"),
        ],
    }


def energy_tiles(ent):
    ids = package_ids()
    for value in ids.values():
        ent.used[value] = "home_energy_package"
    solar_today = ent.energy("solar_today_energy")
    return {
        "type": "grid",
        "columns": 2,
        "square": False,
        "cards": [
            tile(solar_today, "Solar today", "mdi:solar-power-variant", "green"),
            tile(ids["consumption_today"], "Household today", "mdi:home-lightning-bolt", "blue"),
            tile(
                ids["import_today"], "Grid import today", "mdi:transmission-tower-import", "orange"
            ),
            tile(
                ids["export_today"], "Grid export today", "mdi:transmission-tower-export", "green"
            ),
            tile(ids["used_today"], "Solar used directly", "mdi:home-battery", "green"),
            tile(ids["selfcons_today"], "Self-consumption", "mdi:percent-circle", "green"),
        ],
    }


def statistics_cards(ent):
    cards = []
    for key, name in (
        ("solar_today_energy", "Solar generated (statistics)"),
        ("grid_import_total", "Grid import (statistics)"),
        ("grid_export_total", "Grid export (statistics)"),
    ):
        cards.append(
            {
                "type": "statistic",
                "entity": ent.energy(key),
                "name": name,
                "stat_type": "change",
                "period": {"calendar": {"period": "day"}},
            }
        )
    return cards


# ------------------------------------------------------------------ hot water
def hot_water_card(ent):
    mode = ent.thermowatt("sensor", "Hot water operating mode")
    start = ent.thermowatt("button", "12hr Override 62°C")
    cancel = ent.thermowatt("button", "Cancel 12hr Override")
    last_poll = integration_config.DEFAULT_SOURCES["last_poll"]
    ent.used[last_poll] = "thermann_bridge"
    rows = [
        sensor_row(ent.thermowatt("sensor", "Bottom temperature"), "Tank bottom temperature"),
        sensor_row(ent.thermowatt("sensor", "Status age"), "Reading age (min)"),
        sensor_row(mode, "Mode"),
        sensor_row(ent.thermowatt("sensor", "Current heating plan"), "Plan"),
        sensor_row(ent.thermowatt("sensor", "Next intended action"), "Next action"),
        sensor_row(ent.thermowatt("sensor", "Current tariff"), "Tariff"),
        sensor_row(ent.thermowatt("sensor", "Solar boost status"), "Solar boost"),
        sensor_row(last_poll, "Last successful poll"),
        sensor_row(ent.thermowatt("sensor", "Next cloud poll"), "Next poll"),
        sensor_row(ent.thermowatt("sensor", "12hr Override ends"), "Override ends"),
    ]
    on_card = tile(
        mode,
        "12 h override: ON",
        "mdi:water-boiler",
        "blue",
        tap=press(cancel, "Cancel the 12 hour 62 °C override? Normal automatic control resumes."),
        hide_state=True,
    )
    off_card = tile(
        mode,
        "12 h override: OFF",
        "mdi:water-boiler-off",
        "grey",
        tap=press(
            start,
            "Start the 12 hour 62 °C override? It may heat during peak hours; controller safeguards still apply.",
        ),
        hide_state=True,
    )
    unknown = tile(
        mode, "12 h override: status unknown", "mdi:water-boiler-alert", "grey", hide_state=True
    )
    return {
        "type": "vertical-stack",
        "cards": [
            heading("Hot water", "mdi:water-boiler"),
            {"type": "entities", "show_header_toggle": False, "entities": rows},
            conditional(when(mode, "guest"), on_card),
            conditional(when(mode, not_states=("guest", "unavailable", "unknown")), off_card),
            conditional(
                [
                    {
                        "condition": "or",
                        "conditions": [
                            {"condition": "state", "entity": mode, "state": "unavailable"},
                            {"condition": "state", "entity": mode, "state": "unknown"},
                        ],
                    }
                ],
                unknown,
            ),
        ],
    }


def hot_water_controls(ent):
    return [
        {
            "type": "button",
            "name": label,
            "icon": "mdi:water-boiler",
            "tap_action": press(
                ent.thermowatt("button", name),
                f"{label}? Existing controller safeguards still apply.",
            ),
        }
        for name, label in (
            ("Hold heater (owner override)", "Hold automatic heating"),
            ("Resume automatic control", "Resume automatic heating"),
            ("12hr Override 62°C", "Start 12 hour 62 °C override"),
            ("Cancel 12hr Override", "Cancel 12 hour override"),
        )
    ]


# ------------------------------------------------------------------ bathrooms
def bathroom_card(ent, name):
    hum = ent.tapo("sensor", name, "Humidity")
    temp = ent.tapo("sensor", name, "Temperature")
    status = ent.tapo("sensor", name, "Fan Status")
    shower = ent.tapo("binary_sensor", name, "Shower Detected")
    fan = ent.tapo("binary_sensor", name, "Fan Running")
    fan_switch = ent.tapo("switch", name, "Fan Manual Override")
    towel = ent.tapo("binary_sensor", name, "Towel Rail Heating")
    towel_switch = ent.tapo("switch", name, "Towel Rail Manual Override")
    towel_status = ent.tapo("sensor", name, "Towel Rail Status")
    ent.used[towel_status] = "tapo_smart_controller"

    def toggle(entity, switch, label, icon, on_text, off_text, question=None):
        # Colour follows the ACTUAL state (blue running/heating, grey not); the tap acts on the
        # separate manual-request switch, so request state is never mistaken for physical state.
        cancel = tile(
            entity, label, icon, "blue", content="summary", tap=call("switch.turn_off", switch)
        )
        request = tile(
            entity,
            label,
            icon,
            "blue",
            content="summary",
            tap=call("switch.turn_on", switch, question),
        )
        return [
            conditional(when(switch, "on"), cancel),
            conditional(when(switch, not_states=("on",)), request),
        ]

    return {
        "type": "vertical-stack",
        "cards": [
            heading(name, "mdi:shower-head"),
            {
                "type": "grid",
                "columns": 2,
                "square": False,
                "cards": [
                    tile(hum, "Humidity", "mdi:water-percent", "blue"),
                    tile(temp, "Temperature", "mdi:thermometer", "orange"),
                    tile(shower, "Shower", "mdi:shower-head", "blue", content="state"),
                    tile(status, "Extraction", "mdi:fan-clock", None, content="summary"),
                ],
            },
            *toggle(fan, fan_switch, "Fan", "mdi:fan", "ON", "OFF"),
            *toggle(
                towel,
                towel_switch,
                "Towel rail",
                "mdi:radiator",
                "ON",
                "OFF",
                "Request one towel-rail drying cycle? It only heats during off-peak.",
            ),
        ],
    }


# ------------------------------------------------------------------ doors
def door_tiles(ent):
    garage = ent.tapo("sensor", "Garage Door Position")
    front = ent.tapo("binary_sensor", "Front Door Open")
    ent.used[ent.tapo("sensor", "Garage Door Status")] = "tapo_smart_controller"
    ent.used[ent.tapo("sensor", "Front Door Lock Status")] = "tapo_smart_controller"
    closed = tile(garage, "Garage door", "mdi:garage-variant", "grey")
    not_closed = tile(garage, "Garage door", "mdi:garage-open-variant", "orange")
    return [
        conditional(when(garage, "Closed"), closed),
        conditional(when(garage, "Not closed"), not_closed),
        conditional(
            when(garage, not_states=("Closed", "Not closed")),
            tile(garage, "Garage door", "mdi:garage-alert-variant", "grey"),
        ),
        tile(front, "Front door", "mdi:door", "orange", content="state"),
    ]


# ------------------------------------------------------------------ views
def settings_button(label, path):
    return {
        "type": "button",
        "name": label,
        "icon": "mdi:cog-outline",
        "tap_action": {"action": "navigate", "navigation_path": path},
    }


def history(title, entities, hours=24):
    return {"type": "history-graph", "title": title, "hours_to_show": hours, "entities": entities}


def build_views(ent, custom):
    mapping = ent.mapping
    bathrooms = mapping["bathrooms"]
    flow = power_flow_card(ent, custom)

    weather_entity = ent.mapped("weather")
    weather = (
        {
            "type": "weather-forecast",
            "entity": weather_entity,
            "name": "Rokeby, TAS",
            "show_current": True,
            "show_forecast": True,
            "forecast_type": "daily",
        }
        if weather_entity
        else mapping_needed("Rokeby TAS weather", "weather.entity")
    )
    lights = []
    for key, label in (("dining_room", "Dining room"), ("living_room", "Living room")):
        light = ent.mapped("lights", key)
        lights.append(
            tile(light, label, "mdi:lightbulb", "blue", tap=call("light.toggle", light))
            if light
            else mapping_needed(f"{label} light", f"lights.{key}.entity")
        )

    home = {
        "title": "Home",
        "path": "home",
        "icon": "mdi:home",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            section(heading("Energy", "mdi:solar-power"), flow, energy_tiles(ent), span=2),
            section(heading("Weather", "mdi:weather-partly-cloudy"), weather),
            section(hot_water_card(ent)),
            section(heading("Lights", "mdi:lightbulb-group"), *lights),
            section(heading("Doors", "mdi:door"), *door_tiles(ent)),
            section(*[bathroom_card(ent, name) for name in bathrooms], span=2),
        ],
    }
    energy = {
        "title": "Energy",
        "path": "energy",
        "icon": "mdi:solar-power",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            section(heading("Live power flow", "mdi:flash"), flow, energy_tiles(ent)),
            section(
                heading("Today (long-term statistics)", "mdi:chart-bar"),
                *statistics_cards(ent),
                history(
                    "Power (24 h)",
                    [
                        ent.energy("solar_power"),
                        ent.energy("house_power"),
                        ent.energy("grid_power"),
                    ],
                ),
                note(
                    "Daily household, import and export figures come from the optional "
                    "`home_energy_package.yaml` and begin counting when it is installed; the "
                    "statistics cards above are retroactive. EMHASS forecasts are never shown as "
                    "measurements."
                ),
            ),
        ],
    }
    hot_water = {
        "title": "Hot water",
        "path": "hot-water",
        "icon": "mdi:water-boiler",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            section(hot_water_card(ent)),
            section(
                heading("Controls", "mdi:gesture-tap"),
                *hot_water_controls(ent),
                settings_button(
                    "Hot water settings and diagnostic report", THERMOWATT_SETTINGS_PATH
                ),
            ),
            section(
                history(
                    "Tank bottom temperature",
                    [ent.thermowatt("sensor", "Bottom temperature")],
                    48,
                )
            ),
        ],
    }
    bath_view = {
        "title": "Bathrooms",
        "path": "bathrooms",
        "icon": "mdi:shower-head",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            *[
                section(
                    bathroom_card(ent, name),
                    history(
                        f"{name} humidity and temperature",
                        [
                            ent.tapo("sensor", name, "Humidity"),
                            ent.tapo("sensor", name, "Temperature"),
                        ],
                    ),
                )
                for name in bathrooms
            ],
            section(
                settings_button(
                    "Bathroom tuning (towel hours, fan override, humidity)", TAPO_SETTINGS_PATH
                ),
                note(
                    "Towel drying hours (default 4), the fan override length (default 20 min) and the "
                    "advanced humidity tuning are integration options, not dashboard controls."
                ),
            ),
        ],
    }
    doors = {
        "title": "Doors",
        "path": "doors",
        "icon": "mdi:door",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            section(
                heading("Doors (monitoring only)", "mdi:shield-home"),
                *door_tiles(ent),
                note(
                    "Monitoring only. This dashboard offers **no** garage Open/Close/Stop and no lock "
                    "controls; the garage relay and unattended closing stay disabled."
                ),
            ),
            section(
                {
                    "type": "entities",
                    "title": "Door detail",
                    "show_header_toggle": False,
                    "entities": [
                        sensor_row(ent.tapo("sensor", "Garage Door Status"), "Garage status"),
                        sensor_row(
                            ent.tapo("sensor", "Front Door Lock Status"), "Front door status"
                        ),
                    ],
                }
            ),
        ],
    }
    system = {
        "title": "System",
        "path": "system",
        "icon": "mdi:stethoscope",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            section(
                {
                    "type": "entities",
                    "title": "Tapo Smart Controller",
                    "show_header_toggle": False,
                    "entities": [
                        sensor_row(
                            ent.tapo("binary_sensor", "Controller Health Problem"), "Health problem"
                        ),
                        sensor_row(ent.tapo("sensor", "Active Health Warnings"), "Active warnings"),
                        sensor_row(
                            ent.tapo("binary_sensor", "Simulation Mode Active"), "Simulation mode"
                        ),
                        sensor_row(
                            ent.tapo("sensor", "Electricity Tariff Status"),
                            "Tariff read by controller",
                        ),
                    ],
                },
                settings_button("Tapo settings", TAPO_SETTINGS_PATH),
            ),
            section(
                {
                    "type": "entities",
                    "title": "Thermowatt",
                    "show_header_toggle": False,
                    "entities": [
                        sensor_row(ent.thermowatt("sensor", "Cloud health"), "Cloud connection"),
                        sensor_row(
                            ent.thermowatt("sensor", "Controller fault"), "Heating control problem"
                        ),
                        sensor_row(
                            ent.thermowatt("sensor", "Automatic control state"),
                            "Controller supervision",
                        ),
                        sensor_row(
                            ent.thermowatt("sensor", "Last command result"), "Last command outcome"
                        ),
                    ],
                },
                settings_button(
                    "Thermowatt settings and diagnostic report", THERMOWATT_SETTINGS_PATH
                ),
            ),
        ],
    }
    return [home, energy, hot_water, bath_view, doors, system]


def build_dashboard(custom=True):
    ent = Entities(load_mapping())
    views = build_views(ent, custom)
    return {"title": "Home", "views": views}, ent


# ------------------------------------------------------------------ energy package
def _kw(entity):
    return f"{{{{ (states('{entity}') | float / 1000) | round(3) }}}}"


def _numeric(*entities):
    return "{{ " + " and ".join(f"is_number(states('{e}'))" for e in entities) + " }}"


def build_package(mapping=None):
    mapping = mapping or load_mapping()
    e = {
        key: mapping["energy"][key]["entity"]
        for key in mapping["energy"]
        if isinstance(mapping["energy"][key], dict)
    }
    export_positive = bool(mapping["energy"]["grid_export_positive"])
    battery = bool(mapping["energy"]["battery_present"])
    grid_expr = f"(states('{e['grid_power']}') | float)"
    toward_grid = grid_expr if export_positive else f"(0 - {grid_expr})"
    idle_w = IDLE_KW * 1000
    ids = package_ids()

    def tmpl(
        name, unique, state, availability, unit=None, device_class=None, state_class=None, icon=None
    ):
        item = {"name": name, "unique_id": unique, "state": state, "availability": availability}
        if unit:
            item["unit_of_measurement"] = unit
        if device_class:
            item["device_class"] = device_class
        if state_class:
            item["state_class"] = state_class
        if icon:
            item["icon"] = icon
        return item

    grid_ok = _numeric(e["grid_power"])
    sensors = [
        tmpl(
            "Home solar power kW",
            "home_solar_power_kw",
            f"{{{{ ([states('{e['solar_power']}') | float, 0] | max / 1000) | round(3) }}}}",
            _numeric(e["solar_power"]),
            "kW",
            "power",
            "measurement",
        ),
        tmpl(
            "Home house power kW",
            "home_house_power_kw",
            f"{{{{ ([states('{e['house_power']}') | float, 0] | max / 1000) | round(3) }}}}",
            _numeric(e["house_power"]),
            "kW",
            "power",
            "measurement",
        ),
        tmpl(
            "Home grid import kW",
            "home_grid_import_kw",
            f"{{{{ (([0 - {toward_grid}, 0] | max) / 1000) | round(3) }}}}",
            grid_ok,
            "kW",
            "power",
            "measurement",
        ),
        tmpl(
            "Home grid export kW",
            "home_grid_export_kw",
            f"{{{{ (([{toward_grid}, 0] | max) / 1000) | round(3) }}}}",
            grid_ok,
            "kW",
            "power",
            "measurement",
        ),
        tmpl(
            "Home grid state",
            "home_grid_state",
            f"{{% set g = {toward_grid} %}}{{% if g > {idle_w} %}}Grid Export{{% elif g < -{idle_w} %}}Grid Import{{% else %}}Grid Idle{{% endif %}}",
            grid_ok,
            icon="mdi:transmission-tower",
        ),
    ]
    solar_today, export_today = e["solar_today_energy"], ids["export_today"]
    sensors += [
        tmpl(
            "Home solar used directly today",
            "home_solar_used_directly_today",
            f"{{{{ ([states('{solar_today}') | float - states('{export_today}') | float, 0] | max) | round(3) }}}}",
            "{{ false }}" if battery else _numeric(solar_today, export_today),
            "kWh",
            "energy",
            "total",
        ),
        tmpl(
            "Home self-consumption today",
            "home_self_consumption_today",
            f"{{{{ (([states('{solar_today}') | float - states('{export_today}') | float, 0] | max) / states('{solar_today}') | float * 100) | round(0) }}}}",
            # Trustworthy only: no battery, real generation so far today, and counters that agree
            # (export cannot exceed generation beyond a small reset-timing tolerance).
            "{{ false }}"
            if battery
            else (
                "{{ "
                + _numeric(solar_today, export_today)[3:-3]
                + f" and states('{solar_today}') | float >= 1.0"
                + f" and states('{export_today}') | float <= states('{solar_today}') | float + 0.3 }}}}"
            ),
            "%",
            None,
            "measurement",
            "mdi:percent-circle",
        ),
    ]
    return {
        "utility_meter": {
            "home_grid_import_today": {
                "name": "Home grid import today",
                "unique_id": "home_grid_import_today",
                "source": e["grid_import_total"],
                "cycle": "daily",
            },
            "home_grid_export_today": {
                "name": "Home grid export today",
                "unique_id": "home_grid_export_today",
                "source": e["grid_export_total"],
                "cycle": "daily",
            },
            "home_consumption_today": {
                "name": "Home consumption today",
                "unique_id": "home_consumption_today",
                "source": "sensor.home_house_energy_total",
                "cycle": "daily",
            },
        },
        "sensor": [
            {
                "platform": "integration",
                "name": "Home house energy total",
                "unique_id": "home_house_energy_total",
                "source": e["house_power"],
                "unit_prefix": "k",
                "unit_time": "h",
                "round": 3,
                "method": "left",
                "max_sub_interval": "00:05:00",
            }
        ],
        "template": [{"sensor": sensors}],
    }


# ------------------------------------------------------------------ output
HEADERS = {
    "home": (
        "# Home dashboard (generated by tools/build_home_dashboard.py; edit homeowner/home_mapping.yaml)\n"
        f"# Requires the dependency-free custom card {CARD_RESOURCE}\n"
        "# (homeowner/www/thermowatt-power-flow-card.js). Use home_no_custom_card.yaml without it.\n"
    ),
    "native": "# Home dashboard, native power-flow fallback (generated by tools/build_home_dashboard.py)\n",
    "package": (
        "# Optional Home Assistant package (generated by tools/build_home_dashboard.py).\n"
        "# Save as /config/packages/thermowatt_home_energy.yaml with 'homeassistant: packages: !include_dir_named packages'.\n"
        "# Daily meters start counting when installed; a restart (not a reset) is needed to load it.\n"
    ),
}


class _PlainDumper(yaml.SafeDumper):
    """No YAML anchors/aliases: shared card dicts are written out in full (clearer to paste/edit)."""

    def ignore_aliases(self, data):
        return True


def dump(data, key):
    body = yaml.dump(data, Dumper=_PlainDumper, allow_unicode=True, sort_keys=False, width=95)
    return HEADERS[key] + body


def render_all():
    home, _ = build_dashboard(custom=True)
    native, _ = build_dashboard(custom=False)
    return {
        "home": dump(home, "home"),
        "native": dump(native, "native"),
        "package": dump(build_package(), "package"),
    }


def report():
    _, ent = build_dashboard(custom=True)
    _, native_ent = build_dashboard(custom=False)
    used = {**ent.used, **native_ent.used}
    print("Entities used by the Home dashboard:")
    for eid, source in sorted(used.items()):
        print(f"  {eid}  [{source}]")
    mapping = load_mapping()
    flat = []
    for group in ("energy", "weather", "lights"):
        node = mapping[group]
        nodes = (
            {group: node}
            if "entity" in node
            else {f"{group}.{k}": v for k, v in node.items() if isinstance(v, dict)}
        )
        for name, value in nodes.items():
            flat.append((name, value["entity"], value.get("status", "")))
    print("\nMappings (status):")
    for name, entity, status in flat:
        print(f"  {name}: {entity or '(unmapped)'}  [{status}]")
    unresolved = sorted({u for u in ent.unresolved})
    print("\nUnresolved mappings:", ", ".join(unresolved) or "none")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        report()
        return
    rendered = render_all()
    for key, content in rendered.items():
        target = OUTPUTS[key]
        if args.check:
            assert target.read_text(encoding="utf-8") == content, f"{target.name} is stale"
        else:
            target.parent.mkdir(exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
