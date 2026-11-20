"""Native, optional Thermowatt dashboard. Never modify the household dashboard."""

import argparse
import importlib
from pathlib import Path
import sys
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_homeowner")
package.__path__ = [str(ROOT / "custom_components/thermann_shadow")]
sys.modules[package.__name__] = package
naming = importlib.import_module(f"{package.__name__}.naming")
settings = importlib.import_module(f"{package.__name__}.settings")


def sensor(name, label):
    return {"entity": naming.entity_id("sensor", name), "name": label}


def note(text):
    return {"type": "markdown", "content": text}


def rows(title, entities):
    return {"type": "entities", "title": title, "show_header_toggle": False, "entities": entities}


def configure(label="Open settings and diagnostic report"):
    return {
        "type": "button",
        "name": label,
        "icon": "mdi:cog-outline",
        "tap_action": {
            "action": "navigate",
            "navigation_path": "/config/integrations/integration/thermann_shadow",
        },
    }


def action(name, label):
    return {
        "type": "button",
        "name": label,
        "icon": "mdi:water-boiler",
        "tap_action": {
            "action": "perform-action",
            "perform_action": "button.press",
            "target": {"entity_id": naming.entity_id("button", name)},
            "confirmation": {"text": f"{label}? Existing controller safeguards still apply."},
        },
    }


