# Thermann hot water for Home Assistant

An unofficial Home Assistant project for a Thermann smart electric water heater:
the **Thermann Hot Water** app (add-on, `thermowatt-heater/`) connects the heater
to Home Assistant through the Thermowatt cloud, and the **Thermann Controller**
integration (`custom_components/thermann_shadow/`) chooses the thermostat target
from your tariff, solar and forecasts.

**What the system must do is defined in one place:
[docs/OPERATING_POLICY.md](docs/OPERATING_POLICY.md).** Anything else that
disagrees with it — an old setting, default, test or document — is wrong or
historical.

| Document | Use it for |
|---|---|
| [Operating policy](docs/OPERATING_POLICY.md) | The requirements and how the code meets them |
| [Every setting](docs/SETTINGS.md) | What each remaining setting does (generated from the code) |
| [Owner handbook](docs/owner/HANDBOOK.md) | Everyday use, solar, weekends, faults |
| [Upgrade guide](docs/owner/UPGRADE.md) | Updating the existing installation |
| [Dashboard and diagnostic report](docs/owner/INTERFACE.md) | The Thermowatt dashboard and copying a report |
| [App options](thermowatt-heater/DOCS.md) | Thermann Hot Water app options and authentication guards |
| [Forecast setup](shadow_controller/FORECAST_SETUP.md) | Connecting EMHASS forecasts |
| [Temperature decision](docs/decisions/HOT_WATER_TEMPERATURE.md) | The owner's 45/62/70 °C decision record |
| [History](docs/history/README.md) | Earlier reviews, plans and evidence — not requirements |

## In short

- **Manual 45 °C overnight**; the heater's own thermostat manages the element.
  There is no morning temperature target or morning top-up.
- **Manual 62 °C** weekday storage, ready before the evening peak at the cheapest
  available time; weekend comfort window opened by solar or a deadline fallback.
- **Manual 70 °C** only when genuinely measured surplus solar qualifies.
- **OFF during peaks**, unless verified solar-only peak heating is selected.
- Every command is guarded: exact prior state, fresh status, cloud confirmation,
  budgets, no blind retries. **Software OFF is not proof of zero power.**

## What equipment is needed?

A compatible Thermann Smart Electric heater and cloud account, Home Assistant OS
with its MQTT broker, and internet access. Solar, GoodWe, EMHASS forecasts, a
dedicated heater circuit meter (CT) and the dashboard are optional. Without a CT,
required heating, tariffs and peak lockout all work; optional solar boosting
needs either a commissioned CT or the separately commissioned CT-free grid-meter
setup.

## Approvals

Installation, live authentication, automatic control and heater operation each
need the owner's separate approval. This project is not affiliated with
Thermann, Thermowatt, Reece or Ariston.
