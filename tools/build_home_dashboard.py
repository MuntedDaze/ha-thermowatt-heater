"""Unified Home dashboard generator.

Canonical sources: a mapping file (``homeowner/home_mapping.yaml`` = this household's verified profile,
``homeowner/generic/home_mapping.yaml`` = assumption-free defaults) plus this file. Writes, reproducibly:

  homeowner/home.yaml                      dashboard using the dependency-free power-flow card
  homeowner/home_no_custom_card.yaml       same dashboard with a native power-flow fallback
  homeowner/home_energy_package.yaml       optional HA package (kW sensors, daily energy, status)
  homeowner/generic/home.yaml, home_energy_package.yaml   the same for the generic profile

It never modifies the existing Thermowatt or Tapo dashboards. ``--check`` fails if any output is stale,
``--report`` lists every entity used and the mappings still to complete, ``--mapping FILE --out-dir DIR``
builds your own profile.
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
GENERIC_MAPPING = ROOT / "homeowner/generic/home_mapping.yaml"
TAPO_CONTRACT = ROOT / "homeowner/tapo_entity_contract.json"
OUTPUT_FILES = {
    "home": "home.yaml",
    "native": "home_no_custom_card.yaml",
    "package": "home_energy_package.yaml",
}
CARD_RESOURCE = "/local/thermowatt/thermowatt-power-flow-card.js"
IDLE_KW = 0.005  # 5 W: below this a flow is idle, not import/export
TAPO_SETTINGS_PATH = "/config/integrations/integration/tapo_smart_controller"
THERMOWATT_SETTINGS_PATH = "/config/integrations/integration/thermann_shadow"
POWER_FRESH_SECONDS = 900
COUNTER_FRESH_SECONDS = 1800
DAILY_CAP_KWH = 500
BAD = "['unknown', 'unavailable', 'none', '']"


# ------------------------------------------------------------------ mapping + contracts
def load_mapping(path=None):
    return yaml.safe_load(Path(path or MAPPING).read_text(encoding="utf-8"))


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

    def original(self, index, key):
        """Original device entity of bathroom ``index`` or None (history then uses the Tapo sensor)."""
        node = (self.mapping["bathrooms"][index].get("original") or {}).get(key)
        entity = node["entity"] if isinstance(node, dict) else node
        if entity:
            self.used[entity] = "home_mapping"
        return entity or None


# ------------------------------------------------------------------ small card helpers
def span(columns, **extra):
    """Sections-view sizing for a card (12-column section grid)."""
    return {"grid_options": {"columns": columns, **extra}}


def heading(text, icon=None, style="title"):
    card = {"type": "heading", "heading": text, "heading_style": style}
    if icon:
        card["icon"] = icon
    return card


def note(text, columns=None):
    card = {"type": "markdown", "content": text}
    if columns:
        card.update(span(columns))
    return card


def tile(
    entity,
    name=None,
    icon=None,
    color=None,
    content=None,
    tap=None,
    hide_state=False,
    columns=None,
    features=None,
):
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
    if features:
        card["features"] = features
        card["features_position"] = "inline"
    if columns:
        card.update(span(columns))
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


def any_state(entity, states):
    return {
        "condition": "or",
        "conditions": [{"condition": "state", "entity": entity, "state": s} for s in states],
    }


def conditional(conditions, card, columns=None):
    out = {"type": "conditional", "conditions": conditions, "card": card}
    if columns:
        out.update(span(columns))
    return out


def section(*cards, span_columns=None):
    out = {"type": "grid", "cards": list(cards)}
    if span_columns:
        out["column_span"] = span_columns
    return out


def mapping_needed(what, key, columns=None):
    return note(
        f"**{what}: mapping needed.** Set `{key}` in the mapping file to the real entity ID "
        "(Developer Tools -> States), then run `python tools/build_home_dashboard.py`.",
        columns,
    )


def sensor_row(ent, name):
    return {"entity": ent, "name": name}


def settings_tile(label, path, columns=6):
    return {
        "type": "tile",
        "name": label,
        "icon": "mdi:cog-outline",
        "vertical": False,
        "tap_action": {"action": "navigate", "navigation_path": path},
        "icon_tap_action": {"action": "navigate", "navigation_path": path},
        **span(columns),
    }


def history(title, entities, hours=24, columns=None):
    card = {"type": "history-graph", "title": title, "hours_to_show": hours, "entities": entities}
    if columns:
        card.update(span(columns))
    return card


# ------------------------------------------------------------------ energy
def package_ids():
    """Entity IDs created by home_energy_package.yaml (object ids fixed by their names)."""
    return {
        "solar_kw": "sensor.home_solar_power_kw",
        "house_kw": "sensor.home_house_power_kw",
        "import_kw": "sensor.home_grid_import_kw",
        "export_kw": "sensor.home_grid_export_kw",
        "grid_state": "sensor.home_grid_state",
        "import_meter": "sensor.home_grid_import_meter",
        "export_meter": "sensor.home_grid_export_meter",
        "consumption_meter": "sensor.home_consumption_meter",
        "import_today": "sensor.home_grid_import_today",
        "export_today": "sensor.home_grid_export_today",
        "consumption_today": "sensor.home_consumption_today",
        "estimate_today": "sensor.home_consumption_estimate_today",
        "used_today": "sensor.home_solar_used_directly_today",
        "selfcons_today": "sensor.home_self_consumption_today",
        "status": "sensor.home_energy_status",
    }


def power_flow_card(ent, custom):
    if custom:
        return {
            "type": "custom:thermowatt-power-flow-card",
            "solar_entity": ent.energy("solar_power"),
            "house_entity": ent.energy("house_power"),
            "grid_entity": ent.energy("grid_power"),
            "grid_export_positive": bool(ent.mapping["energy"]["grid_export_positive"]),
            **span(12),
        }
    ids = package_ids()
    for key in ("solar_kw", "house_kw", "grid_state", "import_kw", "export_kw"):
        ent.used[ids[key]] = "home_energy_package"
    return {
        "type": "vertical-stack",
        **span(12),
        "cards": [
            {
                "type": "horizontal-stack",
                "cards": [
                    tile(ids["solar_kw"], "Solar", "mdi:solar-power", "green"),
                    tile(ids["house_kw"], "House", "mdi:home-lightning-bolt", "blue"),
                ],
            },
            {
                "type": "horizontal-stack",
                "cards": [
                    tile(ids["grid_state"], "Grid", "mdi:transmission-tower", "orange"),
                    tile(ids["import_kw"], "Import", "mdi:transmission-tower-import", "orange"),
                    tile(ids["export_kw"], "Export", "mdi:transmission-tower-export", "green"),
                ],
            },
        ],
    }


ENERGY_STATUS_TEXT = (
    "{% set s = states('sensor.home_energy_status') %}"
    "{% if s == 'collecting_first_day' %}**Collecting daily data.** Household, direct-use and "
    "self-consumption appear once the daily meters cover a full day (after the next midnight). "
    "Solar, import and export are shown from existing statistics.{% elif s == 'sources_unavailable' %}"
    "**Energy readings unavailable.** Check the inverter integration; figures are withheld, not zero."
    "{% elif s == 'inconsistent' %}**Daily counters disagree** (export exceeds generation); figures "
    "are withheld until they agree.{% elif s == 'battery_unconfirmed' %}**Battery not confirmed.** "
    "Set `battery_present: false` in the mapping if there is no battery.{% elif s == 'ready' %}"
    "{% else %}**Energy status unknown.**{% endif %}"
)


def statistic_tile(ent, key, name, columns):
    return {
        "type": "statistic",
        "entity": ent.energy(key),
        "name": name,
        "stat_type": "change",
        "period": {"calendar": {"period": "day"}},
        **span(columns),
    }


def energy_panel(ent, columns=6):
    """Compact 'today' figures: existing statistics where reliable, package figures when valid."""
    ids = package_ids()
    for value in ids.values():
        ent.used[value] = "home_energy_package"
    ready = [{"condition": "state", "entity": ids["status"], "state": "ready"}]
    not_ready = [{"condition": "state", "entity": ids["status"], "state_not": "ready"}]
    solar_today = ent.energy("solar_today_energy")
    return [
        tile(solar_today, "Solar today", "mdi:solar-power-variant", "green", columns=columns),
        statistic_tile(ent, "grid_import_total", "Grid import today", columns),
        statistic_tile(ent, "grid_export_total", "Grid export today", columns),
        conditional(
            ready,
            tile(ids["consumption_today"], "Household today", "mdi:home-lightning-bolt", "blue"),
            columns,
        ),
        conditional(
            ready,
            tile(ids["used_today"], "Solar used directly", "mdi:home-battery", "green"),
            columns,
        ),
        conditional(
            ready,
            tile(ids["selfcons_today"], "Self-consumption", "mdi:percent-circle", "green"),
            columns,
        ),
        conditional(not_ready, note(ENERGY_STATUS_TEXT), 12),
    ]


def partial_meters(ent, columns=12):
    ids = package_ids()
    rows = []
    for key, label in (
        ("import_meter", "Grid import since the meter started"),
        ("export_meter", "Grid export since the meter started"),
        ("consumption_meter", "Household, integrated from power (estimate)"),
    ):
        ent.used[ids[key]] = "home_energy_package"
        rows.append(sensor_row(ids[key], label))
    return {
        "type": "entities",
        "title": "Daily meters (partial on the day installed)",
        "show_header_toggle": False,
        "entities": rows,
        **span(columns),
    }


# ------------------------------------------------------------------ hot water
HOT_WATER_TEMPLATE = """\
{% macro nice(v) -%}{{ v | replace('_', ' ') | capitalize }}{%- endmacro %}
{% macro hhmm(v) -%}{% set d = as_datetime(v, none) %}{{ as_local(d).strftime('%H:%M') if d is not none else '—' }}{%- endmacro %}
{% set bad = @@BAD@@ %}
{% set t = states('@@TEMP@@') %}
{% set age = states('@@AGE@@') %}
{% set mode_r = states('@@MODE_R@@') %}
{% set tgt_r = states('@@TGT_R@@') %}
{% set tgt_d = states('@@TGT_D@@') %}
{% set ctrl = states('@@CTRL@@') %}
{% set tariff = states('@@TARIFF@@') %}
{% set boost = states('@@BOOST@@') %}
{% set nxt = states('@@NEXT@@') %}
{% set poll = states('@@POLL@@') %}
{% set last = states('@@LAST@@') %}
{% set ends = states('@@ENDS@@') %}
{% set ctrl_names = {'automatic': 'Automatic', 'guest': '12 h override', 'holiday': 'Holiday', 'disabled': 'Off'} %}
{% set tariff_names = {'off_peak': 'Off-peak', 'peak': 'Peak', 'shoulder': 'Shoulder'} %}
# {{ (t | float(0) | round(1) ~ ' °C') if t not in bad else '—' }}
Tank bottom · {{ ('updated ' ~ (age | int(0)) ~ ' min ago') if age not in bad else 'age unknown' }} · last poll {{ hhmm(last) if last not in bad else '—' }}

