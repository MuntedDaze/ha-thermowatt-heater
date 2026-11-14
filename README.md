# Thermann hot water for Home Assistant

An unofficial community bridge and controller for supported Thermann Smart
Electric heaters using the Thermann Control / MyThermowatt cloud. See the heater
in Home Assistant, keep a simple overnight baseline, and plan weekday storage
using your tariff, solar measurements and available forecasts.

**Development candidate: bridge 1.3.14 / controller 0.10.0, draft PR #34.**
The tested 1.3.13 / 0.9.1 recovery candidate remains in draft PR #33. Neither is
a production deployment. New 62°C hardware behaviour still needs supervised
qualification; automatic control is disabled on a fresh installation.

| Part | Purpose |
|---|---|
| **Thermann Hot Water** add-on | Fixed cloud polling, MQTT discovery and guarded commands with fresh exact-prior status and cloud readback |
| **Thermann Controller** integration | One coordinated policy: OFF, baseline 45°C, normal weekday storage 62°C, optional economical solar 70°C |
| **Independent energy monitoring** | Fable's optional dashboard/reporting in [draft PR #32](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/32); never a controller dependency |

A dedicated hot-water CT is **optional** for baseline and required off-peak
storage. Verified fresh circuit measurement is required for optional solar
heating. Users independently choose **Heating during peak periods** and
**Enable optional solar boost**. CT-free installations default to no routine
peak heating. The separate 12-hour Override remains at 70°C.

The native thermostat and protective cycles retain control of the element.
Cloud OFF is a software request, **not proof of zero electrical consumption**.
An owner app change pauses automation; unknown outcomes are reported rather
than replayed. This is a cloud-dependent project, not a local mains isolator,
temperature/hygiene guarantee or universal water-heater framework.

- [Start here: capabilities, architecture and limitations](docs/dual-storage/README.md)
- [Installation, configuration, commissioning and troubleshooting](docs/dual-storage/INSTALLATION.md)
- [Upgrade and rollback](docs/dual-storage/UPGRADE.md)
- [One household example: 315 L, GoodWe, EMHASS and fixed-AEST tariff](docs/dual-storage/HOUSEHOLD_EXAMPLE.md)
- [Backend telemetry for dashboards](docs/dual-storage/TELEMETRY_INTERFACE.md)
- [Reproducible strategy comparisons](docs/dual-storage/SIMULATIONS.md)
- [Bridge options and authentication guards](thermowatt-heater/DOCS.md)
- [Public-distribution review and licence decision](docs/dual-storage/PUBLIC_RELEASE.md)

Home Assistant OS with MQTT and amd64/aarch64 add-on support is the tested
packaging path. GoodWe and EMHASS are supported input examples; a validated
generic circuit-power entity can supply the optional CT. No cloud credentials,
household entity IDs or verified meter direction are supplied for new users.

The integration domain `thermann_shadow`, add-on slug, MQTT topics and existing
entity IDs remain for compatibility. Historical three-state guides are retained
as recovery references. Changelogs: [bridge](CHANGELOG.md) and
[controller](shadow_controller/CHANGELOG.md).

For development, install `requirements-dev.txt`, run `python -m pytest`,
`python -m ruff check .` and `python -m ruff format --check .`. CI adds strict
type checks, three Python versions, actual Home Assistant, native images,
isolated MQTT/lifecycle tests and Supervisor schema validation. Tests use
synthetic data and block external networking. See the
[progress checkpoint](docs/dual-storage/IMPLEMENTATION_PROGRESS.md).

This project is not affiliated with Thermann, Thermowatt, Reece or Ariston.
No open-source licence has yet been selected; public visibility alone does not
grant unrestricted redistribution rights.
