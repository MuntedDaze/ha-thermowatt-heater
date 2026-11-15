"""Write a throwaway Home Assistant config directory holding only the package.

Used by CI to run Home Assistant's own ``check_config`` against the generated
package inside the official image with networking disabled. It never touches
a real Home Assistant installation.

    python energy_monitoring/ha_check.py --out /tmp/cfg            # the committed map
    python energy_monitoring/ha_check.py --out /tmp/cfg --meters 3 # all three CTs mapped
"""

import argparse
from pathlib import Path
import sys

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_monitoring.build import dump  # noqa: E402
from energy_monitoring.mapping import DEFAULT_MAP, validate  # noqa: E402
from energy_monitoring.package import build_package  # noqa: E402

CONFIGURATION = (
    "homeassistant:\n"
    "  name: Energy monitoring check\n"
    "  packages:\n"
    "    thermann_energy: !include packages/thermann_energy.yaml\n"
)


def write(out: Path, meters: int, minimal: bool = False) -> None:
    raw = yaml.safe_load(DEFAULT_MAP.read_text(encoding="utf-8"))
    if minimal:
        for group in ("grid", "solar", "house"):
            for key, value in raw[group].items():
                if isinstance(value, str):
                    raw[group][key] = ""
        raw["appliances"] = []
    for index, circuit in enumerate(raw["circuits"][:meters]):
        circuit["power"] = f"sensor.synthetic_ct_{circuit['key']}_power"
        if index == 1:  # one circuit with a native energy entity, the rest integrated
            circuit["energy"] = f"sensor.synthetic_ct_{circuit['key']}_energy"
    if meters:
        raw["appliances"][0]["circuit"] = raw["circuits"][meters - 1]["key"]
    (out / "packages").mkdir(parents=True, exist_ok=True)
    (out / "configuration.yaml").write_text(CONFIGURATION, encoding="utf-8", newline="\n")
    (out / "packages/thermann_energy.yaml").write_text(
        dump(build_package(validate(raw))), encoding="utf-8", newline="\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--meters", type=int, default=0, choices=range(4))
    parser.add_argument("--minimal", action="store_true", help="no solar or household meters")
    args = parser.parse_args(argv)
    write(args.out, args.meters, args.minimal)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
