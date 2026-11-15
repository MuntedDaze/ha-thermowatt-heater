# Jacob’s normal CT-free installation, then Shelly later

**Future instructions only. Nothing is merged or installed.** First obtain
independent review and explicit approval for the integrated merge, installation,
live read-only observation, supervised commands and automatic operation separately.
A green test run is not any of those approvals.

Your existing system: Home Assistant OS in one Proxmox VM, Thermann bridge with
persistent authentication, MQTT/Mosquitto, Thermann Smart Electric 315 L / 3 kW,
GoodWe GW5000-DNS-30 / HK1000, 6.6 kW solar and EMHASS forecasts. No hot-water CT yet.
Preserve **45°C overnight/weekend baseline, 62°C normal weekday storage,
70°C optional economical solar boost, and the existing configured peak-OFF policy**.
Initially no CT means optional boost unavailable. Start with
**fixed 30-minute polling, adaptive off and learning off**.

The normal route is **review → approved integrated merge to main → Update the
existing add-on**. The PR36 Supervisor cache-pin procedure is unsupported and has
been removed. Do not run old `owner_checkout.py` files, edit Supervisor caches,
add a branch repository, install another bridge, uninstall or press Rebuild.
Old PR36 owner ZIPs are superseded for installation.

Home Assistant may label the menu Apps or Add-ons. Keep a second device open to
this guide. You need HA administration, file-share/editor access and a private
backup location. No Proxmox host shell or Supervisor cache commands are needed.
[Detailed merge/recovery evidence](../audit-remediation/NORMAL_UPDATE.md).

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
   Keep the exact registered repository URL, including any `.git` suffix.
   If it starts `local_`, uses a branch suffix or comes from another repository,
   stop: the normal same-identity route has not been established for it. Do not
   add a replacement repository or uninstall anything.
4. Record controller version, source mappings, entity names, tariff/rates/clock,
   command topic and qualification choices privately. Do not post screenshots
   containing account addresses, MQTT passwords, device serials or tokens.
5. Turn off this bridge’s **Start on boot**, **Watchdog** and **Auto update** and
   stop it. Verify Stopped. Do not uninstall it. Stop any other automation that
   could command this heater. No second bridge may use the account.
   Record the original cloud/command flags privately, then deliberately save
   **cloud_enabled: false** and **commands_enabled: false** while stopped. This
   owner-visible preparation prevents an unexpected post-update start making a
   live request. Keep credentials, tokens, locks and authentication generation
   unchanged. Record these disabled values as the expected upgrade configuration.
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

## 2. Wait for the exact approved integration

The developer handoff must record the reviewed final source SHA, the authorised
main merge SHA/tree, bridge **1.3.17** and controller **0.13.0**, and final-head CI.
At present the code is only a draft. The normal store cannot install this
unmerged candidate. Do not try to make it appear by adding a `#branch` URL.

After merge approval and a verified merge, obtain the exact controller/dashboard
files from that main commit, using its GitHub commit page → Browse files → Code
→ Download ZIP (or the exact-commit source bundle supplied with the handoff).
Check the supplied SHA256 and manifest. Keep the original ZIP unchanged; edit
only a working copy for your own entity mappings. The bridge source inside it is
for review, **not** for copying into Supervisor.

A helper can reproduce a local source bundle with
`python tools/build_owner_bundle.py --commit FULL_MAIN_SHA --out owner-staging/thermann-owner-reviewed.zip`.
This creates files on that computer only; it neither merges nor installs.

## 3. Find the normal update for the same bridge

After approved merge and installation approval:

1. Check the existing registered repository is the same MuntedDaze repository
   recorded in step 1, following its default **main** branch. Preserve the exact
   URL string and installed full ID. The public GitHub default is main; another
   repository/branch or `local_` installation needs its own reviewed plan.
2. Settings → Apps/Add-ons → App store → three-dot menu → **Check for updates**.
   Some versions also show Settings → System → Updates → Check for updates.
