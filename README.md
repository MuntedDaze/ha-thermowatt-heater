# Thermowatt Smart Boiler Bridge for Home Assistant

Version **1.3.2 is a review candidate** with persistent authentication protection.
Cloud access and heater commands default to disabled. No live authentication or
physical heater testing was performed. Compatibility with this owner's Thermann
Control account is unverified; a single-login diagnostic is prepared for later
explicit approval, with no automatic retries or heater access.

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
