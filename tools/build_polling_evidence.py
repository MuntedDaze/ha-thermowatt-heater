"""Readable comparison tables from actual-worker synthetic replay artifacts."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs/next-major"


def build():
    report = json.loads((ROOT / "SEASONAL_RESULTS.json").read_text())
    lines = [
        "# Reproducible polling comparison",
        "",
        "[Interpretation, limitations and validation](EVIDENCE.md). Every row is seven",
        "synthetic days through the actual production policy, controller, bridge worker,",
        "HTTP accounting and mocked MQTT/cloud. All strategies share weather/draw events",
        "and initial tank conditions. Amounts are marginal heater grid cost plus forgone",
        "export payment, adjusted to equal terminal stored energy; not a household bill.",
        "",
    ]
    for season in report["reports"]:
        lines += [
            f"## {season['season'].replace('_', ' ').title()}",
            "",
            "| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in season["runs"]:
            misses = sum(d["required_target_reached"] is False for d in row["days"].values())
            lines.append(
                f"| {'CT' if row['ct'] else 'No CT'} | {row['strategy']} | {row['http_total']} | {row['command_posts']} | {row['equal_terminal_cost_aud']:.4f} | {misses} | {row['maximum_healthy_status_age_minutes']:.1f} | {row['persistent_owner_detection_minutes']} |"
            )
        lines += [
            "",
            "### Actual HTTP categories",
            "",
            "| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in season["runs"]:
            counts = row["http_categories"]
            values = [
                str(counts.get(k, 0))
                for k in (
                    "status",
                    "command_refresh",
                    "confirmation",
                    "command",
                    "token_refresh",
                    "password_login",
                    "discovery",
                )
            ]
            lines.append(
                f"| {'CT' if row['ct'] else 'No CT'} / {row['strategy']} | "
                + " | ".join(values)
                + " |"
            )
        lines += [
            "",
            "Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,",
            "peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale",
            "planning minutes, prediction errors, command/decision history and failure events.",
            "",
        ]
    sensitivity = json.loads((ROOT / "AUTH_SENSITIVITY.json").read_text())["reports"][0]
    lines += [
        "## Synthetic20-minute session sensitivity",
        "",
        "This TTL is an explicit model assumption, not vendor evidence. The same inputs",
        "and real authentication/retry paths are used. Additional401 GETs are counted.",
        "",
        "| Meter | Strategy | All HTTP | Expired status401 | Refresh POST | Commands |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in sensitivity["runs"]:
        lines.append(
            f"| {'CT' if row['ct'] else 'No CT'} | {row['strategy']} | {row['http_total']} | {row['expired_status_401']} | {row['http_categories']['token_refresh']} | {row['command_posts']} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "COMPARISON.md"
    text = build()
    if args.check:
        assert path.read_text(encoding="utf-8") == text
    else:
        path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
