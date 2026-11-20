# Independent-review handoff

Review draft [PR #35](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/35),
`codex/thermann-final-integration` stacked on unchanged #34. Candidate versions
are bridge 1.3.15/controller 0.11.0. No merge, rollout, release or live operation
is authorised. The owner’s newer clarification defers public distribution and
supersedes the earlier request for public-release administration.

## Review order and source authority

1. `thermowatt-heater/thermowatt_polling.py`, bridge adaptive queue/sync and
   `custom_components/thermann_shadow/adaptive.py` / executor: one existing timer,
   monotonic status anchor, finite bounded nonretained plan, expiring lease,
   fixed fallback, read reuse, guarded backoff/auth/accounting priority. New
   bridge/controller enables and independent bridge qualification all default off.
2. `measurement.py`, runtime, `performance.py`, `learning.py`: raw signed CT
   unit/polarity/boot/freshness, steady-zero cadence, continuous session coverage,
   exact target/model/meter provenance, independent held-out days, persistence,
   conservative-only planning and remap invalidation. Both learning gates default
   off; no real history was imported or invented to pass them.
3. `simple_policy.py` / model/config/installation/native: closed targets,
   Never-peak and owner precedence, budget reserve, no-solar CT-free required
   service, IANA/fixed-vs-DST windows, full coverage and future per-slot rates.
   Watch fresh versus legacy migration: existing owner choices must not reset.
4. `energy_monitoring/`: original Fable ancestry plus combined map/availability,
   verified controller price authority, shoulder/zero handling and no-meter
   support. Both components read raw meter inputs independently; optional CTs,
   dashboard and EMHASS cannot become basic-control dependencies.

## Evidence and limits

The [completion matrix](COMPLETION_MATRIX.md) ties requirements to code/tests and
outstanding evidence. [Week results](SIMULATIONS.md) reproduce actual mocked
worker HTTP and expose detection/status-age/service deficits; the retained
[33 strategy comparison](../dual-storage/SIMULATIONS.md) uses a simpler economic
model. They must not be conflated or presented as real bill/API savings.

1,371 local tests and static checks pass. The exact final tested commit and its
eight push/PR workflow results are recorded on #35. CI has 13 jobs per event:
three Python versions, two actual HA combined component checks, four energy
package configurations, two native architectures and two Supervisor schemas.
The package jobs also check minimal no-solar configuration. All run with synthetic
inputs / isolated networking for heater operations. HA frontend appearance is
not tested by check_config or template rendering.

No real thermal accuracy is established. The week’s broad latest-completion
bound was about138 minutes from the simulated crossing, not an accurate point
prediction. Zero clean sessions qualified in that interrupted/changed week.
Standing loss, useful extra heat and whole-tank reserve remain unidentified.
Real 62°C transitions and native behaviour still need supervised qualification.
CT-free adaptive did not save requests. Short app changes can remain unseen.
No check justifies enabling either feature or routine automatic operation here.

## Owner decisions and staged rollout

After independent code review resolves safety concerns, review the current
[installation](INSTALLATION.md) and [upgrade/rollback](UPGRADE.md) plans. Explicit
approval is needed for any merge, installation/deployment, live authentication,
physical transition and automatic enable. Approve these separately as appropriate;
a reviewed GitHub commit is not permission to operate the heater.

Begin with private backups and disabled bridge-first/controller/dashboard upgrade,
verify preserved options/identities/tariff/time and read-only state, then qualify
supported transitions and owner/fault handling. Record real fixed-poll usage before
considering separately supervised adaptive enable. Add the exclusive raw CT only
when commissioned, verify unchanged-zero cadence and outage recovery, then collect
and independently review target-specific held-out history before learned planning.
The last step is separate approval for supervised automatic-control activation.

The worked Tasmania/315L/GoodWe/EMHASS configuration is not universal. Verify the
actual retail contract, clock, temperatures and manufacturer/local storage hygiene
requirements. Demand/tier/conditional-free/controlled-load/time-varying-export
products and arbitrary extra setpoints remain unsupported as described in TARIFFS.

## Future distribution, deferred

No licence, release, tag, speculative packaging, credential rotation, vendor
contact or sensitive history rewrite was performed. Before future promotion,
the owner should prioritise the [existing redacted security findings](../dual-storage/PUBLIC_RELEASE.md):
historical private-key material remains reachable and a pre-existing application
key’s provenance/scope is unknown. Deleting a file or creating this branch does
not revoke an exposed identity. Assess issuer/owner remediation through approved
channels before making security claims; preserve sensitive evidence privately.
Only later, after provenance/contributor rights review, decide a suitable licence
(the prior review compares MIT/GPL) and distribution policy. No secret values
are reproduced and no ownership of third-party code is asserted.

The existing repository identity, native add-on packaging and stable entity IDs
are retained to make a later rollout straightforward. Finishing this owner’s
system takes priority over public-release administration.
