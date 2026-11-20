# Jacob's existing-system upgrade: controller0.16 / bridge1.4

This guide is for the installed HA OS on Proxmox, bridge1.3.17 with persistent
credentials/tokens/guards, MQTT/Mosquitto, controller0.15.1, Thermann315L/3kW,
GoodWe GW5000-DNS-30/HK1000,6.6kW solar and EMHASS. No dedicated heater CT yet.
Development has not inspected or changed that installation. These instructions
are for the owner after review/approval, not permission for an agent to deploy.

## 1. Record and back up

1. Open **Settings → System → Backups**. Create a full backup containing HA
   configuration and the installed Thermann Hot Water App's private data. Download
   it and retain its recovery key securely. A separate verified Proxmox VM backup
   is helpful; a backup file existing is weaker than a tested isolated restore.
2. Privately record App version/options, repository identity, controller version,
   entity IDs/mappings, automatic/command/cloud flags, authentication generation,
   tariff/clock/prices, temperatures, Hold/Holiday/override expiry, pending command
   and protective-exit state. Use the current diagnostic report if available.
   Do not publish options containing credentials or private authentication files.
3. Choose a quiet off-peak maintenance period. Deliberately turn Automatic heater
   control OFF before replacing code, and stop the existing bridge App for its
   update. Inspect any pending/uncertain command first; disabling does not cancel
   an already-sent command or electrical heating. Do not clear intent/guard state.
   Note the original settings so you can deliberately restore them later.

## 2. Get the exact reviewed files

