# Upgrade and rollback: 1.3.14 / 0.10.0 candidate

This is an unmerged development candidate. PR #33 at `cf97d5e` remains the tested
bridge 1.3.13/controller 0.9.1 recovery checkpoint; PR #27 and Fable's PR #32
are independent and unchanged. No tag, production installation, command test
or deployment is included in this work. Review and explicit owner approval
precede any merge, installation, live authentication or physical operation.

## Planned upgrade sequence

1. While the old system is available, deliberately disable automatic control
   and confirm the current appliance mode in the vendor app. Disabling the
   controller does not park the heater. Record the actual state privately.
2. Take and verify a recoverable HA/add-on backup. Preserve the complete add-on
   `/data`, including options/credentials, auth tokens/guard and generation,
   cloud request usage, command state and `thermowatt_config.json`. Preserve HA
   config entries/options, entity registry and `thermann_shadow` storage files.
   Backups contain secrets: keep them private. Do not edit them to clear locks.
3. After separate approval, upgrade the **same bridge installation** to 1.3.14
   first. Do not create a parallel local add-on or second account client. Keep
   cloud/command flags, credentials, auth generation and stored guards exactly
   as configured. The upgrade itself does not authorise new authentication or
   commands. Check read-only availability, identities and advertised transitions.
4. Upgrade the controller to 0.10.0, still disabled. Retain its domain, config
   entry and MQTT/entity IDs; do not delete/re-add it. Confirm all saved mappings,
   sign, tariff clock/rates, verification choices, topics and technical limits.
5. Review the new 45/62/70 target roles, nominal model, peak policy and independent
   boost setting. The new four-state qualification flag starts false. Complete
   the separately authorised commissioning plan in [INSTALLATION](INSTALLATION.md)
   before considering any automatic-control enable.

Bridge 1.3.14 retains the old exact-prior 45/70 transitions and legacy two-command
forms, so the old controller can remain in place during a staged upgrade. The
new controller refuses a missing advertised 62°C transition. Do not use the
bridge's broad `legacy` command policy to work around a refusal.

## What migration preserves and changes

- Add-on options, slug, credentials, tokens, auth generation, persisted lockouts,
  request accounting, command state and MQTT discovery identities are unchanged
  by this increment. No safety store is deleted or quota reset.
- Controller config-entry major version stays 1; minor version becomes 4. Every
  explicit existing sign/clock/verification choice remains. For old entries
  missing those keys, migration writes their previous effective values (including
  old meter/tariff verification assumptions), preserving behaviour rather than
  applying new-user defaults. This is compatibility, not new measurement evidence.
- Existing mappings are preserved. An omitted old `pv_ac` key gets the exact
  previous GoodWe fallback explicitly; an explicitly empty mapping stays empty.
  Fresh installs get no entity IDs and verification flags false.
- An existing explicitly commissioned CT installation retains the previous
  solar-only peak choice if no peak-policy key was saved. Other installations
  default to Never. Existing explicit peak-policy choices always win. Review
  this migrated choice deliberately; migration cannot prove present CT health.
- The old three-state flag and other retired settings are kept for rollback,
  but do not qualify 62°C. New normal storage defaults to 62°C; optional boost
  is independent. The master-enable state is preserved, while missing four-state
  qualification prevents new automatic actions. Disable before upgrading anyway.
- New measured sessions are stored in `.measured_history_v2`; the original
  `.measured_history` is loaded if necessary and left untouched. Old v1 records
  have unknown target and cannot train 62°C/70°C calibration. New records retain
  their actual target, nominal power and tank volume; changing settings never
  relabels old evidence. Calibration remains diagnostic.

Existing entity IDs survive; the historical “Afternoon storage target” sensor
now reports the configured normal target. The telemetry event schema advances
from 1 to 2 with a `heating_plan` object. Consumers must tolerate extra fields
and unknown values; see [the contract](TELEMETRY_INTERFACE.md). Fable's branch is
not merged by this upgrade and must be reviewed/integrated separately later.

## Rollback

Stop automatic control first. Inspect/reconcile any pending or unconfirmed
command using the actual appliance state; never assume a restart cancelled it.
An older bridge 1.3.13 has no guarded `off@62`, `Manual:45@62` or `Manual:70@62`.
**Do not roll back while leaving an unreviewed Manual 62°C state for the older
controller to manage.** Under separate owner approval, return the appliance to
an understood old supported state using the vendor app or a supervised verified
transition, then disable control again. This document executes no such command.

Restore the approved prior controller files and its pre-upgrade HA backup/storage
as required; inspect the same preserved entry/registry and keep control off.
The untouched legacy measured-history file is available to the old controller;
new v2 history is not silently rewritten as old data. Restore the same bridge
installation from the verified partial backup if required. Do not manually
decrease auth generation, delete guards, reuse stale tokens to evade a lock or
reset request accounting. If later authentication/lockout state exists, restoring
an old state requires careful owner review rather than treating a backup as a
fresh login permission. Confirm read-only health before any later operation.

Rollback is a recovery procedure with backups, not deletion/reinstallation or
branch switching on a live HA system. Fable's package and worktree are unaffected.
