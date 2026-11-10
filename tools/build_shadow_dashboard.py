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

CONTROLLER = "sensor.thermann_shadow_controller"
RESTORE = "button.thermann_shadow_restore_recommended_preferences"
UNDO = "button.thermann_shadow_undo_last_restore"
# decision code -> (ha-alert type, icon)
DECISION_STYLE = {
    "heat_now_solar": ("success", "mdi:solar-power-variant"),
    "heat_now_partial_solar": ("success", "mdi:solar-power"),
    "heat_now_grace_period": ("success", "mdi:weather-partly-cloudy"),
    "begin_grid_fallback": ("warning", "mdi:transmission-tower"),
    "insufficient_time": ("error", "mdi:clock-alert-outline"),
    "qualifying_solar": ("info", "mdi:timer-sand"),
    "wait_for_forecast_solar": ("info", "mdi:weather-sunny"),
    "wait_for_cheaper_window": ("info", "mdi:clock-outline"),
    "forecast_unavailable_conservative_fallback": ("warning", "mdi:weather-cloudy-alert"),
    "no_topup_required": ("success", "mdi:check-circle-outline"),
    "data_unavailable": ("error", "mdi:lan-disconnect"),
    "owner_review_required": ("warning", "mdi:account-alert-outline"),
    "paused": ("info", "mdi:pause-circle-outline"),
}