Use the full40-character reviewed commit in PR42's final handoff and its verified
source bundle/SHA256. A moving branch ZIP is not an exact reviewed artifact.
The bundle includes a per-file `REVIEWED_MANIFEST.json`; verify the outer SHA256
and that its commit/component versions match the handoff. Windows PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Downloads\thermowatt-reviewed.zip'
```

The existing GitHub App-store repository follows main, not this unmerged branch.
**The normal App update is available only after the separately approved merge**
and repository catalog refresh. Do not add a second local/development bridge or
change the repository URL to make an unmerged draft look installed. The source
bundle is reviewable staging material; it does not update a running App itself.

## 3. Update the existing bridge in place

After the approved main merge, open **Settings → Apps → App store → ⋮ → Check
for updates** (older HA versions call Apps Add-ons). Open the **existing Thermann
Hot Water App** and confirm the offered1.4.0 changelog/source commit (for the later 1.4.1 maintenance
update, follow [the 1.4.1 procedure](../audits/UPGRADE_1_4_1.md) instead). Use its
normal **Update** action. It builds/updates the existing App identity
`thermowatt_boiler`; do not uninstall, recreate, add a second repository copy or
delete `/data`. Keep MQTT identity/options, credentials, auth store, guard,
generation, accounting and command journal. Updating is not authentication recovery.

Verify your original cloud/command flags and numeric interval are retained.
The new polling choice defaults **Keep existing**. Existing adaptive/qualification
flags are retained; upgrade enables none. Do not change `auth_retry_generation`,
credentials, retry/backoff or cloud flags simply because the App updated.

## 4. Update the controller without recreating it

Using your established HA file-access method, copy the bundle's complete
`custom_components/thermann_shadow/` contents into the same
`/config/custom_components/thermann_shadow/` directory. `manifest.json` must sit
directly there, not inside a repeated subfolder. Overwrite source, not private
state. Keep `.storage`, the existing integration entry, entity registry, MQTT
discovery and all existing YAML/includes. Do not copy another household's data.

Open **Developer tools → YAML → Check configuration**, then restart HA once.
Confirm controller0.16.0, original entry/unique IDs/history, original mappings,
prices/clock and45/62/70 roles. Preserve your existing holiday/override expiry
and pending intent. An active legacy70 override keeps its target/expiry; a new
override requests62. Restart re-inspects and does not blindly replay a command.

## 5. Add the focused dashboard; retain the seven-view dashboard

Follow [the native dashboard installation](../../owner/INTERFACE.md). Add a separate
Thermowatt dashboard from `homeowner/thermowatt.yaml`; do not replace your existing
seven-view whole-home dashboard. This task does not modify Fable's files.
If you renamed entities, adjust only dashboard references using your existing IDs.
New labels do not require re-creating entities.

## 6. Verify the actual sensor mappings

Open **Settings → Devices & services → Thermann Controller → Configure**.
Use **Advanced/System → Bridge status readings** for existing heater, mode,
last-successful-poll, cloud-health and lifetime request counter. Use
**Solar & Meters → Solar and meter readings** for your actual GoodWe grid,
usable AC output, solar, household load and EMHASS PV/load entities.
Check **Developer tools → States** to confirm the exact existing IDs, W/kW units,
raw signs, original generation/report times and post-startup freshness.

Leave hot-water circuit power/energy unmapped until the Shelly is installed.
Do not map `sensor.em_hot_water_power` or another dashboard wrapper as authority.
HK1000 grid power is a whole-house signed reading, not physical heater verification.
For this installation export is positive; verify it against a known household load.
EMHASS remains independently managed; retain original generation timestamps and
forecast series. Do not repeatedly run its optimisation to produce fake freshness.

## 7. Verify tariffs, temperatures and preferences

In **Electricity Tariffs → Plan, prices and clock**, verify Australia/Hobart and
fixed-standard tariff clock. Check the actual Aurora contract and weekdays/windows.
The owner's recorded example prices are peak36.1878c/kWh, off-peak17.02c/kWh,
feed-in9.276c/kWh. These are owner data, not universal/current tariff promises.
At summer daylight saving,07:00AEST is08:00Hobart wall time. Inspect both next
boundaries and prices. Do not mark a contract verified without checking it.

Retain Manual45 baseline,62 normal storage, optional70 and chosen peak policy.
Review the newly documented weekend500W/15min comfort62 preference and sunset/end
settings. The separate override is now62. Upgrade preserves saved roles and gates;
it does not certify manufacturer/plumbing compliance.

## 8. Inspect read-only operation first

Keep Automatic OFF and deliberately retained bridge command settings safe for
this check. Start only the existing App when you choose to resume its established
cloud access. This owner action makes real requests; no development agent has
performed it. Confirm cloud health, actual successful observation, temperature
timestamp and request categories. Inspect Home plan, tariff, requested versus
confirmed states and diagnostic report. Opening forms/reports sends no commands.

## 9. Choose optional experimental modes deliberately

For CT-free boost, complete **Solar & Meters → Set up experimental CT-free solar**
with real live grid/AC/house evidence, known-load direction check and explicit
risk acceptance. Leave peak permission off unless you choose its short-import
and delayed/unconfirmed-OFF exposure. This records no fabricated CT qualification.
It does not enable automation. Existing physical qualifications are preserved,
not automatically ticked. [Capabilities and risks](HANDBOOK.md#solar-and-weekends).

For Smart polling, select Smart in both the App Configuration and controller
**Advanced/System → Cloud checks and data age**. Review the up-to8h healthy quiet
app-change detection delay. Minimum permits12h; Fixed30 remains compatibility.
Do not alter authentication generation or claim vendor session lifetime from models.

## 10. Approved owner trials

Only after your separate installation/operation decision, deliberately restore
the intended bridge command flag and Automatic state. Existing commissioned
four-state guards still apply; do not invent physical qualification. Observe
each actual transition's prior, once-only submission and fresh confirmation.
Check quiet baseline, weekday62 planning, peak OFF/restoration, owner Hold/Resume,
62 override/cancel/expiry and weekend latch. Prefer separately approved monitored
trials at off-peak with the official app available. No software warning promises
electrical zero or automatic cloud recovery.

## 11. Measure real behaviour

Take diagnostic snapshots before/after representative quiet nights and heating
days. Compare lifetime category deltas: status, command-refresh/pre-read,
confirmation, command POST, token refresh, login and discovery. Record starts,
targets, comfort, costs, owner changes and cloud failures. Do not compare only
background polls or call a safely locked/unavailable system a request saving.
Native protection, vendor session expiry, tank stratification and real comfort
need owner evidence; synthetic replays do not establish these physical facts.

## 12. Add the Shelly later

A qualified installer supplies a dedicated heater circuit measurement. Map the
raw signed active-power entity and raw cumulative import-energy entity when
available; keep the signed power. Verify W/kW, energy units, exclusive circuit,
post-startup freshness and repeated steady0W reports. Use the existing approved
circuit commissioning path; a changed mapping clears the old qualification and
learned authority. Do not use AC/oven channels to gate hot water. The dashboard
and required control need no rebuild; clean heating cycles begin learning only
after valid measurements arrive. A meter that expires remains unavailable, not0W.

## 13. Back out safely

If checks fail, leave new routine control disabled, preserve diagnostics/state
and use the official app for deliberate intended temperature when available.
Do not reset authentication or replay pending POSTs. Confirm unresolved protective
OFF/intent before any downgrade; older code may not understand new diagnostic/
cooldown/latch fields. The safest exact rollback is the verified full HA/App
private-data backup plus matching source/image/VM state, restored deliberately
with duplicate instances isolated. App source rollback alone does not restore
private journals or an older image. Do not uninstall to attempt it.

## Success checklist

- Same App identity, entry, entity IDs, mappings, credentials, token/guard/accounting
  and selected temperatures; original flags retained until deliberate choice.
- Correct summer/winter tariff boundaries, rates and next intended changes.
- Clearly separate confirmed cloud state, inferred activity and unavailable CT.
- Working copyable report/JSON; readable desktop/mobile dashboard; no missing rows.
- Owner-approved trials show exact prior and confirmation, no duplicate commands,
  peak policy, known owner holds, useful weekend comfort and baseline return.
- Request-category evidence and any failures captured without exposing secrets.
- Working recovery/backup path and understanding that cloud OFF is not isolation.
