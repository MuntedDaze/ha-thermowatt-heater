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
import datetime
import importlib
import json
import math
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

ENERGY_MAP = ROOT / "energy_monitoring/entity_map.yaml"
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
RESET_EARLY_SECONDS = 30  # a scheduled utility-meter reset fires at 00:00:00; allow clock skew only
RESET_LATE_SECONDS = 120
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


def settings_tile(entity, label, path, columns=6):
    """A compact navigation tile. A tile card requires an entity, so each integration's own
    always-present status entity anchors it (its state is hidden; the tile only navigates)."""
    return {
        "type": "tile",
        "entity": entity,
        "hide_state": True,
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
        ids = package_ids()
        ent.used[ids["used_today"]] = ent.used[ids["status"]] = "home_energy_package"
        return {
            "type": "custom:thermowatt-power-flow-card",
            "solar_entity": ent.energy("solar_power"),
            "house_entity": ent.energy("house_power"),
            "grid_entity": ent.energy("grid_power"),
            "grid_export_positive": bool(ent.mapping["energy"]["grid_export_positive"]),
            "today": {
                "solar": ent.energy("solar_today_energy"),
                "import": ent.energy("grid_import_total"),
                "export": ent.energy("grid_export_total"),
                # solar used directly: the package figure, shown only while its daily meters are complete
                "used": ids["used_today"],
                "status": ids["status"],
            },
            **(
                {"timezone": str(ent.mapping["device_energy"]["timezone"])}
                if (ent.mapping.get("device_energy") or {}).get("timezone")
                else {}
            ),
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
Water temperature · {{ ('updated ' ~ (age | int(0)) ~ ' min ago') if age not in bad else 'age unknown' }} · last poll {{ hhmm(last) if last not in bad else '—' }}

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
        "12-hour 62 °C override: ON",
        "mdi:water-boiler",
        "blue",
        tap=press(cancel, "Cancel the 12-hour 62 °C override? Normal automatic control resumes."),
        hide_state=True,
    )
    off_card = tile(
        mode,
        "12-hour 62 °C override: OFF",
        "mdi:water-boiler-off",
        "grey",
        tap=press(
            start,
            "Start the 12-hour 62 °C override? It may heat during peak hours; controller safeguards still apply.",
        ),
        hide_state=True,
    )
    unknown = tile(
        mode,
        "12-hour 62 °C override: status unknown",
        "mdi:water-boiler-alert",
        "grey",
        hide_state=True,
    )
    return [
        conditional(when(mode, "guest"), on_card, columns),
        conditional(
            when(mode, not_states=("guest", "unavailable", "unknown", "holiday", "disabled")),
            off_card,
            columns,
        ),
        conditional([any_state(mode, ("unavailable", "unknown"))], unknown, columns),
        conditional(
            [any_state(mode, ("holiday", "disabled"))],
            tile(
                mode,
                "12-hour 62 °C override: not available now",
                "mdi:water-boiler-off",
                "grey",
                hide_state=True,
            ),
            columns,
        ),
    ]


def automatic_toggle(ent, columns=12):
    """Automatic heater control: the integration's own master switch (it refuses ON until commissioned)."""
    auto = ent.thermowatt("switch", "Automatic heater control")
    return [
        conditional(
            when(auto, "on"),
            tile(
                auto,
                "Automatic heater control: ON",
                "mdi:robot",
                "blue",
                tap=call(
                    "switch.turn_off",
                    auto,
                    "Turn automatic heater control OFF? Thermowatt stops sending commands to the "
                    "heater (the heater keeps its current mode) until you turn it on again.",
                ),
                hide_state=True,
            ),
            columns,
        ),
        conditional(
            when(auto, "off"),
            tile(
                auto,
                "Automatic heater control: OFF",
                "mdi:robot-off",
                "grey",
                tap=call(
                    "switch.turn_on",
                    auto,
                    "Turn automatic heater control ON? Thermowatt will start managing the heater. "
                    "It refuses to start until commissioning is complete.",
                ),
                hide_state=True,
            ),
            columns,
        ),
        conditional(
            [any_state(auto, ("unavailable", "unknown"))],
            tile(
                auto,
                "Automatic heater control: status unknown",
                "mdi:robot-confused",
                "grey",
                hide_state=True,
            ),
            columns,
        ),
    ]


def solar_boost_toggle(ent, columns=12):
    """Optional solar boost on/off. The integration locks this setting while automatic control is on,
    so then the tile is inert and says why; it is never a way to force the heater on or off."""
    auto = ent.thermowatt("switch", "Automatic heater control")
    boost = ent.thermowatt("switch", "Enable optional solar boost")
    locked = "locked: automatic control is on"
    cards = []
    for boost_state, label in (("on", "enabled"), ("off", "disabled")):
        cards.append(
            conditional(
                [*when(auto, "on"), *when(boost, boost_state)],
                tile(
                    boost,
                    f"Optional solar boost: {label} ({locked})",
                    "mdi:solar-power-variant"
                    if boost_state == "on"
                    else "mdi:solar-power-variant-outline",
                    "grey",
                    tap={"action": "none"},
                    hide_state=True,
                ),
                columns,
            )
        )
    cards.append(
        conditional(
            [*when(auto, "off"), *when(boost, "on")],
            tile(
                boost,
                "Optional solar boost: enabled",
                "mdi:solar-power-variant",
                "orange",
                tap=call(
                    "switch.turn_off",
                    boost,
                    "Disable optional solar boost? This only stops extra solar storage; it does not "
                    "turn the heater on or off.",
                ),
                hide_state=True,
            ),
            columns,
        )
    )
    cards.append(
        conditional(
            [*when(auto, "off"), *when(boost, "off")],
            tile(
                boost,
                "Optional solar boost: disabled",
                "mdi:solar-power-variant-outline",
                "grey",
                tap=call(
                    "switch.turn_on",
                    boost,
                    "Enable optional solar boost? It does not start boosting by itself: automatic "
                    "control and every safety check still apply.",
                ),
                hide_state=True,
            ),
            columns,
        )
    )
    cards.append(
        conditional(
            [
                {
                    "condition": "or",
                    "conditions": [
                        {"condition": "state", "entity": e, "state": st}
                        for e in (auto, boost)
                        for st in ("unavailable", "unknown")
                    ],
                }
            ],
            tile(
                boost,
                "Optional solar boost: status unknown",
                "mdi:solar-power-variant-outline",
                "grey",
                hide_state=True,
            ),
            columns,
        )
    )
    return cards


def hot_water_controls(ent, columns=12):
    """Everyday hot-water controls, all through existing Thermowatt entities (no new control path)."""
    return [
        heading("Everyday controls", "mdi:tune-variant", "subtitle"),
        *automatic_toggle(ent, columns),
        *solar_boost_toggle(ent, columns),
        *override_toggle(ent, columns),
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
def bathroom_card(ent, name, columns=6, controls_only=False, towel_controls=True):
    hum = ent.tapo("sensor", name, "Humidity")
    temp = ent.tapo("sensor", name, "Temperature")
    fan = ent.tapo("binary_sensor", name, "Fan Running")
    fan_switch = ent.tapo("switch", name, "Fan Manual Override")
    towel = ent.tapo("binary_sensor", name, "Towel Rail Heating")
    towel_switch = ent.tapo("switch", name, "Towel Rail Manual Override")
    ent.used[ent.tapo("sensor", name, "Towel Rail Status")] = "tapo_smart_controller"

    cols = 12 if controls_only else None

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
                    columns=cols,
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
                    columns=cols,
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
                    columns=cols,
                ),
            ),
            conditional(
                [*when(switch, not_states=("on",)), unknown_any],
                tile(
                    entity,
                    f"{label}: status unknown",
                    unknown,
                    "grey",
                    content="summary",
                    columns=cols,
                ),
            ),
        ]

    if controls_only:
        return [
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
            *(
                toggle(
                    towel,
                    towel_switch,
                    "Towel rail",
                    ("mdi:radiator", "mdi:radiator", "mdi:radiator-off", "mdi:radiator-disabled"),
                    "Request one towel-rail drying cycle? It only heats during off-peak.",
                )
                if towel_controls
                else [  # Home: the towel rail is status only (no manual request from the main screen)
                    tile(
                        towel,
                        "Towel rail",
                        "mdi:radiator",
                        "orange",
                        content="summary",
                        tap={"action": "none"},
                    )
                ]
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
{% macro dayhm(v) -%}{% set d = as_datetime(v, none) %}{{ as_local(d).strftime('%d %b %H:%M') if d is not none else '' }}{%- endmacro %}
{% set cloud = {'ok': 'Connected', 'disabled': 'Disabled', 'auth_locked': 'Sign-in locked: check the Thermann app', 'quota_limited': 'Request limit reached', 'backoff': 'Backing off after an error', 'unavailable': 'Unavailable'} %}
{% set sup = {'observing': 'Observing: checking the heater before acting', 'parked': 'Heater confirmed off', 'baseline_45': 'Holding the 45 °C baseline', 'normal_storage_62': 'Holding 62 °C storage', 'storage_70': 'Holding the 70 °C boost', 'change_requested': 'A change is needed but is waiting for conditions', 'confirming': 'Command sent: waiting for confirmation', 'owner_override': 'On hold: you pressed Hold', 'disabled': 'Automatic control is off', 'fault_locked': 'Fault: needs acknowledgement'} %}
{% set tariff = {'off_peak': 'Off-peak', 'peak': 'Peak', 'shoulder': 'Shoulder', 'unknown': 'Unknown'} %}
{% set fault = states('@@FAULT@@') %}
{% set ack_fault = state_attr('@@FAULT@@', 'last_acknowledged_fault') %}
{% set ack_at = state_attr('@@FAULT@@', 'last_acknowledged_at') %}
{% set has_fault = fault not in ['none', 'None', '', 'unknown', 'unavailable'] %}
{% set c = states('@@CLOUD@@') %}
{% set s = states('@@SUP@@') %}
{% set t = states('@@TARIFF_T@@') %}
{% set w = states('@@WARN@@') %}
**Thermowatt**
- Cloud connection: {{ cloud.get(c, nice(c)) if c not in bad else 'Unknown' }}
- Heating control problem: {% if fault in ['none', 'None', ''] %}No problems detected{% elif fault in ['unknown', 'unavailable'] %}Unknown{% else %}{{ nice(fault) }}{% endif %}
- Supervision: {% if s == 'disabled' and has_fault %}Automatic control is off (fault needs acknowledgement){% else %}{{ sup.get(s, nice(s)) if s not in bad else 'Unknown' }}{% endif %}
{% if not has_fault and ack_fault and ack_fault not in ['none', 'None', '', 'unknown', 'unavailable'] -%}
- Last acknowledged fault: {{ nice(ack_fault) }}{% if dayhm(ack_at) %} ({{ dayhm(ack_at) }}){% endif %}
{% endif %}
**Tapo Smart Controller**
- Health: {% if is_state('@@HEALTH@@', 'on') %}Problem reported{% elif is_state('@@HEALTH@@', 'off') %}No problems detected{% else %}Unknown{% endif %}{% if w not in bad %} ({{ w }} active warnings){% endif %}
- Mode: {% if is_state('@@SIM@@', 'on') %}Simulation: no devices are switched{% elif is_state('@@SIM@@', 'off') %}Live control{% else %}Unknown{% endif %}
- Tariff read by the controller: {{ tariff.get(t, nice(t)) if t not in bad else 'Unknown' }}
"""


def fault_acknowledge_tile(ent, columns=12):
    """Visible only when an active unacknowledged controller fault exists."""
    fault = ent.thermowatt("sensor", "Controller fault")
    ack = ent.thermowatt("button", "Acknowledge controller fault")
    return conditional(
        when(fault, not_states=("none", "unknown", "unavailable")),
        tile(
            fault,
            "Acknowledge controller fault",
            "mdi:alert-circle-check-outline",
            "red",
            tap=press(
                ack,
                "Acknowledge controller fault? Check the official Thermann app first. "
                "The controller will wait for a fresh heater status read before acting "
                "and never retries an uncertain command.",
            ),
            hide_state=True,
        ),
        columns,
    )


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


DIAGNOSTICS_TEMPLATE = """{% set bad = @@BAD@@ %}
{% macro nice(v) -%}{{ v | replace('_', ' ') | capitalize }}{%- endmacro %}
{% macro hhmm(v) -%}{% set d = as_datetime(v, none) %}{{ as_local(d).strftime('%H:%M') if d is not none else '—' }}{%- endmacro %}
{% set plan = states('@@PLAN@@') %}
{% set nxt = states('@@NEXT@@') %}
{% set start = states('@@START@@') %}
{% set boost = states('@@BOOST@@') %}
{% set why = states('@@WHY@@') %}
{% set last = states('@@LAST@@') %}
{% set reqs = states('@@REQS@@') %}
- **Plan** {{ plan if plan not in bad else '—' }}
- **Next action** {{ nice(nxt) if nxt not in bad else '—' }}
- **Next heating start** {{ hhmm(start) if start not in bad else 'none planned' }}
- **Solar boost** {{ nice(boost) if boost not in bad else '—' }}
- **Why this decision** {{ nice(why) if why not in bad else '—' }}
- **Last command** {{ nice(last) if last not in bad else '—' }}
- **Cloud requests in 24 h** {{ reqs if reqs not in bad else '—' }}
"""


def diagnostics_summary(ent, columns=12):
    text = (
        DIAGNOSTICS_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@PLAN@@", ent.thermowatt("sensor", "Current heating plan"))
        .replace("@@NEXT@@", ent.thermowatt("sensor", "Next intended action"))
        .replace("@@START@@", ent.thermowatt("sensor", "Next heating start"))
        .replace("@@BOOST@@", ent.thermowatt("sensor", "Solar boost status"))
        .replace("@@WHY@@", ent.thermowatt("sensor", "Why Thermowatt made this decision"))
        .replace("@@LAST@@", ent.thermowatt("sensor", "Last command result"))
        .replace("@@REQS@@", ent.thermowatt("sensor", "Cloud requests in last 24 hours"))
    )
    return note(text, columns)


# ------------------------------------------------------------------ designed (custom-card) panels
PANEL_CARD = "custom:thermowatt-panel-card"
LIGHTS_CARD = "custom:thermowatt-lights-card"


def _js(value):
    """A Jinja string literal (JSON quoting is valid Jinja)."""
    return json.dumps(value, ensure_ascii=False)


def panel_card(template=None, model=None, columns=12, **extra):
    card = {"type": PANEL_CARD, **span(columns)}
    if template:
        card["template"] = template
    if model:
        card["model"] = model
    card.update(extra)
    return card


_PANEL_MACROS = """\
{% set bad = @@BAD@@ %}
{% macro nice(v) -%}{{ v | replace('_', ' ') | capitalize }}{%- endmacro %}
{% macro hhmm(v) -%}{% set d = as_datetime(v, none) %}{{ as_local(d).strftime('%H:%M') if d is not none else '—' }}{%- endmacro %}
"""

HOT_WATER_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
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
{% set target = ('Target ' ~ ('%d' | format(tgt_r | float(0) | round(0)) ) ~ ' °C') if tgt_r not in bad else none %}
{% set desired = (' · desired ' ~ ('%d' | format(tgt_d | float(0) | round(0))) ~ ' °C') if (tgt_d not in bad and tgt_r not in bad and (tgt_d | float(0) | round(0)) != (tgt_r | float(0) | round(0))) else '' %}
{% set stats = [
  {'label': 'Heater', 'value': nice(mode_r) if mode_r not in bad else none, 'detail': (target ~ desired) if target else none},
  {'label': 'Tariff', 'value': tariff_names.get(tariff, nice(tariff)) if tariff not in bad else none, 'tone': 'warn' if tariff == 'peak' else ('ok' if tariff == 'off_peak' else 'idle')},
  {'label': 'Solar boost', 'value': nice(boost) if boost not in bad else none},
  {'label': 'Next', 'value': nice(nxt) if nxt not in bad else none, 'detail': ('Next poll ' ~ hhmm(poll)) if poll not in bad else none}
] %}
{% if ctrl == 'guest' and ends not in bad %}{% set left = ((as_datetime(ends, none) - now()).total_seconds() // 60) | int(0) if as_datetime(ends, none) is not none else none %}{% set stats = stats + [{'label': '12 h override ends', 'value': hhmm(ends), 'tone': 'warn', 'detail': ((((left // 60) | string) ~ ' h ' ~ ((left % 60) | string) ~ ' min left') if left is not none and left > 0 else none)}] %}{% endif %}
{{ {
  'title': 'Hot water',
  'icon': 'mdi:water-boiler',
  'badge': {'text': ctrl_names.get(ctrl, nice(ctrl)) if ctrl not in bad else 'Status unknown', 'tone': 'warn' if ctrl == 'guest' else ('idle' if ctrl in bad else 'info')},
  'hero': {'label': 'Water temperature', 'value': ('%.1f' | format(t | float(0))) if t not in bad else none, 'unit': '°C',
           'caption': (('Updated ' ~ (age | int(0)) ~ ' min ago') if age not in bad else 'Age unknown') ~ ' · last poll ' ~ (hhmm(last) if last not in bad else '—')},
  'stats': stats,
  'columns': 2
} | tojson }}
"""
)


def hot_water_panel(ent, columns=12):
    last_poll = integration_config.DEFAULT_SOURCES["last_poll"]
    ent.used[last_poll] = "thermann_bridge"
    template = (
        HOT_WATER_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
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
    return panel_card(template, columns)


DIAGNOSTICS_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
{% set plan = states('@@PLAN@@') %}
{% set nxt = states('@@NEXT@@') %}
{% set start = states('@@START@@') %}
{% set boost = states('@@BOOST@@') %}
{% set why = states('@@WHY@@') %}
{% set last = states('@@LAST@@') %}
{% set reqs = states('@@REQS@@') %}
{{ {
  'title': 'Plan and diagnostics',
  'icon': 'mdi:text-box-search-outline',
  'rows': [
    {'label': 'Plan', 'value': plan if plan not in bad else none},
    {'label': 'Next action', 'value': nice(nxt) if nxt not in bad else none},
    {'label': 'Next heating start', 'value': hhmm(start) if start not in bad else 'none planned'},
    {'label': 'Solar boost', 'value': nice(boost) if boost not in bad else none},
    {'label': 'Why this decision', 'value': nice(why) if why not in bad else none},
    {'label': 'Last command', 'value': nice(last) if last not in bad else none},
    {'label': 'Cloud requests in 24 h', 'value': reqs if reqs not in bad else none}
  ]
} | tojson }}
"""
)


def diagnostics_panel(ent, columns=12):
    template = (
        DIAGNOSTICS_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@PLAN@@", ent.thermowatt("sensor", "Current heating plan"))
        .replace("@@NEXT@@", ent.thermowatt("sensor", "Next intended action"))
        .replace("@@START@@", ent.thermowatt("sensor", "Next heating start"))
        .replace("@@BOOST@@", ent.thermowatt("sensor", "Solar boost status"))
        .replace("@@WHY@@", ent.thermowatt("sensor", "Why Thermowatt made this decision"))
        .replace("@@LAST@@", ent.thermowatt("sensor", "Last command result"))
        .replace("@@REQS@@", ent.thermowatt("sensor", "Cloud requests in last 24 hours"))
    )
    return panel_card(template, columns)


SYSTEM_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
{% macro dayhm(v) -%}{% set d = as_datetime(v, none) %}{{ as_local(d).strftime('%d %b %H:%M') if d is not none else '' }}{%- endmacro %}
{% set cloud = {'ok': 'Connected', 'disabled': 'Disabled', 'auth_locked': 'Sign-in locked: check the Thermann app', 'quota_limited': 'Request limit reached', 'backoff': 'Backing off after an error', 'unavailable': 'Unavailable'} %}
{% set sup = {'observing': 'Observing: checking the heater before acting', 'parked': 'Heater confirmed off', 'baseline_45': 'Holding the 45 °C baseline', 'normal_storage_62': 'Holding 62 °C storage', 'storage_70': 'Holding the 70 °C boost', 'change_requested': 'A change is needed but is waiting for conditions', 'confirming': 'Command sent: waiting for confirmation', 'owner_override': 'On hold: you pressed Hold', 'disabled': 'Automatic control is off', 'fault_locked': 'Fault: needs acknowledgement'} %}
{% set tariff = {'off_peak': 'Off-peak', 'peak': 'Peak', 'shoulder': 'Shoulder', 'unknown': 'Unknown'} %}
{% set fault = states('@@FAULT@@') %}
{% set ack_fault = state_attr('@@FAULT@@', 'last_acknowledged_fault') %}
{% set ack_at = state_attr('@@FAULT@@', 'last_acknowledged_at') %}
{% set has_fault = fault not in ['none', 'None', '', 'unknown', 'unavailable'] %}
{% set c = states('@@CLOUD@@') %}
{% set s = states('@@SUP@@') %}
{% set t = states('@@TARIFF_T@@') %}
{% set w = states('@@WARN@@') %}
{% set good_sup = ['observing', 'parked', 'baseline_45', 'normal_storage_62', 'storage_70'] %}
{% set wait_sup = ['change_requested', 'confirming', 'owner_override', 'disabled'] %}
{% set tw_rows = [
  {'label': 'Cloud connection', 'value': cloud.get(c, nice(c)) if c not in bad else 'Unknown',
   'tone': 'ok' if c == 'ok' else ('warn' if c in ['disabled', 'quota_limited', 'backoff'] else ('bad' if c in ['auth_locked', 'unavailable'] else 'idle'))},
  {'label': 'Heating control problem', 'value': 'No problems detected' if fault in ['none', 'None', ''] else ('Unknown' if fault in ['unknown', 'unavailable'] else nice(fault)),
   'tone': 'ok' if fault in ['none', 'None', ''] else ('idle' if fault in ['unknown', 'unavailable'] else 'bad')},
  {'label': 'Supervision',
   'value': 'Automatic control is off (fault needs acknowledgement)' if (s == 'disabled' and has_fault) else (sup.get(s, nice(s)) if s not in bad else 'Unknown'),
   'tone': 'bad' if (s == 'fault_locked' or (s == 'disabled' and has_fault)) else ('ok' if s in good_sup else ('warn' if s in wait_sup else 'idle'))}
] %}
{% if not has_fault and ack_fault and ack_fault not in ['none', 'None', '', 'unknown', 'unavailable'] %}
  {% set ack_time = dayhm(ack_at) %}
  {% set tw_rows = tw_rows + [{'label': 'Last acknowledged fault', 'value': nice(ack_fault) ~ ((' (' ~ ack_time ~ ')') if ack_time else ''), 'tone': 'idle'}] %}
{% endif %}
{{ {
  'title': 'System status',
  'icon': 'mdi:stethoscope',
  'groups': [
    {'title': 'Thermowatt', 'rows': tw_rows},
    {'title': 'Tapo Smart Controller', 'rows': [
      {'label': 'Health', 'value': ('Problem reported' if is_state('@@HEALTH@@', 'on') else ('No problems detected' if is_state('@@HEALTH@@', 'off') else 'Unknown')) ~ ((' (' ~ w ~ ' active warnings)') if w not in bad else ''),
       'tone': 'bad' if is_state('@@HEALTH@@', 'on') else ('ok' if is_state('@@HEALTH@@', 'off') else 'idle')},
      {'label': 'Mode', 'value': 'Simulation: no devices are switched' if is_state('@@SIM@@', 'on') else ('Live control' if is_state('@@SIM@@', 'off') else 'Unknown'),
       'tone': 'warn' if is_state('@@SIM@@', 'on') else ('ok' if is_state('@@SIM@@', 'off') else 'idle')},
      {'label': 'Tariff read by the controller', 'value': tariff.get(t, nice(t)) if t not in bad else 'Unknown'}
    ]}
  ]
} | tojson }}
"""
)


def system_panel(ent, columns=12):
    template = (
        SYSTEM_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@FAULT@@", ent.thermowatt("sensor", "Controller fault"))
        .replace("@@CLOUD@@", ent.thermowatt("sensor", "Cloud health"))
        .replace("@@SUP@@", ent.thermowatt("sensor", "Automatic control state"))
        .replace("@@TARIFF_T@@", ent.tapo("sensor", "Electricity Tariff Status"))
        .replace("@@WARN@@", ent.tapo("sensor", "Active Health Warnings"))
        .replace("@@HEALTH@@", ent.tapo("binary_sensor", "Controller Health Problem"))
        .replace("@@SIM@@", ent.tapo("binary_sensor", "Simulation Mode Active"))
    )
    return panel_card(template, columns)


def settings_panel(ent, columns=12):
    """Navigation to both integrations' own settings pages (static content, no template)."""
    ent.used[ent.thermowatt("sensor", "Automatic control state")] = "thermann_shadow"
    return panel_card(
        model={
            "title": "Settings",
            "icon": "mdi:cog-outline",
            "lines": [
                "Tuning, schedules and diagnostic reports live in the two integrations' own settings pages."
            ],
        },
        columns=columns,
        actions=[
            {
                "label": "Thermowatt settings and diagnostic report",
                "detail": "Hot-water heating, tariff and cloud settings",
                "icon": "mdi:water-boiler",
                "path": THERMOWATT_SETTINGS_PATH,
            },
            {
                "label": "Tapo Smart Controller settings",
                "detail": "Bathroom tuning, towel-rail schedules and relays",
                "icon": "mdi:shower-head",
                "path": TAPO_SETTINGS_PATH,
            },
        ],
    )


BATHROOM_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
{% set h = states('@@HUM@@') %}
{% set t = states('@@TEMP@@') %}
{% set shower = states('@@SHOWER@@') %}
{% set bg = states('@@BG@@') %}
{% set reason = state_attr('@@FANSTATUS@@', 'reason') %}
{% set fan_s = state_attr('@@FAN@@', 'summary') %}
{% set towel_s = state_attr('@@TOWEL@@', 'summary') %}
{% set left = states('@@LEFT@@') %}
{% set waiting = state_attr('@@LEFT@@', 'waiting_for_off_peak') %}
{% set rows = [
  {'label': 'Learned background humidity', 'value': (('%d' | format(bg | float(0) | round(0))) ~ ' %') if bg not in bad else none},
  {'label': 'Fan', 'value': fan_s if fan_s else none, 'tone': 'info' if is_state('@@FAN@@', 'on') else 'idle'},
  {'label': 'Why the fan is in this state', 'value': reason if reason else none},
  {'label': 'Towel rail', 'value': towel_s if towel_s else none, 'tone': 'warn' if is_state('@@TOWEL@@', 'on') else 'idle'},
  {'label': 'Drying time left', 'value': (left ~ (' · waiting for off-peak' if waiting else '')) if left not in bad else none}
] %}
{{ {
  'title': @@NAME@@,
  'icon': 'mdi:shower-head',
  'badge': {'text': 'Shower detected', 'tone': 'info', 'icon': 'mdi:shower'} if shower == 'on' else ({'text': 'No shower detected', 'tone': 'idle'} if shower == 'off' else {'text': 'Shower status unknown', 'tone': 'idle'}),
  'heroes': [
    {'label': 'Humidity', 'value': ('%d' | format(h | float(0) | round(0))) if h not in bad else none, 'unit': '%', 'tone': 'info' if shower == 'on' else 'idle'},
    {'label': 'Temperature', 'value': ('%.1f' | format(t | float(0))) if t not in bad else none, 'unit': '°C'}
  ],
  'groups': [{'title': 'Monitoring', 'rows': rows}] if @@DETAIL@@ else []
} | tojson }}
"""
)


def bathroom_panel(ent, name, columns=12, detail=False):
    template = (
        BATHROOM_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@NAME@@", _js(name))
        .replace("@@HUM@@", ent.tapo("sensor", name, "Humidity"))
        .replace("@@TEMP@@", ent.tapo("sensor", name, "Temperature"))
        .replace("@@SHOWER@@", ent.tapo("binary_sensor", name, "Shower Detected"))
        .replace("@@BG@@", ent.tapo("sensor", name, "Background Humidity"))
        .replace("@@FANSTATUS@@", ent.tapo("sensor", name, "Fan Status"))
        .replace("@@FAN@@", ent.tapo("binary_sensor", name, "Fan Running"))
        .replace("@@TOWEL@@", ent.tapo("binary_sensor", name, "Towel Rail Heating"))
        .replace("@@LEFT@@", ent.tapo("sensor", name, "Towel Rail Remaining Time"))
        .replace("@@DETAIL@@", "true" if detail else "false")
    )
    return panel_card(template, columns)


def bathroom_setting_tiles(ent, name, columns=12):
    """The two per-bathroom settings as the Tapo integration's own number entities (tap to type a value).

    They are views of the integration's saved options (the same values Configure edits), not copies."""
    fan_minutes = ent.tapo("number", name, "Manual Fan Duration")
    towel_hours = ent.tapo("number", name, "Towel Drying Duration")
    return [
        tile(
            fan_minutes,
            "Run fan length (5-120 min): tap to change",
            "mdi:fan-clock",
            "blue",
            content="state",
            columns=columns,
        ),
        tile(
            towel_hours,
            "Towel drying per shower (1-12 h): tap to change",
            "mdi:radiator",
            "orange",
            content="state",
            columns=columns,
        ),
    ]


DOORS_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
{% set gp = states('@@GARAGE_POS@@') %}
{% set gs = state_attr('@@GARAGE_STATUS@@', 'summary') %}
{% set fo = states('@@FRONT_OPEN@@') %}
{% set fs = state_attr('@@FRONT_STATUS@@', 'summary') %}
{% macro tail(v) -%}{{ v.split(' — ')[1] if v and ' — ' in v else '' }}{%- endmacro %}
{{ {
  'title': 'Doors',
  'icon': 'mdi:shield-home',
  'badge': {'text': 'Monitoring only', 'tone': 'idle'},
  'stats': [
    {'label': 'Garage door', 'value': gp if gp in ['Closed', 'Not closed'] else 'Unknown',
     'tone': 'ok' if gp == 'Closed' else ('warn' if gp == 'Not closed' else 'idle'), 'detail': tail(gs) or none},
    {'label': 'Front door', 'value': 'Open' if fo == 'on' else ('Closed' if fo == 'off' else 'Unknown'),
     'tone': 'warn' if fo == 'on' else ('ok' if fo == 'off' else 'idle'), 'detail': tail(fs) or none}
  ],
  'columns': 2,
  'lines': [@@LINES@@]
} | tojson }}
"""
)

DOORS_NOTE = (
    "Monitoring only: no garage Open/Close/Stop and no lock controls. The garage is "
    "operated by its physical Tapo button, and a closed door contact does not mean "
    "the front door is locked."
)


def doors_panel(ent, detailed=False, columns=12):
    template = (
        DOORS_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@GARAGE_POS@@", ent.tapo("sensor", "Garage Door Position"))
        .replace("@@GARAGE_STATUS@@", ent.tapo("sensor", "Garage Door Status"))
        .replace("@@FRONT_OPEN@@", ent.tapo("binary_sensor", "Front Door Open"))
        .replace("@@FRONT_STATUS@@", ent.tapo("sensor", "Front Door Lock Status"))
        .replace("@@LINES@@", _js(DOORS_NOTE) if detailed else "")
    )
    return panel_card(template, columns)


ENERGY_PANEL_TEMPLATE = (
    _PANEL_MACROS
    + """\
{% set s = states('@@STATUS@@') %}
{% macro kwh(e) -%}{{ ('%.2f' | format(states(e) | float(0)) ~ ' kWh') if is_number(states(e)) else '—' }}{%- endmacro %}
{% set figures = [
  {'label': 'Household today', 'value': kwh('@@CONSUMPTION@@'), 'tone': 'info'},
  {'label': 'Solar used directly', 'value': kwh('@@USED@@'), 'tone': 'ok'},
  {'label': 'Self-consumption', 'value': (('%d' | format(states('@@SELF@@') | float(0))) ~ ' %') if is_number(states('@@SELF@@')) else '—', 'tone': 'ok'}
] %}
{% set meters = [
  {'label': 'Grid import since the meter started', 'value': kwh('@@IMPORT_METER@@')},
  {'label': 'Grid export since the meter started', 'value': kwh('@@EXPORT_METER@@')},
  {'label': 'Household, integrated from power (estimate)', 'value': kwh('@@ESTIMATE@@')}
] %}
{% set lines = {
  'collecting_first_day': 'Household, direct-use and self-consumption appear once the daily meters cover a full day (after the next midnight). Solar, import and export are shown from existing statistics.',
  'sources_unavailable': 'Check the inverter integration; figures are withheld, not zero.',
  'inconsistent': 'Daily counters disagree (export exceeds generation); figures are withheld until they agree.',
  'battery_unconfirmed': 'Set battery_present: false in the mapping if there is no battery.'
} %}
{% set badges = {
  'ready': {'text': 'Complete day', 'tone': 'ok'},
  'collecting_first_day': {'text': 'Collecting daily data', 'tone': 'info'},
  'sources_unavailable': {'text': 'Readings unavailable', 'tone': 'bad'},
  'inconsistent': {'text': 'Counters disagree', 'tone': 'bad'},
  'battery_unconfirmed': {'text': 'Battery not confirmed', 'tone': 'warn'}
} %}
{{ {
  'title': "Today's energy",
  'icon': 'mdi:chart-bar',
  'badge': badges.get(s, {'text': 'Status unknown', 'tone': 'idle'}),
  'stats': figures if s == 'ready' else [],
  'columns': 3,
  'groups': [] if s == 'ready' else [{'title': 'Daily meters (partial on the day installed)', 'rows': meters}],
  'lines': [lines[s]] if s in lines else []
} | tojson }}
"""
)


def energy_panel_card(ent, columns=12):
    ids = package_ids()
    for value in ids.values():
        ent.used[value] = "home_energy_package"
    template = (
        ENERGY_PANEL_TEMPLATE.replace("@@BAD@@", BAD)
        .replace("@@STATUS@@", ids["status"])
        .replace("@@CONSUMPTION@@", ids["consumption_today"])
        .replace("@@USED@@", ids["used_today"])
        .replace("@@SELF@@", ids["selfcons_today"])
        .replace("@@IMPORT_METER@@", ids["import_meter"])
        .replace("@@EXPORT_METER@@", ids["export_meter"])
        .replace("@@ESTIMATE@@", ids["consumption_meter"])
    )
    return panel_card(template, columns)


def lights_card(ent, columns=12):
    """Lights are DISCOVERED at run time; the mapping only holds exclusions and display names."""
    cfg = ent.mapping.get("lights") or {}
    card = {
        "type": LIGHTS_CARD,
        "discover": cfg.get("discover", True) is not False,
        "exclude_label": str(cfg.get("exclude_label", "hide_from_dashboard") or ""),
        **span(columns),
    }
    exclude = [str(x) for x in cfg.get("exclude") or []]
    if exclude:
        card["exclude"] = exclude
    names = {str(k): str(v) for k, v in (cfg.get("names") or {}).items()}
    if names:
        card["names"] = names
        for entity in names:
            ent.used[entity] = "home_mapping"
    return card


def home_page_card(ent):
    """ONE card: the whole Home page, fitted to the space the browser gives it (see thermowatt-home-page)."""
    mapping = ent.mapping
    last_poll = integration_config.DEFAULT_SOURCES["last_poll"]
    ent.used[last_poll] = "thermann_bridge"
    flow = {
        k: v for k, v in power_flow_card(ent, True).items() if k not in ("type", "grid_options")
    }
    lights = {k: v for k, v in lights_card(ent).items() if k not in ("type", "grid_options")}
    weather_entity = ent.mapped("weather")
    place = mapping.get("place") or ""
    card = {
        "type": HOME_PAGE_CARD,
        "flow": flow,
        "hot_water": {
            "temperature": ent.thermowatt("sensor", "Bottom temperature"),
            "mode": ent.thermowatt("sensor", "Thermann mode"),
            "target": ent.thermowatt("sensor", "Thermann target"),
            "automatic": ent.thermowatt("switch", "Automatic heater control"),
            "operating": ent.thermowatt("sensor", "Hot water operating mode"),
            "tariff": ent.thermowatt("sensor", "Current tariff"),
            "boost": ent.thermowatt("sensor", "Solar boost status"),
            "boost_enabled": ent.thermowatt("switch", "Enable optional solar boost"),
            "next_action": ent.thermowatt("sensor", "Next intended action"),
            "last_poll": last_poll,
            "next_poll": ent.thermowatt("sensor", "Next cloud poll"),
        },
        "doors": {
            "garage_position": ent.tapo("sensor", "Garage Door Position"),
            "front_open": ent.tapo("binary_sensor", "Front Door Open"),
        },
        "bathrooms": [
            {
                "name": b["name"],
                "humidity": ent.tapo("sensor", b["name"], "Humidity"),
                "temperature": ent.tapo("sensor", b["name"], "Temperature"),
                "shower": ent.tapo("binary_sensor", b["name"], "Shower Detected"),
                "fan_running": ent.tapo("binary_sensor", b["name"], "Fan Running"),
                "towel_heating": ent.tapo("binary_sensor", b["name"], "Towel Rail Heating"),
                "towel_remaining": ent.tapo("sensor", b["name"], "Towel Rail Remaining Time"),
                "fan_switch": ent.tapo("switch", b["name"], "Fan Manual Override"),
            }
            for b in mapping["bathrooms"]
        ],
        "lights": lights,
    }
    if weather_entity:
        card["weather"] = {"entity": weather_entity, **({"name": place} if place else {})}
    if (mapping.get("device_energy") or {}).get("timezone"):
        card["timezone"] = str(mapping["device_energy"]["timezone"])
    return card


LIGHTING_PACKAGE = "homeowner/optional/evening_lights_schedule.yaml"
LIGHTING_AUTOMATIONS = ("automation.evening_lights_on", "automation.evening_lights_off")
LIGHT_LABEL = "Evening lights"


def lighting_view(ent):
    """Lights page: every light with its brightness, why any light is missing, and the evening schedule."""
    lights = lights_card(ent)
    lights["diagnostics"] = True
    lights.pop("grid_options", None)
    on_automation, off_automation = LIGHTING_AUTOMATIONS
    for automation in LIGHTING_AUTOMATIONS:
        ent.used[automation] = "lighting_schedule_package"
    schedule = panel_card(
        model={
            "title": "Evening lights schedule",
            "icon": "mdi:weather-sunset",
            "lines": [
                'When switched on below: lights with the "'
                + LIGHT_LABEL
                + '" label turn ON two hours before '
                "sunset (it follows the seasons and Tasmanian daylight saving by itself) and OFF at 01:00.",
                "Switching a light yourself at any time always works: the schedule only acts at those two "
                "moments and never turns a light back on or off afterwards.",
                "Nothing is scheduled until the optional schedule file is installed (the install notes "
                "explain how). Add the label to a light in Settings, Areas, labels and zones, Labels.",
            ],
        },
        columns=12,
    )

    def schedule_tile(automation, name, icon):
        known = [{"condition": "state", "entity": automation, "state": st} for st in ("on", "off")]
        return conditional(
            [{"condition": "or", "conditions": known}],
            tile(
                automation,
                name,
                icon,
                "orange",
                content="state",
                tap=call(
                    "automation.toggle",
                    automation,
                    f'Switch the "{name}" schedule on or off?',
                ),
            ),
            12,
        )

    missing = [
        {"condition": "state", "entity": automation, "state_not": st}
        for automation in (on_automation,)
        for st in ("on", "off")
    ]
    return {
        "title": "Lights",
        "path": "lights",
        "type": "sections",
        "max_columns": 2,
        "dense_section_placement": True,
        "sections": [
            section(lights),
            section(
                schedule,
                schedule_tile(
                    on_automation,
                    "Evening lights on (2 h before sunset)",
                    "mdi:weather-sunset-down",
                ),
                schedule_tile(off_automation, "Evening lights off (01:00)", "mdi:weather-night"),
                conditional(
                    missing,
                    note(
                        "The evening schedule is not installed, so no lights are scheduled. See "
                        "docs/owner/HOME_DASHBOARD.md (Lighting schedule) for the optional file.",
                        12,
                    ),
                    12,
                ),
                settings_tile("sun.sun", "Edit automations", "/config/automation/dashboard", 12),
                settings_tile("sun.sun", "Light labels", "/config/labels", 12),
            ),
        ],
    }


def bathroom_toggles(ent, name):
    """The fan and towel-rail controls of one bathroom (state-aware, inert when status is unknown)."""
    return bathroom_card(ent, name, 12, controls_only=True)


# ------------------------------------------------------------------ device energy
HOME_PAGE_CARD = "custom:thermowatt-home-page"
DEVICE_ENERGY_CARD = "custom:thermowatt-device-energy-card"
DEVICE_ENERGY_PAGE = "custom:thermowatt-device-energy-page"


def tariff_from_energy_map():
    """The authoritative peak/off-peak windows: the same file the Thermowatt energy package uses."""
    tariff = yaml.safe_load(ENERGY_MAP.read_text(encoding="utf-8"))["tariff"]
    windows = [
        {"days": list(w["days"]), "start": str(w["start"]), "end": str(w["end"])}
        for w in tariff["peak_windows"]
    ]
    return {
        "clock": tariff.get("clock", "standard"),
        "utc_offset_hours": tariff.get("utc_offset_hours", 10),
        "peak_windows": windows,
    }


def device_energy_fallback():
    return note(
        "**Device Energy needs the Thermowatt card.** Use `home.yaml` with the "
        f"`{CARD_RESOURCE}` resource installed; this native fallback has no per-device tables.",
        12,
    )


def _rate_entry(rate):
    """One validated price entry: finite non-negative prices and a real ISO date (or null = start unconfirmed)."""
    prices = {}
    for key in ("offpeak", "peak"):
        value = rate.get(key) if isinstance(rate, dict) else None
        if isinstance(value, bool) or value is None:
            raise ValueError(f"device_energy.rates entry {rate} needs a numeric '{key}'")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(
                f"device_energy.rates entry {rate}: '{key}' must be finite and not negative"
            )
        prices[key] = number
    start = rate.get("effective_from")
    if start is not None:
        try:
            parsed = datetime.date.fromisoformat(str(start))
        except ValueError as error:
            raise ValueError(
                f"device_energy.rates effective_from must be YYYY-MM-DD or null, got {start!r}"
            ) from error
        start = parsed.isoformat()
    return {"effective_from": start, **prices}


def _validated_rates(raw):
    rates = [_rate_entry(r) for r in raw or []]
    starts = [r["effective_from"] for r in rates]
    if len(set(starts)) != len(starts):
        raise ValueError("device_energy.rates has two entries with the same effective_from")
    return rates


def device_energy_sections(ent, custom=False):
    """The no-custom-card fallback: only an explanation (the designed view is :func:`device_energy_view`)."""
    return [section(device_energy_fallback())]


def device_energy_view(ent):
    """Device energy as ONE full-width card in a panel view.

    The page card arranges its own parts (balance hero beside a summary column, then the Today table and the
    monthly history) with container queries, so the layout does not depend on how many columns Home
    Assistant's sections grid offers (a wide section is not always honoured there).
    """
    base = device_energy_card(ent)
    if base.get("type") != DEVICE_ENERGY_CARD:  # rates missing: just the mapping note
        return view("Device energy", "device-energy", None, [section(base)], max_columns=2)
    page = {k: v for k, v in base.items() if k != "grid_options"}
    page["type"] = DEVICE_ENERGY_PAGE
    return {"title": "Device energy", "path": "device-energy", "type": "panel", "cards": [page]}


def _house_sources(mapping):
    """The inverter's verified energy sources for the whole-house balance (read from the mapping, never invented).

    `battery_present` is passed through as written (true / false / unknown): the card only derives household
    energy when it is exactly false, because with a battery generation, import and export do not balance.
    """
    energy = mapping.get("energy") or {}

    def entity(key):
        value = energy.get(key)
        if not isinstance(value, dict) or value.get("status") not in (
            "verified",
            "owner-confirmed",
        ):
            return ""  # an unverified mapping is never used for the balance
        return str(value.get("entity") or "")

    sources = {
        "solar": entity("solar_today_energy"),
        "import": entity("grid_import_total"),
        "export": entity("grid_export_total"),
    }
    if not any(sources.values()):
        return None
    house = {key: value for key, value in sources.items() if value}
    battery = energy.get("battery_present")
    house["battery_present"] = battery if isinstance(battery, bool) else "unknown"
    return house


def device_energy_card(ent):
    cfg = ent.mapping.get("device_energy") or {}
    rates = _validated_rates(cfg.get("rates"))
    if not rates:
        ent.unresolved.append("device_energy.rates")
        return mapping_needed("Device energy rates", "device_energy.rates", 12)
    card = {
        "type": DEVICE_ENERGY_CARD,
        "tariff": tariff_from_energy_map(),
        "rates": rates,
        "platforms": list(cfg.get("platforms") or ["tplink", "tapo"]),
        "history_months": int(cfg.get("history_months", 6)),
        **span(12),
    }
    house = _house_sources(ent.mapping)
    if house:
        card["house"] = house
    if cfg.get("timezone"):
        card["timezone"] = str(cfg["timezone"])
    for key in ("exclude", "include_only"):
        if cfg.get(key):
            card[key] = [str(x) for x in cfg[key]]
    if cfg.get("exclude_label"):
        card["exclude_label"] = str(cfg["exclude_label"])
    return card


# ------------------------------------------------------------------ views
def view(title, path, icon, sections, max_columns=4):
    """A sections view. The tab shows its TITLE: Home Assistant shows only the icon when one is set, and
    seven unlabelled icons are hard to tell apart, so ``icon`` is accepted but deliberately not emitted."""
    return {
        "title": title,
        "path": path,
        "type": "sections",
        "max_columns": max_columns,
        "dense_section_placement": True,
        "sections": sections,
    }


def build_views_native(ent):
    custom = False
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
    light_names = (mapping.get("lights") or {}).get("names") or {}
    for light, label in light_names.items():
        ent.used[str(light)] = "home_mapping"
        lights.append(
            tile(
                str(light),
                str(label),
                "mdi:lightbulb",
                "blue",
                tap=call("light.toggle", str(light)),
                columns=6,
                features=[{"type": "light-brightness"}],
            )
        )
    if not lights:
        ent.unresolved.append("lights.names")
        lights.append(mapping_needed("Lights", "lights.names", 12))
    bathrooms = [
        bathroom_card(ent, name, 12, towel_controls=False) for name in names
    ]  # one column wide each

    home = view(
        "Home",
        "home",
        "mdi:home",
        [
            section(flow),
            section(*energy_panel(ent, 6)),
            section(hot_water_summary(ent)),
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
            section(hot_water_summary(ent), *hot_water_controls(ent)),
            section(
                heading("Plan and diagnostics", "mdi:text-box-search-outline", "subtitle"),
                diagnostics_summary(ent),
                heading("Advanced", "mdi:cog-outline", "subtitle"),
                *hold_toggle(ent),
                settings_tile(
                    ent.thermowatt("sensor", "Automatic control state"),
                    "Thermowatt Settings",
                    THERMOWATT_SETTINGS_PATH,
                    12,
                ),
            ),
            section(
                history(
                    "Water temperature, last 48 hours",
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
                settings_tile(
                    ent.tapo("binary_sensor", "Controller Health Problem"),
                    "Bathroom tuning (Tapo settings)",
                    TAPO_SETTINGS_PATH,
                    12,
                ),
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
                fault_acknowledge_tile(ent),
                span_columns=2,
            ),
            section(
                settings_tile(
                    ent.thermowatt("sensor", "Automatic control state"),
                    "Thermowatt settings and diagnostic report",
                    THERMOWATT_SETTINGS_PATH,
                    12,
                ),
                settings_tile(
                    ent.tapo("binary_sensor", "Controller Health Problem"),
                    "Tapo Smart Controller settings",
                    TAPO_SETTINGS_PATH,
                    12,
                ),
            ),
        ],
        max_columns=3,
    )
    device_energy = view(
        "Device energy",
        "device-energy",
        "mdi:meter-electric",
        device_energy_sections(ent, custom),
        max_columns=3,
    )
    return [home, energy, hot_water, bath_view, doors_view, system, device_energy]


def _weather_card(ent, place):
    weather_entity = ent.mapped("weather")
    if not weather_entity:
        return mapping_needed("Weather", "weather.entity", 12)
    return {
        "type": "weather-forecast",
        "entity": weather_entity,
        **({"name": place} if place else {}),
        "show_current": True,
        "show_forecast": True,
        "forecast_type": "daily",
        **span(12),
    }


def build_views_designed(ent):
    """The designed dashboard: large-type display cards, native controls, text tabs.

    Display (read-only) cards are the Thermowatt custom cards; every control stays a native tile with its
    original state-aware logic, so nothing about what can be operated changes.
    """
    mapping = ent.mapping
    names = [b["name"] for b in mapping["bathrooms"]]
    flow = power_flow_card(ent, True)

    # The Home page is ONE card in a panel view: it fits a tablet in landscape without scrolling.
    home = {"title": "Home", "path": "home", "type": "panel", "cards": [home_page_card(ent)]}
    de_base = device_energy_card(ent)
    energy_mini = (
        [{**de_base, "part": "balancemini"}] if de_base.get("type") == DEVICE_ENERGY_CARD else []
    )
    energy = view(
        "Energy",
        "energy",
        None,
        [
            section(flow),
            section(energy_panel_card(ent), *energy_mini),
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
                )
            ),
        ],
        max_columns=3,
    )
    hot_water = view(
        "Hot water",
        "hot-water",
        None,
        [
            section(hot_water_panel(ent), *hot_water_controls(ent)),
            section(
                diagnostics_panel(ent),
                heading("Advanced", "mdi:cog-outline", "subtitle"),
                *hold_toggle(ent),
                settings_tile(
                    ent.thermowatt("sensor", "Automatic control state"),
                    "Thermowatt Settings",
                    THERMOWATT_SETTINGS_PATH,
                    12,
                ),
            ),
            section(
                history(
                    "Water temperature, last 48 hours",
                    [ent.thermowatt("sensor", "Bottom temperature")],
                    48,
                    12,
                )
            ),
        ],
        max_columns=3,
    )
    bath_view = view(
        "Bathrooms",
        "bathrooms",
        None,
        [
            section(
                bathroom_panel(ent, name, detail=True),
                heading("Controls", "mdi:tune-variant", "subtitle"),
                *bathroom_toggles(ent, name),
                heading("Settings", "mdi:cog-outline", "subtitle"),
                *bathroom_setting_tiles(ent, name),
                *bathroom_history(ent, index, name),
                settings_tile(
                    ent.tapo("binary_sensor", "Controller Health Problem"),
                    "Tapo Controller Settings",
                    TAPO_SETTINGS_PATH,
                    12,
                ),
            )
            for index, name in enumerate(names)
        ],
        max_columns=2,
    )
    lights_view = lighting_view(ent)
    contacts = []
    for key in ("garage_contact", "front_contact"):
        node = mapping["doors"].get(key) or {}
        if node.get("entity"):
            ent.used[node["entity"]] = "home_mapping"
            contacts.append(node["entity"])
    doors_view = view(
        "Doors",
        "doors",
        None,
        [
            section(
                doors_panel(ent, detailed=True),
                *([history("Door contacts, last 7 days", contacts, 168, 12)] if contacts else []),
            ),
            *(
                [
                    section(
                        {
                            "type": "logbook",
                            "target": {"entity_id": contacts},
                            "hours_to_show": 168,
                            **span(12),
                        }
                    )
                ]
                if contacts
                else []
            ),
        ],
        max_columns=2,
    )
    system = view(
        "System",
        "system",
        None,
        [section(system_panel(ent), fault_acknowledge_tile(ent)), section(settings_panel(ent))],
        max_columns=2,
    )
    device_energy = device_energy_view(ent)
    return [home, energy, hot_water, bath_view, lights_view, doors_view, system, device_energy]


def build_views(ent, custom):
    return build_views_designed(ent) if custom else build_views_native(ent)


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
        """The meter was reset at THIS local midnight, so it holds the whole local day.

        The reset must fall between RESET_EARLY_SECONDS before and RESET_LATE_SECONDS after local midnight
        (a scheduled reset fires at 00:00:00). A meter created at 00:09, one last reset at 23:55 the
        previous day, a missed midnight reset or a clock jump all fail this test. ``now()`` is local time,
        so DST changes do not matter at midnight. It cannot tell whether the SOURCE was available through
        the rollover; that limitation is stated in the status attributes and the docs.
        """
        last = f"(state_attr('{meter}', 'last_reset') | as_datetime(none))"
        return (
            f"({last} is not none and {last} >= {midnight} - timedelta(seconds={RESET_EARLY_SECONDS}) "
            f"and {last} <= {midnight} + timedelta(seconds={RESET_LATE_SECONDS}))"
        )

    def fresh(entity, seconds):
        return (
            f"(states['{entity}'] is not none "
            f"and (now() - states['{entity}'].last_reported).total_seconds() < {seconds})"
        )

    def counter_ok(entity):
        """A genuine, current kWh lifetime counter: numeric, kWh, non-negative, fresh and not declared as a
        non-cumulative (``measurement``) quantity. A missing state class is accepted because utility_meter
        does not need one."""
        return (
            f"(is_number(states('{entity}')) "
            f"and state_attr('{entity}', 'unit_of_measurement') == 'kWh' "
            f"and state_attr('{entity}', 'state_class') not in ['measurement'] "
            f"and states('{entity}') | float >= 0 and {fresh(entity, COUNTER_FRESH_SECONDS)})"
        )

    def daily_ok(meter):
        return (
            f"(is_number(states('{meter}')) and states('{meter}') | float >= 0 "
            f"and states('{meter}') | float < {DAILY_CAP_KWH} "
            f"and state_attr('{meter}', 'last_valid_state') not in [none, 'None'])"
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
                ),
                "limitation": (
                    "ready means the daily meters were reset at this local midnight and the counters are "
                    "current. Home Assistant cannot show whether an inverter counter was available through "
                    "midnight: if it was offline, its gap lands in the first reading after it returns."
                ),
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
            attributes={
                "basis": "daily utility meter on the inverter import counter (measured). If the inverter is offline overnight, the gap is added to the day its counter returns."
            },
        ),
        tmpl(
            "Home grid export today",
            "home_grid_export_today",
            f"{{{{ states('{meter_id['export']}') | float | round(3) }}}}",
            "{{ " + ready + " }}",
            "kWh",
            "energy",
            icon="mdi:transmission-tower-export",
            attributes={
                "basis": "daily utility meter on the inverter export counter (measured). If the inverter is offline overnight, the gap is added to the day its counter returns."
            },
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


def _quote_clock_times(dumper, data):
    """Always quote HH:MM so no YAML parser can read a time as a number (sexagesimal)."""
    style = "'" if re.fullmatch(r"\d{1,2}:\d{2}", data) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_PlainDumper.add_representer(str, _quote_clock_times)


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
    for group in ("energy", "weather", "doors"):
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
