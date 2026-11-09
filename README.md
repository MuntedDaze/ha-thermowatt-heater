# Thermowatt Smart Boiler Bridge for Home Assistant

Version **1.3.3 is a review candidate** for updating the existing 1.3.2 add-on.
The [upgrade notes](UPGRADING_1_3_3.md) explain retained state/options and the
intentional Unknown heating state. PR #2 remains draft; no update is deployed.
Cloud access and heater commands default to disabled. On 2026-11-09 the owner
reported successful Thermann Control authentication directly from the HA OS
add-on, MQTT heater discovery, and current/target temperature and heating-status
display, with `cloud_enabled: true` and `commands_enabled: false`.

This establishes initial read-only operation for that account and installation.
The owner subsequently reported matching current/target readings of 17°C/70°C,
Thermann app 3.15.17, heater 07.00.09.06 and Wi-Fi 01.03.21. This is a matching
snapshot, not full temperature calibration or proof of physical heating.

The 1.3.3 read-only follow-up adds a Vendor mode sensor for Schedule and
other inherited codes, while retaining the native heater entity and its IDs.
The unverified heating binary sensor reports Unknown rather than claiming the
element is off or on. Heater commands remain disabled and untested on this unit.
See the [compatibility/control review](THERMANN_CONTROL_REVIEW.md) for the command
matrix, schedule limitations and staged owner-approved testing plan. No separate
Windows login workflow or automation is added.

The bridge keeps Home Assistant MQTT discovery for compatible MyThermowatt
heaters. It validates responses, survives authentication failures without exiting,
limits transient auth retries across restarts, and publishes observed cloud state.
Rejected or unrecognised authentication requires an explicit operator reset.

Read the [configuration, safe reset and installation guide](thermowatt-heater/DOCS.md),
[security review](SECURITY_REVIEW.md), and [changelog](CHANGELOG.md) before installation.
For repeated authentication messages or `cloud_operation_failed`, see the
[cloud diagnostic review](CLOUD_DIAGNOSTICS.md). It explains the hidden error
paths, fixed diagnostic codes and restart-persistent refresh cooldown without
requiring a new login or diagnostic environment.
The [deployment-readiness report](DEPLOYMENT_READINESS.md) records passing native
amd64/aarch64 builds and isolated startup/MQTT/shutdown checks, plus the checks
that still require an approved Home Assistant installation.

For a later owner-approved installation, add this repository to the Home Assistant
app/add-on store: `https://github.com/MuntedDaze/ha-thermowatt-heater`.
Use Home Assistant OS on amd64 or aarch64 with the Mosquitto service and MQTT
integration. Keep cloud access disabled for the initial isolated smoke test.

Thermann Control and MyThermowatt accounts are **not assumed interchangeable**.
This project is not affiliated with Thermowatt, Thermann, Reece, or Ariston.
