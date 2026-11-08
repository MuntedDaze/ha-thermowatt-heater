# 1.3.2 deployment-readiness checks — 2026-11-09

PR: [#1](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/1), branch
`codex/auth-safety-1.3.2`. The PR remains unmerged and the add-on remains disabled
by default. These checks add no integration features and required no correction
to the bridge, Dockerfile or launcher.

Evidence for code/test commit `15e420a735e9df657f66172cb51c7ea7103aab49`:
[deployment CI run](https://github.com/MuntedDaze/ha-thermowatt-heater/actions/runs/42499024539),
[offline CI run](https://github.com/MuntedDaze/ha-thermowatt-heater/actions/runs/42499024546).
The deployment run retains per-architecture `results.json` and container logs
as artifacts. No image was published to a registry or installed on the owner's
systems. Docker was unavailable in the local workspace; all container work ran
on disposable GitHub-hosted Linux runners.

| Check | Result | Evidence / scope |
| --- | --- | --- |
| Actual amd64 add-on image | PASS | Native Ubuntu 24.04 runner built `thermowatt-heater/Dockerfile` from HA `base:3.24`. |
| Actual aarch64 add-on image | PASS | Native Ubuntu 24.04 ARM runner built and executed the ARM64 image; no emulation. |
| Installed dependencies and CA bundle | PASS | `pip check`, Requests/Paho imports, certificate bundle presence, default HTTPS verification and absence of removed key/certificate files checked in both images. |
| Supervisor configuration and options | PASS | Actual `SCHEMA_APP_CONFIG` / `AppOptions` from official Supervisor 2026.10.5 and 2026.11.0 images accepted app YAML/default options, recognised `mqtt:need` and rejected invalid synthetic options. No Supervisor daemon ran; validation used `--network none`. |
| S6/Bashio startup and service discovery | PASS | Actual image `/init` → `/run.sh` → bridge, synthetic `/data`, and a mock local `/services/mqtt` endpoint supplying authenticated broker details. |
| MQTT startup/discovery | PASS | Authenticated MQTT v5 connection to isolated Mosquitto 2.0.22; existing heater discovery topic observed for a synthetic cached device. This does not prove HA Core accepts the discovery payload. |
| Disabled cloud/commands | PASS | Both images recorded zero HTTP attempts and zero forbidden DNS/socket attempts, despite 12 synthetic MQTT commands per architecture across two launches. Guard attempts stayed zero; no tokens or heater status appeared. |
| Clean shutdown and persistent restart | PASS | Both launches per architecture stopped within 15 seconds, exit code 0, no OOM/forced kill, offline availability and MQTT DISCONNECT observed. Guard unchanged after restart. |
| Existing 135 offline tests and static checks | PASS | CI passed Python 3.12/3.13/3.14, Ruff lint/format, compileall and Bash syntax checks. |
| Real Home Assistant OS installation | NOT RUN | Requires an owner-approved test installation; see remaining checks below. |
| Live Thermann authentication / physical heater | NOT RUN | Prohibited for this work; no compatibility claim made. |

## Isolation and measurements

The runtime network was created with Docker `--internal`, with no published
ports or host networking, devices or Docker socket mounts. Container DNS was
limited to the internal fixture network. The Supervisor mock cannot proxy
requests and only serves the MQTT service-discovery response.

Only synthetic credentials and device metadata were used:
`cloud_enabled=false`, `commands_enabled=false`, `auth_retry_generation=1`.
Generation 1 intentionally left the local guard ready, so a pre-existing lockout
could not mask a disabled-cloud failure. The test mounted a Python-only audit
hook that rejects any Requests HTTP call before network I/O, disallows external
DNS/sockets, and permits only the isolated broker plus Paho's loopback wakeup
socket. The hook is outside the Docker build context and is not shipped in the
add-on image. The normal image entrypoint/launcher/bridge were not replaced.

Per architecture, the audit recorded two hook loads, two broker connections,
two loopback connections, and **zero HTTP, forbidden DNS or forbidden socket
attempts**. The broker delivered Manual/Off/Eco/Auto/Holiday and temperature
commands to the bridge's synthetic-device subscription on each launch. No
cloud/heater request or invented `/STATUS` publication followed. Synthetic
credentials were also checked for absence from add-on logs.

Installed versions in both tested images: Python 3.14.10, Requests 2.32.5,
Paho MQTT 2.1.0, urllib3 2.8.0 and certifi 2026.10.23. Direct dependencies are
pinned; base tags and transitive dependencies can change on a later rebuild.
The CI logs record the base digest and dependency resolution for that reason.

Tested image IDs (local to those disposable runners):

- amd64: `sha256:de844292b21338fbdd1898de6987d2f2094f905042e2ec2c4f9c22054abdcd1a`
- aarch64: `sha256:28799bfeabfc4da0f365818d6aa76b5547c29f3752ab37afb21f0611276f6a36`

## Checks still requiring real Home Assistant

The following have **not** passed by implication from Docker/schema tests:

- Installation/update through the Supervisor store on the target HA OS,
  including its actual security profile and service dependency enforcement.
- Real Supervisor MQTT provider registration/credentials, options migration,
  `!secret` resolution, start/stop/Watchdog behaviour and persistent-data backups.
- HA Core accepting discovery and presenting entities/availability/mode mapping
  correctly in the UI. The isolated broker check verifies transport/publication.

These can be checked later on an approved isolated installation with cloud and
commands disabled. They do not require live Thermann credentials or a heater.
The owner's Home Assistant server, Proxmox VMs and Docker infrastructure were
not accessed or changed.

## Decision

The requested isolated build/schema/runtime gates passed. Version 1.3.2 is ready
for owner review and an explicitly approved **cloud-disabled controlled install**,
subject to the real-HA checks above. It is not approved for merging, deployment,
live Thermann authentication or heater control. Account compatibility and the
historically exposed key remain separate open issues. The standalone one-login
diagnostic has not been executed against any live API.