3. Open the **existing Thermann Hot Water** entry or its update card. Check the
   installed version, offered 1.3.17, release notes and unchanged full ID.
4. If it offers Install instead of Update, offers another version, or the ID
   differs, stop. Do not install a second copy or change the repository URL.
5. Confirm the bridge is still stopped, watchdog/start-on-boot/auto-update off,
   controller disabled, and the sealed backup is available.

No GitHub release, second repository or source-cache pin is required. The final
approved files must actually be on main before the store can offer them. If main
has changed after review, obtain review of that exact offered version first.

## 4. Update in place and preserve private state

Choose **Update** on the same stopped entry. Enable the offered backup of the
current version as an additional precaution. Do not choose Install, uninstall,
Rebuild or Reset. Keep the bridge stopped after the update; verify its state.

Check version 1.3.17 and the unchanged full ID. Compare the saved Configuration
privately: credentials, MQTT settings, topic, poll/retry settings, cloud/command
flags and authentication generation must retain their recorded values. The
existing instance's private data is retained, including tokens, authentication
locks, request accounting and pending-command records. New options default off;
upgrade never authorises a login, retry-generation bump or heater operation.

For the later approved read-only phase, deliberately select
**commands_enabled: false**, fixed **poll_interval_minutes: 30** with minutes as
the unit, and all bridge adaptive/qualification flags false. The controller stays
off. Do not lower retry limits or alter generation to force recovery. The
60-minute minimum cloud retry and exponential backoff remain unchanged. Review
any existing different retry choice explicitly rather than overwriting it.

Normal updates and real Supervisor source/catalog refresh are tested in isolated
CI. They do not prove your VM backup can restore the previous image; step 13
separates source recovery from private-state/VM restore.

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

In Thermann Controller → Configure → Solar & Meters → Solar and meter readings,
select actual optional entities from
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

## 7. Verify your household settings and hygiene

Configure now separates **Hot Water**, **Electricity Tariffs**, **Solar & Meters**
and **Advanced/System**. Bridge status mappings are under Advanced/System; the
optional solar/meter mappings are under Solar & Meters. Every field has inline
help. Prices display c/kWh and allowances display percentages; existing values
are preserved. [Settings walkthrough](../configuration/SETTINGS.md). Disable
automatic control before changing critical settings.

- Household zone: **Australia/Hobart**. Tariff clock: **standard**, fixed AEST.
  Verify Aurora 93 retail contract, rates and feed-in price against your bill.
  Example weekday peaks are 07:00–10:00 and 16:00–21:00 AEST, weekends off-peak.
  During daylight saving they display 08:00–11:00 and 17:00–22:00 in Hobart.
- Nominal tank **315 L**, element **3 kW**. These are planning estimates only.
- **Overnight/weekend baseline: Manual 45°C. Normal weekday storage: Manual 62°C.
  Optional economical solar target: Manual 70°C.** This is the owner's agreed
  variable-temperature strategy following plumber discussion. Preserve these
  saved roles and the existing peak policy. No new restrictive software gate is
  introduced, and no upgrade changes the actual heater target silently.