def build():
    views = [
        {
            "title": "Home",
            "path": "home",
            "icon": "mdi:home",
            "cards": [
                note(
                    "# Thermowatt\nComfortable hot water with cheaper electricity and useful solar.\n\n**Current plan:** {{ states('sensor.thermann_shadow_current_heating_plan') }}\n\nThe latest temperature is at the **bottom** of the tank. It does not describe every litre of hot water."
                ),
                rows(
                    "Your hot water",
                    [
                        {
                            "entity": "switch.thermann_shadow_automatic_heater_control",
                            "name": "Automatic heating",
                        },
                        sensor("Thermann mode", "Confirmed cloud mode"),
                        sensor("Thermann target", "Reported thermostat target"),
                        sensor("Bottom temperature", "Latest bottom temperature"),
                        sensor("Status age", "Minutes since cloud observation"),
                        sensor("Heater element state", "Heating estimate"),
                        sensor("Circuit measurement mode", "Circuit meter"),
                    ],
                ),
                rows(
                    "What happens next",
                    [
                        sensor("Current tariff", "Electricity period"),
                        sensor("Next tariff change", "Next price boundary"),
                        sensor("Next intended action", "Requested mode"),
                        sensor("Next heating start", "Planned start"),
                        sensor("Solar boost status", "Optional solar heating"),
                        sensor("Cloud health", "Cloud connection"),
                        sensor("Controller fault", "Heating control problem"),
                    ],
                ),
                configure("Copy diagnostic report / settings"),
                note(
                    "**Cloud OFF is a software state, not electrical isolation.** Without a dedicated circuit meter, physical element ON/OFF remains unverified. Native protective cycles, manual changes and outages can still occur."
                ),
            ],
        },
        {
            "title": "Controls",
            "path": "controls",
            "icon": "mdi:gesture-tap",
            "cards": [
                note(
                    "# Everyday controls\n**Hold** preserves owner control. **Resume** re-inspects before normal policy can act. The **12hr Override 62°C** explicitly permits comfort heating, including peak hours; it expires after 12 hours. Native protections and command verification remain.\n\nTurning automatic heating off stops new routine commands; it does not electrically isolate the heater or cancel a command already sent."
                ),
                rows(
                    "Preferences",
                    [
                        {
                            "entity": "switch.thermann_shadow_automatic_heater_control",
                            "name": "Automatic heating",
                        },
                        {
                            "entity": naming.entity_id(
                                "switch", settings.CATALOG["optional_solar_boost"].name
                            ),
                            "name": "Enable optional solar boost",
                        },
                        sensor("12hr Override ends", "Override ends"),
                    ],
                ),
                action("Hold heater (owner override)", "Hold automatic heating"),
                action("Resume automatic control", "Resume automatic heating"),
                action("12hr Override 62°C", "12hr Override 62°C"),
                action("Cancel 12hr Override", "Cancel override"),
                rows(
                    "Holiday dates",
                    [
                        {
                            "entity": "date.thermann_shadow_holiday_departure_date",
                            "name": "Leave home",
                        },
                        {
                            "entity": "date.thermann_shadow_holiday_return_date",
                            "name": "Return home",
                        },
                    ],
                ),
                action("Cancel holiday mode", "Cancel holiday"),
                note(
                    "**Fault recovery:** check the official Thermann app and connection first. Acknowledgement does not repeat an uncertain command or unlock authentication. If OFF restoration is unconfirmed, choose your intended mode in the official app; cloud access may still be unavailable."
                ),
                action("Acknowledge controller fault", "Acknowledge checked fault"),
            ],
        },
        {
            "title": "Heating preferences",
            "path": "heating",
            "icon": "mdi:thermometer-water",
            "cards": [
                note(
                    "# Heating preferences\nOpen **Configure → Hot Water** for target temperatures and peak permissions. Open **Solar & Meters → Weekend and heating preferences** for weekend solar, sunset, restart cooldown and low-water warnings. Every field includes help. Protected changes require automatic heating off. Your saved settings are retained."
                ),
                rows(
                    "Selected targets",
                    [
                        sensor("Overnight baseline target", "Night/weekend baseline"),
                        sensor("Normal storage target", "Normal weekday/daytime storage"),
                        sensor("Solar boost target", "Optional extra solar storage"),
                        sensor("Peak heating policy", "Heating during peak periods"),
                        sensor("Optional solar boost enabled", "Extra solar storage enabled"),
                    ],
                ),
                configure("Configure heating preferences"),
                note(
                    "**Owner example: 45 / 62 / 70°C.** The thermostat maintains the chosen setpoint with approximately 8°C hysteresis. Weekend PV of at least 500 W for 15 continuous minutes opens 62°C comfort heating; this deliberately permits off-peak grid assistance. Optional 70°C has stronger measured-surplus and economic requirements. The daytime latch avoids reacting to each cloud; configured sunset/end limits return to baseline.\n\nThese are this owner's choices, not a universal water-hygiene recommendation. Follow appliance instructions and your plumber's advice. Occasional hotter cycles do not independently establish hygiene compliance."
                ),
            ],
        },
        {
            "title": "Electricity and optimisation",
            "path": "electricity",
            "icon": "mdi:solar-power",
            "cards": [
                note(
                    "# Electricity and optimisation\n**Configure → Electricity Tariffs** explains your prices and guided schedule. Peak is usually dearer; off-peak cheaper; shoulder intermediate. Use your retail contract, not a network price assumed to be your bill. Fixed-standard clocks ignore daylight saving; local clocks follow it.\n\n**Cloud polling** is set once, in the Thermann Hot Water app options (Smart, with an automatic fixed 30-minute fallback); this controller follows it automatically. **Configure → Advanced/System → Data freshness** only sets how old readings may be."
                ),
                rows(
                    "Local electricity",
                    [
                        sensor("Measured PV AC output", "Usable inverter solar power"),
                        sensor("Measured house load", "Household power"),
                        sensor("Measured signed grid", "Raw signed grid power"),
                        sensor("Measured grid export", "Power exported"),
                        sensor("Measured grid import", "Power imported"),
                        sensor("Current import price", "Import price in dollars/kWh"),
                        sensor("Configured feed in rate", "Export payment in dollars/kWh"),
                        sensor("Household forecast quality", "Forecast reliability"),
                    ],
                ),
                rows(
                    "Cloud requests and estimates",
                    [
                        sensor("Next cloud poll", "Next useful cloud check"),
                        sensor("Cloud poll interval", "Seconds between cloud checks"),
                        sensor(
                            "Cloud requests in last 24 hours", "Actual request attempts in 24 hours"
                        ),
                        sensor("Cloud request budget remaining", "Remaining request budget"),
                        sensor("Expected heating completion", "Estimated finish"),
                        sensor("Heating prediction confidence", "Estimate confidence"),
                        sensor("Learned heating rate", "Measured heating performance"),
                    ],
                ),
                configure("Configure electricity and polling"),
                note(
                    "**CT-free:** normal tariff heating needs no dedicated circuit meter or solar forecast. Experimental optional solar heating requires real, fresh, signed grid evidence and explicit setup. Estimated watts never verify physical heating. Learning needs clean dedicated-meter cycles; nominal predictions are deliberately conservative.\n\n**Smart polling:** quiet confirmed overnight targets can be left to the native thermostat for hours, with observations arranged before useful decisions. This delays detecting app changes (up to 8 hours). Every command still requires its exact current prior and confirmation. Original fixed fallback remains if the controller lease expires."
                ),
            ],
        },
        {
            "title": "Advanced and diagnostics",
            "path": "diagnostics",
            "icon": "mdi:stethoscope",
            "cards": [
                note(
                    "# Copy diagnostic report\nOpen the button below, choose **Configure → Copy diagnostic report**, select all text and copy it. On a computer use Ctrl+A then Ctrl+C inside the field; on a phone touch and hold → Select all → Copy. Closing does not save edits or send commands.\n\n**Download detailed diagnostics:** integration three-dot menu → Download diagnostics. This authenticated JSON uses the same allowlist. Review HA's surrounding system metadata before sharing. Source names and device/MQTT identifiers are omitted."
                ),
                configure("Copy diagnostic report / Download detailed diagnostics"),
                rows(
                    "Engineering status",
                    [
                        sensor("Automatic control state", "Controller supervision"),
                        sensor("Automatic control reason", "Blocking reason code"),
                        sensor(
                            "Controller last evaluated", "Controller heartbeat (up to 15 minutes)"
                        ),
                        sensor("Last command result", "Last command outcome"),
                        sensor("Waiting to restore heat since", "Unconfirmed restoration since"),
                        sensor("Solar boost cooldown ends", "Restart cooldown ends"),
                        sensor("Why Thermowatt made this decision", "Decision evidence"),
                    ],
                ),
                note(
                    "Sensor mappings, qualification records and quotas remain in **Advanced/System** and **Solar & Meters**. They are engineering permissions, not everyday controls. Do not tick physical qualifications to hide a fault.\n\nThe heartbeat publishes genuine completed timestamps at most 15 minutes apart or on a supervision change. Local evaluation, solar supervision and command confirmations keep their normal fast timing; the exact latest evaluation is in the report. Existing 30-minute watchdogs remain conservative."
                ),
            ],
        },
    ]
    # The telemetry entity retains its historical ID even though its label changed.
    views[-1]["cards"][-2]["entities"][-1]["entity"] = naming.entity_id(
        "sensor", "Controller telemetry"
    )
    # Supported sections layout bounds desktop columns; HA stacks sections on a phone.
    for view in views:
        view["type"] = "sections"
        view["max_columns"] = 2
        view["sections"] = [{"type": "grid", "cards": [card]} for card in view.pop("cards")]
    return {"title": "Thermowatt", "views": views}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "homeowner/thermowatt.yaml"
    content = yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=95)
    if args.check:
        assert target.read_text(encoding="utf-8") == content
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
