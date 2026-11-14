# Thermann Controller

Current development candidate: **0.10.0** with bridge **1.3.14**, in draft PR #34.

Start with the [four-state guide](../docs/dual-storage/README.md),
[installation and commissioning](../docs/dual-storage/INSTALLATION.md),
[upgrade/rollback](../docs/dual-storage/UPGRADE.md) and
[backend telemetry contract](../docs/dual-storage/TELEMETRY_INTERFACE.md).

The default strategy is OFF / Manual45 baseline / required weekday Manual62 /
optional economical solar Manual70. Dedicated CT measurement is optional for
baseline and required off-peak storage. Peak policy and optional boost are
independent user settings. No new transition has been physically commissioned.
Automatic control remains disabled for new users, with a separate four-state
qualification gate. The bounded owner 12hr Override remains at 70°C.

`thermann_shadow` and existing entity IDs remain for compatibility. The same
single policy runs read-only when automatic control is off. Calibration remains
diagnostic and adaptive polling remains shadow-only. Cloud OFF is not proof of
zero electrical consumption. Fable's dashboard remains a separate draft PR.

The earlier [SIMPLIFIED_STRATEGY](SIMPLIFIED_STRATEGY.md),
[HOW_IT_DECIDES](HOW_IT_DECIDES.md) and
[COMMISSIONING_SIMPLIFIED](COMMISSIONING_SIMPLIFIED.md) describe the three-state
0.9.x recovery candidate in unchanged PR #33, not this four-state candidate.
Keep them as versioned recovery references.

[Forecast input setup](FORECAST_SETUP.md) and the [controller changelog](CHANGELOG.md)
remain useful. Development has not installed, enabled or operated this candidate.
