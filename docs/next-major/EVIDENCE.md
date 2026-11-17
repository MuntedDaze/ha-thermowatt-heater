# Engineering evidence and independent-review handoff

Candidate controller0.16.0 / bridge1.4.0, based on main
`7553821dceb3bc78a67621399984bbc992567aea`, [draft PR42](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/42).
Implementation/test checkpoints are in [PROGRESS](PROGRESS.md). The PR's final
handoff records the exact final head, CI results and verified artifact checksum;
the review findings are in [REVIEW](REVIEW.md).
No live HA, vendor authentication, MQTT commands or physical heater tests are used.

## Why CT-free adaptive previously cost more

V1 used30-minute CT-free checks,15-minute uncertainty fallback and a10-minute
decision prefetch. A prefetch10 minutes before a command is too old for the
unchanged60-second bridge prior rule, adding another GET. Arbitrary40-minute
phases could drift from tariff/command timing. Without a CT, absent physical
completion information also drove conservative uncertainty reads. Most ordinary
30-minute operations triggered the20-minute request-driven authentication
heuristic, making a background observation often two HTTP operations. Idle worker
ticks themselves were never password login/keepalive HTTP calls.

Earlier v2 already separated quiet owner detection from temperature freshness
and aligned consequential reads. This release extends that same bridge scheduler
with explicit v3 Smart/Minimum choices, longer bounded quiet nights, useful
prepeak observations, unchanged command-prior/confirmation, lease-loss fixed30
fallback and ordinary-GET session reuse. There is no second scheduler/client.
Actual command authentication preparation retains the old safeguards; a bounded
401 refresh/retry is counted, not hidden. No vendor lifetime is asserted.

## Compare the actual worker, including failures

[Readable comparison/category tables](COMPARISON.md),
[full seasonal JSON](SEASONAL_RESULTS.json), [short-session sensitivity](AUTH_SENSITIVITY.json).
Reproduce with dependencies from `requirements-dev.txt`:

```text
python tools/next_major_replay.py --output docs/next-major/SEASONAL_RESULTS.json
python tools/build_polling_evidence.py --check
python -m pytest tests/test_next_major_replay.py tests/test_next_major_integration.py
```

The seasonal test re-executes real production code with denied external sockets
and mocked HTTP/MQTT/storage. Summer/winter and a spring DST week include sunny,
cloudy/optimistic forecasts, heavy draws, both weekday peaks, Friday cloud/CT loss,
Saturday HA/history restart, deliberate app changes and owner resumption. The
failure cohort also drops plan delivery and rejects refresh; it verifies zero
HTTP after the persistent authentication rejection. Failure-week request counts
are **reliability evidence**, not savings from an unavailable system.

The tank model is uniform315L/3kW,8°C hysteresis,0.2°C/hour loss, rounded cloud
probe and30-second delayed command readback. It is not stratified measured tank
physics. No native protection cycle, unusual vendor/session behaviour, real
plumbing compliance or physical zero-watt proof is established. Initial/final
stored heat and export opportunity costs are accounted for; no annual saving
claim is made. Full JSON exposes temperature-target misses and nominal exposure.
CT-free Friday target misses occur in the reference fixed strategy too during
heavy demand/outage; the controller does not bypass faults/peak policy to hide them.

## Freshness and trade-offs

| Purpose | Authority retained |
|---|---|
| Immediate command | Controller configured poll+5min gate, bridge exact-prior≤60sec or guarded pre-read, once-only POST and observed confirmation |
| Heating prediction | Normal45-minute temperature validity; nominal CT-free estimates stay conditional; shorter useful observations during heating |
| Outside app change | Explicit Smart healthy quiet maximum8h / Minimum12h; daytime quiet90/180min; transient changes can be missed and outages delay further |
| Passive display | Genuine last timestamp/age; expired temperature may be unavailable. A fresh-looking display is not authority |

