# Thermowatt Smart Boiler Bridge for Home Assistant

Version **1.3.2 is a review candidate** with persistent authentication protection.
Cloud access and heater commands default to disabled. On 2026-11-09 the owner
reported successful Thermann Control authentication directly from the HA OS
add-on, MQTT heater discovery, and current/target temperature and heating-status
display, with `cloud_enabled: true` and `commands_enabled: false`.

This establishes initial read-only operation for that account and installation.
Temperature accuracy, operating-mode mapping and heater commands remain
unverified. The additional Windows login diagnostic is no longer needed. Further
development and control testing are paused for owner review.

The bridge keeps Home Assistant MQTT discovery for compatible MyThermowatt
heaters. It validates responses, survives authentication failures without exiting,
limits transient auth retries across restarts, and publishes observed cloud state.
Rejected or unrecognised authentication requires an explicit operator reset.

Read the [configuration, safe reset and installation guide](thermowatt-heater/DOCS.md),
[security review](SECURITY_REVIEW.md), and [changelog](CHANGELOG.md) before installation.
The [deployment-readiness report](DEPLOYMENT_READINESS.md) records passing native
amd64/aarch64 builds and isolated startup/MQTT/shutdown checks, plus the checks
that still require an approved Home Assistant installation.

For a later owner-approved installation, add this repository to the Home Assistant
app/add-on store: `https://github.com/MuntedDaze/ha-thermowatt-heater`.
Use Home Assistant OS on amd64 or aarch64 with the Mosquitto service and MQTT
integration. Keep cloud access disabled for the initial isolated smoke test.

Thermann Control and MyThermowatt accounts are **not assumed interchangeable**.
This project is not affiliated with Thermowatt, Thermann, Reece, or Ariston.
