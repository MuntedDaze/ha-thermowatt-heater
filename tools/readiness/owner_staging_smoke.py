"""Actual Supervisor source loading, disposable checkout, no daemon/network."""

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import yaml

from supervisor.const import SUPERVISOR_VERSION, UpdateChannel
from supervisor.store.git import GitRepo
from supervisor.store.data import StoreData

sys.path.insert(0, "/owner-tools")
from owner_checkout import stage, ORIGIN  # noqa: E402


def denied(*args, **kwargs):
    raise AssertionError("Owner staging test attempted external I/O")


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
        caches = root / "git"
        repo = caches / "12345678"
        app = repo / "thermowatt-heater"
        shutil.copytree("/addon-source", app)
        config_file = app / "config.yaml"
        reviewed_config = config_file.read_text()
        config = yaml.safe_load(reviewed_config)
        config_file.write_text(yaml.safe_dump({**config, "version": "0.0.1"}))
        git(repo, "init", "-b", "installed")
        git(repo, "remote", "add", "origin", ORIGIN)
        git(repo, "add", ".")
        git(repo, "commit", "-m", "Synthetic old source")
        old = git(repo, "rev-parse", "HEAD")
        config_file.write_text(reviewed_config)
        git(repo, "commit", "-am", "Synthetic reviewed source")
        reviewed = git(repo, "rev-parse", "HEAD")
        git(repo, "switch", "-c", "previous-source", old)
        private = root / "private-data.json"
        private.write_text('{"synthetic_guard":"locked","generation":7}')
        before = hashlib.sha256(private.read_bytes()).hexdigest()
        plan = stage(repo, "12345678_thermowatt_boiler", reviewed, root / "record.json", (caches,))
        coresys = SimpleNamespace(
            run_in_executor=execute,
            store=SimpleNamespace(repositories={}),
            updater=SimpleNamespace(channel=UpdateChannel.STABLE),
            apps=SimpleNamespace(installed=[], data=SimpleNamespace(system={})),
        )
        loader = GitRepo(coresys, repo, ORIGIN)
        await loader.load()  # real Supervisor fsck/origin validation, no pull
        assert loader.repo.active_branch.name == plan["pinned_branch"]
        assert loader.repo.head.commit.hexsha == reviewed
        catalog = await StoreData(coresys)._read_apps_folder(repo, "12345678")
        assert set(catalog) == {"12345678_thermowatt_boiler"}
        assert str(catalog["12345678_thermowatt_boiler"]["version"]) == str(config["version"])
        assert hashlib.sha256(private.read_bytes()).hexdigest() == before
        assert git(repo, "status", "--porcelain") == ""
        print(
            json.dumps(
                {
                    "supervisor": str(SUPERVISOR_VERSION),
                    "pinned_source_and_catalog": True,
                    "identity_and_private_state_preserved": True,
                    "daemon_started": False,
                    "vendor_requests": 0,
                }
            )
        )


asyncio.run(main())