def slug(value):
    """Mirror HA's slugify for the ASCII names used here (has_entity_name IDs)."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def sensor(name):
    return f"sensor.thermann_shadow_{slug(name)}"


def entity(key):
    meta = settings.CATALOG[key]
    return f"{meta.kind}.thermann_shadow_{slug(meta.name)}"


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
            "**Shadow recommendation only.** No heater command is sent; the native "
            "Schedule still controls the real heater."
        ),
    }


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
        section(
            "Right now",
            "mdi:water-boiler",
            [
                recommendation_card(),
                {
                    "type": "gauge",
                    "entity": sensor("Bottom temperature"),
                    "name": "Tank · bottom sensor",
                    "min": 10,
                    "max": 75,
                    "needle": True,
                    "severity": {"red": 10, "yellow": 40, "green": 60},
                },
                tile("Morning comfort threshold", "mdi:weather-sunset-up"),
                tile("Afternoon storage target", "mdi:water-thermometer"),
                tile("Comfort countdown", "mdi:timer-sand"),
                tile("Next decision threshold", "mdi:target"),
            ],
        ),
        section(
            "Next heating (hypothetical)",
            "mdi:calendar-clock",
            [
                tile("Hypothetical heating start", "mdi:play-circle-outline"),
                tile("Simulated completion", "mdi:clock-check-outline"),
                tile("Planning deadline", "mdi:flag-checkered"),
                tile("Off peak fallback start", "mdi:transmission-tower"),
                tile("Heating time estimate", "mdi:timer-outline"),
                tile("Mixed tank energy estimate", "mdi:lightning-bolt"),
                tile("Plan cost estimate", "mdi:cash"),
                tile("Recommended energy source", "mdi:solar-power"),
            ],
        ),
        section(
            "Energy & prices",
            "mdi:home-lightning-bolt",
            [
                tile("Measured PV", "mdi:solar-power"),
                tile("Measured house load", "mdi:home-lightning-bolt"),
                tile("Measured grid export", "mdi:transmission-tower-export"),
                tile("Measured grid import", "mdi:transmission-tower-import"),
                tile("Current tariff", "mdi:tag-outline"),
                tile("Current import price", "mdi:currency-usd"),
                tile("Forecast net surplus", "mdi:weather-sunny"),
                tile("Forecast usable solar before deadline", "mdi:solar-panel"),
                {
                    "type": "markdown",
                    "content": (
                        "### Heat now or later?\n"
                        "Whole remaining cycle at full 3 kW: **now "
                        "{{ states('" + sensor("Continuous cycle cost now") + "') }} AUD** · "
                        "best later **{{ states('"
                        + sensor("Continuous cycle cost later")
                        + "') }} AUD** · "
                        "benefit of now **{{ states('"
                        + sensor("Benefit of heating now")
                        + "') }} AUD**.\n\n"
                        "Costs include imported electricity **and foregone solar feed-in**. "
                        "Partial solar counts: 2 kW surplus + 1 kW import is cheaper than "
                        "3 kW off-peak grid. Forecasts are uncertain; comfort wins over small savings."
                    ),
                },
            ],
        ),
        section(
            "History",
            "mdi:chart-line",
            [
                {
                    "type": "history-graph",
                    "title": "Bottom temperature · 24 h",
                    "hours_to_show": 24,
                    "entities": [sensor("Bottom temperature"), sensor("Reported target")],
                },
                {
                    "type": "history-graph",
                    "title": "Solar, house and grid · 12 h (kW)",
                    "hours_to_show": 12,
                    "entities": [
                        sensor("Measured PV"),
                        sensor("Measured house load"),
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
                "# Hot-water preferences\n"
                "**Local shadow settings only.** These controls and the integration's "
                "Configure dialog edit **one** saved configuration. Changes are validated "
                "together (an invalid change saves nothing), recalculate locally at once and "
                "never contact Thermann, restart the heater or change the native Schedule "
                "or T-Comfort. Recommended values are experimental starting points, not "
                "manufacturer limits."
            ),
        }
    ]
    groups = ("Comfort", "Solar & Forecasting", "Heating Cycles", "Advanced")
    icons = ("mdi:home-thermometer", "mdi:solar-power", "mdi:sync", "mdi:tune")
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
                                    "Restore recommended comfort, solar, cycle and freshness "
                                    "preferences? The tariff contract, entity mappings, "
                                    "verifications, meter direction, pause state and native "
                                    "references are kept. You can undo this once. No heater "
                                    "command is sent."
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
                "## Shadow mode\n**Commands disabled · control capable: "
                "{{ state_attr('" + CONTROLLER + "','control_capable') }} · extra cloud "
                "requests: {{ state_attr('" + CONTROLLER + "','additional_cloud_requests') }}**. "
                "Physical heating is **unverified**; simulated cycles never prove element power."
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
            "title": "Forecast and simulation (estimates)",
            "entities": [
                sensor(name)
                for name in (
                    "Forecast age",
                    "Forecast net surplus",
                    "Simulated cycle state",
                    "Simulated cycle count",
                    "Simulated stop count",
                    "Suppressed switching episodes",
                    "Simulated session cost",
                    "Scenario cost difference",
                    "Modelled energy shortfall",
                    "Latest continuous heating start",
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
                "- Measured PV (15-min mean): {{ f.measured_pv_average_kw }} kW · "
                "error vs forecast: {{ f.pv_error_kw }} kW\n"
                "- Correction now: {{ f.pv_correction_now }} (fades to none after "
                "{{ f.pv_correction_fades_to_none_after_hours }} h; never increases PV)\n"
                "### Simulated cycle\n"
                "{% set c = state_attr('" + CONTROLLER + "','cycle') or {} %}"
                "{% for key, value in c.items() %}- {{ key }}: {{ value }}\n{% endfor %}"
            ),
        },
        {
            "type": "markdown",
            "content": (
                "### Reasons\n"
                "{% for item in state_attr('" + CONTROLLER + "','reasons') or [] %}"
                "- {{ item }}\n{% endfor %}"
                "### Warnings and assumptions\n"
                "{% for item in state_attr('" + CONTROLLER + "','warnings') or [] %}"
                "- {{ item }}\n{% endfor %}"
                "### Hypothetical windows (local time)\n"
                "{% for item in state_attr('" + CONTROLLER + "','windows') or [] %}"
                "- {{ as_timestamp(item.start) | timestamp_custom('%a %H:%M') }} → "
                "{{ as_timestamp(item.end) | timestamp_custom('%H:%M') }} · {{ item.source }}\n"
                "{% endfor %}\n"
                "Native clock: compare manually with Hobart "
                "{{ now().strftime('%a %d %b %H:%M') }} after DST changes. Tariff 93 stays "
                "fixed AEST. 30-minute cloud polls can include status→refresh→replay "
                "(3 attempts); the planner adds zero requests."
            ),
        },
    ]
    return {
        "title": "Thermann Hot Water",
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


def main():
    (ROOT / "shadow_controller/dashboard.yaml").write_text(
        yaml.safe_dump(build(), sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    for filename in (PACKAGE / "strings.json", PACKAGE / "translations/en.json"):
        data = json.loads(filename.read_text(encoding="utf-8"))
        for step in (data["config"]["step"]["user"], data["options"]["step"]["init"]):
            step["description"] = (
                "Read local HA states only; no heater commands, MQTT writes or cloud requests. "
                "Optional forecast mappings: a PV forecast (EMHASS forecasts list or buffered "
                "Forecast.Solar watts) with forecast_generated_at, and a household load "
                "forecast or measured baseline. Configure and dashboard controls share the "
                "same stored preferences."
            )
            step["data"].update(
                {
                    "pv": "PV production (display and forecast correction)",
                    "forecast_pv": "Optional published PV forecast",
                    "forecast_load": "Optional household load forecast or measured baseline",
                }
            )
        step = data["options"]["step"]["settings"]
        step["description"] = (
            "Local shadow preferences only; no setting enables execution. Dashboard controls "
            "use these exact same saved values. Current/recommended/original values and "
            "guidance are on the Settings dashboard. Morning is before noon; afternoon after "
            "noon; tariff peak times must increase. Aurora 93 uses fixed AEST, weekends "
            "off-peak. The stored custom weekly table is always validated and needs gap-free "
            "coverage."
        )
        step["data"] = {key: meta.name for key, meta in settings.CATALOG.items()}
        data["options"]["error"]["invalid_settings"] = (
            "Nothing saved. Check finite planning bounds; morning before noon and afternoon "
            "after noon; increasing tariff times without overlaps; gap-free custom weekly "
            "periods (validated in every tariff mode); T-Comfort reference not above expected "
            "native target. No heater settings were changed."
        )
        filename.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
