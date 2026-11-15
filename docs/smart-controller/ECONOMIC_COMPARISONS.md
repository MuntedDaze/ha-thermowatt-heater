# Offline dispatch and polling comparisons

Reproduce with `python tools/controller_replay.py --output
docs/smart-controller/SIMULATION_RESULTS.json`. The JSON is checked against the
current code by tests. No network or Home Assistant instance is used. These are
illustrative scenarios, not observed operation, a tariff quote or annual savings.
The existing configured tariff/FIT values are inputs, to be checked at commissioning.

Each dispatch row supplies the same 1.50 kWh useful heat: heat not delivered in
the 30-minute peak slice is replenished later off-peak by construction. This
makes monetary comparisons meaningful, but does not prove future comfort or
available solar. The model uses a continuous element, no command latency or
stratification. The full executor/bridge/tank regressions separately cover real
guard interactions with mocked HTTP.

| Injected conditions | Five-minute withdrawal | Two-minute withdrawal | Result |
|---|---|---|---|
| Three useful sun minutes, then dark | 0.25 kWh peak grid | 0.10 kWh peak grid | Faster OFF saves about 2.9 cents |
| Four-minute passing cloud | 0.20 peak / 0.50 later grid kWh | 0.10 peak / 1.20 later grid kWh | Faster OFF costs about 2.7 cents after forgone export |
| Clear | 1.00 kWh solar + 0.50 later grid | Same | No benefit from shorter withdrawal |
| Small sustained import within tolerance | Allowed measured tolerance | Same | Avoid trivial toggles |

Retain the shared **five-minute** withdrawal, ten-minute full-cover qualification,
0.2 kW import tolerance and 15-minute ordinary command spacing. Faster withdrawal
does not win reliably on these counterexamples. Weekend optional heat now
returns to native 45 on sustained import even if forecasts promise returning
solar; ordinary spacing still bounds its early-session exposure. Weekday required
storage may deliberately import off-peak; it is not an optional opportunity.

Feed-in revenue is an opportunity cost. A peak solar start is uneconomic when
that foregone value fails the minimum saving against later off-peak grid heat.
That condition now blocks optional peak starts/continuation. It does not alter
owner override or hard import/sensor guards. Advanced preferences expose the
existing 2 cents/kWh optional margin and 30 cents minimum saving to pause a
committed weekday heat. Defaults are unchanged; changing these settings requires
control off and Restore preserves them. A verified low ON plateau advances the
required latest start conservatively; a momentarily high plateau never delays
it past nominal physics. Learned temperature slopes remain diagnostic.

Optional starts now reserve ten controller-estimated HTTP operations for two
essential transitions (pre-read, POST, bounded confirmations and possible refresh).
This does not grant or bypass vendor quota, bridge backoff or authentication.
Missing request accounting blocks eligibility; remaining budget is a rolling
24-hour controller estimate, not a known vendor allowance. OFF retains existing
priority and prior-state/confirmation protections. Future-dated observations
cannot start **or confirm** a command; future bridge result times are rejected.
Scheduled control also requires verified tariff commissioning.

The 24-hour request model includes four synthetic commands at minutes
367/667/907/1327, refresh at token age ≥20 minutes, pre-reads when status is older
than one minute, post-command confirmation, and three-minute routine reuse.
It independently produces **108 / 60 / 51** HTTP operations for fixed 30 / fixed
60 / bounded adaptive timing. These differ from Astra's 107/59/50 because the
phase/initial ledger differs. They are not acceptance targets or vendor results.
The injected persistent owner event at minute 383 is detected after 7 / 37 / 45
minutes respectively; maximum status gaps are 30 / 60 / 90 minutes. A transient
event can be missed. Counts assume successful operations and an unchanged command
timeline; auth failures and unobserved app changes are not modelled probabilities.
Actual adaptive polling remains disabled and shadow-only.

Preserved regression coverage includes no/stale GoodWe, raw CT loss/recovery,
Manual 45 thermostat cycles, idle Manual 70, appliances, sunset/peak/soft target,
weekend imports, holiday/hold/override, missing forecasts, HA restart, future
timestamps, auth/backoff/budgets, confirmation, duplicate callbacks and DST/tariff
rollovers. Additional hardware and held-out learning validation is required before
any enablement. Existing bridge and native protection behaviour are unchanged.
