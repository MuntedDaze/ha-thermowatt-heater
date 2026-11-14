# Final integration checkpoint

Branch `codex/thermann-final-integration`, original isolated worktree
`C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater`.
Base PR #34: `d3e26f8d54003586f9d75c29ee781231581af9cb` (1155 tests, 18 CI jobs).
Confirmed remote PR heads on 2026-11-15: #27 `1b29be1`, #33 `cf97d5e`,
#34 `d3e26f8`, #32 `4c078f0`. All remain drafts and unchanged. Fable's separate
worktree is untouched. Owner untracked `review-1b29be1/` and `uv.lock` preserved.

## Approved scope and boundaries

Implement combined read-only monitoring/dashboard, real disabled-by-default
guarded adaptive polling, validated learning architecture, week-long integrated
simulations and release/commissioning documentation. No main/protected-branch
merge, installation, real Thermann/MQTT/authentication, heater operation,
credential/history rewrite, licence selection or release publication.
New draft PR will target `codex/economic-dual-storage` (PR #34).

## Stages

1. A: inspected actual heads, AGENTS, recovery checkpoints and interfaces.
   Bridge owns HTTP/auth/accounting/confirmation. Pure policy and executor own
   desired state/guarded intent. Compact measured history is separate from HA
   Recorder. Fable package reads original entities independently. Official latest
   releases checked: HA Core 2026.11.1, Supervisor 2026.11.0; existing matrices
   already include them. Local merge of Fable #32 into this new branch is clean.
2. B: next, preserve Fable tests and validate/update four-state maps, seven
   views and actual combined HA configuration. Keep controller independent.
3. C: implement one bridge polling authority with bounded expiring controller
   hints, monotonic deadlines, fixed fallback, startup reinspection and existing
   command/auth/backoff/accounting gates. Live option defaults false and needs
   separate commissioning. Do not change vendor-token assumptions.
4. D: enrich target-labelled measured sessions and robust held-out prediction
   diagnostics; gate any learned scheduling on real evidence/commissioning and
   retain conservative nominal lower-rate fallback.
5. E: comparative polling and full-week end-to-end scenarios including owner,
   restart, cloud/meter failures, CT-free and CT-measured; equal service/terminal
   energy, request categories and detection/error trade-offs must be explicit.
6. F: compatible candidate metadata, public docs, prioritised security/licence
   remediation and rollout plan, requirements matrix and independent-review
   handoff. Full local suite and all applicable final-head CI required.

## Targeted integration findings

- Fable maps still describe the 0.9.1 baseline and omit already available
  completion/poll/learning/62-degree telemetry. Update only the combined branch.
- Fable's HA workflow validates the monitoring package alone. Add combined
  component/package/template/entity checks without external networking.
- The bridge has one clock-aligned poll timer; shadow suggestions currently have
  no actuation interface. Extend this authority rather than adding a cloud loop.
- Existing command/status freshness must not be silently relaxed by adaptive
  scheduling. Anchor hints to actual successful status; advance consequential
  reads, reuse confirmation and fall back if the controller/lease is absent.
- Learning records lack session/error/validation detail and held-out gating;
  nominal model remains the only scheduling authority until real gates pass.
- Reassess power-source freshness and strict map validation: numeric stale
  sensors currently remain available to derived monitoring energy even though
  Health reports staleness. Do not hide outages as zero measurements.

## Resume

Inspect branch/status first. Do not switch/reset existing PR branches or touch
Fable's worktree. Finish staged merge and stage B, commit logical increments and
push a separate draft PR. Python runtime:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
PYTHONPATH = absolute `.test-deps`. Use UTF-8 explicitly for text reads/writes.
Do not print the existing application key or historical private-key material.
Independent review and all physical/production gates remain outstanding.
