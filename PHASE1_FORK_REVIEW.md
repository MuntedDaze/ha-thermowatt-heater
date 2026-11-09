# Phase 1 source comparison — review only, 2026-11-09

Baseline: MuntedDaze v1.3.6 (`41ace62`). Public GitHub source/discussions only;
no vendor endpoint, Home Assistant host, live credential or physical device was
accessed. Fork files were inspected as references, never blindly merged/executed.

| Reference | Evidence reviewed | Decision |
| --- | --- | --- |
| [MMicieli main](https://github.com/MMicieli/ha-thermowatt-heater) | Bridge blob `21ed51f0af922d83bb95c1a4d0f83bfa94092d6a`, config blob `776abf1c09946ba9a173a3146e25e15f5bf7f100`: quota classification, persistent counters/episodes, diagnostic freshness and single-loop demand refresh. | Adopt the concepts of confirmed quota classification, privacy-safe attempt counting, freshness diagnostics and single-worker coalescing. Independently implement small equivalents around our existing guard. |
| [MMicieli issue #17](https://github.com/MMicieli/ha-thermowatt-heater/issues/17) | First-party deployment observations and design discussion. Rejections can coincide with HTTP 200. Expired tokens can cause a GET 401, refresh POST and read replay. Counts at rejection differ by observation window. | Count all attempts, including auth/replays/confirmation. These are another installation's observations, not our vendor allowance, reset rule, token lifetime or guaranteed quota. Do not infer a daily limit from the cited totals. |
| [MMicieli PR #22](https://github.com/MMicieli/ha-thermowatt-heater/pull/22) | PR metadata, changed-file list/patch and discussion; reviewed head `16127483d14c988db9f5df435b3f7edab08ec07f`. No HTTP in MQTT callback, coalesced device requests and loop-owned reads. The discussion records a previously reviewed runtime head and later operator Docker evidence. | Use the single-worker concept for the separate optional on-demand follow-up, with stronger spacing and no immediate transport retry. Do not import its HA Package 19, proactive token refresh or control policy. Its 120-second freshness contract and 300-second offline bound belong to that installation, not ours. |
| [savvaskoualis](https://github.com/savvaskoualis/ha-thermowatt-heater) | Bridge blob `268b91149ba9c273d76729f73ebdc1533ba8a41b`: diagnostic availability independent of device availability, last-success timestamps, command observation. | Adopt read-only diagnostic availability/freshness ideas. Retain our existing command implementation. Do not adopt unverified `WaterHeaterSts & 1` heating interpretation or derived electrical measurements. |
| [echoztrip](https://github.com/echoztrip/ha-thermowatt-heater) | Bridge blob `c7934e28e11ba096d901a6595590d927ffece554`: adaptive fast polling and `_inject_fake_status`; directory includes legacy private-key/certificate files. | Do not adopt synthetic/optimistic status injection, heating-bit decoding, bundled keys, short automatic polling escalations or broad source replacement. No key contents were fetched. |

## Stronger local protections retained

TLS verification, no credential redirects, private token storage, persisted
authentication intent/budgets, fail-closed interruption, operator-controlled
lockouts, no password fallback, default-disabled commands and confirmed-state
guards remain. HTTP 429 still locks persistently; a fork's automatic recovery
probe must not silently replace that policy. JSON quota failures retain ordinary
bounded cooldown behavior and gain an exact diagnostic, not guessed API forms.

Exact detection means `error == "Daily request limit exceeded"` in a JSON object,
not substring matching, case folding, arbitrary message fields or treating every
`success=false` as quota. No token-expiry/JWT changes are adopted in Phase 1.

## Configuration and accounting decisions

There is one numeric polling field and one unit selector. The numeric field keeps
the old `poll_interval_minutes` key but has the form label **Polling interval**.
Missing units mean Minutes. This preserves old saved values even when Supervisor
merges in new defaults and avoids two numeric settings with ambiguous precedence.
In raw YAML the historic key follows the selected unit; examples document this.
The bridge checks the combined 60–7200-second bounds before startup; the form
describes the valid ranges (Seconds 60–7200; Minutes 1–120).

Request accounting is a local lifetime attempt ledger, not a calendar-day or
rolling vendor-consumption meter. Six fixed categories and aggregate timestamps
are private, persisted before I/O when possible, and contain no account/device
IDs, credentials, tokens, URLs or bodies. A crash can overcount an unsent attempt;
transport errors do not prove server receipt. Corrupt/unwritable storage marks
history incomplete rather than changing authentication/command permission.
Local ordinary cooldown persistence uses our own deadlines, not an inferred
vendor reset. A configurable enforced quota remains deferred.

## Smart polling scope

Slow background polling plus explicit, bounded demand reads is the useful
pattern. It does not mean polling on every PV/grid-price change, dashboard
subscription, temperature comparison or optimiser recalculation. A demand caller
must wait for a genuinely newer last-success timestamp and fail closed on
cooldown, missing data or timeout. The optional follow-up stays disabled by
default. It does not relax the existing 60-second command-state freshness guard.

The live vendor quota, sustainable cadence, physical heating indication and
control/handback semantics remain unverified. External fork test reports are
reference evidence, not tests passed by this repository or this heater.
