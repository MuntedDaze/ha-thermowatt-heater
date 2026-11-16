# Independent technical review

An independent code-review agent inspected the controller runtime changes,
existing bridge contracts, new regressions and source-preserving upgrade.
It changed no source files and used no live system. Final result:
**no outstanding material findings; approved for remaining offline checks/CI**.
It independently ran all **45 focused upgrade tests**, which passed.

Reviewer-reported LF-normalized SHA256 across38 reviewed controller source/
regression files: `b2b7fbab86c80ca8b2199edc17dcbf479f230e8e85fbacb46c0ba17fc3d3c614`.
The final PR records the actual final commit and complete CI; this digest is
review-scope evidence, not a substitute for the Git tree or final-head checks.

| Finding | Correction and regression |
|---|---|
| Pending START masks later protective OFF | Durable independent exit latch; original intent retained; one exact-prior OFF at the earliest permitted opportunity |
| Missing pending diagnostics treated as false | ExplicitFalse plus fresh/healthy diagnostics required; unknown state cannot clear exit or grant a command |
| Legacy request-counter reset creates negative usage | Anchor old0.14 samples before normalising resets, retain observed usage, reject negative totals |
| Unqualified already-heating peak state gets grace | Qualified active session or continuous full-cover export required in both CT and CT-free paths |
| Owner intervention leaves stale solar authority | App change, Hold, disable and restart retire session authority; protective-exit requirement remains separately durable |
| Statistics coverage ratio mistaken for full-day evidence | Mean remains provisional with unknown window duration; insufficient/zero/stale inputs use labelled nonzero assumption |
| OFF STATUS precedes terminal DIAGNOSTICS | Resolve from sufficient post-latch OFF evidence when final diagnostics arrive; no new-poll requirement or repeated cooldown extension |
| CT session loses permission at pre-peak boundary after using surplus | Both valid measurement modes carry an already-qualified session without requiring another3.3kW remaining export |
| Qualification inherits old80% window tolerance | Actual new solar starts require continuous10-minute genuine report coverage; repeated local ticks cannot extend it |

Tests include separate status/diagnostic delivery, delayed cloud readback, actual
mocked bridge and controller restarts, owner actions, authentication/backoff/
unknown-state blocks, CT failure, legacy persistence and cooldown overlap.
Existing bridge authentication, retry, command allowlist, persistence and
confirmation guards are unchanged. Physical commissioning remains separate.

Digest recipe: sort37 component `.py`/`.json` files plus
`tests/test_existing_installation_upgrade.py`; normalize CRLF toLF; hash each
relative POSIX path, NUL and binary SHA256 digest in order. Final boundary
regression confirms acceptable-power CT/CT-free carry and importing-session OFF.
