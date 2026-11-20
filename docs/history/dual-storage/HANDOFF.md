# Review handoff

Development branch: `codex/economic-dual-storage`, [draft PR #34](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/34),
targeting unchanged PR #33 recovery branch `codex/smart-controller-next` at
`cf97d5eec4aca82d7faa6f21e3e7a20f9aaff41b`. PR #27 and Fable's PR #32/head
`4c078f0802faaafc5d5fcc4264af7894b28fc95c` remain unchanged and unmerged.
Fable's separate worktree and dashboard files have not been modified.

## Delivered

- Bridge **1.3.14** and controller **0.10.0**, unreleased candidates. Closed
  physical states OFF / Manual45 / Manual62 / Manual70. Every directed
  transition has an exact-prior guard; see [the twelve payloads](../../../thermowatt-heater/DOCS.md#commands-when-enabled).
  The old unqualified `Manual:70` from OFF and `off` from Manual70 retain their
  narrower meanings. No arbitrary setpoint, auth/retry change or native-protection
  change was introduced.
- One coordinated required-62 / optional-70 policy, direct sunny starts and
  later top-ups, with useful-demand/feed-in/standby/switching economics. Overnight
  and weekend baseline remains 45; explicit owner 12-hour Override stays 70.
- Independent **Heating during peak periods** and **Enable optional solar boost**.
  Never takes priority over routine export/forecast opportunities; unconfirmed
  OFF is an unverified lockout, never a claim of electrical zero.
- Supported CT-free baseline/required off-peak heating. Generic raw W/kW and
  optional native cumulative Wh/kWh integration; signed diagnostics and genuine
  steady-zero report freshness. A commissioned CT failure remains a fault.
- Fresh-install verification false and no assumed entity IDs. Preserving upgrade
  migration, supported temperature/volume/power/margin/economic settings, separate
  target/model-labelled history store, schema-2 telemetry and target-aware polling
  comparison. Learning is diagnostic; adaptive polling is shadow-only.
- Public [configuration/commissioning](INSTALLATION.md), [household example](HOUSEHOLD_EXAMPLE.md),
  [upgrade/rollback](UPGRADE.md), [telemetry](TELEMETRY_INTERFACE.md), and
  [redacted distribution/licence review](PUBLIC_RELEASE.md). No dashboard copy
  or dependency, production change, licence addition or GitHub release.

## Evidence

The local suite contains **1155 mocked regressions** (1059 at the recovery
checkpoint). Relevant additions cover twelve transitions/confirmation, CT-free
required heat, disabled boost, peak lockout despite export, owner changes,
restart/failed OFF, target-specific history, fresh-install migration, thermostat
hysteresis, forecast fluctuation and eight DST/tariff-boundary cases. The real-HA
harness captures and confirms `Manual:62@off` with networking disabled. The
telemetry regression verifies changed boost-rejection reasons update the event
while identical callbacks still deduplicate.

Local checks: pytest, Ruff lint/format, both strict mypy targets, compileall and
Bash syntax. Applicable final-head GitHub checks are Python 3.12/3.13/3.14, HA
2026.10.4/2026.11.1, native amd64/aarch64 image + isolated MQTT/lifecycle/demand
tests and Supervisor 2026.10.5/2026.11.0 schemas, on both push and PR (18 jobs).
Exact final head and completed CI results are recorded in PR #34 after the
runs settle; inspect that head before independent review. Earlier complete
matrix evidence is green at `ee0edcf`.

[The 11 cases / 33 policy replays](SIMULATIONS.md) include energy conservation,
same useful draws, terminal-energy reconciliation and explicit modelled request
counts. Sunny direct70 costs AUD 0.890 versus 62-only raw AUD 0.612, or AUD 1.106
after equal-terminal replenishment. Cloudy 62 costs AUD 1.123 versus mandatory70
AUD 1.634 raw; after accounting for remaining heat, 62 is AUD 1.617. Most raw
cloudy savings purchase less stored energy. Patchy optimistic forecasts cause
measured withdrawals and capped optional re-entry; late cold starts miss storage
targets while obeying the intended peak park. No synthetic annual savings or
real zero-watt guarantee is claimed.

## Remaining gates

Independent code review, owner approval and separate hardware commissioning
remain required. New 62°C behaviour and transitions are not physically qualified.
The future CT must independently pass circuit/sign/unit/cadence/ON/OFF/outage
tests; software cannot make a change-only sensor fresh at steady zero. Native
hysteresis, stratification/draws, cloud receipt delay/outage and manual actions
remain limitations; completion is conditional and nominal models are estimates.

Preserve private backups and guards; upgrade the same bridge first, then the
controller disabled. A rollback to bridge 1.3.13 must deliberately reconcile a
Manual62 appliance state first because the old bridge cannot guard `off@62`.
No deploy, real MQTT/cloud request, automatic enable or physical operation has
been performed or authorised by this development.

Public-distribution concerns remain: old private-key material is still reachable
in repository history despite its earlier removal, and the pre-existing application
key's scope/provenance is unknown. No value was exposed or changed here. Owner/vendor
review is needed before broad release assurances. MIT is recommended subject to
ownership/provenance review, but a licence requires the owner's explicit choice.
