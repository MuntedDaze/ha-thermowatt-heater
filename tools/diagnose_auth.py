"""Owner-approved diagnostic entrypoint. Never started by the add-on."""

import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "thermowatt-heater"))
from thermowatt_bridge import CloudError, MyThermowattBridge, load_options  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="One explicit login; no heater reads or commands.")
    parser.add_argument("--allow-single-login", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        options = load_options(args.data_dir / "options.json")
        if options.get("commands_enabled", False):
            logging.error("Diagnostic refused: commands must be disabled.")
            return 1
        if not options.get("cloud_enabled", False):
            logging.error("Diagnostic refused: cloud access must be explicitly enabled.")
            return 1
        bridge = MyThermowattBridge(options, data_dir=args.data_dir)
        try:
            bridge.diagnose_auth_once()
            return 0
        except CloudError as error:
            logging.warning("Diagnostic stopped: %s. No retry.", error)
            return 1
        finally:
            bridge.session.close()
    except Exception:
        logging.error("Diagnostic stopped: configuration, storage or internal error. No retry.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
