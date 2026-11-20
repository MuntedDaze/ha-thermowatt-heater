"""Exact source bundles for controller/dashboard files; never bridge cache staging."""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
bundle = importlib.import_module("build_owner_bundle")


def git(repo, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "git"
    repo = root / "12345678"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/MuntedDaze/ha-thermowatt-heater")
    for path, content in {
        "thermowatt-heater/config.yaml": "slug: thermowatt_boiler\nversion: '1.3.15'\n",
        "custom_components/thermann_shadow/manifest.json": '{"domain":"thermann_shadow","version":"0.11.0"}',
        "README.md": "# Synthetic reviewed guide\n",
        "docs/history/audit/synthetic_config.json": '{"fixture":"DO_NOT_EXPORT"}',
        "shadow_controller/FORECAST_SETUP.md": "# Synthetic forecast guide\n",
        "energy_monitoring/generated/packages/thermann_energy.yaml": "template: []\n",
        "energy_monitoring/entity_map.yaml": "version: 1\n",
        "homeowner/thermowatt.yaml": "title: Synthetic Thermowatt\nviews: []\n",
        "docs/owner/UPGRADE.md": "# Synthetic current owner upgrade\n",
        "docs/history/pre-review/OWNER_INSTALLATION.md": "# Synthetic owner guide\n",
    }.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Synthetic checkpoint")
    before = git(repo, "rev-parse", "HEAD")
    (repo / "thermowatt-heater/config.yaml").write_text(
        "slug: thermowatt_boiler\nversion: '1.3.16'\n", encoding="utf-8"
    )
    git(repo, "commit", "-am", "Synthetic reviewed candidate")
    reviewed = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-c", "installed-fixture", before)
    return repo, root, before, reviewed


def test_bundle_uses_only_committed_source_and_has_verifiable_hashes(source, tmp_path):
    repo, _, _, reviewed = source
    (repo / "owner-secret.txt").write_text("SYNTHETIC_PRIVATE", encoding="utf-8")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    assert bundle.build(repo, reviewed, first) == bundle.build(repo, reviewed, second)
    with zipfile.ZipFile(first) as archive:
        manifest = json.loads(archive.read("REVIEWED_MANIFEST.json"))
        assert manifest["commit"] == reviewed and manifest["bridge_version"] == "1.3.16"
        assert manifest["bridge_installation"] == "normal_update_after_approved_main_merge"
        assert "tools/owner_checkout.py" not in archive.namelist()
        assert not any("owner-secret" in name or ".git/" in name for name in archive.namelist())
        assert not any(name.startswith("docs/history/audit/") for name in archive.namelist())
        import hashlib

        for path, digest in manifest["sha256"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == digest
    with pytest.raises(FileExistsError):
        bundle.build(repo, reviewed, first)
