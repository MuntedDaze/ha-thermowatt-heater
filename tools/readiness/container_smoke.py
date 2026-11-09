"""Build-independent smoke checks on disposable CI Docker resources, never HA hosts.

Only invoke against a local image on an isolated test runner. No ports, devices,
Docker socket or HA directories are mounted into any test container.
"""

import argparse
from collections import Counter
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import uuid

FIXTURES = Path(__file__).resolve().parent
BROKER_IMAGE = "eclipse-mosquitto:2.0"
PYTHON = "/opt/venv/bin/python3"


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, check=False)
    if check and result.returncode:
        # All test data are synthetic; avoid echoing commands or environment values.
        raise RuntimeError(f"Docker {args[0]} failed: {result.stderr.decode()}")
    return result


def mount(source, destination, readonly=False):
    return f"type=bind,src={source},dst={destination}" + (",readonly" if readonly else "")


def copied_file(container, filename):
    copied = docker("cp", f"{container}:{filename}", "-", check=False)
    if copied.returncode:
        return b""
    with tarfile.open(fileobj=io.BytesIO(copied.stdout)) as archive:
        return archive.extractfile(archive.getmembers()[0]).read()


def wait_for(predicate, description, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError(f"Timed out: {description}")


def json_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def smoke(image, arch, output):
    prefix = f"tw-smoke-{uuid.uuid4().hex[:10]}"
    network = f"{prefix}-network"
    broker, supervisor, observer, addon = [
        f"{prefix}-{part}" for part in ("mqtt", "supervisor", "observer", "addon")
    ]
    containers = []
    results = {"architecture": arch, "image": image, "status": "FAIL"}
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thermowatt-smoke-") as temporary:
        temporary = Path(temporary)
        data, evidence, broker_config = [
            temporary / part for part in ("data", "evidence", "broker")
        ]
        for directory in (data, evidence, broker_config):
            directory.mkdir()
        data.chmod(0o700)
        options = {
            "email": "synthetic@example.invalid",
            "password": "SYNTHETIC_CLOUD_PASSWORD",
            "cloud_enabled": False,
            "commands_enabled": False,
            "auth_retry_generation": 1,
        }
        # Deliberately arm the guard so a default lockout cannot mask a cloud-disable bug.
        (data / "options.json").write_text(json.dumps(options))
        (data / "options.json").chmod(0o600)
        (data / "thermowatt_config.json").write_text(
            json.dumps(
                {
                    "device_uuid": "00000000-0000-4000-8000-000000000001",
                    "devices": {"SYNTHETIC123": {"name": "Synthetic heater"}},
                }
            )
        )
        (broker_config / "mosquitto.conf").write_text(
            "listener 1883 0.0.0.0\nallow_anonymous false\n"
            "password_file /mosquitto/config/password\nlog_dest stdout\nlog_type all\n"
        )
        try:
            facts = json.loads(docker("image", "inspect", image).stdout)[0]
            assert facts["Architecture"] == {"amd64": "amd64", "aarch64": "arm64"}[arch]
            assert facts["Config"]["Entrypoint"] == ["/init"]
            assert facts["Config"]["Cmd"] == ["/run.sh"]
            results["image_id"] = facts["Id"]
            facts_code = (
                "import certifi,json,pathlib,requests,importlib.metadata as m; "
                "assert pathlib.Path(certifi.where()).is_file(); "
                "assert requests.Session().verify is True; "
                "assert not any(pathlib.Path('/'+p).exists() for p in ['client.key','client.crt','root.pem']); "
                "print(json.dumps({p:m.version(p) for p in ['requests','paho-mqtt','urllib3','certifi']}))"
            )
            results["dependencies"] = json.loads(
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    PYTHON,
                    image,
                    "-c",
                    facts_code,
                ).stdout
            )
            docker("pull", BROKER_IMAGE)
            results["broker_digest"] = json.loads(docker("image", "inspect", BROKER_IMAGE).stdout)[
                0
            ]["RepoDigests"]
            docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "/bin/sh",
                "--mount",
                mount(broker_config, "/fixture"),
                BROKER_IMAGE,
                "-c",
                "mosquitto_passwd -b -c /fixture/password synthetic-mqtt SYNTHETIC_MQTT_PASSWORD && chown mosquitto:mosquitto /fixture/password && chmod 600 /fixture/password",
            )
            docker("network", "create", "--internal", network)
            assert json.loads(docker("network", "inspect", network).stdout)[0]["Internal"] is True
            results["network_internal"] = True

            def start(name, *arguments):
                containers.append(name)
                docker(
                    "run",
                    "--detach",
                    "--name",
                    name,
                    "--network",
                    network,
                    "--dns",
                    "127.0.0.1",
                    *arguments,
                )

            start(
                broker,
                "--network-alias",
                "mqtt",
                "--entrypoint",
                "mosquitto",
                "--mount",
                mount(broker_config, "/mosquitto/config", True),
                BROKER_IMAGE,
                "-c",
                "/mosquitto/config/mosquitto.conf",
            )
            wait_for(lambda: b"running" in docker("logs", broker).stdout, "isolated MQTT broker")
            broker_ip = json.loads(docker("inspect", broker).stdout)[0]["NetworkSettings"][
                "Networks"
            ][network]["IPAddress"]
            start(
                supervisor,
                "--network-alias",
                "supervisor",
                "--entrypoint",
                PYTHON,
                "--mount",
                mount(FIXTURES / "mock_supervisor.py", "/fixture.py", True),
                "--mount",
                mount(evidence, "/evidence"),
                image,
                "/fixture.py",
            )
            start(
                observer,
                "--entrypoint",
                PYTHON,
                "--mount",
                mount(FIXTURES / "mqtt_observer.py", "/fixture.py", True),
                "--mount",
                mount(evidence, "/evidence"),
                image,
                "/fixture.py",
            )
            wait_for(lambda: b"smoke-observer" in docker("logs", broker).stdout, "MQTT observer")
            # Leave the image's /init, /run.sh and bridge source untouched. The mounted
            # Python hook audits and rejects HTTP/socket escape before it can occur.
            start(
                addon,
                "--env",
                "SUPERVISOR_TOKEN=SYNTHETIC_SUPERVISOR_TOKEN",
                "--env",
                "PYTHONPATH=/smoke-hooks",
                "--env",
                f"SMOKE_MQTT_IP={broker_ip}",
                "--mount",
                mount(FIXTURES / "hooks", "/smoke-hooks", True),
                "--mount",
                mount(data, "/data"),
                image,
            )

            def online_count():
                return sum(
                    row == {"topic": "thermowatt/bridge/availability", "payload": "online"}
                    for row in json_lines(evidence / "mqtt.jsonl")
                )

            first_guard = None
            for cycle in range(2):
                if cycle:
                    docker("start", addon)
                wait_for(
                    lambda cycle=cycle: online_count() >= cycle + 1, "bridge authenticated to MQTT"
                )
                wait_for(
                    lambda cycle=cycle: sum(
                        "/CMD/" in row["topic"] for row in json_lines(evidence / "mqtt.jsonl")
                    )
                    >= 6 * (cycle + 1),
                    "synthetic MQTT commands delivered",
                )
                time.sleep(3)
                assert json.loads(docker("inspect", addon).stdout)[0]["State"]["Running"] is True
                stop_start = time.monotonic()
                docker("stop", "--time", "15", addon)
                state = json.loads(docker("inspect", addon).stdout)[0]["State"]
                assert state["ExitCode"] == 0 and not state["OOMKilled"], "Shutdown failed/forced"
                assert time.monotonic() - stop_start < 15, "Shutdown exceeded grace period"
                wait_for(
                    lambda: json_lines(evidence / "mqtt.jsonl")[-1]
                    == {"topic": "thermowatt/bridge/availability", "payload": "offline"},
                    "clean offline announcement",
                )
                guard = json.loads(copied_file(addon, "/data/auth_state.json"))
                assert guard["attempts"] == 0 and guard["generation"] == 1
                assert guard["access_token"] is None and guard["refresh_token"] is None
                assert guard["mode"] == "ready", "Disabled cloud touched authentication state"
                if first_guard is not None:
                    assert first_guard == guard, "Restart changed the persistent auth guard"
                first_guard = guard

            audit = Counter(
                json.loads(line)["kind"]
                for line in copied_file(addon, "/data/network-audit.jsonl").splitlines()
            )
            assert audit["guard_loaded"] == 2 and audit["mqtt_connect"] >= 2
            assert not any(
                audit[k] for k in ("forbidden_http", "forbidden_dns", "forbidden_socket")
            ), audit
            supervisor_calls = json_lines(evidence / "supervisor.jsonl")
            assert supervisor_calls and all(
                call == {"method": "GET", "path": "/services/mqtt"} for call in supervisor_calls
            )
            messages = json_lines(evidence / "mqtt.jsonl")
            assert any(
                row["topic"] == "homeassistant/water_heater/SYNTHETIC123/config" for row in messages
            )
            mode_config = next(
                json.loads(row["payload"])
                for row in messages
                if row["topic"] == "homeassistant/sensor/SYNTHETIC123/vendor_mode/config"
            )
            assert mode_config["unique_id"] == "thermowatt_SYNTHETIC123_vendor_mode"
            assert "command_topic" not in mode_config
            heating_config = next(
                json.loads(row["payload"])
                for row in messages
                if row["topic"] == "homeassistant/binary_sensor/SYNTHETIC123/heating/config"
            )
            assert heating_config["unique_id"] == "thermowatt_SYNTHETIC123_heating"
            assert heating_config["value_template"] == "{{ 'None' }}"
            assert not any(row["topic"].endswith("/STATUS") for row in messages), (
                "Invented heater status"
            )
            broker_log = docker("logs", broker).stdout.decode()
            assert "Received DISCONNECT from" in broker_log, "No clean MQTT disconnect"
            assert "Sending PUBLISH to auto-" in broker_log, (
                "Commands did not reach the bridge subscription"
            )
            logs = docker("logs", addon).stdout.decode() + docker("logs", addon).stderr.decode()
            assert "Bridge running; cloud=False, commands=False" in logs
            assert "Traceback" not in logs and "Startup paused" not in logs
            for secret in (
                options["password"],
                options["email"],
                "SYNTHETIC_MQTT_PASSWORD",
                "SYNTHETIC_SUPERVISOR_TOKEN",
            ):
                assert secret not in logs, "Sensitive configuration appeared in logs"
            # Replace the container while preserving a 1.3.2-format /data volume.
            # These states contain only synthetic credentials/tokens. HTTP remains
            # prohibited and disabled; this is not a real Supervisor installation.
            upgrade_fixture = FIXTURES.parents[1] / "tests/fixtures/upgrade_1_3_2.json"
            legacy = json.loads(upgrade_fixture.read_text())
            results["upgrade_1_3_2_to_1_3_3"] = {}
            for index, upgrade_state in enumerate(("authorized", "blocked"), start=3):
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    PYTHON,
                    "--mount",
                    mount(data, "/data"),
                    "--mount",
                    mount(upgrade_fixture, "/upgrade.json", True),
                    "--mount",
                    mount(FIXTURES / "seed_upgrade.py", "/seed.py", True),
                    image,
                    "/seed.py",
                    upgrade_state,
                )
                replacement = f"{prefix}-upgrade-{upgrade_state}"
                start(
                    replacement,
                    "--env",
                    "SUPERVISOR_TOKEN=SYNTHETIC_SUPERVISOR_TOKEN",
                    "--env",
                    "PYTHONPATH=/smoke-hooks",
                    "--env",
                    f"SMOKE_MQTT_IP={broker_ip}",
                    "--mount",
                    mount(FIXTURES / "hooks", "/smoke-hooks", True),
                    "--mount",
                    mount(data, "/data"),
                    image,
                )
                wait_for(lambda index=index: online_count() >= index, "upgraded image MQTT startup")
                wait_for(
                    lambda index=index: sum(
                        "/CMD/" in row["topic"] for row in json_lines(evidence / "mqtt.jsonl")
                    )
                    >= 6 * index,
                    "synthetic commands delivered after replacement",
                )
                time.sleep(3)
                docker("stop", "--time", "15", replacement)
                state = json.loads(docker("inspect", replacement).stdout)[0]["State"]
                assert state["ExitCode"] == 0 and not state["OOMKilled"]
                assert (
                    copied_file(replacement, "/data/options.json")
                    == json.dumps(legacy["options"]).encode()
                )
                assert (
                    json.loads(copied_file(replacement, "/data/thermowatt_config.json"))
                    == legacy["metadata"]
                )
                assert (
                    json.loads(copied_file(replacement, "/data/auth_state.json"))
                    == legacy["auth_states"][upgrade_state]
                )
                replacement_logs = (
                    docker("logs", replacement).stdout.decode()
                    + docker("logs", replacement).stderr.decode()
                )
                assert "Bridge running; cloud=False, commands=False" in replacement_logs
                assert (
                    "Traceback" not in replacement_logs and "Startup paused" not in replacement_logs
                )
                for value in (
                    legacy["options"]["email"],
                    legacy["options"]["password"],
                    "SYNTHETIC_UPGRADE_ACCESS",
                    "SYNTHETIC_UPGRADE_REFRESH",
                ):
                    assert value not in replacement_logs
                results["upgrade_1_3_2_to_1_3_3"][upgrade_state] = "PASS"
            audit = Counter(
                json.loads(line)["kind"]
                for line in copied_file(replacement, "/data/network-audit.jsonl").splitlines()
            )
            assert audit["guard_loaded"] == 4 and audit["mqtt_connect"] >= 4
            assert not any(
                audit[k] for k in ("forbidden_http", "forbidden_dns", "forbidden_socket")
            ), audit
            final_messages = json_lines(evidence / "mqtt.jsonl")
            assert not any(row["topic"].endswith("/STATUS") for row in final_messages)
            for row in final_messages:
                if row["topic"] in legacy["mqtt_ids"]:
                    assert (
                        json.loads(row["payload"])["unique_id"] == legacy["mqtt_ids"][row["topic"]]
                    )
            results.update(
                status="PASS",
                startup_shutdown_restart="PASS",
                mqtt_authentication="PASS",
                mqtt_clean_disconnect="PASS",
                synthetic_commands_sent=sum("/CMD/" in row["topic"] for row in final_messages),
                external_http_attempts=audit["forbidden_http"],
                network_audit=dict(audit),
                supervisor_service_discovery="PASS",
                discovery="PASS",
                synthetic_only=True,
            )
        finally:
            for name in containers:
                logs = docker("logs", name, check=False)
                (output / f"{name.rsplit('-', 1)[-1]}.log").write_bytes(logs.stdout + logs.stderr)
            (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps(results, indent=2), flush=True)
            for name in reversed(containers):
                docker("rm", "--force", name, check=False)
            docker("network", "rm", network, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--arch", choices=("amd64", "aarch64"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    smoke(arguments.image, arguments.arch, arguments.output)
