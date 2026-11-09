# Security review for 1.3.2

## Removed bundled client identity

`thermowatt-heater/client.key` was an **unencrypted RSA private key**. Offline
cryptographic inspection confirmed its public key matches `client.crt`. That
certificate is valid from 2021-02-15 through 2049-12-31. It was copied into every
add-on image even though certificate-based cloud MQTT support was removed in
1.3.0. Its current cloud permissions/revocation status are unknown and were not
tested. Treat it as exposed: deletion from this branch does not revoke it or
erase Git history, forks, caches or previously built images. The issuer/owner
should assess revocation and replacement of any affected identity. No issuer or
external party was contacted during this work.

`client.crt` is the corresponding public certificate. `root.pem` is a public CA
certificate (valid 2015-05-26 through 2038-01-17), not a private key. Both are
unused by the current REST implementation and were removed with the key. None
is used as a substitute trust store for HTTPS. The Docker build context now
excludes key/certificate files and copies only the required application files.

The pre-existing hardcoded API key and app/version identifiers remain solely to
preserve the existing MyThermowatt contract. The key is already public in repository
history. Its scope and whether the vendor considers it confidential are unknown.
It must not be used as proof of account eligibility, logged, or treated as a
user credential. Only the vendor can confirm its scope and rotate it if necessary.

## Credentials and tokens

- Supervisor supplies the password through supported `/data/options.json` and
  its `password` schema type / `!secret` mechanism. Masking the field in the UI
  is not encryption at rest. The bridge no longer logs email or passes the
  password to Python through process arguments. It does not copy passwords
  into its own persisted files.
- Access/refresh tokens must remain available across restarts to avoid repeated
  password logins. They are stored only with the guard in private `/data/auth_state.json`,
  using atomic replacement, file/directory fsync on Linux and mode 0600. The
  existing metadata file is migrated to remove legacy tokens. This does not
  erase secrets from older backups or filesystem snapshots.
- Tokens are plaintext at rest, accessible to administrators, container root
  and anyone with an unencrypted backup. They are not encrypted with a key
  shipped in the same image. Protect backups and private data; use encrypted
  backups and revoke exposed sessions through official vendor mechanisms.
- Account association is a SHA-256 fingerprint of the configured email, not
  the email itself. It is a consistency check, not encryption. Changing accounts
  cannot automatically reuse the old account's tokens or clear a lockout.
- MQTT credentials come from Supervisor service discovery and are passed in
  the process environment. They are never logged. The existing local MQTT
  connection is plaintext on the Supervisor network; host/container administrators
  remain trusted. No cloud MQTT keys are used.
- HTTPS verification remains mandatory with normal trusted CAs, explicit
  connect/read timeouts, no redirects and no implicit netrc/proxy credentials.
  The runtime logs fixed diagnostic codes, never response bodies, raw exceptions,
  credentials, API keys or tokens. Status publication uses an allowlist.

## Remaining operational limits

The persistent guard assumes one Supervisor-managed instance and intact private
storage. It cannot coordinate separate installations or survive storage deletion,
backup rollback or an administrator deliberately authorising repeated generations.
An auth request interrupted by termination is treated as unknown and locks.
Read failures never cause password fallback; write timeouts are never replayed.

Mock tests verify local policy, not the vendor's undocumented API or physical
device behaviour. On 2026-11-09 the owner reported successful real HA OS
authentication, MQTT discovery and initial read-only status display using the
Thermann Control account with commands disabled. This does not verify temperature
accuracy, mode mapping, heater controls or the cause of the earlier lockout.
The agent did not access or modify the owner's Home Assistant, VMs or Docker
services. Further development and control testing are paused for owner review.