**Heater** {{ nice(mode_r) if mode_r not in bad else '—' }} · target {{ (tgt_r | float(0) | round(0) | int ~ ' °C') if tgt_r not in bad else '—' }}{% if tgt_d not in bad and tgt_r not in bad and (tgt_d | float(0) | round(0)) != (tgt_r | float(0) | round(0)) %} · desired {{ tgt_d | float(0) | round(0) | int }} °C{% endif %}
**Control** {{ ctrl_names.get(ctrl, nice(ctrl)) if ctrl not in bad else '—' }} · **Tariff** {{ tariff_names.get(tariff, nice(tariff)) if tariff not in bad else '—' }} · **Solar boost** {{ nice(boost) if boost not in bad else '—' }}
**Next** {{ nice(nxt) if nxt not in bad else '—' }} · next poll {{ hhmm(poll) if poll not in bad else '—' }}{% if ctrl == 'guest' and ends not in bad %}
**Override ends** {{ hhmm(ends) }}{% endif %}
"""


def hot_water_summary(ent, columns=12):
    last_poll = integration_config.DEFAULT_SOURCES["last_poll"]
    ent.used[last_poll] = "thermann_bridge"
    text = (
        HOT_WATER_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@TEMP@@", ent.thermowatt("sensor", "Bottom temperature"))
        .replace("@@AGE@@", ent.thermowatt("sensor", "Status age"))
        .replace("@@MODE_R@@", ent.thermowatt("sensor", "Thermann mode"))
        .replace("@@TGT_R@@", ent.thermowatt("sensor", "Thermann target"))
        .replace("@@TGT_D@@", ent.thermowatt("sensor", "Desired thermostat temperature"))
        .replace("@@CTRL@@", ent.thermowatt("sensor", "Hot water operating mode"))
        .replace("@@TARIFF@@", ent.thermowatt("sensor", "Current tariff"))
        .replace("@@BOOST@@", ent.thermowatt("sensor", "Solar boost status"))
        .replace("@@NEXT@@", ent.thermowatt("sensor", "Next intended action"))
        .replace("@@POLL@@", ent.thermowatt("sensor", "Next cloud poll"))
        .replace("@@LAST@@", last_poll)
        .replace("@@ENDS@@", ent.thermowatt("sensor", "12hr Override ends"))
    )
    return note(text, columns)


def override_toggle(ent, columns=12):
    mode = ent.thermowatt("sensor", "Hot water operating mode")
    start = ent.thermowatt("button", "12hr Override 62°C")
    cancel = ent.thermowatt("button", "Cancel 12hr Override")
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
    return [
        conditional(when(mode, "guest"), on_card, columns),
        conditional(when(mode, not_states=("guest", "unavailable", "unknown")), off_card, columns),
        conditional([any_state(mode, ("unavailable", "unknown"))], unknown, columns),
    ]


CONTROLLABLE = (
    "observing",
    "parked",
    "baseline_45",
    "normal_storage_62",
    "storage_70",
    "change_requested",
    "confirming",
)


def hold_toggle(ent, columns=12):
    """One state-aware control for holding / resuming automatic heating."""
    state = ent.thermowatt("sensor", "Automatic control state")
    hold = ent.thermowatt("button", "Hold heater (owner override)")
    resume = ent.thermowatt("button", "Resume automatic control")
    held = tile(
        state,
        "Automatic heating: on hold",
        "mdi:pause-circle",
        "orange",
        tap=press(resume, "Resume automatic heating? The controller re-inspects the heater first."),
        hide_state=True,
    )
    active = tile(
        state,
        "Automatic heating: active",
        "mdi:play-circle",
        "blue",
        tap=press(hold, "Hold automatic heating? Nothing is sent to the heater until you resume."),
        hide_state=True,
    )
    inert = tile(state, "Automatic heating: not available", "mdi:cancel", "grey", hide_state=True)
    return [
        conditional(when(state, "owner_override"), held, columns),
        conditional([any_state(state, CONTROLLABLE)], active, columns),
        conditional(when(state, not_states=(*CONTROLLABLE, "owner_override")), inert, columns),
    ]


# ------------------------------------------------------------------ bathrooms
def bathroom_card(ent, name, columns=6):
    hum = ent.tapo("sensor", name, "Humidity")
    temp = ent.tapo("sensor", name, "Temperature")
    fan = ent.tapo("binary_sensor", name, "Fan Running")
    fan_switch = ent.tapo("switch", name, "Fan Manual Override")
    towel = ent.tapo("binary_sensor", name, "Towel Rail Heating")
    towel_switch = ent.tapo("switch", name, "Towel Rail Manual Override")
    ent.used[ent.tapo("sensor", name, "Towel Rail Status")] = "tapo_smart_controller"

    def toggle(entity, switch, label, icons, question=None):
        """Four mutually exclusive states; colour follows the OBSERVED state (entity).

        manual request  -> tap cancels (also a queued request still waiting for off-peak)
        automatic       -> running without a request; tap requests a manual run
        off             -> grey, tap requests a manual run
        status unknown  -> grey and inert (never a command on an unknown state)
        """
        unknown_any = {
            "condition": "or",
            "conditions": [
                {"condition": "state", "entity": e, "state": st}
                for e in (switch, entity)
                for st in ("unavailable", "unknown")
            ],
        }
        manual, auto, off, unknown = icons
        return [
            conditional(
                when(switch, "on"),
                tile(
                    entity,
                    f"{label}: manual",
                    manual,
                    "blue",
                    content="summary",
                    tap=call("switch.turn_off", switch),
                ),
            ),
            conditional(
                [*when(switch, "off"), {"condition": "state", "entity": entity, "state": "on"}],
                tile(
                    entity,
                    f"{label}: automatic",
                    auto,
                    "blue",
                    content="summary",
                    tap=call("switch.turn_on", switch, question),
                ),
            ),
            conditional(
                [*when(switch, "off"), {"condition": "state", "entity": entity, "state": "off"}],
                tile(
                    entity,
                    f"{label}: off",
                    off,
                    "grey",
                    content="summary",
                    tap=call("switch.turn_on", switch, question),
                ),
            ),
            conditional(
                [*when(switch, not_states=("on",)), unknown_any],
                tile(entity, f"{label}: status unknown", unknown, "grey", content="summary"),
            ),
        ]

    return {
        "type": "vertical-stack",
        **span(columns),
        "cards": [
            heading(name, "mdi:shower-head", "subtitle"),
            {
                "type": "horizontal-stack",
                "cards": [
                    tile(hum, "Humidity", "mdi:water-percent", "blue"),
                    tile(temp, "Temperature", "mdi:thermometer", "orange"),
                ],
            },
            *toggle(
                fan,
                fan_switch,
                "Fan",
                ("mdi:fan-clock", "mdi:fan", "mdi:fan-off", "mdi:fan-alert"),
            ),
            *toggle(
                towel,
                towel_switch,
                "Towel rail",
                ("mdi:radiator", "mdi:radiator", "mdi:radiator-off", "mdi:radiator-disabled"),
                "Request one towel-rail drying cycle? It only heats during off-peak.",
            ),
        ],
    }


def bathroom_history(ent, index, name, columns=12):
    """Humidity/temperature from the ORIGINAL sensors (older history) and the physical relays."""
    hum = ent.original(index, "humidity") or ent.tapo("sensor", name, "Humidity")
    temp = ent.original(index, "temperature") or ent.tapo("sensor", name, "Temperature")
    fan = ent.original(index, "fan") or ent.tapo("binary_sensor", name, "Fan Running")
    towel = ent.original(index, "towel") or ent.tapo("binary_sensor", name, "Towel Rail Heating")
    return [
        history(f"{name}: humidity and temperature", [hum, temp], 24, columns),
        history(f"{name}: fan and towel rail relays", [fan, towel], 24, columns),
    ]


# ------------------------------------------------------------------ doors
def door_tiles(ent, columns=6):
    garage = ent.tapo("sensor", "Garage Door Position")
    front = ent.tapo("binary_sensor", "Front Door Open")
    ent.used[ent.tapo("sensor", "Garage Door Status")] = "tapo_smart_controller"
    ent.used[ent.tapo("sensor", "Front Door Lock Status")] = "tapo_smart_controller"
    return [
        conditional(
            when(garage, "Closed"),
            tile(garage, "Garage door", "mdi:garage-variant", "grey"),
            columns,
        ),
        conditional(
            when(garage, "Not closed"),
            tile(garage, "Garage door", "mdi:garage-open-variant", "orange"),
            columns,
        ),
        conditional(
            when(garage, not_states=("Closed", "Not closed")),
            tile(garage, "Garage door", "mdi:garage-alert-variant", "grey"),
            columns,
        ),
        tile(front, "Front door", "mdi:door", "orange", content="state", columns=columns),
    ]


def door_detail(ent):
    garage = ent.tapo("sensor", "Garage Door Status")
    front = ent.tapo("sensor", "Front Door Lock Status")
    return [
        tile(garage, "Garage", "mdi:garage", None, content="summary", columns=12),
        tile(front, "Front door", "mdi:door", None, content="summary", columns=12),
    ]


# ------------------------------------------------------------------ system (plain-English status)
SYSTEM_TEMPLATE = """\
{% set bad = @@BAD@@ %}
{% macro nice(v) -%}{{ v | replace('_', ' ') | capitalize }}{%- endmacro %}
{% set cloud = {'ok': 'Connected', 'disabled': 'Disabled', 'auth_locked': 'Sign-in locked: check the Thermann app', 'quota_limited': 'Request limit reached', 'backoff': 'Backing off after an error', 'unavailable': 'Unavailable'} %}
{% set sup = {'observing': 'Observing: checking the heater before acting', 'parked': 'Heater confirmed off', 'baseline_45': 'Holding the 45 °C baseline', 'normal_storage_62': 'Holding 62 °C storage', 'storage_70': 'Holding the 70 °C boost', 'change_requested': 'A change is needed but is waiting for conditions', 'confirming': 'Command sent: waiting for confirmation', 'owner_override': 'On hold: you pressed Hold', 'disabled': 'Automatic control is off', 'fault_locked': 'Fault: needs acknowledgement'} %}
{% set tariff = {'off_peak': 'Off-peak', 'peak': 'Peak', 'shoulder': 'Shoulder', 'unknown': 'Unknown'} %}
{% set fault = states('@@FAULT@@') %}
{% set c = states('@@CLOUD@@') %}
{% set s = states('@@SUP@@') %}
{% set t = states('@@TARIFF_T@@') %}
{% set w = states('@@WARN@@') %}
**Thermowatt**
- Cloud connection: {{ cloud.get(c, nice(c)) if c not in bad else 'Unknown' }}
- Heating control problem: {% if fault in ['none', 'None', ''] %}No problems detected{% elif fault in ['unknown', 'unavailable'] %}Unknown{% else %}{{ nice(fault) }}{% endif %}
- Supervision: {{ sup.get(s, nice(s)) if s not in bad else 'Unknown' }}

