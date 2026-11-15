"""Source-only staging against disposable local Git fixtures; no HA connection."""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
checkout = importlib.import_module("owner_checkout")
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
    git(repo, "remote", "add", "origin", checkout.ORIGIN)
    for path, content in {
        "thermowatt-heater/config.yaml": "slug: thermowatt_boiler\nversion: '1.3.15'\n",
        "custom_components/thermann_shadow/manifest.json": '{"domain":"thermann_shadow","version":"0.11.0"}',
        "tools/owner_checkout.py": "# synthetic staging source\n",
        "README.md": "# Synthetic reviewed guide\n",
        "docs/history/audit/synthetic_config.json": '{"fixture":"DO_NOT_EXPORT"}',
        "shadow_controller/FORECAST_SETUP.md": "# Synthetic forecast guide\n",
        "energy_monitoring/generated/packages/thermann_energy.yaml": "template: []\n",
        "energy_monitoring/entity_map.yaml": "version: 1\n",
        "docs/pre-review/OWNER_INSTALLATION.md": "# Synthetic owner guide\n",
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


def test_staging_preserves_identity_original_branch_and_any_external_private_state(
    source, tmp_path
):
    repo, root, before, reviewed = source
    private = tmp_path / "data.json"
    private.write_text('{"synthetic_guard":"locked","generation":7}', encoding="utf-8")
    record = tmp_path / "share" / "record.json"
    plan = checkout.inspect(repo, "12345678_thermowatt_boiler", reviewed, (root,))
    assert plan["reviewed_version"] == "1.3.16" and not record.exists()
    result = checkout.stage(repo, "12345678_thermowatt_boiler", reviewed, record, (root,))
    assert result["original_commit"] == before and result["original_branch"] == "installed-fixture"
    assert git(repo, "rev-parse", "HEAD") == reviewed
    assert checkout.stage(repo, "12345678_thermowatt_boiler", reviewed, record, (root,)) == result
    assert json.loads(private.read_text(encoding="utf-8"))["generation"] == 7


def test_changed_or_wrong_identity_cache_is_never_overwritten(source, tmp_path):
    repo, root, before, reviewed = source
    assert checkout.locate("12345678_thermowatt_boiler", (root, root)) == repo.resolve()
    other = tmp_path / "other-cache"
    (other / "12345678").mkdir(parents=True)
    with pytest.raises(checkout.StageError, match="expected_one_existing_repository_cache"):
        checkout.locate("12345678_thermowatt_boiler", (root, other))
    for slug in ("local_thermowatt_boiler", "87654321_thermowatt_boiler"):
        with pytest.raises(checkout.StageError):
            checkout.inspect(repo, slug, reviewed, (root,))
    (repo / "owner.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(checkout.StageError, match="source_cache_has_changes"):
        checkout.stage(
            repo, "12345678_thermowatt_boiler", reviewed, tmp_path / "record.json", (root,)
        )
    assert git(repo, "rev-parse", "HEAD") == before
    assert (repo / "owner.txt").read_text(encoding="utf-8") == "preserve"


def test_bundle_uses_only_committed_source_and_has_verifiable_hashes(source, tmp_path):
    repo, _, _, reviewed = source
    (repo / "owner-secret.txt").write_text("SYNTHETIC_PRIVATE", encoding="utf-8")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    assert bundle.build(repo, reviewed, first) == bundle.build(repo, reviewed, second)
    with zipfile.ZipFile(first) as archive:
        manifest = json.loads(archive.read("REVIEWED_MANIFEST.json"))
        assert manifest["commit"] == reviewed and manifest["bridge_version"] == "1.3.16"
        assert not any("owner-secret" in name or ".git/" in name for name in archive.namelist())
        assert not any(name.startswith("docs/history/audit/") for name in archive.namelist())
        import hashlib

        for path, digest in manifest["sha256"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == digest
    with pytest.raises(FileExistsError):
        bundle.build(repo, reviewed, first)
