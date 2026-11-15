# Jacob’s CT-free installation, then Shelly later

This is a **future owner procedure**, not permission to run it now. The candidate
is unmerged and has not been installed on your system. Complete independent
review first. Approve staging/install, live read-only access, supervised commands
and automatic control separately. This work performed none of those operations.

Your system: Home Assistant OS in a Proxmox VM; existing Thermann Hot Water bridge
and its private persistent authentication state; Mosquitto/MQTT; Thermann Smart
Electric 315 L/3 kW; GoodWe GW5000-DNS-30/HK1000; 6.6 kW solar and EMHASS. Initially
there is **no dedicated hot-water CT**. Proposed roles are 45/62/70°C, with Never
peak policy and optional boost disabled until the future Shelly is commissioned.
These are proposed household settings, not temperature/hygiene certification.

## What you will need

- A second device/browser to read this guide while HA restarts.
- Your exact reviewed commit and the local owner ZIP supplied with the final
  handoff. Keep its SHA256 and `REVIEWED_MANIFEST.json` together. A green CI result
  is not independent safety approval.
- Access to HA’s file shares/editor and the Proxmox VM Console. The source-cache
  staging section is an advanced developer procedure. Ask for help if unfamiliar;
  do not substitute uninstall/reinstall or a second bridge.
- A safe approved way to operate the heater manually during downtime, following
  the appliance instructions. Stopping the bridge/controller does not send OFF.

HA versions may call the menu **Apps** or **Add-ons**. In either case open the
existing **Thermann Hot Water** entry. Menu labels and the dashboard still need
visual verification on your actual frontend; automated YAML tests cannot do that.

## 1. Record, disable and back up

1. In Settings → Devices & services → Thermann Controller, turn **Automatic
   heater control** off, if the integration is already installed. Check that no
   command is awaiting confirmation. This switch sends no heater command.
2. Inspect the heater in the vendor app. Resolve any pending/unknown command
   under separate approval before changing software. Do not assume reboot cancels it.
3. Open Settings → Apps/Add-ons → Thermann Hot Water. Record its current version,
   the **full installed ID** from the page URL (for example
   `12345678_thermowatt_boiler`), its source repository and configured polling.
   Your ID may have a different eight-character prefix. Do not use the example ID.
   If it starts `local_` or comes from another repository, this helper refuses;
   preserve that installation and obtain a reviewed source-path plan instead.
4. Record controller version, source mappings, entity names, tariff/rates/clock,
   command topic and qualification choices privately. Do not post screenshots
   containing account addresses, MQTT passwords, device serials or tokens.
5. Turn off this bridge’s **Start on boot**, **Watchdog** and **Auto update** and
   stop it. Verify Stopped. Do not uninstall it. Stop any other automation that
   could command this heater. No second bridge may use the account.
6. Settings → System → Backups: make a manual full backup including HA and this
   bridge. Download it to Windows and retain its encryption/recovery key privately.
   Confirm completion, included components, size and successful download. A file
   merely existing is not a proven restore. If practical, verify it on an isolated
   restore with networking disabled, never a second online account client.
