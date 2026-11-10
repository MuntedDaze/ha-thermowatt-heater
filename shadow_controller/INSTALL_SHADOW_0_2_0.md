# Shadow Planner 0.2.0 — later owner installation and verification

**Read-only trial, not heater-control commissioning.** No step below has been
executed on the owner's HA. Use a reviewed PR #9 revision; main does not yet
contain this unmerged component. Record the downloaded commit for support.

1. Back up HA configuration and the existing add-on data. Record current bridge
   options privately. Keep v1.3.8, existing cloud setting/credentials/generation,
   30-minute polling, 60-minute minimum error cooldown, commands **false** and
   on-demand refresh **false**. Do not reset locks, delete private data or change
   Schedule, 70°C native target, power state or 10°C T-Comfort for this trial.
2. Using the owner's normal file-management method, copy only the reviewed
   `custom_components/thermann_shadow` folder to
   `/config/custom_components/thermann_shadow`. Check that `manifest.json` sits
   directly there and says `0.2.0`; avoid an extra nested repository directory.
   No add-on reinstall, HACS hook, extra runtime package or pairing is needed.
3. Restart **HA Core once**, not the heater or add-on. Add **Thermann Shadow
   Planner** under Settings → Devices & services. Select the supplied existing
   Thermann/GoodWe entities; setup needs no cloud account or credentials.
4. In Configure, verify export-positive meter direction, fixed-AEST Tariff 93
   and prices, morning threshold 40°C, storage planning target 70°C, margin 30 min,
   export headroom 0.3 kW and hold 10 min. Existing saved overrides stay unchanged;
   review any old placeholder tariff deliberately. Compare the existing device
   clock to Hobart and record the check date only if checked; no automatic device
   clock or programme adjustment occurs.
5. Wait for a new **normal** bridge poll after planner setup/reload (up to about
   30 minutes plus processing). Initial blocked/stale status is expected; do not
   restart repeatedly, enable demand or change authentication to accelerate it.
6. Add `shadow_controller/dashboard.yaml` as a separate manual YAML dashboard.
   Verify its entity IDs against the registry if old naming produced suffixes.
   The Hot water view is the day-to-day view; Diagnostics contains assumptions.
7. Verify current/target readings and vendor Schedule agree with the existing
   read-only display. The water-heater entity may still say Unknown for Schedule.
   The Heating sensor must remain unverified/Unknown. Positive signed grid should
   appear as export, not import; compare the existing GoodWe readings.
8. Check summer weekday peak 17:00 local versus winter 16:00; weekends have no
   peak. Confirm `control_capable=false`, `shadow_mode=true` and
   `additional_cloud_requests=0` on the controller's attributes. Recommendations,
   windows and estimated costs are simulations, never heater operation or savings.
9. Observe at least one normal poll cycle. Request growth may include the existing
   status/refresh/replay pattern; it must not track solar updates or dashboard
   refreshes. Check cloud health, age, reasons and the device-clock reminder.
   Missing/stale data should block recommendations; do not break live networking
   to test this. Existing offline scenarios exercise failures and shortages.

If mappings/prices/status look wrong, pause or remove **only the shadow
integration** and correct its settings. Do not enable commands/demand to fix it.
Removal cancels its local timer and sensors; there is no heater handback because
it never acquired control. Preserve fixed error codes and aggregate attempt counts
for review, without credentials, tokens or response bodies.

Actual UI rendering, owner installation and physical heater behaviour still need
owner observation. Any app Off/On, API write, outage experiment or execution adapter
requires separate explicit approval; see NATIVE_ON_OFF_REVIEW.md.
