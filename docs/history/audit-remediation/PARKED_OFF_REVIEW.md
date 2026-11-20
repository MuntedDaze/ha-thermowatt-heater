# PR37 parked-OFF warning follow-up

Review baseline: `94a7dd4cee49901d972ece2606315ac97ca3e314`, preserved in history.
Scope is notification/diagnostics only. Candidate bridge 1.3.17/controller 0.13.0
versions are retained; no released installation is changed.

## Correction

`Executor.decide` still returns the actual `hold` decision when the controller's
current heater state is unknown. If its last genuine observation was OFF, it
also asks the **same unchanged policy**, with that previous OFF as a diagnostic
reference, whether a thermostat restoration is wanted now. Only the target is
attached as `plan.unconfirmed_restore_target_c`; no counterfactual command is
used or published. The real decision's state/reason/command remain unchanged.

The policy's target before its command gates retains unmet need during command
spacing/freshness holds. Holiday, peak/lead parking, reserved pre-peak command
slots, economic waiting and deliberate owner holds supply no restoration target.
Simply allowing every unknown heater would incorrectly arm warnings in these
legitimate OFF periods, because unknown-state HOLD precedes those policy rules.

`Controller._supervise_alerts` accepts this diagnostic only for unknown-current
`hold/heater_state_not_controlled`, with a supported target, genuine last OFF,
enabled supervision and no owner hold/override. The existing timestamp, 30-minute
threshold, notification key/title/message/cooldown and persistence remain.

On a new genuine report, an uncontrolled mode/unsupported target invalidates
older OFF evidence. Unavailable entities retain the last genuine observation.
A new Manual report clears the restoration warning but does **not** acknowledge
a fault or re-enable commands. Acknowledgement during an outage still requires
a new genuine status and does not restart the warning's age.

## Regression evidence

`tests/test_parked_off_warning.py`: 19 tests use the actual executor-generated
desired state, real controller/bridge worker and synthetic HA/MQTT/HTTP/time.

- Authentication refusal before `Manual:45@off`, failed pre-command GET and an
  uncertain POST each reach fault-locked unknown-current HOLD and warn at 30 minutes.
- Confirmation/pending outcomes and normal backoff run without forced retries;
  no heater POST is added. A blocked authentication guard sends no further HTTP.
- Fault acknowledgement during outage, restart before/after the warning and
  persisted notification deduplication keep the original age and safeguards.
- Genuine restoration clears the warning while the fault stays locked until
  explicit acknowledgement and a fresh status; no repeated restoration command.
- Negative cases cover peak, peak lead, reserved command slot, holiday, owner
  hold/change, economic OFF waiting and missing previous provenance.
- Unavailable entities retain genuine OFF; newer Schedule/unsupported Manual
  reports invalidate it even while fault-locked.

The full suite/static checks and every applicable final-head CI workflow are
required. Exact final SHA and results are recorded in draft PR37/completion
report as delegated by the checkpoint; do not infer them from the 94a7dd4 checks.

## Short independent verification

Inspect only the `controller.py`/`executor.py` diagnostic delta from 94a7dd4 and
the new regression file. Confirm the actual decision stays HOLD with no command,
only a current policy requirement can arm the timer, deliberate OFF is excluded,
and fresh uncontrolled reports invalidate stale OFF provenance. Re-run the 19
tests and inspect final-head CI. The bridge, authentication, polling, command
gates, acknowledgement and 45/62/70 roles have no functional changes.

No merge, install, live HA/cloud access, authentication, actual MQTT/heater
command or automatic enablement was performed or authorised. Next steps remain
brief independent verification and the owner's separate merge/install approvals.
