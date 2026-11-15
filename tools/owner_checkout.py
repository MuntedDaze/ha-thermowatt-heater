"""Future owner-only source staging inside Supervisor; default is inspection.

Never installs/starts an add-on, edits options/auth/data, or contacts Thermann.
--stage requires separate owner approval and a stopped existing bridge. This
advanced cache checkout is version-dependent; follow OWNER_INSTALLATION.md.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOTS = (Path("/data/addons/git"), Path("/data/apps/git"))
ORIGIN = "https://github.com/munteddaze/ha-thermowatt-heater"
APP_PATH = "thermowatt-heater/config.yaml"


class StageError(RuntimeError):
    """Deliberately public, bounded error code; raw subprocess errors stay private."""


def locate(slug, roots=ROOTS):
    if not re.fullmatch(r"[0-9a-f]{8}_thermowatt_boiler", slug):
        raise StageError("use_existing_full_repository_addon_slug")
    prefix = slug.split("_")[0]
    # Supervisor path migrations may leave aliases. Count distinct resolved
    # caches, not two spellings of the same directory; distinct copies refuse.
    repos = {(root / prefix).resolve() for root in roots if (root / prefix).is_dir()}
    if len(repos) != 1:
        raise StageError("expected_one_existing_repository_cache")
    return repos.pop()


def git(repo, *args, optional=False):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.longpaths=true",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        if optional:
            return None
        raise StageError("git_operation_failed_no_private_output")
    return result.stdout.strip()


def inspect(repo, slug, commit, roots=ROOTS):
    if not re.fullmatch(r"[0-9a-f]{8}_thermowatt_boiler", slug):
        raise StageError("use_existing_full_repository_addon_slug")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise StageError("full_reviewed_commit_required")
    repo = repo.resolve()
    if repo.name != slug.split("_")[0] or repo.parent not in {root.resolve() for root in roots}:
        raise StageError("repository_path_does_not_match_existing_identity")
    origin = git(repo, "remote", "get-url", "origin")
    if origin.lower().removesuffix(".git").rstrip("/") != ORIGIN:
        raise StageError("unexpected_origin")
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise StageError("source_cache_has_changes_nothing_discarded")
    branch = git(repo, "symbolic-ref", "--short", "HEAD", optional=True)
    if branch is None:
        raise StageError("unexpected_detached_cache_ask_for_help")
    cached = git(repo, "cat-file", "-e", commit + "^{commit}", optional=True) is not None
    version = None
    if cached:
        config = yaml.safe_load(git(repo, "cat-file", "blob", commit + ":" + APP_PATH))
        if (
            not isinstance(config, dict)
            or config.get("slug") != "thermowatt_boiler"
            or "image" in config
        ):
            raise StageError("unexpected_reviewed_addon_identity_or_image")
        version = str(config["version"])
    return {
        "source_path": str(repo),
        "existing_slug": slug,
        "original_branch": branch,
        "original_commit": git(repo, "rev-parse", "HEAD"),
        "reviewed_commit": commit,
        "reviewed_version": version,
        "commit_cached": cached,
        "pinned_branch": "owner-reviewed-" + commit[:12],
        "installs_or_starts_bridge": False,
        "changes_private_options_or_auth": False,
    }


def stage(repo, slug, commit, record, roots=ROOTS):
    plan = inspect(repo, slug, commit, roots)
    if not plan["commit_cached"]:
        # Only this exact reachable public GitHub object is requested. No vendor
        # endpoint, account credential or mutable branch tip is used.
        git(repo, "fetch", "--depth=1", "origin", commit)
        plan = inspect(repo, slug, commit, roots)
        if not plan["commit_cached"]:
            raise StageError("reviewed_commit_was_not_fetched")
    if record.exists():
        old = json.loads(record.read_text(encoding="utf-8"))
        if (
            old.get("reviewed_commit") == commit
            and plan["original_commit"] == commit
            and plan["original_branch"] == plan["pinned_branch"]
            and old.get("existing_slug") == slug
        ):
            return old
        raise StageError("existing_staging_record_requires_review")
    if git(repo, "show-ref", "--verify", "refs/heads/" + plan["pinned_branch"], optional=True):
        raise StageError("pinned_branch_already_exists_requires_review")
    record.parent.mkdir(parents=True, exist_ok=True)
    # Persist a source-only recovery record before checkout. Contains no secrets.
    with record.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, indent=2)
        stream.write("\n")
    record.chmod(0o600)
    git(repo, "switch", "-c", plan["pinned_branch"], commit)
    if git(repo, "rev-parse", "HEAD") != commit:
        raise StageError("staged_head_mismatch_keep_bridge_stopped")
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--stage", action="store_true", help="owner-approved source checkout only")
    args = parser.parse_args(argv)
    try:
        repo = locate(args.slug)
        record = Path(__file__).resolve().parent.parent / "owner-checkout-record.json"
        if args.stage:
            if Path("/data/share") not in record.parents:
                raise StageError("run_reviewed_helper_from_data_share")
            plan = stage(repo, args.slug, args.commit, record)
        else:
            plan = inspect(repo, args.slug, args.commit)
        print(json.dumps(plan, indent=2))
        return 0
    except StageError as error:
        print(
            f"Staging stopped: {error}. Keep the existing bridge stopped. No install/start or private-state edit was attempted."
        )
        return 1
    except (OSError, ValueError, KeyError):
        # Never print arbitrary command stderr, YAML/options or a raw exception.
        print(
            "Staging refused or failed; keep the existing bridge stopped and inspect the local recovery record. No install/start or private-state edit was attempted."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
