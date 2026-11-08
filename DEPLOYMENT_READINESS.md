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
| Real Home Assistant OS initial installation | OWNER-REPORTED SUCCESS | Owner reports 1.3.2 installed and running; not tested by the agent. |
| Real Thermann authentication and initial read-only display | OWNER-REPORTED SUCCESS | MQTT discovery and current/target temperature and heating status displayed; commands disabled. |
| Temperature accuracy, mode mapping and heater commands | UNVERIFIED | No live command tests performed or authorised. |

## Owner update — 2026-11-09

The owner reports successful authentication directly through the HA OS add-on
with the recovered Thermann Control account. MQTT discovered the heater and HA
displays current temperature, target temperature and heating status. The reported
settings are `cloud_enabled=true`, `commands_enabled=false`. This is real initial
read-only success reported by the owner, separately from the earlier CI evidence.
The agent made no live API request or server change to verify it independently.
The separate Windows diagnostic was cancelled and its uncommitted changes were
discarded. The subsequent owner report matches app/heater and HA temperatures at
17°C current / 70°C target; app Schedule appears as native HA Unknown. The
[read-only compatibility/control review](THERMANN_CONTROL_REVIEW.md) proposes the
minimal presentation correction and records unverified heating/control behaviour.
Live command testing remains paused for owner approval.

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

The initial real installation, authentication and discovery now have an owner
success report. The following have **not** passed by implication from that report
or from Docker/schema tests:

- Reinstallation/update, security-profile and service dependency enforcement.
- Options migration, `!secret` resolution, start/stop/Watchdog behaviour and
  persistent-data backup/restore. Initial MQTT connectivity/discovery is reported
  working; these additional lifecycle behaviours are not independently verified.
- Actual temperature accuracy, operating-mode mapping and availability behaviour
  beyond the initially displayed current/target temperature and heating status.
- Temperature setpoints, operating modes, heating requests and the effect of Off
  on anti-legionella protection, thermostat limits and the fallback schedule.

Non-cloud lifecycle checks can be assessed later in an approved isolated
installation. Read-only accuracy and individual commands need separate owner
review/approval; no such testing is authorised now.
The owner's Home Assistant server, Proxmox VMs and Docker infrastructure were
not accessed or changed.

## Decision

The isolated build/schema/runtime gates passed, and the owner has now reported
real authentication, discovery and initial read-only status success. Heater
controls and automation remain unverified and disabled. Further development and
live testing stop pending owner review; no merge or control approval is implied.
The historical exposed-key concern remains open. The standalone diagnostic was
not executed against a live API and is not needed for this owner's account.
