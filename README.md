# Thermann hot water for Home Assistant

Two parts, for a Thermann Smart Electric water heater (tested on a 315 L / 3 kW unit) connected to the Thermann Control / MyThermowatt cloud:

| Part | What it does | Installed from |
| --- | --- | --- |
| **Thermowatt bridge** (add-on, `thermowatt-heater/`) | Reads the heater from the cloud every 30 minutes and publishes it to Home Assistant over MQTT. When commands are enabled, it accepts only two: `Manual:70` (heating allowed) and `off` (parked). | Home Assistant add-on store, from this repository |
| **Hot Water Controller** (integration, `custom_components/thermann_shadow`) | Plans when heating is cheapest using tariffs, solar, comfort deadlines and the GoodWe meter, and tells the bridge to allow or park heating. Off by default. | Copied into `custom_components/` |

Thermann's own thermostat always decides when the element runs. The controller only allows heating (Manual at 70 °C) or parks the heater (Thermann OFF, which keeps the manufacturer's anti-bacterial and frost protection active). It never changes the temperature setting, the native Schedule or mains power.

This project is not affiliated with Thermowatt, Thermann, Reece or Ariston.

## Requirements

- Home Assistant OS on amd64 or aarch64, with the Mosquitto broker and the MQTT integration.
- A Thermann Control / MyThermowatt account for the heater.
- For the controller: a GoodWe inverter with its meter in Home Assistant (solar, house load, grid). EMHASS forecasts are optional.

## Install

**Bridge:**
1. Settings → Add-ons → Add-on store → ⋮ → Repositories, then add `https://github.com/MuntedDaze/ha-thermowatt-heater`.
2. Install **Thermowatt Smart Boiler**. Set your account details, then `cloud_enabled: true` and `auth_retry_generation: 1`. Leave `commands_enabled: false` for now.
3. Start it. The heater appears as an MQTT water heater, with diagnostic sensors.

Full options, the authentication safety rules and troubleshooting: [thermowatt-heater/DOCS.md](thermowatt-heater/DOCS.md).

**Controller:**
1. Copy `custom_components/thermann_shadow` into `/config/custom_components/` and restart Home Assistant once.
2. Add the integration and map your entities.
3. Automatic control stays off until the commissioning steps are done.

Guide: [shadow_controller/README.md](shadow_controller/README.md).

## Safety in one paragraph

- **Bridge:**
  - Cloud access and commands are off until you enable them.
  - Failed authentication locks rather than retrying, and the lock survives restarts.
  - It polls every 30 minutes.
  - Every command is checked against a fresh reading, sent once, never repeated, and confirmed from the heater's reported state.
- **Controller:**
  - Sends nothing until it is commissioned and switched on.
  - Pauses whenever you change the heater in the Thermann app.
  - Never interrupts heating the heater starts itself while OFF (anti-bacterial or frost protection).
  - Stops with a clear notification when something does not add up.

## If something goes wrong

- **Hot water now:** in the Thermann app, choose **Manual at 70 °C**. To return to your normal programme, choose **Schedule**.
- **Stop all automatic control:** turn off *Automatic heater control* in Home Assistant. That never changes the heater.
- **Add-on authentication locked:** see "Clearing an authentication lock" in [DOCS.md](thermowatt-heater/DOCS.md). Never delete `/data/auth_state.json`.

## Repository layout

| Path | Contents |
| --- | --- |
| `thermowatt-heater/` | the bridge add-on, its changelog and DOCS.md (shown in the add-on page) |
| `custom_components/thermann_shadow/` | the controller integration |
| `shadow_controller/` | controller guide, commissioning, dashboard data contract, thermal model, upgrade notes |
| `tests/`, `tools/` | offline tests (no network; synthetic data) and readiness checks |
| `docs/history/` | earlier reviews, stage reports, upgrade notes and audit evidence, kept for reference |
| `AGENTS.md` | the owner's development and release rules for this repository |

## Development

```shell
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check . && python -m ruff format --check .
```

The tests block all network access. CI also builds the add-on for amd64/aarch64, runs it against an isolated MQTT broker, validates the Supervisor schema and loads the integration in real Home Assistant Core.

Changelogs: [bridge](CHANGELOG.md), [controller](shadow_controller/CHANGELOG.md).
