"""Real Supervisor load/pull/catalog with a local public-origin substitute.

CI only. No daemon, installation or live network. URL rewrite is scoped to this
temporary test's Git config; it is never a proposed owner installation method.
"""

import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from types import SimpleNamespace

import yaml

from supervisor.const import SUPERVISOR_VERSION, UpdateChannel
from supervisor.store.git import GitRepo
from supervisor.store.data import StoreData
from supervisor.store.utils import get_hash_from_repository

PUBLIC_ORIGIN = "https://github.com/MuntedDaze/ha-thermowatt-heater"
ORIGIN = os.environ.get("THERMANN_TEST_ORIGIN", PUBLIC_ORIGIN)
assert ORIGIN in (PUBLIC_ORIGIN, PUBLIC_ORIGIN + ".git")


def denied(*args, **kwargs):
    raise AssertionError("Normal-update smoke attempted external network")


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
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


async def execute(function, *args, **kwargs):
    return function(*args, **kwargs)


async def main():
    socket.socket.connect = socket.socket.connect_ex = denied
    socket.create_connection = socket.getaddrinfo = denied
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        upstream = root / "upstream"
        upstream.mkdir()
        shutil.copytree("/addon-source", upstream / "thermowatt-heater")
        config_path = upstream / "thermowatt-heater/config.yaml"
        candidate = config_path.read_text()
        version = yaml.safe_load(candidate)["version"]
        config_path.write_text(yaml.safe_dump({**yaml.safe_load(candidate), "version": "1.3.13"}))
        git(upstream, "init", "-b", "main")
        git(upstream, "add", ".")
        git(upstream, "commit", "-m", "Synthetic installed source")
        repo_id = get_hash_from_repository(ORIGIN)
        full_id = f"{repo_id}_thermowatt_boiler"
        cache = root / "cache" / repo_id
        git(root, "clone", str(upstream), str(cache))
        git(cache, "remote", "set-url", "origin", ORIGIN)
        # Even real ls-remote/fetch execute locally, under --network none.
        git_config = root / "gitconfig"
        git_config.write_text(
            f'[url "{upstream.as_uri()}"]\n\tinsteadOf = {ORIGIN}\n[protocol "file"]\n\tallow = always\n'
        )
        os.environ["GIT_CONFIG_GLOBAL"] = str(git_config)
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        private = root / "private"
        private.mkdir()
        for name, value in {
            "auth_state.json": {"mode": "blocked", "generation": 7, "reason": "synthetic"},
            "command_state.json": {"version": 1, "pending": {"payload": "off@62"}},
            "options.json": {"commands_enabled": False, "auth_retry_generation": 7},
            "usage.json": {"synthetic_attempts": 112},
            "ha-entry.json": {
                "entry_id": "existing",
                "entities": ["old_entity"],
                "sources": {"heater": "water_heater.existing"},
            },
        }.items():
            (private / name).write_text(json.dumps(value))
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in private.iterdir()}
        coresys = SimpleNamespace(
            run_in_executor=execute,
            store=SimpleNamespace(repositories={}),
            updater=SimpleNamespace(channel=UpdateChannel.STABLE),
            apps=SimpleNamespace(installed=[], data=SimpleNamespace(system={})),
        )
        loader = GitRepo(coresys, cache, ORIGIN)
        await loader.load()

        async def catalog_version():
            catalog = await StoreData(coresys)._read_apps_folder(cache, repo_id)
            assert set(catalog) == {full_id}
            return str(catalog[full_id]["version"])

        assert await catalog_version() == "1.3.13"
        # Skip only daemon Job preconditions; execute the entire real pull body.
        pull = inspect.unwrap(GitRepo.pull)
        assert await pull(loader) is False
        config_path.write_text(candidate)
        git(upstream, "commit", "-am", "Synthetic approved main update")
        assert await pull(loader) is True
        assert await catalog_version() == str(version)
        assert await pull(loader) is False
        # A forward recovery build on the same main branch is offered normally;
        # do not roll private auth/command/usage state back to an older backup.
        config_path.write_text(yaml.safe_dump({**yaml.safe_load(candidate), "version": "99.0.0"}))
        git(upstream, "commit", "-am", "Synthetic reviewed forward recovery")
        assert await pull(loader) is True
        assert await catalog_version() == "99.0.0"
        assert await pull(loader) is False
        assert loader.repo.active_branch.name == "main"
        # get-url expands the deliberate test-only insteadOf rewrite; inspect
        # the stored URL to verify Supervisor preserved the registered source.
        assert git(cache, "config", "--get", "remote.origin.url") == ORIGIN
        assert {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in private.iterdir()
        } == hashes
        print(
            json.dumps(
                {
                    "supervisor": str(SUPERVISOR_VERSION),
                    "repository_id": repo_id,
                    "same_identity_update_and_forward_recovery": True,
                    "private_state_unchanged": True,
                    "live_network": False,
                    "container_install_or_backup_restore_tested": False,
                }
            )
        )


asyncio.run(main())