**Tapo Smart Controller**
- Health: {% if is_state('@@HEALTH@@', 'on') %}Problem reported{% elif is_state('@@HEALTH@@', 'off') %}No problems detected{% else %}Unknown{% endif %}{% if w not in bad %} ({{ w }} active warnings){% endif %}
- Mode: {% if is_state('@@SIM@@', 'on') %}Simulation: no devices are switched{% elif is_state('@@SIM@@', 'off') %}Live control{% else %}Unknown{% endif %}
- Tariff read by the controller: {{ tariff.get(t, nice(t)) if t not in bad else 'Unknown' }}
"""


def system_summary(ent, columns=12):
    text = (
        SYSTEM_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@FAULT@@", ent.thermowatt("sensor", "Controller fault"))
        .replace("@@CLOUD@@", ent.thermowatt("sensor", "Cloud health"))
        .replace("@@SUP@@", ent.thermowatt("sensor", "Automatic control state"))
        .replace("@@TARIFF_T@@", ent.tapo("sensor", "Electricity Tariff Status"))
        .replace("@@WARN@@", ent.tapo("sensor", "Active Health Warnings"))
        .replace("@@HEALTH@@", ent.tapo("binary_sensor", "Controller Health Problem"))
        .replace("@@SIM@@", ent.tapo("binary_sensor", "Simulation Mode Active"))
    )
    return note(text, columns)


# ------------------------------------------------------------------ views
def view(title, path, icon, sections, max_columns=4):
    return {
        "title": title,
        "path": path,
        "icon": icon,
        "type": "sections",
        "max_columns": max_columns,
        "dense_section_placement": True,
        "sections": sections,
    }


def build_views(ent, custom):
    mapping = ent.mapping
    names = [b["name"] for b in mapping["bathrooms"]]
    place = mapping.get("place") or ""
    flow = power_flow_card(ent, custom)

    weather_entity = ent.mapped("weather")
    weather = (
        {
            "type": "weather-forecast",
            "entity": weather_entity,
            **({"name": place} if place else {}),
            "show_current": True,
            "show_forecast": True,
            "forecast_type": "daily",
            **span(12),
        }
        if weather_entity
        else mapping_needed("Weather", "weather.entity", 12)
    )
    lights = []
    for key, label in (("dining_room", "Dining room"), ("living_room", "Living room")):
        light = ent.mapped("lights", key)
        lights.append(
            tile(
                light,
                label,
                "mdi:lightbulb",
                "blue",
                tap=call("light.toggle", light),
                columns=6,
                features=[{"type": "light-brightness"}],
            )
            if light
            else mapping_needed(f"{label} light", f"lights.{key}.entity", 6)
        )
    bathrooms = [bathroom_card(ent, name, 12) for name in names]  # one column wide each

    home = view(
        "Home",
        "home",
        "mdi:home",
        [
            section(flow),
            section(*energy_panel(ent, 6)),
            section(hot_water_summary(ent), *override_toggle(ent)),
            section(weather),
            # Row 2 on a 4-column screen: one bathroom per column, then lights and doors across two.
            *[section(bathroom) for bathroom in bathrooms],
            section(
                heading("Lights and doors", "mdi:home-switch", "subtitle"),
                *lights,
                *door_tiles(ent, 6),
                span_columns=2,
            ),
        ],
    )
    energy = view(
        "Energy",
        "energy",
        "mdi:solar-power",
        [
            section(heading("Live power flow", "mdi:flash", "subtitle"), flow),
            section(heading("Today", "mdi:chart-bar", "subtitle"), *energy_panel(ent, 6)),
            section(
                heading("Statistics and meters", "mdi:chart-line", "subtitle"),
                statistic_tile(ent, "solar_today_energy", "Solar generated (statistics)", 12),
                partial_meters(ent),
            ),
            section(
                history(
                    "Power, last 24 hours",
                    [
                        ent.energy("solar_power"),
                        ent.energy("house_power"),
                        ent.energy("grid_power"),
                    ],
                    24,
                    12,
                ),
                span_columns=3,
            ),
        ],
        max_columns=3,
    )
    hot_water = view(
        "Hot water",
        "hot-water",
        "mdi:water-boiler",
        [
            section(
                hot_water_summary(ent),
                *override_toggle(ent),
                *hold_toggle(ent),
                settings_tile("Hot water settings", THERMOWATT_SETTINGS_PATH, 12),
            ),
            section(
                heading("Plan and diagnostics", "mdi:text-box-search-outline", "subtitle"),
                {
                    "type": "entities",
                    "show_header_toggle": False,
                    "entities": [
                        sensor_row(ent.thermowatt("sensor", "Current heating plan"), "Plan"),
                        sensor_row(ent.thermowatt("sensor", "Next intended action"), "Next action"),
                        sensor_row(
                            ent.thermowatt("sensor", "Next heating start"), "Next heating start"
                        ),
                        sensor_row(ent.thermowatt("sensor", "Solar boost status"), "Solar boost"),
                        sensor_row(
                            ent.thermowatt("sensor", "Why Thermowatt made this decision"),
                            "Decision evidence",
                        ),
                        sensor_row(
                            ent.thermowatt("sensor", "Last command result"), "Last command outcome"
                        ),
                        sensor_row(
                            ent.thermowatt("sensor", "Cloud requests in last 24 hours"),
                            "Cloud requests (24 h)",
                        ),
                    ],
                    **span(12),
                },
            ),
            section(
                history(
                    "Tank bottom temperature",
                    [ent.thermowatt("sensor", "Bottom temperature")],
                    48,
                    12,
                ),
                span_columns=2,
            ),
        ],
    )
    bath_sections = [
        section(bathroom_card(ent, name, 12), *bathroom_history(ent, index, name), span_columns=2)
        for index, name in enumerate(names)
    ]
    bath_view = view(
        "Bathrooms",
        "bathrooms",
        "mdi:shower-head",
        [
            *bath_sections,
            section(
                settings_tile("Bathroom tuning (Tapo settings)", TAPO_SETTINGS_PATH, 12),
                note(
                    "Towel drying hours, the manual fan request length and the humidity tuning are "
                    "integration settings, not dashboard controls.",
                    12,
                ),
                span_columns=2,
            ),
        ],
    )
    contacts = []
    for key in ("garage_contact", "front_contact"):
        node = mapping["doors"].get(key) or {}
        if node.get("entity"):
            ent.used[node["entity"]] = "home_mapping"
            contacts.append(node["entity"])
    doors_view = view(
        "Doors",
        "doors",
        "mdi:door",
        [
            section(
                heading("Doors (monitoring only)", "mdi:shield-home", "subtitle"),
                *door_tiles(ent, 6),
                *door_detail(ent),
                note(
                    "Monitoring only: no garage Open/Close/Stop and no lock controls. The garage is "
                    "operated by its physical Tapo button, and a closed door contact does not mean "
                    "the front door is locked.",
                    12,
                ),
            ),
            *(
                [section(history("Door contacts, last 7 days", contacts, 168, 12), span_columns=2)]
                if contacts
                else []
            ),
        ],
        max_columns=3,
    )
    system = view(
        "System",
        "system",
        "mdi:stethoscope",
        [
            section(
                heading("Status", "mdi:stethoscope", "subtitle"),
                system_summary(ent),
                span_columns=2,
            ),
            section(
                settings_tile(
                    "Thermowatt settings and diagnostic report", THERMOWATT_SETTINGS_PATH, 12
                ),
                settings_tile("Tapo Smart Controller settings", TAPO_SETTINGS_PATH, 12),
            ),
        ],
        max_columns=3,
    )
    return [home, energy, hot_water, bath_view, doors_view, system]


def build_dashboard(custom=True, mapping=None):
    ent = Entities(mapping or load_mapping())
    views = build_views(ent, custom)
    return {"title": "Home", "views": views}, ent


# ------------------------------------------------------------------ energy package
def _numeric(*entities):
    return " and ".join(f"is_number(states('{e}'))" for e in entities)


def build_package(mapping=None):
    mapping = mapping or load_mapping()
    e = {
        key: mapping["energy"][key]["entity"]
        for key in mapping["energy"]
        if isinstance(mapping["energy"][key], dict)
    }
    export_positive = bool(mapping["energy"]["grid_export_positive"])
    grid_expr = f"(states('{e['grid_power']}') | float)"
    toward_grid = grid_expr if export_positive else f"(0 - {grid_expr})"
    idle_w = IDLE_KW * 1000

    def tmpl(
        name,
        unique,
        state,
        availability=None,
        unit=None,
        device_class=None,
        state_class=None,
        icon=None,
        attributes=None,
    ):
        item = {"name": name, "unique_id": unique, "state": state}
        if availability is not None:
            item["availability"] = availability
        if unit:
            item["unit_of_measurement"] = unit
        if device_class:
            item["device_class"] = device_class
        if state_class:
            item["state_class"] = state_class
        if icon:
            item["icon"] = icon
        if attributes:
            item["attributes"] = attributes
        return item

    grid_ok = "{{ " + _numeric(e["grid_power"]) + " }}"
    sensors = [
        tmpl(
            "Home solar power kW",
            "home_solar_power_kw",
            f"{{{{ ([states('{e['solar_power']}') | float, 0] | max / 1000) | round(3) }}}}",
            "{{ " + _numeric(e["solar_power"]) + " }}",
            "kW",
            "power",
            "measurement",
        ),
        tmpl(
            "Home house power kW",
            "home_house_power_kw",
            f"{{{{ ([states('{e['house_power']}') | float, 0] | max / 1000) | round(3) }}}}",
            "{{ " + _numeric(e["house_power"]) + " }}",
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

    solar_today = e["solar_today_energy"]
    imp_total, exp_total = e["grid_import_total"], e["grid_export_total"]
    meters = {
        "import": ("home_grid_import_meter", "Home grid import meter", imp_total),
        "export": ("home_grid_export_meter", "Home grid export meter", exp_total),
        "consumption": (
            "home_consumption_meter",
            "Home consumption meter",
            "sensor.home_house_energy_total",
        ),
    }
    meter_id = {k: f"sensor.{v[0]}" for k, v in meters.items()}
    midnight = "now().replace(hour=0, minute=0, second=0, microsecond=0)"

    def covers_today(meter):
        """The meter was reset at THIS local midnight (+/-10 min), so it holds the whole local day.

        A meter created mid-day, a missed midnight reset (stale previous-day reset) or a clock jump
        all fail this test. ``now()`` is local time, so DST changes do not matter at midnight.
        """
        last = f"(state_attr('{meter}', 'last_reset') | as_datetime(none))"
        return (
            f"({last} is not none and {last} >= {midnight} - timedelta(minutes=10) "
            f"and {last} <= {midnight} + timedelta(minutes=10))"
        )

    def fresh(entity, seconds):
        return (
            f"(states['{entity}'] is not none "
            f"and (now() - states['{entity}'].last_reported).total_seconds() < {seconds})"
        )

    def counter_ok(entity):
        """A genuine, current kWh counter: numeric, kWh, total class, non-negative and fresh."""
        return (
            f"(is_number(states('{entity}')) "
            f"and state_attr('{entity}', 'unit_of_measurement') == 'kWh' "
            f"and state_attr('{entity}', 'state_class') in ['total', 'total_increasing'] "
            f"and states('{entity}') | float >= 0 and {fresh(entity, COUNTER_FRESH_SECONDS)})"
        )

    def daily_ok(meter):
        return (
            f"(is_number(states('{meter}')) and states('{meter}') | float >= 0 "
            f"and states('{meter}') | float < {DAILY_CAP_KWH} "
            f"and state_attr('{meter}', 'last_valid_state') is not none)"
        )

    solar_ok = (
        f"(is_number(states('{solar_today}')) "
        f"and state_attr('{solar_today}', 'unit_of_measurement') == 'kWh' "
        f"and states('{solar_today}') | float >= 0 and states('{solar_today}') | float < {DAILY_CAP_KWH} "
        f"and {fresh(solar_today, COUNTER_FRESH_SECONDS)})"
    )
    sources_ok = " and ".join([solar_ok, counter_ok(imp_total), counter_ok(exp_total)])
    meters_full_day = " and ".join(
        [
            daily_ok(meter_id["import"]),
            daily_ok(meter_id["export"]),
            covers_today(meter_id["import"]),
            covers_today(meter_id["export"]),
        ]
    )
    battery_ok = "true" if mapping["energy"]["battery_present"] is False else "false"
    consistent = f"states('{meter_id['export']}') | float <= states('{solar_today}') | float"
    status_state = (
        f"{{% if not {battery_ok} %}}battery_unconfirmed"
        f"{{% elif not ({sources_ok}) %}}sources_unavailable"
        f"{{% elif not ({meters_full_day}) %}}collecting_first_day"
        f"{{% elif not ({consistent}) %}}inconsistent"
        "{% else %}ready{% endif %}"
    )
    ready = "is_state('sensor.home_energy_status', 'ready')"
    sensors += [
        tmpl(
            "Home energy status",
            "home_energy_status",
            status_state,
            icon="mdi:chart-timeline-variant",
            attributes={
                "meaning": (
                    "ready = full-day figures valid; collecting_first_day = the daily meters do not "
                    "yet cover a whole local day; sources_unavailable = an inverter counter is "
                    "missing, stale or not kWh; inconsistent = export exceeds generation; "
                    "battery_unconfirmed = battery_present is not confirmed false in the mapping"
                )
            },
        ),
        tmpl(
            "Home grid import today",
            "home_grid_import_today",
            f"{{{{ states('{meter_id['import']}') | float | round(3) }}}}",
            "{{ " + ready + " }}",
            "kWh",
            "energy",
            icon="mdi:transmission-tower-import",
            attributes={"basis": "daily utility meter on the inverter import counter (measured)"},
        ),
        tmpl(
            "Home grid export today",
            "home_grid_export_today",
            f"{{{{ states('{meter_id['export']}') | float | round(3) }}}}",
            "{{ " + ready + " }}",
            "kWh",
            "energy",
            icon="mdi:transmission-tower-export",
            attributes={"basis": "daily utility meter on the inverter export counter (measured)"},
        ),
        tmpl(
            "Home consumption today",
            "home_consumption_today",
            f"{{{{ (states('{solar_today}') | float + states('{meter_id['import']}') | float - states('{meter_id['export']}') | float) | round(3) }}}}",
            "{{ " + ready + " }}",
            "kWh",
            "energy",
            icon="mdi:home-lightning-bolt",
            attributes={
                "basis": "energy balance: solar + import - export (battery-free), all inverter counters"
            },
        ),
        tmpl(
            "Home consumption estimate today",
            "home_consumption_estimate_today",
            f"{{{{ states('{meter_id['consumption']}') | float | round(3) }}}}",
            "{{ "
            + " and ".join(
                [
                    daily_ok(meter_id["consumption"]),
                    covers_today(meter_id["consumption"]),
                    fresh(e["house_power"], POWER_FRESH_SECONDS),
                ]
            )
            + " }}",
            "kWh",
            "energy",
            icon="mdi:home-lightning-bolt-outline",
            attributes={
                "basis": "integrated estimate from sampled house power; outages leave gaps (not a measured total)"
            },
        ),
        tmpl(
            "Home solar used directly today",
            "home_solar_used_directly_today",
            f"{{{{ (states('{solar_today}') | float - states('{meter_id['export']}') | float) | round(3) }}}}",
            "{{ " + ready + " }}",
            "kWh",
            "energy",
            icon="mdi:home-battery",
            attributes={"basis": "solar generated minus exported (battery-free)"},
        ),
        tmpl(
            "Home self-consumption today",
            "home_self_consumption_today",
            f"{{{{ (((states('{solar_today}') | float - states('{meter_id['export']}') | float) / states('{solar_today}') | float * 100) | round(0)) }}}}",
            "{{ " + ready + f" and states('{solar_today}') | float >= 1.0 }}}}",
            "%",
            None,
            "measurement",
            "mdi:percent-circle",
            attributes={"basis": "direct use / solar generated; needs at least 1 kWh generated"},
        ),
    ]
    utility_meter = {
        meters[k][0]: {
            "name": meters[k][1],
            "unique_id": meters[k][0],
            "source": meters[k][2],
            "cycle": "daily",
        }
        for k in meters
    }
    return {
        "utility_meter": utility_meter,
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
        "# Home dashboard (generated by tools/build_home_dashboard.py; edit the mapping file instead)\n"
        f"# Requires the dependency-free custom card {CARD_RESOURCE}\n"
        "# (homeowner/www/thermowatt-power-flow-card.js). Use home_no_custom_card.yaml without it.\n"
    ),
    "native": "# Home dashboard, native power-flow fallback (generated by tools/build_home_dashboard.py)\n",
    "package": (
        "# Optional Home Assistant package (generated by tools/build_home_dashboard.py).\n"
        "# Save as /config/packages/thermowatt_home_energy.yaml. Existing unique IDs are unchanged, so it\n"
        "# upgrades in place; the daily meters and the integration sensor keep their accumulated data.\n"
        "# Daily figures stay 'collecting' until the meters cover a whole local day.\n"
    ),
}


class _PlainDumper(yaml.SafeDumper):
    """No YAML anchors/aliases: shared card dicts are written out in full (clearer to paste/edit)."""

    def ignore_aliases(self, data):
        return True


def dump(data, key):
    body = yaml.dump(data, Dumper=_PlainDumper, allow_unicode=True, sort_keys=False, width=95)
    return HEADERS[key] + body


def render_profile(mapping_path):
    mapping = load_mapping(mapping_path)
    home, _ = build_dashboard(True, mapping)
    native, _ = build_dashboard(False, mapping)
    return {
        "home": dump(home, "home"),
        "native": dump(native, "native"),
        "package": dump(build_package(mapping), "package"),
    }


def render_all():
    """{relative output path: content} for the homeowner and generic profiles."""
    out = {}
    for profile, mapping_path, prefix in (
        ("homeowner", MAPPING, "homeowner/"),
        ("generic", GENERIC_MAPPING, "homeowner/generic/"),
    ):
        rendered = render_profile(mapping_path)
        for key, content in rendered.items():
            if profile == "generic" and key == "native":
                continue
            out[f"{prefix}{OUTPUT_FILES[key]}"] = content
    return out


def report(mapping_path=None):
    mapping = load_mapping(mapping_path)
    _, ent = build_dashboard(True, mapping)
    _, native_ent = build_dashboard(False, mapping)
    used = {**ent.used, **native_ent.used}
    print("Entities used by the Home dashboard:")
    for eid, source in sorted(used.items()):
        print(f"  {eid}  [{source}]")
    print("\nMappings (status):")
    for group in ("energy", "weather", "lights", "doors"):
        node = mapping[group]
        nodes = (
            {group: node}
            if "entity" in node
            else {f"{group}.{k}": v for k, v in node.items() if isinstance(v, dict)}
        )
        for name, value in nodes.items():
            print(f"  {name}: {value['entity'] or '(unmapped)'}  [{value.get('status', '')}]")
    print("  energy.battery_present:", mapping["energy"]["battery_present"])
    print("\nUnresolved mappings:", ", ".join(sorted(set(ent.unresolved))) or "none")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--mapping", help="build only this mapping file")
    parser.add_argument("--out-dir", help="with --mapping: where to write the three outputs")
    args = parser.parse_args()
    if args.report:
        report(args.mapping)
        return
    if args.mapping:
        out_dir = Path(args.out_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        for key, content in render_profile(args.mapping).items():
            (out_dir / OUTPUT_FILES[key]).write_text(content, encoding="utf-8", newline="\n")
        return
    for relative, content in render_all().items():
        target = ROOT / relative
        if args.check:
            assert target.read_text(encoding="utf-8") == content, f"{relative} is stale"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
