"""Build a local exact-commit owner handoff, never a release or deployment."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

import yaml

PATHS = (
    "thermowatt-heater",
    "custom_components/thermann_shadow",
    "energy_monitoring",
    "homeowner",
    "README.md",
    "docs",
    "shadow_controller/FORECAST_SETUP.md",
)


def build(repo, commit, output):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Use the full reviewed commit SHA")
    archive = subprocess.run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "-C",
            str(repo),
            "archive",
            "--format=zip",
            commit,
            "--",
            *PATHS,
        ],
        capture_output=True,
        check=True,
    ).stdout
    contents = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for entry in source.infolist():
            if entry.is_dir():
                continue
            path = PurePosixPath(entry.filename)
            if path.parts[:3] == ("docs", "history", "audit"):
                continue  # historical captured runtime payloads are not owner installation files
            if (
                path.is_absolute()
                or ".." in path.parts
                or {".git", ".storage", "__pycache__"} & set(path.parts)
                or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}
                or path.name
                in {
                    "options.json",
                    "auth_store.json",
                    "auth_guard.json",
                    "tokens.json",
                    "thermowatt_config.json",
                }
            ):
                raise ValueError("Unexpected private or unsafe artifact path")
            contents[entry.filename] = source.read(entry)
    required = (
        "thermowatt-heater/config.yaml",
        "custom_components/thermann_shadow/manifest.json",
        "docs/pre-review/OWNER_INSTALLATION.md",
    )
    if not all(path in contents for path in required):
        raise ValueError("Commit does not contain the complete owner handoff")
    addon = yaml.safe_load(contents[required[0]])
    controller = json.loads(contents[required[1]])
    if addon["slug"] != "thermowatt_boiler" or controller["domain"] != "thermann_shadow":
        raise ValueError("Installation identity mismatch")
    manifest = {
        "commit": commit,
        "bridge_version": addon["version"],
        "controller_version": controller["version"],
        "sha256": {
            path: hashlib.sha256(data).hexdigest() for path, data in sorted(contents.items())
        },
        "installs_or_starts_anything": False,
        "bridge_installation": "normal_update_after_approved_main_merge",
    }
    contents["REVIEWED_MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as target:
        for path, data in sorted(contents.items()):
            target.writestr(zipfile.ZipInfo(path, (2000, 1, 1, 0, 0, 0)), data)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    digest = build(Path(__file__).resolve().parents[1], args.commit, args.out)
    print(f"SHA256 {digest}  {args.out.name}")


if __name__ == "__main__":
    main()