7. For a second recovery layer, take a Proxmox backup of the HAOS VM while it is
   cleanly stopped, then restart the same VM. This does not replace the HA backup.
   [HA backup/emergency-kit guide](https://www.home-assistant.io/common-tasks/general/backups/),
   [Proxmox backup modes](https://github.com/proxmox/pve-docs/blob/master/vzdump.adoc).
   The bridge must remain stopped with watchdog/start-on-boot off afterwards.

The bridge’s private `/data` contains credentials/options, tokens, authentication
guards/generation, request accounting and pending-command state. Back up the
whole installed add-on, not just its visible YAML. Keep HA’s config entries,
entity registry and controller storage too. Never delete guard/token files,
reset request counts or increment authentication generation as an upgrade step.

## 2. Obtain and check the reviewed files

The normal repository URL still follows its normal branch. It **cannot install
this unmerged candidate**. Adding `#codex/polling-owner-readiness` also changes
HA’s repository ID and would create a different full add-on identity.
[HA’s repository identity rules](https://contributors.home-assistant.io/apps/guides/repository/).

Use the exact-commit owner ZIP from the handoff. On Windows, open PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 'C:\path\to\thermann-owner-reviewed.zip'
```

Replace that path with the downloaded file. Compare the hash with the handoff,
then extract it. The manifest records the full 40-character commit, bridge and
controller versions and every included file’s hash. Keep this original ZIP
unchanged. It contains committed source only, no HA backups or private runtime
state. A hash detects changes; the trusted review/handoff establishes provenance.

An experienced helper can reproduce it from this repository using:

```text
python tools/build_owner_bundle.py --commit FULL_REVIEWED_SHA --out owner-staging/thermann-owner-reviewed.zip
```

It does not install anything. Do not replace the full reviewed SHA with a moving
branch name. Copy the extracted folder to HA’s share as `thermann-reviewed`, so
`/share/thermann-reviewed/tools/owner_checkout.py` exists. With the standard Samba
share this is usually `\\homeassistant\share\thermann-reviewed` on Windows;
use your actual Samba share/hostname. Do not upload a private backup to GitHub.

## 3. Stage the existing bridge in place

**This is advanced, version-dependent developer staging, not the normal store
installer.** It preserves the existing repository ID and add-on instance. CI exercises real Supervisor 2026.10.5/2026.11.0 source-loading/schema code.
Confirm final-head success before using it; it has not run on your live VM. Check Settings → System → Repairs → System information for
your Supervisor version. For another version, obtain a reviewed compatibility
check before proceeding. Do not edit Supervisor’s installed-app JSON or `/data`.

From Proxmox, select the **existing HAOS VM → Console**. At the HA prompt enter
`login` to reach the HAOS host shell, as described in the
[official host-console guide](https://contributors.home-assistant.io/os/operating-system/debugging/). This is not a Home Assistant service call.
Before executing the helper, verify its transferred hash against the trusted
ZIP manifest entry `tools/owner_checkout.py`:

```sh
docker exec hassio_supervisor sha256sum /data/share/thermann-reviewed/tools/owner_checkout.py
```

Compare the hash before running the Python inspection command below. If the file
is missing, hash differs, or you are unsure, stop.

Set two shell variables, copying your actual installed ID and the manifest SHA:

```sh
thermann_addon='YOUR_EXISTING_FULL_ID'
thermann_review='FULL_40_CHARACTER_REVIEWED_SHA'
docker exec hassio_supervisor python3 /data/share/thermann-reviewed/tools/owner_checkout.py --slug "$thermann_addon" --commit "$thermann_review"
```

The default Python command only inspects the existing source cache: expected public
origin, matching ID/path, clean working files, original branch/commit and whether
the reviewed object is already cached. It prints no private options/auth state.
If it refuses, stop and ask for help. It will not discard local changes.

Only after approving the displayed plan, with the bridge still Stopped:

```sh
docker exec hassio_supervisor python3 /data/share/thermann-reviewed/tools/owner_checkout.py --slug "$thermann_addon" --commit "$thermann_review" --stage
```

This fetches only the requested public GitHub commit if needed and creates a
local named `owner-reviewed-<commit>` branch in the **existing** repository cache.
It saves `owner-checkout-record.json` beside the extracted bundle before switching.
It does not install/start a container, change private options/data or contact
Thermann. Keep that recovery record. Repeating the same completed stage is safe;
a different stage or dirty cache is refused for review.

Now restart Supervisor so its catalog reads the pinned source:

```sh
ha supervisor restart
```

Wait for Supervisor to return. Re-run the inspection command and confirm the exact
reviewed commit and pinned branch. Open the **same existing** Thermann Hot Water
entry: its full ID must be unchanged and the offered version must match the
manifest. If either differs, do not press Install/Update/Rebuild.

The local pin intentionally has no matching remote branch. Later store refreshes
can report that specific Git branch reference is absent. Do not press a store
Reset, change repository URL, or rebuild from another checkout to hide it. That
would remove the reviewed pin. Future source changes need another reviewed plan.
The method follows Supervisor’s [cache load](https://github.com/home-assistant/supervisor/blob/2026.11.0/supervisor/store/git.py)
and [catalog reader](https://github.com/home-assistant/supervisor/blob/2026.11.0/supervisor/store/data.py);
it does not change the repository’s GitHub branches or publish a release.

## 4. Upgrade without resetting private state

On that **same** stopped bridge entry, choose **Update**, not Install or uninstall.
If no correct update is offered, stop; do not guess with Rebuild. Supervisor builds
from the pinned reviewed source. Since the bridge was stopped, keep it stopped
afterwards. Confirm installed version and unchanged full ID.

Compare the private Configuration with your record: account/MQTT settings,
cloud/command flags, auth generation, retry/poll settings and topic must retain
the intended values. Do not paste tokens/guards into the UI or restore a template
options file. The complete existing private data remains with the same instance.
New adaptive options start false. An upgrade is not permission to authenticate.

For later read-only testing, deliberately make **commands_enabled false** while
the controller is also disabled. This is an explicit owner safety choice, not a
silent migration. Preserve credentials, tokens, locks and auth generation. Do not
start yet unless live read-only access is separately approved.

## 5. Install/update the controller without deleting its entry

Copy the ZIP’s `custom_components/thermann_shadow` directory to
`/config/custom_components/thermann_shadow`, replacing code files from the same
integration. Check that `manifest.json` is directly inside that directory, not
in a doubled subfolder. Do not delete HA’s `.storage`, configuration entry or
entity registry. Existing options and identities migrate in place.

Developer tools → YAML → Check configuration, then restart HA once. The bridge
should still be stopped. If upgrading, retain the existing Thermann Controller
entry. If new, Settings → Devices & services → Add integration → Thermann
Controller. Leave **Automatic heater control** off and all adaptive/learning
flags off. Existing master state is preserved, which is why it was disabled first.

## 6. Map your real entities

In Thermann Controller → Configure → Sources, select actual entities from
Developer tools → States. IDs below are recorded household examples, not automatic
discovery or proof the registry still uses them. If renamed, choose the actual ID.

| Controller input | Household example / verification |
|---|---|
| Thermann water heater | `water_heater.home_boiler_home`; check current/target attributes |
| Vendor mode | `sensor.home_boiler_home_vendor_mode` |
| Last successful cloud poll | `sensor.home_last_successful_poll`; must advance on genuine successful reads |
| Cloud health | `sensor.home_cloud_health`; inspect guard/commands/request diagnostics |
| Persistent request attempts | `sensor.home_cloud_request_attempts_local_lifetime`; do not reset it |
| Signed HK1000 grid power | `sensor.goodwe_inverter_meter_active_power`; verify your export-positive sign |
| PV generation | `sensor.goodwe_inverter_pv_power` |
| Household consumption | `sensor.goodwe_inverter_house_consumption` |
| Inverter AC power | Historic mapping `sensor.goodwe_inverter_total_power`; confirm the actual AC-output identity and W/kW units |
| PV forecast | `sensor.p_pv_forecast`, with genuine `forecast_generated_at` |
| Household forecast | `sensor.p_load_forecast`, same timestamp/units requirements |
| Heater power / heater energy | **Empty until Shelly commissioning**; commissioning identity also empty |

Verify W/kW and sign with a known load during separately approved observation;
negative/export conventions differ by integration. The reported AC output must
not be confused with DC panel power. Follow [forecast setup](../../shadow_controller/FORECAST_SETUP.md)
for genuine calculation timestamps; a heartbeat is not a new forecast. CT-free
required heating can use verified raw grid export plus forecasts. It never
subtracts inferred element watts to create optional-solar authority.

## 7. Check household settings

Configure → Preferences and System show plain setting names. Critical settings
are locked while automatic control is active; disable first.

- Household time zone: **Australia/Hobart**.
- Tariff clock: **standard**, fixed AEST; tariff profile Aurora 93 or equivalent
  custom full-week rows. Verify the actual **retail contract** and current rates,
  not a network schedule or prices copied from this repository.
- Weekday peaks 07:00–10:00 and 16:00–21:00 AEST; weekends off-peak for this example.
  During daylight saving these display 08:00–11:00 and 17:00–22:00 Hobart time.
- Nominal tank 315 L, element 3 kW. Baseline 45 / normal 62 / future boost 70 are the
  proposed household roles. Verify manufacturer/storage hygiene and local plumbing
  requirements before selecting 45; it is not universally appropriate.
- Completion margin 30 min: normal storage aims before 15:30 AEST, with software
  OFF requested before 16:00. A late draw or outage can still defeat readiness.
- Heating during peak periods: **Never schedule heating during peak**.
- Enable optional solar boost: **off** initially. No CT means unavailable even
  if enabled. The separate 12-hour Override is a real 70°C request and may heat at peak.
- Use published forecasts: enable only after checking actual generation/units.
  Missing EMHASS does not prevent basic required tariff control.
- All adaptive and learned-planning/qualification flags: **off initially**.

## 8. Install the seven-view read-only dashboard

In a **working copy** of the extracted files, edit `energy_monitoring/entity_map.yaml`
for your actual IDs. Keep all three CT circuit mappings blank initially. Remove
or blank optional appliances you do not have, including unverified examples.
Keep `tariff.source: controller`; set prices in the controller, not two competing
rate schedules. Match the mapped controller sensor IDs to the actual registry.

The ZIP includes the generator. If you need it on Windows, install Python3.12 or
newer from python.org, then in PowerShell opened in that working folder:

```powershell
py -3 -m pip install --user PyYAML==6.0.3
py -3 energy_monitoring/build.py
py -3 energy_monitoring/build.py --check
```

These local commands only generate YAML; they never connect to HA or the heater.
Keep the original ZIP/hash unchanged. Generated files with your mappings are
local configuration, not a change to the reviewed controller source.

Copy `generated/packages/thermann_energy.yaml` to `/config/packages/thermann_energy.yaml`.
If needed, merge this under the existing `homeassistant:` section of
`configuration.yaml` (do not add a duplicate top-level section):

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Check configuration before restarting HA. Settings → Dashboards → Add dashboard →
New dashboard from scratch, open Edit → three-dot menu → Raw configuration editor,
and paste `generated/dashboards/energy.yaml`. Keep all seven views. Configure HA’s
built-in Energy dashboard separately with actual import/export/solar energy
meters and the generated current-price sensors. Without a hot-water CT there is
no measured heater energy/cycle total to add. Set the supply-charge helper from
your bill if using cost totals. Estimates spanning meter gaps/rate boundaries
are not exact utility-bill reconciliation.

## 9. Inspect read-only operation, after separate approval

Only now, with live read-only access approved, start the **same bridge** with
commands disabled and controller disabled. No authentication generation bump is
part of installation. If already locked, stop and diagnose through the existing
deliberate recovery procedure; do not restart or change generation repeatedly.

Compare mode/target/probe to the vendor app; inspect successful-poll timestamps,
health and request categories. Confirm the planned62°C weekday storage and peak
OFF are only wishes while disabled. CT-free physical element state and completion
clock must show unknown. The continuous-heating estimate means **if the element runs at nominal
power**, not a measured ON state, deadline promise or shower-volume guarantee.
Verify the seven views and all actual setting labels on your display.

## 10. Supervised four-state qualification, separate command approval

With explicit owner approval and supervision, qualify OFF/45/62/70 transitions,
exact-prior refusal after an app change, delayed confirmation, native hysteresis
and protection, peak OFF, return to baseline, restart and fault recovery. Follow
the independent reviewer’s acceptance plan. Observe cloud readback; without a CT
this cannot prove electrical consumption. Stop on a refusal or unknown outcome.
Never repeat a POST blindly or use the legacy command policy to bypass guards.

Only record **Four-state commands qualified (1.3.14)** after that evidence; its
historical label identifies the protocol, not the installed bridge version. The
topic and advertised transitions must match the same heater. Leave new polling
and learning gates off. A qualified flag does not enable automatic control.

## 11. CT-free automatic trial and real request measurements

After separate approval, enable automatic control under supervision with fixed
30-minute polling first. Observe overnight baseline, normal weekday storage,
cloudy/sunny forecasts, both peak transitions, weekend, owner hold and a safe
restart. Actual hot-water comfort matters more than an estimated probe target.
If control is disabled again, it sends no OFF; inspect the vendor-app setting.

Record request counter **differences** and categories over equal 24-hour/week
periods; do not reset them. Include refresh, status, pre-command GET, POST,
confirmation and failures. Compare weather, demand, targets, temperature deficits,
cost, maximum age and app-change detection, not just raw HTTP totals.

Only after reviewing that baseline and separately approving dynamic polling:

1. Disable automatic control to edit critical settings.
2. Qualify/enable the bridge’s two adaptive options and **Longer quiet checks
   independently qualified** deliberately. Confirm the health diagnostic advertises
   plan versions 1 and 2; without that separate new gate, requested event-aware
   operation sends no plans and uses fixed fallback.
3. Enable **Send adaptive cloud scheduling plans** and **Allow longer checks
   during quiet periods**, initially choosing **60 minutes** for app-change checks
   only if that detection delay is acceptable. 30 is the tighter choice; 90 is a
   comparative option, not the initial recommendation.
4. Re-enable control only under the approved trial. Watch actual next poll/reason,
   lease fallback and temperature age. A quiet temperature can expire after 45 min;
   this is intentionally unknown passive data, not permission for a stale command.
5. Compare actual outcomes. Disable the event-aware/adaptive flags to return to
   the original fixed30 policy if savings or reliability do not justify it.

For a separately approved **read-only inactivity check**, keep commands and
automatic control off, temporarily use fixed 60-minute bridge polling, and observe
refresh/health over equal periods. Restore 30 before an automatic-control trial.
This tests session inactivity without enabling heater commands. Do not change
authentication generations or retry locks for this experiment.

Synthetic savings are not a guarantee of your vendor session behaviour. The
20-minute refresh heuristic remains request-driven and unchanged. Authentication
failure after inactivity locks conservatively rather than extending a session
or retrying indefinitely. Brief app changes between observations can be missed.

## 12. Add Shelly later, without rebuilding

Use qualified electrical installation. Disable automatic control before changing
mappings. Identify the exclusive hot-water channel’s raw signed W/kW and optional
cumulative Wh/kWh entities. Map those same raw sources independently in the
controller and dashboard; never map `sensor.em_hot_water_power` as control authority.
Verify sign, units, actual heating/low draw, genuine unchanged-zero reports within
120sec and outage/recovery before recording its commissioning identity.

A previously commissioned CT failing is a fault, never silently zero or CT-free.
Oven/AC channels remain optional and independent. Regenerate only dashboard YAML
when mappings change. Requalify any affected measurement/learning authority; do
not delete the integration or old history. Optional solar and learned planning
remain separate approval/validation decisions. Learning needs real clean sessions
and whole-day held-out error checks; a few successful nights are not qualification.

## 13. Stop, back out and verify success

| Check | Success / stop condition |
|---|---|
| Identity | Same full bridge ID and controller entry/entity IDs; stop if duplicated |
| Private state | Intended credentials/options/generation/locks retained; no manual guard edits |
| Files | Reviewed SHA, versions and pinned source match manifest immediately before update |
| Disabled inspection | No controller POSTs, correct cloud status, read-only dashboard |
| Tariff | Verified contract, fixed AEST, correct local DST display and boundary wishes |
| CT-free | Normal heat supported; optional boost unavailable; physical element unknown |
| Commands | Every approved command gets actual cloud confirmation or a clear fault |
| Polling | Actual categories/age/detection recorded; lease loss selects fixed fallback |
| Usability | Seven views render clearly on desktop/mobile; no broken IDs or misleading controls |

If something fails, disable control, stop bridge commands and inspect the actual
appliance state. Keep the same add-on installed. Preserve logs/records privately;
never publish tokens, raw sensitive errors or backup files. Use approved manual
operation for hot water while recovering.

If the new bridge was **never started** and no live command/authentication occurred
since the sealed backup, a reviewed restore of that backup/VM can return to the
old installation. If live operation occurred, do not blindly restore older token,
guard or request-accounting state. Obtain review, retain newer safety state and
reconcile pending commands. Bridge 1.3.13 cannot safely manage an unreviewed
Manual 62 prior state: return to an understood old supported state only under
separate approval before rollback. The source-only staging record records the
old Git branch/commit; it is not a private-data backup or automatic rollback tool.
See [upgrade/recovery](../final-integration/UPGRADE.md).

Do not uninstall/re-add, delete `.storage`, run a second active bridge, reset
repository/source pins blindly, or clear authentication locks to get past a
problem. Independent review and supervised physical evidence are still required.
