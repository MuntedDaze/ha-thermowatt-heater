"""Generate the native-card dashboard and settings labels from the shared catalogue.

Native HA cards only (sections, tile, gauge, markdown, entities, history-graph,
button). Every entity reference is checked against a real isolated HA instance
by tools/readiness/shadow_ha_smoke.py; every markdown template is rendered there.
"""

import importlib
import json
from pathlib import Path
import re
import sys
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components/thermann_shadow"
package = ModuleType("_shadow_dashboard")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package
config = importlib.import_module(f"{package.__name__}.config")
settings = importlib.import_module(f"{package.__name__}.settings")
naming = importlib.import_module(f"{package.__name__}.naming")

CONTROLLER = "sensor.thermann_shadow_controller"
RESTORE = "button.thermann_shadow_restore_recommended_preferences"
MASTER = "switch.thermann_shadow_automatic_heater_control"
CONTROLLER_BUTTONS = {
    "button.thermann_shadow_hold_heater_owner_override": (
        "Hold heater",
        "mdi:hand-back-left",
        "Hold: automatic control will send NO further commands until you press Resume. "
        "The heater stays in its current mode; change it yourself in the Thermann app.",
    ),
    "button.thermann_shadow_resume_automatic_control": (
        "Resume control",
        "mdi:play-circle",
        "Resume automatic control? It first re-reads the heater from a NEW bridge status and "
        "only continues if the heater is OFF or in Manual at 70 °C.",
    ),
    "button.thermann_shadow_acknowledge_controller_fault": (
        "Acknowledge fault",
        "mdi:check-decagram",
        "Acknowledge the fault? Check the Thermann app first. The controller re-inspects the "
        "heater from a new status; nothing is re-sent.",
    ),
}
UNDO = "button.thermann_shadow_undo_last_restore"
# decision code -> (ha-alert type, icon)
DECISION_STYLE = {
    "heat_now_cheapest": ("success", "mdi:solar-power-variant"),
    "heat_now_saving_too_small": ("success", "mdi:solar-power"),
    "heat_now_comfort_fallback": ("warning", "mdi:transmission-tower"),
    "native_heating_economical": ("success", "mdi:water-boiler"),
    "native_heating_costlier_than_waiting": ("warning", "mdi:water-boiler-alert"),
    "wait_cheaper_later": ("info", "mdi:weather-sunny"),
    "flexible_no_cost_difference": ("info", "mdi:clock-outline"),
    "no_heating_needed": ("success", "mdi:check-circle-outline"),
    "insufficient_time": ("error", "mdi:clock-alert-outline"),
    "data_unavailable": ("error", "mdi:lan-disconnect"),
    "owner_review_required": ("warning", "mdi:account-alert-outline"),
    "paused": ("info", "mdi:pause-circle-outline"),
}


