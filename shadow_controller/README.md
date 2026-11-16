# Thermann Controller

The owner already runs **0.14.0** in Shadow Mode with bridge **1.3.17**, GoodWe
and EMHASS. This release prepares controller **0.15.0** in the same installation.
The bridge code/version and existing integration identities remain unchanged.

Use the [current in-place upgrade and commissioning guide](../docs/completion/UPGRADE.md),
[compatible interfaces](../docs/completion/INTERFACES.md),
[beginner settings walkthrough](../docs/configuration/SETTINGS.md) and
[controller changelog](CHANGELOG.md). Earlier draft guides are historical references.

One policy chooses OFF / Manual45 baseline / required weekday Manual62 / optional
Manual70. Peak lockout and optional boost are independent owner choices. A
separately commissioned CT-free grid-only path supports peak and off-peak solar;
a verified exclusive circuit meter adds physical element/energy evidence.
Without it, electrical ON/OFF remains unknown. No missing reading becomes zero.

One guarded command arbiter persists intent before the bridge receives it.
Protective OFF requirements survive a pending start, restart and returning sun;
unknown outcomes are never replayed or authentication safeguards bypassed.
The same policy remains read-only in Shadow Mode. An upgrade grants no new
live command, automatic-control, adaptive-polling or learned-planning permission.

The existing seven-view dashboard reads these entities; it is not a second
controller. EMHASS remains the external forecast/optimisation source. Future
whole-house and bathroom projects use the documented interfaces without adding
another heater command path. [Forecast setup](FORECAST_SETUP.md) remains compatible.
