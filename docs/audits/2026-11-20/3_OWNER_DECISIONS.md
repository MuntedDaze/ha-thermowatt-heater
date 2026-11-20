# Owner decisions — Thermowatt cleanup (20 November 2026)

> **Owner answers, 20 November 2026** (recorded in
> [OPERATING_POLICY.md](../../OPERATING_POLICY.md)):
>
> - **Policy:** accepted. Every historical morning-temperature requirement is superseded.
> - **D1 approved:** 35 °C low-water warning before the evening peak only; notifications only, never heating permission or native protections.
> - **D2 approved with conditions:** Smart is the single normal polling mode, one coordinated configuration with bridge and controller aligned automatically; automatic safe fixed-polling fallback for startup, communication problems, missing plans and scheduler failures, never bypassing command freshness or request protections; keep genuinely necessary diagnostic/recovery capability without redundant normal-use choices.
> - **D3 approved:** keep 0.3 kW headroom (3.3 kW threshold) as a documented constant; check the installed value and make sure the migration cannot silently change solar qualification.
> - **D4 approved with conditions:** live controller is already 0.17.1; remove obsolete bridge command forms in a separate tested bridge release, only after verifying their consumers; never remove manual owner control, recovery, command validation or confirmation.
>
> The questions below are kept as asked.

**Base:** main d137c4c (Controller 0.17.1, bridge 1.4.1). Nothing has been
changed. This is the only document that needs your answers.

## Proposed default: the confirmed operating policy

| When | Thermostat |
|---|---|
| Weekday overnight | **Manual 45.** The heater's own thermostat runs the element (~8 °C hysteresis). No morning top-up, no 42 °C chase, no morning deadline. A bottom probe below 42 °C is accepted. |
| Weekday morning and evening peaks | OFF, or verified solar-only heating (your current setting) |
| Weekday between peaks | **Manual 62**, cheapest window, ready 30 min before the evening peak; **70** when solar genuinely qualifies |
| Weekend | 45 until 500 W PV (or the deadline fallback) opens the window; 62 by 15:30; 70 on qualified surplus; 45 at 18:00 |
| Holiday / app change / hold / 12-h Override | OFF / paused until Resume / paused / Manual 62 for 12 h |
| Protective rules | Unchanged: OFF never budget-blocked, exact-prior guarded commands, no blind retries, no auto-reset of authentication locks |

**This supersedes the 0.7.0 morning requirements (45 °C by 06:00 preferred,
42 °C by 07:00 hard) everywhere: defaults, parser, validation, documents and
tests.** The audit confirmed the running code already behaves this way; the
cancelled values survive only as stored settings, validation and documents.

If you accept the table above, no further approval is needed for it.

## Questions (only genuine behavioural choices)

### Decision 1 — Low-water notification before the morning peak

Today a fresh bottom-probe reading below 35 °C in the 30 minutes before
**either** peak sends "Hot water may be running low". With Manual 45 overnight
and early showers, this can fire before the 07:00 (AEST) morning peak even
though that is the accepted state.

- **Recommended: evening peak only.** Keeps the useful signal (62 storage did not happen before the evening peak). Morning probe readings stop notifying. Fault alerts (`parked_off_cannot_restore`, `storage_not_heating`, stale status, cloud) are unaffected.
- Keep both peaks: unchanged behaviour; occasional morning notices you have said you accept.
- Disable entirely: no low-water notices; the evening-peak check is lost.

### Decision 2 — One polling control

Smart polling only works when **both** the controller and the app are set to
Smart; the controller still defaults to "Keep existing".

- **Recommended: Smart becomes the controller's only mode** on upgrade (Minimum and Fixed 30 kept as choices; "Keep existing", the v1/v2 adaptive plans and the six legacy polling settings retire). The app's own `polling_mode` stays the single switch for the bridge. If the app is not on Smart, the bridge simply stays on fixed 30-minute reads (safe fallback, as today).
- Keep as is: two controls, explained in help text.

This changes polling behaviour on your installation, so it needs your yes.

### Decision 3 — The hidden 0.3 kW solar-start headroom

The boost start threshold is element power + 0.3 kW = **3.3 kW** of sustained
export. The 0.3 kW comes from `export_headroom_kw`, a setting wrongly labelled
"Retired" and not visible anywhere.

- **Recommended: make it a fixed constant (0.3 kW)** in code, same value, no setting. Behaviour unchanged.
- Show it as an Advanced setting instead (same value), if you want to tune boost sensitivity.

### Decision 4 — Old bridge command forms (later release, optional)

The app still accepts the 1.3.11 bare `Manual:70`/`off` commands and an
explicit `command_policy: legacy` (full old command set). Neither is used by
Controller ≥ 0.9.0.

- **Recommended: defer.** Leave them until the controller and app upgrade on your system is complete, then remove in a separate approved bridge release. Removing them now gains little and is a command-path change.
- Remove in this cleanup.

## Not asked (decided by the audit; no behaviour change)

Retire the 32 inert settings and stop validating them; keep stored values for
rollback; rename the "Morning hot water availability" sensor label (ID kept);
delete the unused morning helper; fix stale docstrings and alert text;
consolidate documentation (below). Commissioning records, budgets, freshness
limits and safety checks stay exactly as they are.

## Undecided items deliberately left alone

From the 19 Nov report, P1 (allow a qualified pre-peak solar start under
solar-only), P2 (avoid "62 first" when export already qualifies) and P3
(GoodWe gaps during a peak solar session) remain open. **Recommended: no
change until live exports show the 19 Nov cause.** They are optimisation, not
cleanup.

## One source of truth

Proposed: a single `docs/OPERATING_POLICY.md` with three clearly separated parts:

1. **Current policy** — the table above and the decisions you make here, each dated. Explicitly supersedes the morning requirements.
2. **How it is implemented** — the specification in `1_OPERATING_SPECIFICATION.md`, with code locations, kept in step with each release.
3. **Pointers to history** — everything else.

`docs/decisions/HOT_WATER_TEMPERATURE.md` stays as the temperature decision
record and is linked from part 1. `README.md`, `shadow_controller/README.md`
and the add-on `DOCS.md` link to it instead of restating policy. Every phase
folder moves to `docs/history/` unchanged.

---

Reply with, for example: "Accept policy; D1 evening only; D2 Smart; D3 constant;
D4 defer."
