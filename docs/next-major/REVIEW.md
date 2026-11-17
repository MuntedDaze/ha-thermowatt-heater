# Independent review and remediation

Reviewer: **GPT-6 Astra, High reasoning**, strictly read-only. Claude Fable5.2 was
the owner's preferred reviewer but is unavailable in this agent environment.
Initial reviewed range: `7553821d..0b374a203f2505987297db1d99ec5da568289ba3`.
The reviewer received the full attached master request, architecture, complete
changed-file diff, tests and evidence paths, not just an implementation summary.
It did not edit files, push, merge, operate services or contact equipment/vendor.

| Finding | Severity / original reference | Correction and verification |
|---|---|---|
| Non-divisor measurement cadence prevents sustained withdrawal/qualification | P1, `simple_policy.py` original170–181,260–315 | One genuine suffix-coverage helper anchored to the latest report; includes the first report at/before the boundary, gaps/liveness and every failing reset. Tests130s grid,120s PV, uneven timing and brief resets; no early inference from timer ticks |
| Already-selected normal storage bypasses CT-free startup checks; adopted session not recorded | P1, original610–640; controller928 | In-place peak adoption now reuses the complete optional-start/economic test and requires genuinely recent matching cloud state plus existing exit guard readiness. Records permission without any heater command; restart/owner/fault/required-only context clears it. Tests actual executor-generated desired states from raw valid/missing/inconsistent AC evidence and naturally falling export |
| Completion margin/peak lead combination crashes policy construction | P2, config308/executor165 | Shared validation requires completion margin greater than lead. Equality/both sides regressions and actual HA form rejection/no-save check |
| Weekend ended baseline cannot use quiet Smart polling | P2, executor366 | Confirmed eligible `weekend_day_ended` is treated as baseline for quiet classification; genuine cold readings still need useful checks |
| Quiet alerts trust stale diagnostics/max interval instead of actual missed poll | P2, executor384–423 | Requires post-startup≤120s bridge heartbeat and bridge availability; deadline is accepted actual next check bounded by owner limit, plus5min grace. Tests missed earlier check/frozen diagnostics |
| PV dip/recovery can escape continuous qualification | P2, `__init__.py`129–137 | PV included and subscriptions rebound on mapping edits. Genuine event payloads are captured before queued evaluations coalesce; grid evidence also retains intermediate resets. Unit/raw-event and actual HA same-turn dip/recovery regressions |
| Diagnostic history omits solar reasons and actual timestamps/override | P2, runtime377–412/report182–190 | Typed eligibility/rejection retained in allowlisted event persistence/export;62 override code/explanation and resolved/protective-exit timestamps preserved; secret redaction regressions |

No new uncertain-POST replay or authentication-lock bypass was identified by the
initial reviewer. Its conclusion was **corrections required before merge**.
The implementing agent accepted all seven findings. Another CI portability issue
was also corrected: the generated owner guide no longer enumerates OS-dependent
time-zone aliases, with a regression proving output stability.

The follow-up review at66aee0d accepted the original reproductions but found
twoP1 races in the new raw-event capture: a circuit reading more than60 seconds
from grid could leave a false positive qualification vote, and grid loss/recovery
within one event-loop turn could erase a required withdrawal.

The next correction permits raw CT callbacks to **invalidate only**, with the
existing60-second pairing check and failure/reset markers. Only the canonical
executor can grant positive CT votes from its current paired observations.
Impossible CT-free export is rejected before becoming a vote. Transient grid/CT
loss is retained until the single controller durably records a protective exit
or resolves the optional context; sunshine/recovery cannot erase it, including
while START is pending. No callback sends commands. New regressions reproduce
old ON→fresh0W, impossible export→valid, and active/pending meter loss/recovery;
the real HA fixture also exercises coalesced outage/recovery with all commands
blocked by absent transport/commissioning.

Twenty-five targeted remediation tests pass. The existing non-replay regression
suite also passed before the final added tests. Functional corrections and replay
artifacts are committed; final independent acceptance follows below. Use the
PR's final-head CI results for completion evidence. This is not physical
commissioning or installation approval.

## Final independent code verification

Astra High accepted the corrected code at
`a197c5ce48fcf858bef616b529fdc0a0a8a0c450`, conditional on passing final-head CI.
Both remainingP1 reproductions were resolved; no further actionable code defect
was reported. The reviewer traced owner Hold, override, restart, failed save and
pending-command handling and inspected regressions without running tests or
contacting live equipment. Final CI and explicit owner merge approval are separate.
Subsequent changes are documentation, test-fixture cleanup and exact-head source-artifact metadata,
not controller behaviour. Final checks are linked from the PR's current head.
