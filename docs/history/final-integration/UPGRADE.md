> Historical checkpoint: superseded for installation and current audit status.
> Use the [audit remediation handoff](../audit-remediation/HANDOFF.md) and
> [normal owner guide](../pre-review/OWNER_INSTALLATION.md). Supervisor cache
> staging is unsupported; preserve the owner’s agreed45/62/70 strategy.

# Candidate upgrade and rollback

Unmerged bridge 1.3.15 / controller 0.11.0. No rollout is performed or authorised
by this document. Follow the [owner plan](INSTALLATION.md) only after separate
review and approval. Public distribution and licence administration are deferred.

## Compatibility and preservation

Keep the existing add-on slug, `thermann_shadow` domain, entry and MQTT/HA unique
IDs. Do not delete/re-add devices. Existing explicit options, mappings, tariffs,
clock, sign, verification, credentials, tokens, auth generation, locks, quota
accounting and pending-command state are preserved. Neither new scheduling nor
learning enables cloud/commands/control. The controller master state is retained
on upgrade, so deliberately disable it before upgrading.

Upgrade the **same bridge installation first**, then the controller while disabled,
then the optional read-only package/dashboard. Preserve complete private backups
of add-on `/data`, HA storage/options and registry. Check every actual version,
entity and preserved flag before commissioning. Do not start another bridge.

Entry major version stays 1; minor becomes 5. Pre-v4 implicit household facts are
materialised as their previous effective values (including Hobart/Aurora/GoodWe
fallback) rather than replaced with fresh-install defaults. A v4 entry preserves
its effective zone and verification/sign choices without reintroducing the
legacy source fallback. Explicit saved choices always win. New entries instead
inherit HA’s IANA zone, use unverified flat placeholders and no household sources,
disable forecast/boost and initially select 62°C baseline/normal. Migration is
compatibility, not new hardware or tariff evidence.

The four-state protocol remains the same closed OFF/45/62/70 set from bridge
1.3.14. Its qualification flag/label stays independent. New bridge options
`adaptive_polling_enabled` and `adaptive_polling_qualified` default false; controller
plan enable also defaults false. The bridge’s optional `poll_state.json` contains
only scheduling diagnostics/counts, never authorization. Lease/deadline/cache are
not restored; restart uses normal status inspection and fixed fallback. Corrupt
or unwritable scheduling state does not bypass cloud guards.

Compact `.measured_history_v2` retains the existing format and adds optional clean
session provenance. Old rows lacking it stay diagnostic. Existing v1 history
remains untouched. Active partial cycles/anchors are cleared on restart, never
reconstructed as clean sessions. Learning/hardware flags default false and
meter/unit/model remaps invalidate authority. HA Recorder remains the raw history;
no new raw database is installed. The schema-2 telemetry event has additive fields;
consumers must tolerate unknown/missing values and extra fields.

Monitoring retains stable `em_` IDs. Default combined tariff source now reads the
controller’s verified prices; review any renamed registry mappings. Standalone
mode retains the prior monitoring helper path. Do not add a circuit’s integrated
energy to its native cumulative energy or count downstream plugs twice. Historical
statistics are not automatically backfilled/repriced by installing new sensors.

## Rollback and recovery

Preserved draft anchors:

| PR | Branch | Checkpoint |
|---|---|---|
| #27 | codex/audit-fixes-0.9.1 | `1b29be165ddc61eb0b2e64a69eea9a435f7f7a53` |
| #33 | codex/smart-controller-next | `cf97d5eec4aca82d7faa6f21e3e7a20f9aaff41b` |
| #34 | codex/economic-dual-storage | `d3e26f8d54003586f9d75c29ee781231581af9cb` |
| #32 | fable/thermann-energy-dashboard | `4c078f0802faaafc5d5fcc4264af7894b28fc95c` |

Disable automatic control and both adaptive sides; inspect/reconcile pending
commands against actual appliance state. Restoring old files does not cancel a
request already sent. Bridge 1.3.13 cannot safely manage an unreviewed Manual62
prior state: under separate authorisation first reconcile to an understood older
supported state using the vendor app or supervised qualified transition. Keep
control off throughout recovery. Bridge 1.3.14 can retain the four-state protocol
but does not understand adaptive hints; never assume its timer became adaptive.

Restore reviewed prior controller files and its compatible private pre-upgrade
storage/registry backup as needed. Preserve later locks/auth/usage safety state;
restoring an old token store is not permission for a new login. Do not delete
guards, decrease generations, reset usage or replay unresolved intents. An older
version may ignore new optional learning fields; restoring the verified backup
avoids pretending new evidence belongs to its old calibration model. The original
v1 file remains available. The optional scheduling diagnostic file is not an auth
or command store and must never be substituted for one.

Check read-only health and actual owner state before any later authorised enable.
No merge, tag, release, installation, live authentication or physical test is
included in the integration development.
