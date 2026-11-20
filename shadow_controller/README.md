# Thermann Controller

The requirements are in [docs/OPERATING_POLICY.md](../docs/OPERATING_POLICY.md);
every setting is described in [docs/SETTINGS.md](../docs/SETTINGS.md).

One policy (`custom_components/thermann_shadow/simple_policy.py`) chooses OFF,
Manual 45 baseline, required Manual 62 storage or optional Manual 70 solar
storage. One guarded command arbiter (`controller.py`) decides whether a change
may be sent and supervises its confirmation; nothing else publishes heater
commands. With automatic control off the same policy runs read-only.

Files here: [changelog](CHANGELOG.md), [forecast setup](FORECAST_SETUP.md) and
the Thermowatt dashboard source (`dashboard.yaml`). Upgrading:
[docs/owner/UPGRADE.md](../docs/owner/UPGRADE.md). Older controller documents,
including the 0.9 decision walkthrough and commissioning runbook, are in
[docs/history/controller](../docs/history/controller/).