Smart is the recommended new option for this owner's accepted experimental
trade-off, not proof of instant app-change detection. Minimum saves more at the
cost of longer uncertainty; it is not the default upgrade choice. Fixed30 is
the conservative compatibility/fallback. Fixed60 is included for comparison,
but can increase consequential stale-planning time and cost. New modes require
matching explicit bridge/controller settings; old options/flags remain untouched.

Equal target outcomes do not imply identical energy/cost. Small CT-measured
differences are shown in the tables, not claimed away. The synthetic24-hour
session is not known vendor behaviour; the20-minute sensitivity counts expired
GET401 operations and reduces the savings. Actual TTL, refresh-token rotation,
account throttling and long-idle behaviour require separately authorised owner
evidence. Command auth locks, quota/backoff and uncertain-command no-replay cannot
be relaxed from a synthetic successful session.

## Interface and supported HA conventions

Real frontend CI on HA2026.10.4/2026.11.1 at1280/390px passed at
`0c85a0dea92838ca9056df2b2c8f31a092c026a1`. The captured phone/desktop screenshots
were downloaded and inspected. Earlier visual findings were corrected: shorter
labels, native enum translations, supported two-column sections and a plan
summary updated from the executor's completed decision. The home plan agrees
with the current requested mode, the electricity heading fits and the native
diagnostic report is selectable and readable on a phone.
No owner installation was accessed. Service calls are denied in the isolated
frontend fixture. Python/YAML checks alone are not called visual verification.

The native copyable multiline options view and standard authenticated JSON
download use an allowlist. They never serialize the config entry/raw attributes,
credentials, topics or vendor bodies. Privacy tests inject secrets in nested
state/options/intent/events. Clipboard is deliberately a native select-all/copy
view, not an unsupported automatic-copy button. HA's download wrapper can add
system metadata; the guide tells owners to inspect it before sharing.

The published heartbeat cadence is15 minutes or supervision changes; the internal
completed-evaluation time remains exact. Existing30-minute watchdogs have at
least15 minutes of normal headroom; a stopped controller is detected no later
than before. Local evaluation/command/fault supervision is not throttled.
Separate200-event diagnostic persistence cannot grant authority or block commands.

HA references: [entity descriptions and translations](https://contributors.home-assistant.io/core/entities/entity-class/),
[supported diagnostics](https://contributors.home-assistant.io/core/integrations/diagnostics/).
Standard More Info has no integration-controlled arbitrary help panel/column
widening; forms, explanatory attributes and the focused dashboard provide help.

## Independent review and final verification

Owner authorised a strictly read-only independent review after implementation,
preferably Claude Fable5.2 High. Claude was unavailable; **GPT-6 Astra High**
reviewed the full request, architecture, complete diff and applicable tests.
The implementation resolved the initial seven findings and two event-capture
races found in follow-up. [Full severity/disposition record](REVIEW.md).
Final independent code verification accepted
`a197c5ce48fcf858bef616b529fdc0a0a8a0c450`, then explicitly carried acceptance to
`0c85a0dea92838ca9056df2b2c8f31a092c026a1`, conditional on passing final-head CI,
with no additional actionable defect. No reviewer modified files or used live I/O.

Final unit/static/Python3.12/3.13/3.14, real HA, frontend, nativeamd64/aarch64,
isolatedMQTT/lifecycle/demand and Supervisor results remain required on the final
commit. The initial checkpoint's outdated upgrade-name/saved-replay expectations
were corrected; it is not the final passing head. No merge or live-installation
approval is inferred from a draft PR or modelled result.

Actual HA2026.10.4/2026.11.1 core/combined monitoring, both desktop/mobile
frontends, nativeamd64/aarch64 and Supervisor checks passed on the accepted
code head. The complete local/CI unit suites were running when this checkpoint
was written; use the final commit's actual check results linked in PR42.
Source artifacts now explicitly use the reviewed PR head, rather than GitHub's
synthetic merge-test commit, with per-file hashes and outer SHA256SUMS.
