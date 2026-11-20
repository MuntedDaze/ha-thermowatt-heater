"""Index every current setting (and name the retired keys) from the validated metadata."""

import argparse
import importlib
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_owner_settings")
package.__path__ = [str(ROOT / "custom_components/thermann_shadow")]
sys.modules[package.__name__] = package
config = importlib.import_module(f"{package.__name__}.config")
layout = importlib.import_module(f"{package.__name__}.configuration")
text = importlib.import_module(f"{package.__name__}.configuration_text")
settings = importlib.import_module(f"{package.__name__}.settings")


def build():
    lines = [
        "# Every Thermowatt setting",
        "",
        "[Handbook](owner/HANDBOOK.md) · [Screens/report](owner/INTERFACE.md)",
        "",
        "Generated from the same catalogue and form-unit conversion used by the integration.",
        "Current saved values always take precedence. Defaults below are schema fallbacks for",
        "missing historical fields, not permission to overwrite the household. Fresh setup",
        "separately starts with flat/unverified tariffs, HA's zone, local clock,62°C baseline/",
        "normal and optional boost off. Existing45/62/70 and all mappings/IDs are retained.",
        "",
        "Open Settings → Devices & services → Thermann Controller → Configure.",
        "Each page saves separately. Closing without Submit changes nothing. Prices are",
        "cents/kWh here, percentages are0–100; native entity units/IDs remain compatible.",
        "",
        "## Index",
        "",
    ]
    for page in layout.PAGES:
        lines.append(f"- [{text.TITLES[page]}](#{page.replace('_', '-')})")
    lines += [
        "- [Sensor mappings](#sensor-mappings)",
        "- [Retired settings](#retired-settings)",
        "",
    ]
    for page, keys in layout.PAGES.items():
        lines += [
            f'<a id="{page.replace("_", "-")}"></a>',
            f"## {text.TITLES[page]}",
            "",
            text.DESCRIPTIONS[page].replace("{detail}", "").strip(),
            "",
        ]
        for key in keys:
            meta = settings.CATALOG[key]
            label, help_text = layout.FIELDS[key]
            value = layout.display_value(key, config.DEFAULT_OPTIONS[key])
            allowed = (
                " / ".join(meta.choices)
                if meta.choices
                else (
                    f"{layout.display_value(key, meta.low):g}–{layout.display_value(key, meta.high):g}"
                    if meta.kind == "number"
                    else {
                        "switch": "On / Off",
                        "time": "24-hour local/tariff time as described",
                        "form": "validated schedule table",
                        "text": "as described",
                    }.get(meta.kind, meta.kind)
                )
            )
            locked = (
                "Turn Automatic off before changing."
                if key in settings.LOCKED_WHILE_ACTIVE
                else "Existing active-control guard applies where relevant."
            )
            if key == "time_zone":
                # OS/tzdata builds expose different aliases. Do not generate a
                # platform-dependent list of hundreds of zones in an owner guide.
                allowed = "A supported IANA zone, for example Australia/Hobart"
            lines += [
                f"### {label}",
                "",
                f"Stored key: `{key}`. Default: `{value}`. Allowed: {allowed}. Units: {layout.unit(key) or meta.unit or 'none'}. {locked}",
                "",
                help_text,
                "",
            ]
    lines += [
        "## Sensor mappings",
        "",
        "Bridge sources are in Advanced/System → Bridge status readings; other sources",
        "are in Solar & Meters → Solar and meter readings. Map actual existing entities.",
        "",
    ]
    for key, (label, help_text) in layout.SOURCES.items():
        lines += [f"### {label}", "", f"Mapping key: `{key}`. {help_text}", ""]
    lines += [
        "## Retired settings",
        "",
        "These keys are not settings any more: nothing reads, validates or shows them.",
        "Controller 0.18.0 moved any saved value, unchanged, into the unread",
        "`retired_options` record (kept only for rollback and audit). They are never",
        "requirements; see [OPERATING_POLICY.md](OPERATING_POLICY.md) section 1.1.",
        "",
        ", ".join(f"`{key}`" for key in sorted(config.RETIRED_OPTIONS)),
        "",
        "## Practical starting choices",
        "",
        "Use the household's verified contract and appliance settings. The owner retains",
        "45/62/70, fixed AEST, verified Aurora periods and export-positive GoodWe; these are",
        "examples, not universal defaults. Weekend 500 W trigger, end 18:00 and cooldown 10 min",
        "are editable starting preferences. Minimum 15-minute ordinary command spacing remains.",
        "Cloud polling is chosen once, in the Thermann Hot Water app (Smart). Keep physical",
        "qualifications truthful. Do not change token/lockout state to clear a warning.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "docs/SETTINGS.md"
    content = build()
    if args.check:
        assert target.read_text(encoding="utf-8") == content
    else:
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
