"""Generate native-card dashboard/settings labels from the shared catalogue."""

import importlib
import json
from pathlib import Path
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


def slug(value):
    return value.lower().replace("-", "_").replace(" ", "_")


def entity(key):
    meta = settings.CATALOG[key]
    return f"{meta.kind}.thermann_shadow_{slug(meta.name)}"


def tile(name, icon):
    return {"type": "tile", "entity": f"sensor.thermann_shadow_{name}", "icon": icon}


def build():
    main = [
        {
            "type": "markdown",
            "content": "# Hot water\n**SHADOW ONLY · no heater commands**\nNative Schedule remains in charge. All heating decisions and cycle costs below are hypothetical, not measured element operation.",
        },
        {
            "type": "markdown",
            "content": "# {{ states('sensor.thermann_shadow_bottom_temperature') }} °C\nBottom-tank temperature · not whole-tank usable reserve\n## {{ states('sensor.thermann_shadow_recommendation') }}\n{{ state_attr('sensor.thermann_shadow_controller','decision_explanation') or 'Waiting for fresh inputs' }}",
        },
        {
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": [
                tile("morning_comfort_threshold", "mdi:weather-sunset-up"),
                tile("afternoon_storage_target", "mdi:water-thermometer"),
                tile("comfort_countdown", "mdi:timer-sand"),
                tile("simulated_completion", "mdi:clock-check-outline"),
            ],
        },
        {
            "type": "entities",
            "title": "Next hypothetical heating window",
            "entities": [
                f"sensor.thermann_shadow_{key}"
                for key in (
                    "hypothetical_heating_start",
                    "planning_deadline",
                    "off_peak_fallback_start",
                    "heating_time_estimate",
                    "mixed_tank_energy_estimate",
                    "recommended_energy_source",
                )
            ],
        },
        {
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": [
                tile("measured_pv", "mdi:solar-power"),
                tile("measured_house_load", "mdi:home-lightning-bolt"),
                tile("measured_grid_export", "mdi:transmission-tower-export"),
                tile("measured_grid_import", "mdi:transmission-tower-import"),
            ],
        },
        {
            "type": "entities",
            "title": "Energy costs — calculated scenarios",
            "entities": [
                f"sensor.thermann_shadow_{key}"
                for key in (
                    "current_tariff",
                    "current_import_price",
                    "forecast_net_surplus",
                    "continuous_cycle_cost_now",
                    "continuous_cycle_cost_later",
                    "benefit_of_heating_now",
                )
            ],
        },
        {
            "type": "markdown",
            "content": "**Cost includes imported electricity and foregone solar exports.** Positive benefit favours now; negative favours later. Forecast surplus is uncertain. Required comfort wins over small savings. The bottom-temperature estimate and 8°C thermostat hysteresis do not prove a real element run.",
        },
        {
            "type": "history-graph",
            "title": "Bottom temperature · last 24 hours",
            "hours_to_show": 24,
            "entities": [
                "sensor.thermann_shadow_bottom_temperature",
                "sensor.thermann_shadow_reported_target",
            ],
        },
        {
            "type": "history-graph",
            "title": "Measured solar, household and grid · kW",
            "hours_to_show": 12,
            "entities": [
                f"sensor.thermann_shadow_{key}"
                for key in ("measured_pv", "measured_house_load", "measured_signed_grid")
            ],
        },
    ]
    controls = [
        {
            "type": "markdown",
            "content": "# Your hot-water preferences\n**Local shadow settings only.** Controls and Configure share one saved configuration. No setting enables execution or changes native Schedule/T-Comfort. Recommended values are experimental starting points, not manufacturer safety limits. Current values appear in the controls; matching recommended/original defaults are shown once below. Changes reset the session simulation and recalculate locally; no Thermann requests.",
        }
    ]
    for group in ("Comfort", "Solar & Forecasting", "Heating Cycles", "Advanced"):
        keys = [
            key
            for key, meta in settings.CATALOG.items()
            if meta.group == group and meta.kind != "form"
        ]
        controls.append(
            {
                "type": "entities",
                "title": group,
                "show_header_toggle": False,
                "entities": [entity(key) for key in keys],
            }
        )
        guidance = [f"### {group} · starting values & guidance"]
        for key in keys:
            meta, default = settings.CATALOG[key], config.DEFAULT_OPTIONS[key]
            if type(default) is bool:
                default = "On" if default else "Off"
            guidance.append(
                f"**{meta.name}** — recommended & original: **{default if default != '' else 'blank / unknown'} {meta.unit or ''}**. {meta.explanation}"
            )
        controls.append({"type": "markdown", "content": "\n\n".join(guidance)})
    controls.extend(
        [
            {
                "type": "button",
                "name": "Entity mappings & custom weekly/reference periods",
                "icon": "mdi:cog-outline",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": "/config/integrations/integration/thermann_shadow",
                },
            },
            {
                "type": "markdown",
                "content": "**Advanced custom/reference periods:** edit in Configure (no Python/YAML). Current and recommended/original values:\n{% for name, item in (state_attr('sensor.thermann_shadow_controller','advanced_form_settings') or {}).items() %}\n- **{{ name }}** · current: `{{ item.current }}`\n  Recommended & original: `{{ item.recommended_and_original_default }}`\n{% endfor %}\nCustom periods apply only in custom tariff mode; native periods are references, never device writes.",
            },
            {
                "type": "button",
                "entity": "button.thermann_shadow_restore_recommended_preferences",
                "name": "Restore recommended preferences",
                "icon": "mdi:restore",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "button.press",
                    "target": {
                        "entity_id": "button.thermann_shadow_restore_recommended_preferences"
                    },
                    "confirmation": {
                        "text": "Restore shadow recommendations and confirmed Aurora tariff defaults? Entity mappings, meter verification/direction and native references stay unchanged. This sends no heater commands."
                    },
                },
            },
        ]
    )
    diagnostics = [
        {
            "type": "entities",
            "title": "Connection and simulated cycles",
            "entities": [
                f"sensor.thermann_shadow_{key}"
                for key in (
                    "cloud_health",
                    "status_age",
                    "forecast_age",
                    "simulated_cycle_state",
                    "simulated_cycle_count",
                    "simulated_stop_count",
                    "suppressed_switching_episodes",
                    "simulated_session_cost",
                    "observed_request_attempts",
                    "observed_requests_per_hour",
                    "reported_schedule_window",
                    "t_comfort_reference",
                    "device_clock_check",
                )
            ],
        },
        {
            "type": "markdown",
            "content": "## Reasons & warnings\n{% for item in state_attr('sensor.thermann_shadow_controller','reasons') or [] %}\n- {{ item }}\n{% endfor %}\n{% for item in state_attr('sensor.thermann_shadow_controller','warnings') or [] %}\n- {{ item }}\n{% endfor %}\n### Simulated cycle / forecast\n`{{ state_attr('sensor.thermann_shadow_controller','cycle') }}`\n\n`{{ state_attr('sensor.thermann_shadow_controller','forecast') }}`\n\nPhysical heating is **unverified**. Session counters/ideal energy reset on restart or changed preferences; prevented-switching episodes are not a measured command saving. No simulation restores or switches the heater. 30-minute cloud polls can include status→refresh→replay (3 attempts); 48 cycles does not mean 48 HTTP requests or a known quota. The planner adds zero requests.",
        },
        {
            "type": "markdown",
            "content": "### Hypothetical windows\n{% for item in state_attr('sensor.thermann_shadow_controller','windows') or [] %}\n- {{ item.start }} → {{ item.end }} UTC · {{ item.source }}\n{% endfor %}\nNative clock: compare manually with Hobart {{ now().strftime('%a %d %b %H:%M') }} after DST changes. Tariff 93 remains fixed AEST. T-Comfort 10°C is not a usable comfort reserve. Neither Schedule permission nor simulated heating proves element power.",
        },
    ]
    return {
        "title": "Thermann Hot Water",
        "views": [
            {
                "title": "Hot Water",
                "path": "thermann-shadow",
                "icon": "mdi:water-boiler",
                "cards": main,
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


def main():
    (ROOT / "shadow_controller/dashboard.yaml").write_text(
        yaml.safe_dump(build(), sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    for filename in (PACKAGE / "strings.json", PACKAGE / "translations/en.json"):
        data = json.loads(filename.read_text(encoding="utf-8"))
        for step in (data["config"]["step"]["user"], data["options"]["step"]["init"]):
            step["description"] = (
                "Read local HA states only; no heater commands, MQTT writes or cloud requests. Optional PV/load forecast mappings require timestamped published forecast series. Configure and dashboard controls share the same stored preferences."
            )
            step["data"].update(
                {
                    "forecast_pv": "Optional published PV forecast",
                    "forecast_load": "Optional published household load forecast",
                }
            )
        step = data["options"]["step"]["settings"]
        step["description"] = (
            "Local shadow preferences only; no setting enables execution. Dashboard controls use these exact same saved values. Recommended/original defaults and guidance are on the Settings dashboard. Morning is before noon; afternoon after noon; tariff peak times must increase. Aurora 93 uses fixed AEST, weekends off-peak. Custom weekly periods require gap-free coverage."
        )
        step["data"] = {key: meta.name for key, meta in settings.CATALOG.items()}
        data["options"]["error"]["invalid_settings"] = (
            "Nothing saved. Check finite planning bounds; morning before noon and afternoon after noon; increasing tariff times without overlaps; custom weekly coverage; T-Comfort reference not above expected native target. No heater settings were changed."
        )
        filename.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
