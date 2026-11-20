# Public-distribution review and licence decision

Review date: 2026-11-15. Scope: this candidate's tracked source/docs/tests and
reachable `HEAD` history, plus new files prepared in this increment. No live HA,
cloud credentials, account login, MQTT service or heater was accessed. No secret
was printed, modified, added to a report or revoked. No Git history was rewritten.
This is a scoped release review, not a guarantee that every historic disclosure
or arbitrary future artifact is absent.

## Redacted findings

The scan examined 360 tracked files at the simulation checkpoint and added lines
across 70 reachable commits. It searched literal secret assignments, personal
token/private-key patterns, private-address patterns and email literals. Candidate
lines were classified without printing their values. Tests use synthetic account
domains/credentials. New docs contain example settings, no account/device serials,
private HA address or copied commissioning logs. The pre-existing untracked
`review-1b29be1/` and `uv.lock` are not staged or published by this work.

| Finding | Disposition |
|---|---|
| No private-address or personal-token pattern hit in current tracked files | Limited scan result, not a certification that all possible formats are absent |
| `repository.yaml:3` contains existing public author contact metadata | Unchanged; owner should decide whether it remains appropriate before broad promotion; value omitted here |
| Account-address fixtures | Synthetic example/test/invalid domains; no real cloud account identified by this review |
| `thermowatt-heater/run.sh:10` | MQTT password variable reference, not a literal household password; unchanged |
| `thermowatt-heater/thermowatt_bridge.py:25` | Pre-existing application API key; scope/confidentiality unknown; unchanged and never printed |
| Historical `client.key` / `thermowatt-heater/client.key` | Private-key material remains in Git history; removed from current source by `dfc3c4e`. Do not reproduce it. |
| Historical root README / `.history` / shell secret-pattern matches | Existing application-key or variable-reference candidates, not new candidate additions; do not treat deletion as revocation |

The historic key exposure was already documented in
[the earlier security review](../bridge/SECURITY_REVIEW.md). Its current
permissions/revocation remain unknown; the issuer/owner should assess revocation
and replacement through official channels before claiming the old identity is
safe. The application API key's provenance and vendor terms also need owner/vendor
review before broad release assurances. A new branch cannot erase existing
history, forks or images. Do not rotate credentials, remove keys from history or
contact the issuer without separate authorisation. This work changes none of
those security behaviours.

Do not publish `/data`, HA `.storage`, add-on options, token/guard stores, debug
response bodies, unredacted serials or private commissioning backups. Current
packaging excludes key/certificate artifacts and uses a narrow source copy.
The candidate does not add any runtime secret or extra credential dependency.

## Licence recommendation, awaiting owner decision

No licence file is added or selected. Subject to verifying ownership and inherited
source/contributor rights, **MIT** is the recommended simple option for this small
community integration: broad reuse and commercial/private forks are permitted
with notice preservation, without requiring modified source to be shared.
See [the OSI MIT text](https://opensource.org/license/mit).

**GPL-3.0** is an alternative if the owner wants distributed derivative versions
to retain copyleft/source obligations; that adds redistribution obligations and
compatibility decisions for downstream adopters. It is not a promise that every
private modification must be published. See [the OSI GPL-3.0 text](https://opensource.org/license/gpl-3.0).

Public GitHub visibility does not itself supply a general open-source licence.
GitHub allows viewing/forking under its terms, while other reuse rights still
need a suitable licence. Review the repository's provenance before licensing
material the owner may not own. See [GitHub's licensing guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

## Advanced development and release boundary

Use an isolated checkout/worktree and a `codex/` development branch. Read the
owner's `AGENTS.md`; preserve uncommitted work and the tested recovery branch.
Install `requirements-dev.txt` in a private development environment, use synthetic
credentials/mocked HTTP and run the workflows in `.github/workflows/`. They cover
pytest, Ruff, strict type checks, compileall/Bash, Python 3.12–3.14, actual HA,
native amd64/aarch64 and Supervisor validation. The readiness containers have
no external network during execution; do not point tools at a running HA system.

The supported temperature protocol is closed in `targets.py` and the bridge
transition table. Extending it requires real compatibility evidence, exact-prior
guards, regressions and owner review; do not replace it with arbitrary MQTT
payloads or a guessed heating status bit. Change the one policy rather than
adding a competing planner. Keep history and adaptive comparisons diagnostic
until independent held-out/hardware validation supports further authority.

Forking/customisation depends on the outstanding licence decision. Keep any
private/local experimentation isolated and respect inherited rights. Never copy
production secrets into a fork. Dashboard work remains in Fable's independent
PR #32. This candidate stays draft, unmerged and undeployed until independent
review and explicit owner approval; GitHub approval does not authorise live HA
installation, authentication or physical heating.