def slug(value):
    """Mirror HA's slugify for the ASCII names used here (has_entity_name IDs)."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def sensor(name):
    return naming.entity_id("sensor", name)


def entity(key):
    meta = settings.CATALOG[key]
    return naming.entity_id(meta.kind, meta.name)


def tile(name, icon, **extra):
    return {"type": "tile", "entity": sensor(name), "icon": icon, **extra}


def section(title, icon, cards):
    return {
        "type": "grid",
        "cards": [{"type": "heading", "heading": title, "icon": icon}, *cards],
    }


def recommendation_card():
    styles = json.dumps({code: style[0] for code, style in DECISION_STYLE.items()})
    icons = json.dumps({code: style[1] for code, style in DECISION_STYLE.items()})
    return {
        "type": "markdown",
        "text_only": True,
        "content": (
            "{% set code = states('" + sensor("Decision code") + "') %}"
            "{% set kind = " + styles + ".get(code, 'info') %}"
            "{% set icon = " + icons + ".get(code, 'mdi:water-boiler') %}\n"
            '<ha-alert alert-type="{{ kind }}">'
            '<h1><ha-icon icon="{{ icon }}"></ha-icon> '
            "{{ states('" + sensor("Recommendation") + "') }}</h1>"
            "{{ state_attr('" + CONTROLLER + "','decision_explanation') "
            "or 'Waiting for fresh heater and meter readings.' }}"
            "</ha-alert>\n\n"
            "{% if is_state('" + MASTER + "', 'on') %}**Automatic control is ON.** The "
            "controller follows this plan: Manual 70 °C permits heating, Thermann OFF "
            "parks it (antibacterial and frost protection stay active); the Thermann "
            "thermostat decides when the element runs."
            "{% else %}**Planner only.** Automatic control is off, so no heater command is "
            "sent.{% endif %}"
        ),
    }


def controller_card():
    rows = [
        sensor("Automatic control state"),
        sensor("Automatic control reason"),
        sensor("Thermann mode"),
        sensor("Thermann target"),
        sensor("Next intended action"),
        sensor("Next heating start"),
        sensor("Next heating stop"),
        sensor("Last command"),
        sensor("Last command result"),
        sensor("Last command time"),
        sensor("Commands in last 24 hours"),
        sensor("Cloud requests in last 24 hours"),
        sensor("Controller fault"),
    ]
    status = sensor("Automatic control state")
    return section(
        "Automatic control",
        "mdi:robot",
        [
            {
                "type": "markdown",
                "text_only": True,
                "content": (
                    "{% set s = states('" + status + "') %}"
                    "{% set kind = {'fault_locked':'error','owner_override':'warning',"
                    "'confirming':'info','disabled':'info'}.get(s, 'success') %}"
                    "<ha-alert alert-type=\"{{ kind }}\"><b>{{ s | replace('_', ' ') | upper }}</b>"
                    " — {{ states('"
                    + sensor("Automatic control reason")
                    + "') | replace('_', ' ') }}"
                    "</ha-alert>\n"
                    "{{ state_attr('" + status + "', 'recovery_guidance') or '' }}\n\n"
                    "{% set missing = state_attr('" + MASTER + "', 'commissioning_missing') %}"
                    "{% if missing %}Commissioning still needed: "
                    "{{ missing | join(', ') | replace('_', ' ') }}. The controller cannot send any "
                    "command until these are done.{% endif %}"
                ),
            },
            {
                "type": "tile",
                "entity": MASTER,
                "icon": "mdi:robot",
                "name": "Automatic heater control",
            },
            {
                "type": "entities",
                "title": "Controller status",
                "show_header_toggle": False,
                "entities": rows,
            },
            *[
                {
                    "type": "button",
                    "entity": entity_id,
                    "name": name,
                    "icon": icon,
                    "show_state": False,
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "button.press",
                        "target": {"entity_id": entity_id},
                        "confirmation": {"text": text},
                    },
                }
                for entity_id, (name, icon, text) in CONTROLLER_BUTTONS.items()
            ],
        ],
    )


def guidance(group, keys):
    lines = [f"### {group} — current, recommended and original values"]
    for key in keys:
        meta = settings.CATALOG[key]
        recommended = config.DEFAULT_OPTIONS[key]
        original = settings.ORIGINAL_DEFAULTS[key]

        def show(value, meta=meta):
            if type(value) is bool:
                return "On" if value else "Off"
            if value == "":
                return "blank / unknown"
            return f"{value:g}" if isinstance(value, float) else str(value)

        unit = f" {meta.unit}" if meta.unit else ""
        if recommended == original:
            defaults = f"recommended & original **{show(recommended)}{unit}**"
        else:
            defaults = (
                f"recommended **{show(recommended)}{unit}** · original **{show(original)}{unit}**"
            )
        restore = "restored" if key in settings.RESTORED else "kept"
        lines.append(
            f"**{meta.name}** — current **{{{{ states('{entity(key)}') }}}}{unit}** · "
            f"{defaults} · *{restore} by Restore*  \n{meta.explanation}"
        )
    return {"type": "markdown", "content": "\n\n".join(lines)}


def build():
    hot_water = [
        controller_card(),
        section(
            "Right now",
            "mdi:water-boiler",
            [
                recommendation_card(),
                {
                    "type": "gauge",
                    "entity": sensor("Bottom temperature"),
                    "name": "Tank reading (T_Avg)",
                    "min": 10,
                    "max": 75,
                    "severity": {"red": 10, "yellow": 42, "green": 60},
                },
                tile("Heater element state", "mdi:heat-wave"),
                tile("Heater state confidence", "mdi:help-circle-outline"),
                tile("Morning readiness", "mdi:weather-sunset-up"),
                tile("Afternoon readiness", "mdi:water-thermometer"),
                tile("Morning ready deadline", "mdi:alarm"),
                tile("Afternoon ready deadline", "mdi:alarm"),
            ],
        ),
        section(
            "Heat now or later?",
            "mdi:scale-balance",
            [
                tile("Continuous cycle cost now", "mdi:cash-fast"),
                tile("Continuous cycle cost later", "mdi:cash-check"),
                tile("Saving by waiting", "mdi:piggy-bank-outline"),
                tile("Decision confidence", "mdi:shield-check-outline"),
                tile("Hypothetical heating start", "mdi:play-circle-outline"),
                tile("Simulated completion", "mdi:clock-check-outline"),
                tile("Native Schedule predicted cost", "mdi:calendar-clock"),
                tile("Native Schedule extra cost vs best plan", "mdi:calendar-alert"),
                {
                    "type": "markdown",
                    "content": (
                        "Costs are the **extra** electricity cost of heating, including "
                        "**foregone feed-in**, for the same required energy. The 3 kW element "
                        "is never treated as variable power; the real heater's load is removed "
                        "from household demand once. *Start and completion are hypothetical: the "
                        "native Schedule controls the heater.*"
                    ),
                },
            ],
        ),
        section(
            "Energy & tariff",
            "mdi:home-lightning-bolt",
            [
                tile("Measured PV AC output", "mdi:solar-power"),
                tile("Base household load excluding hot water", "mdi:home-lightning-bolt"),
                tile("Hypothetical solar surplus if heater off", "mdi:solar-panel"),
                tile("Measured grid export", "mdi:transmission-tower-export"),
                tile("Measured grid import", "mdi:transmission-tower-import"),
                tile("Current tariff", "mdi:tag-outline"),
                tile("Current tariff rate", "mdi:currency-usd"),
                tile("Next tariff change", "mdi:timer-outline"),
                tile("Forecast net surplus", "mdi:weather-sunny"),
                tile("Forecast age", "mdi:update"),
            ],
        ),
        section(
            "History",
            "mdi:chart-line",
            [
                {
                    "type": "history-graph",
                    "title": "Tank reading and heater state · 24 h",
                    "hours_to_show": 24,
                    "entities": [sensor("Bottom temperature"), sensor("Heater element state")],
                },
                {
                    "type": "history-graph",
                    "title": "Solar, house and grid · 12 h (kW)",
                    "hours_to_show": 12,
                    "entities": [
                        sensor("Measured PV AC output"),
                        sensor("Measured house load"),
                        sensor("Base household load excluding hot water"),
                        sensor("Measured signed grid"),
                    ],
                },
            ],
        ),
    ]
    controls = [
        {
            "type": "markdown",
            "content": (
                "# Hot-water settings\n"
                "These controls and **Configure** edit **one** saved configuration. Every "
                "change is checked together with the rest (an invalid change saves nothing) "
                "and applies at once, without a restart. **System** settings and the tariff "
                "contract can only be changed while Automatic heater control is off. "
                "Nothing here contacts Thermann or changes the heater's own settings."
            ),
        }
    ]
    groups = settings.GROUPS
    icons = ("mdi:home-thermometer", "mdi:tune", "mdi:shield-check")
    for group, icon in zip(groups, icons, strict=True):
        keys = [
            key
            for key, meta in settings.CATALOG.items()
            if meta.group == group and meta.kind != "form"
        ]
        controls.append(
            {
                "type": "entities",
                "title": group,
                "icon": icon,
                "show_header_toggle": False,
                "state_color": True,
                "entities": [entity(key) for key in keys],
            }
        )
        controls.append(guidance(group, keys))
    controls.extend(
        [
            {
                "type": "markdown",
                "content": (
                    "### Advanced weekly periods\nEdit in **Configure** (no YAML). Custom tariff "
                    "periods apply only in custom tariff mode; native periods are references, "
                    "never device writes.\n"
                    "{% for name, item in (state_attr('"
                    + CONTROLLER
                    + "','advanced_form_settings')"
                    " or {}).items() %}\n- **{{ name }}** · "
                    "{{ 'changed from recommended' if item.changed_from_recommended "
                    "else 'recommended & original' }}\n{% endfor %}"
                ),
            },
            {
                "type": "button",
                "name": "Configure mappings & weekly periods",
                "icon": "mdi:cog-outline",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": "/config/integrations/integration/thermann_shadow",
                },
            },
            {
                "type": "grid",
                "columns": 2,
                "square": False,
                "cards": [
                    {
                        "type": "button",
                        "entity": RESTORE,
                        "name": "Restore recommended",
                        "icon": "mdi:restore",
                        "tap_action": {
                            "action": "perform-action",
                            "perform_action": "button.press",
                            "target": {"entity_id": RESTORE},
                            "confirmation": {
                                "text": (
                                    "Restore the recommended comfort, forecast and planning "
                                    "preferences? System settings, the tariff contract, "
                                    "sensor mappings and verifications are kept. You can undo "
                                    "this once. No heater command is sent."
                                )
                            },
                        },
                    },
                    {
                        "type": "button",
                        "entity": UNDO,
                        "name": "Undo last restore",
                        "icon": "mdi:undo-variant",
                        "tap_action": {
                            "action": "perform-action",
                            "perform_action": "button.press",
                            "target": {"entity_id": UNDO},
                            "confirmation": {
                                "text": "Put back the preferences replaced by the last restore?"
                            },
                        },
                    },
                ],
            },
        ]
    )
    diagnostics = [
        {
            "type": "markdown",
            "content": (
                "## Planner\n**Automatic control active: "
                "{{ state_attr('" + CONTROLLER + "','control_capable') }} · extra cloud "
                "requests: {{ state_attr('" + CONTROLLER + "','additional_cloud_requests') }}**. "
                "The planner only estimates; heater commands come from the controller alone "
                "(Automatic heater control). Thermann Controller is unofficial community "
                "software, not a Thermann product."
            ),
        },
        {
            "type": "markdown",
            "content": (
                "### Heater state evidence\n"
                "{% set h = state_attr('" + CONTROLLER + "','heater_state') or {} %}"
                "- State **{{ h.state }}** ({{ h.confidence }}) · basis: "
                "{{ (h.basis or []) | join(', ') }}\n"
                "- WaterHeaterSts raw {{ h.status_raw }} (bit 0 = {{ h.status_bit0 }}; "
                "{{ h.status_semantics }})\n"
                "- Last 3 kW load step: {{ h.last_load_step }} at {{ h.last_load_step_at }}\n"
                "{% set l = state_attr('" + CONTROLLER + "','load') or {} %}"
                "- Base load {{ l.base_low_kw }}–{{ l.base_high_kw }} kW "
                "(median {{ l.base_p50_kw }}); meter suspect: "
                "{{ l.meter_suspect_pre_commissioning_signature }}"
            ),
        },
        {
            "type": "markdown",
            "content": (
                "### Goals and strategies\n"
                "{% for g in state_attr('" + CONTROLLER + "','goals') or [] %}"
                "- {{ g.kind }}: {{ g.target_c }} °C by "
                "{{ as_timestamp(g.deadline) | timestamp_custom('%a %H:%M') }} ({{ g.basis }})\n"
                "{% endfor %}"
                "| Strategy | Start | Cost | Solar |\n|---|---|---:|---:|\n"
                "{% for name, p in (state_attr('" + CONTROLLER + "','strategies') or {}).items() %}"
                "| {{ name }} | {{ as_timestamp(p.start) | timestamp_custom('%H:%M') "
                "if p.start else '—' }} | ${{ p.cost_aud }} | {{ (p.solar_share * 100) | round(0) }}% |\n"
                "{% endfor %}"
            ),
        },
        {
            "type": "entities",
            "title": "Measured inputs (actual)",
            "entities": [
                sensor(name)
                for name in (
                    "Bottom temperature",
                    "Reported target",
                    "Measured signed grid",
                    "Derived net export",
                    "Measured PV",
                    "Measured PV AC output",
                    "Measured house load",
                    "Cloud health",
                    "Status age",
                    "Observed request attempts",
                    "Observed requests per hour",
                )
            ],
        },
        {
            "type": "entities",
            "title": "Estimates and plan (not measurements)",
            "entities": [
                sensor(name)
                for name in (
                    "Decision code",
                    "Simulated cycle state",
                    "Next tariff period",
                    "Forecast usable solar before deadline",
                    "Scenario cost difference",
                    "Modelled energy shortfall",
                    "Latest continuous heating start",
                    "Off peak fallback start",
                    "Planning deadline",
                    "Comfort deadline",
                    "Configured afternoon peak",
                    "Controller",
                )
            ],
        },
        {
            "type": "entities",
            "title": "Native heater references",
            "entities": [
                sensor(name)
                for name in (
                    "Reported Schedule window",
                    "T Comfort reference",
                    "Device clock check",
                )
            ],
        },
        {
            "type": "markdown",
            "content": (
                "### Forecast\n"
                "{% set f = state_attr('" + CONTROLLER + "','forecast') or {} %}"
                "- Source: **{{ f.source }}** · load basis: {{ f.load_basis }}\n"
                "- Age: {{ f.age_minutes }} min · intervals: {{ f.intervals }}\n"
                "- Measured AC PV (15-min mean): {{ f.measured_pv_average_kw }} kW · "
                "error vs forecast: {{ f.pv_error_kw }} kW\n"
                "- Correction now: {{ f.pv_correction_now }} (two-way, bounded; fades after "
                "{{ f.pv_correction_fades_to_none_after_hours }} h)\n"
                "### Reasons\n"
                "{% for item in state_attr('" + CONTROLLER + "','reasons') or [] %}"
                "- {{ item }}\n{% endfor %}"
                "### Warnings and assumptions\n"
                "{% for item in state_attr('" + CONTROLLER + "','warnings') or [] %}"
                "- {{ item }}\n{% endfor %}"
                "{% for item in state_attr('" + CONTROLLER + "','strategy_warnings') or [] %}"
                "- {{ item }}\n{% endfor %}\n"
                "{% if 'not_applicable' not in states('" + sensor("Device clock check") + "') %}"
                "Native clock: compare manually with Hobart "
                "{{ now().strftime('%a %d %b %H:%M') }} after DST changes. {% else %}"
                "The native Schedule is not in use: the heater clock does not affect heating. "
                "{% endif %}Tariff 93 stays fixed AEST. The planner adds zero cloud requests."
            ),
        },
    ]
    return {
        "title": "Hot Water",
        "views": [
            {
                "title": "Hot Water",
                "path": "thermann-shadow",
                "icon": "mdi:water-boiler",
                "type": "sections",
                "max_columns": 3,
                "sections": hot_water,
            },
            {"title": "Settings", "path": "settings", "icon": "mdi:cog", "cards": controls},
            {
                "title": "Diagnostics",
                "path": "diagnostics",
                "icon": "mdi:information-outline",
                "cards": diagnostics,
            },
        ],
    }


def references(node):
    """Every thermann_shadow entity ID in a dashboard, including inside templates."""
    text = json.dumps(node)
    return sorted(
        set(
            re.findall(
                r"\b(?:sensor|number|time|select|switch|text|button)\.thermann_shadow_[a-z0-9_]+",
                text,
            )
        )
    )


def templates(node):
    """All markdown templates, for rendering in a real HA instance."""
    found = []
    if isinstance(node, dict):
        if node.get("type") == "markdown":
            found.append(node["content"])
        for value in node.values():
            found.extend(templates(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(templates(value))
    return found


SOURCE_LABELS = {
    "pv": "PV production (display and forecast correction)",
    "forecast_pv": "Optional published PV forecast",
    "forecast_load": "Optional household load forecast or measured baseline",
    "import_energy": "Cumulative grid import (not used; kept for reference)",
    "export_energy": "Cumulative grid export (not used; kept for reference)",
    "pv_ac": "Optional inverter AC output (default: GoodWe total power)",
    "heater_power": "Optional heater power sensor (element detection)",
}
OPTIONS_STEPS = {
    "init": (
        "Settings",
        "Choose what to change. Everyday comfort settings are also available as controls on "
        "the device page. System settings, the tariff contract and the sensor mappings can "
        "only be changed while Automatic heater control is off.",
    ),
    "sources": (
        "Sensor mappings",
        "Which Home Assistant entities the controller reads. Reading only: nothing here sends "
        "a command or contacts the cloud. Changing a mapping restarts the planner's evidence; "
        "it needs Automatic heater control off.",
    ),
    "preferences": (
        "Comfort, tariff and forecast settings",
        "Morning times are Hobart local and before noon; the weekend afternoon time is after "
        "noon. Tariff peak times use the tariff clock (Aurora 93: fixed AEST, so one hour later "
        "in summer) and must increase. The tariff contract can only be changed while Automatic "
        "heater control is off. Every change is checked together with the rest of the "
        "configuration; an invalid combination saves nothing.",
    ),
    "system": (
        "System and commissioning",
        "Command destination, T3 qualification, safety timing, budgets, data freshness and "
        "verification. Except for the notification service, these can only be changed while "
        "Automatic heater control is off. The command topic must be the one the bridge "
        "announced for your heater.",
    ),
}


def main():
    (ROOT / "shadow_controller/dashboard.yaml").write_text(
        yaml.safe_dump(build(), sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    for filename in (PACKAGE / "strings.json", PACKAGE / "translations/en.json"):
        data = json.loads(filename.read_text(encoding="utf-8"))
        user = data["config"]["step"]["user"]
        user["description"] = (
            "Unofficial community integration, not a Thermann product. Automatic control "
            "stays off until you commission it. "
            "Read local HA states only; no heater commands, MQTT writes or cloud requests. "
            "Optional forecast mappings: a PV forecast (EMHASS forecasts list or buffered "
            "Forecast.Solar watts) with forecast_generated_at, and a household load "
            "forecast or measured baseline."
        )
        user["data"].update(SOURCE_LABELS)
        steps = {}
        for step_id, (title, description) in OPTIONS_STEPS.items():
            steps[step_id] = {"title": title, "description": description}
        steps["init"]["menu_options"] = {
            "preferences": OPTIONS_STEPS["preferences"][0],
            "system": OPTIONS_STEPS["system"][0],
            "sources": OPTIONS_STEPS["sources"][0],
        }
        steps["sources"]["data"] = dict(user["data"])
        for step_id, groups in (("preferences", ("Everyday", "Advanced")), ("system", ("System",))):
            steps[step_id]["data"] = {
                key: meta.name for key, meta in settings.CATALOG.items() if meta.group in groups
            }
        data["options"] = {
            "step": steps,
            "error": {
                "invalid_settings": "Nothing saved. {detail}",
                "locked_while_active": "{detail}",
            },
        }
        filename.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