- Tasmania's [official heated-water guidance](https://buildingstandards.tas.gov.au/topics/technical-regulation/plumbing-standards/heated-water)
  specifies at least 60°C stored-water settings and separate delivery/scald
  protection. The owner has deliberately chosen variable-temperature operation,
  including periodic62/70°C heating. **Independent compliance has not been
  established by this project.** Manufacturer instructions, plumbing requirements,
  whole-tank temperature and actual native protections must be understood. A
  bottom-probe reading or selected target does not prove disinfection. The
  software neither replaces the appliance protections nor certifies an exception
  to the published requirements. See [appliance/strategy limitations](../audit-remediation/OPERATIONS.md#storage-temperature-requirements-and-the-owners-strategy).
- Completion margin **30 minutes**; required storage aims before the relevant
  peak with OFF requested two minutes ahead. Late draws/outages can defeat it.
- Heating during peak periods: **Never schedule heating during peak**.
  This policy can leave the heater OFF if control fails. Software cannot promise
  to restore heat with no working cloud path. Decide whether this reliability
  trade-off is acceptable before enabling it; do not defeat the peak policy.
- Published forecasts: enable only after genuine EMHASS timestamp/units checks.
  Required tariff heating also works without forecasts/solar.
- Adaptive/longer-check/learning flags: **off**. Fixed **30 minutes** initially.
- **Owner notification service:** enter your actual mobile service name without
  `notify.` (for example `mobile_app_jacobs_phone`). In Developer tools → Actions,
  select that actual `notify` service, send a test, and confirm receipt on the
  phone while HA is not open. Record the date/service. A configured name alone
  is not a successful test. This is a mandatory Never-policy commissioning item.

Set up and test the independent read-only watchdog described in
[monitoring/recovery](../audit-remediation/OPERATIONS.md). It can notify when the
controller stops evaluating while HA is alive. Total HA/internet/power failure
needs an external availability check or owner checks; HA cannot notify if down.

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

## 9. Seven-day read-only soak, separately approved

Only after live read-only approval, deliberately enable cloud reads and start
the **same bridge** with commands off
and the controller off, at fixed 30-minute polling. Keep its normal authentication safeguards.
First start may refresh existing tokens before the first read; rejection locks
conservatively. Stop and diagnose rather than changing generation/restarting
repeatedly. No setup step erases tokens or clears a lock.

For **at least seven days**, record request counter differences/categories,
authentication health, mode, target and probe agreement with the vendor app.
Verify tariff boundaries, baseline/normal wishes, all seven dashboard views and
actual setting labels on desktop/mobile. CT-free element ON/OFF and absolute
completion remain unknown. Continuous-heating time is conditional nominal physics.

Inspect **Controller last evaluated**, active alerts and phone notifications.
Temperature history can help assess actual native behaviour, but no target,
point reading or absence of faults proves whole-tank hygiene. Automated dashboard
checks are not an independent dashboard audit or a visual usability check.

## 10. Supervised qualification, separate command approval

Use the independent reviewer’s accepted plan. Verify OFF/45/62/70 exact-prior
protocol behaviour, one POST per intent, confirmation, app-change refusal,
pending-command restart/no repeat, faults, native protections and reported
`WaterHeaterSts`. Record each result. Preserve the agreed45/62/70 roles; these supervised tests do not independently
establish storage-temperature compliance. Finish in the owner-approved state
for that time and tariff period. Do not assume any raw status flag proves physical ON/OFF.

Stop on refusal/unknown outcome. Acknowledge only after understanding the actual
state; never use legacy command policy, repeated POST or authentication reset to
bypass a failure. Without CT, cloud confirmation cannot prove zero consumption.
Only record Four-state commands qualified after evidence. Its historical 1.3.14
label identifies the protocol, not the installed version. Keep polling and
learning gates off. Qualification does not enable automatic control.

## 11. CT-free automatic trial, fixed 30-minute polling, separate approval

Before enablement: agreed45/62/70 roles retained, verified tariff/GoodWe/forecast mapping,
read-only soak accepted, supervised commands accepted, tested phone service,
parked-OFF warning and independent watchdog accepted, manual recovery understood,
and strict-peak versus availability trade-off accepted. There is no added baseline restriction. The owner's plumber discussion is
recorded context, not an independent compliance certificate from this software.

Under the separately approved supervised trial, observe overnight, weekday
storage, sunny/cloudy days, both peaks, weekend, app changes, restart and return
to the baseline. Record at least two weeks of actual comfort, request categories,
temperatures, faults and boundaries before unattended acceptance. No CT means
no optional solar-only authority and no learned control.

Separately approve a controlled outage exercise while parked OFF. Cloud/control
recovery cannot be promised: after permitted heat has been wanted for 30 minutes,
the distinct **parked OFF, cannot restore heat** warning should reach your phone.
Backoff may last hours; locks need deliberate recovery, controller faults may
need Acknowledge. The warning does not bypass peak lockout or issue a fallback
command. Follow the [manual recovery runbook](../audit-remediation/OPERATIONS.md).

Measure request **differences** over equal days/weeks, including login/refresh,
status, pre-command GET, POST, confirmation and failures. Do not reset counters.
Include weather/demand, costs, target misses, status age and owner-change delays.

**Adaptive polling stays off** until the hard independent inactivity gate in
[the observation plan](../audit-remediation/OPERATIONS.md#read-only-inactivity-qualification)
passes: at least seven complete days fixed 60-minute polling read-only, zero refresh rejections,
no hidden keepalive/extra requests, accepted delay and reviewed evidence. Repeat
at fixed 90-minute polling before 90 is allowed. Read-only means commands and automatic control
off. Restore fixed 30-minute polling before returning to an automatic trial. Any failure blocks
qualification; do not alter auth generations or retry safeguards to pass.

Only then, with separate approval, enable both bridge adaptive flags, its
separate longer-quiet qualification, and controller plan/quiet permissions.
Start with an accepted 60-minute bound, observe actual plans/lease fallback and
compare equal-service outcomes. Disable adaptive flags to return to fixed 30-minute polling if
reliability or savings are not demonstrated. Brief app changes can be missed;
command-specific fresh prior and confirmation remain mandatory.

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

## 13. Stop, recover and verify success

| Check | Success / stop condition |
|---|---|
| Identity | Same repository URL, full bridge ID, controller entry/entity IDs; no second bridge |
| Versions | Exact approved main tree, offered/installed 1.3.17 and controller 0.13.0 |
| Private state | Recorded options, tokens/locks/generation, pending and usage preserved |
| Read-only | Seven-day accepted record; no controller/heater POST; correct status |
| Strategy/requirements | Agreed45/62/70 retained; appliance/plumbing limitations understood; no claimed independent compliance |
| Tariff | Verified retail rates/fixed AEST and correct DST display |
| CT-free | Normal required heat works; optional boost/learning unavailable; element unknown |
| Faults | Tested phone/watchdog; parked-OFF warning and manual recovery understood |
| Commands | Every approved intent confirmed or clearly faulted, never blindly repeated |
| Usability | Seven readable views on desktop/mobile, actual IDs and conditional labels |

If anything fails, disable control, stop bridge commands and inspect the actual
heater. Disabling control does not send OFF. Use the approved manufacturer/manual
operation plan while software recovers. If the cloud/app is down, use only the
manufacturer-supported local controls or qualified service; do not improvise
wiring, bypass protection or assume the bridge can restore heat.

Preferred recovery after live activity is a **reviewed forward recovery build**
on the same main repository, offered by normal Update, preserving newer private
state. It needs its own review/approval and a higher offered version. Do not use
an old cache checkout. Disable affected controller/adaptive features while waiting.

A sealed HA/Proxmox backup taken before any later authentication/command can be
restored only through an approved recovery plan. Verify the backup/image restore
in a disconnected isolated VM first; this development has not proven a real
Supervisor backup restores your old built image. Never boot both VMs online.
After live activity, old tokens/locks/accounting and pending-command data must
not be blindly rolled back. Preserve newer safety state and obtain review.
Record your **actual** old version, rather than assuming 1.3.11 or1.3.13. Older
bridges may not support Manual 62; reconcile to an independently approved older
supported state before any downgrade. Restoring files does not cancel sent commands.

For controller/dashboard-only rollback, stop control, restore compatible code
and configuration from the matching private backup, retain the same entry and
registry, and verify read-only again. Do not delete `.storage`, reset guards,
uninstall/re-add or run another bridge. [Detailed recovery limits](../audit-remediation/NORMAL_UPDATE.md).
