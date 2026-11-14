# Heating observations and validated prediction gate

Actual control is not enabled by this development. The new **Use validated
conservative learned heating rate** and **Heating learning independently
qualified** settings both default false. Synthetic regression success never
sets either commissioning fact or supplies real heater evidence.

## What is measured

The existing compact `.measured_history_v2` sidecar retains covered CT-integrated
energy and optional native-counter epochs. HA Recorder retains original meter,
temperature and controller events. No second raw-sample database is added.
Gaps/restarts are never filled with nominal watts. Native counter deltas can
recover total energy across a gap but cannot invent the missing timing,
tariff/solar allocation or a heating cycle.

New clean session rows add model version, actual target (45/62/70), volume,
nominal power, commissioned meter identity, first-observed cycle start/end,
whether an OFF→ON start was actually covered, fitted interval start/end,
temperature change, covered fit energy and duration, and quality. Cycle energy
is the covered integral from reports, not exact electrical switch timing or a
whole-tank energy measurement. All timestamps are HA/bridge receipt times; the
vendor's acquisition time remains unverified.

A cycle first seen already running may remain diagnostic, but cannot satisfy
the new complete-start gate. Duplicate callbacks do not add energy or sessions.
Meter loss, long gaps, target/mode/command changes, implausible slopes and
draw-like temperature changes invalidate the fit; the existing gap count remains
visible. Unknown/missing old fields never become invented good evidence.
Old v1 target-unknown records and v2 records lacking the new validation provenance
are retained, not relabelled as new qualified training sessions.

## Robust held-out validation

Each fit uses only its target, nominal model and exact commissioned meter identity.
Only complete clean independent sessions from the last 30 days are eligible:

- At least **20 sessions on five days**.
- The latest **at least two whole days** (30% of observed days, rounded up) are
  held out; at least ten training and five held-out sessions are required.
- The fitted rate is the median of training rates; variation uses median
  absolute deviation. Held-out observations never enter that fitted rate.
- Held-out mean absolute time error must be ≤15 minutes, 90th-percentile
  relative error ≤25%, and the conservative duration must cover at least 90%
  of held-out intervals.
- The conservative rate uses a lower observed training quantile with a 5%
  reserve, capped at nominal. These are explicit engineering qualification
  thresholds, not a proved probabilistic guarantee about a stratified tank.

Remapping or changing the meter/unit, volume or nominal power clears hardware
qualification or changes the cohort. Restart preserves completed observations
but clears active cycle/anchors. Corrupt/incomplete rows, duplicates, future
times and old cohorts cannot manufacture eligibility. History must save
successfully; a persistence failure returns planning to nominal.

## Planning authority

Before every condition and both enable/commissioning gates pass, planning uses
conservative nominal physics or slower verified instantaneous element watts.
CT-free operation always retains the labelled nominal model and unknown physical
element state. After real qualification, each target can supply only a lower
rate bound, also capped by current verified live-watt physics. It can advance
a required start or reject an optional opportunity that no longer fits; it
cannot use an optimistic fit to delay required heating beyond the nominal
boundary. Every cloud/owner/peak/budget/command-confirmation guard still applies.

Telemetry includes learning eligibility, training/held-out counts/days, fitted
rate and variation, held-out error/coverage, chosen rate/basis and whether it
actually affected planning. The dashboard shows those diagnostics separately
from the requested target and measured probe. Completion remains a conditional
continuous-heating range, not a guaranteed shower reserve or achieved target.

## What one probe cannot identify

The bottom probe cannot independently separate standby loss, stratification and
water draws. It also cannot establish whether extra 62→70°C heat was usefully
consumed instead of lost. The telemetry explicitly marks thermal-loss
identification false and extra-storage usefulness unidentified. The existing
configured useful-demand fraction remains an assumption. Independent demand/no-draw
evidence and real held-out observations are needed before fitting those effects
or allowing them to influence scheduling. Native hysteresis is respected; sparse
cloud readings do not prove exact cut-in/cut-out temperatures.
