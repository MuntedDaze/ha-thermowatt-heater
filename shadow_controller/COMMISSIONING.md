# Commissioning runbook — Thermann Hot Water Controller 0.6.0

**Method:** Manual 70 °C = heating permitted; Thermann software **OFF** =
parked. No native Schedule configuration is required, and none is changed.

Every stage needs the owner's **separate, explicit approval**. Each has
pass/fail criteria and a rollback. Nothing here has been performed by the
agent.

| Stage | What | Needs |
| --- | --- | --- |
| A | Install the controller with control **off** | Done for 0.5.0 (installed, disabled). Next: upgrade to 0.6.0 ([UPGRADE_0_5_0_TO_0_6_0.md](UPGRADE_0_5_0_TO_0_6_0.md)) |
| B | **T3**: prove the bridge's `off` and `Manual:70` reproduce the app results | Approval to merge PR #12 (bridge 1.3.9), update the add-on and enable commands temporarily |
| C | Supervised controller trial (limited cycles) | Approval to enable automatic control |
| D | Production enablement | Approval after reviewing C |

The 0.5.0 runbook's empty-Schedule stage is **withdrawn**.

**General recovery (any stage).** In the official app:
- choose **Manual at 70 °C** for hot water now, or
- turn the heater **OFF** to park it, or
- choose **Schedule** to return to your normal native programme.

In HA, turn *Automatic heater control* off; that never changes the heater mode.
Never reset Thermowatt authentication locks to force anything.

---

## Stage A — controller installed, control off

0.5.0 is installed and disabled. Upgrade to 0.6.0 with
[UPGRADE_0_5_0_TO_0_6_0.md](UPGRADE_0_5_0_TO_0_6_0.md): replace one folder,
restart once.

**Pass:**
- the control state is `disabled`, and *commissioning missing* lists 2 items
  (topic, T3);
- the bridge polls as before, `command: 0`;
- the app is unchanged.

**Rollback:** reinstall the 0.5.0 package and restart.

---

## Stage B — T3 bridge qualification (supervised)

**Preconditions:**
- PR #12 is approved and merged, and the add-on is updated to **1.3.9** (it
  never updates automatically);
- credentials, tokens and guard state are unchanged;
- the owner is present, the app works, and the reading is ≤60 °C so the
  thermostat will call for heat;
- the test runs off-peak.

1. **Command topic.** Settings → Devices & services → MQTT → *Boiler …* → MQTT
   INFO → water-heater discovery → `mode_command_topic` (`P/<serial>/CMD/MODE`).
   Keep it private.
2. **Enable commands for the test only.** Add-on Configuration:
   `commands_enabled: true`, `command_policy: automation` (the default); leave
   `on_demand_refresh_enabled: false`. Restart the add-on.
   - *Check:* diagnostics show `commands_enabled: true`,
     `command_policy: automation`, cloud health `ok`, auth `authorized`.
   - *Allowlist check:* publish `Eco` (or `TEMP` 65) once. **Expect**
     `refused_by_policy`, no request and no change.
3. **Start from Manual 70 °C** (set it in the app if needed). Record mode,
   target, reading, grid power and the request counter.
4. **Manual 70 → OFF.**
   - Within **20 s** after *Last successful poll* changes, run Developer Tools →
     Actions → `mqtt.publish` with topic = the command topic, payload `off`,
     retain **off**.
   - **Expect:**
     - `last_command.result` = `observed_in_status`;
     - mode **Off**;
     - if the element was heating, import down by about 3 kW within 2 minutes;
     - the app shows OFF.
   - **Record what OFF reports:** `T_SetPoint`, `setpoint_valid` and
     `WaterHeaterSts` (vendor-mode attributes and the STATUS payload).
   - If OFF reports a **usable target other than 70**, stop here. `Manual:70`
     would be refused by design. Decide with ChatGPT before continuing.
5. Wait at least one poll (30 min) in OFF.
   - *Check:* the bridge stays healthy, with no `status_temperature_out_of_range`.
6. **OFF → Manual 70.**
   - Same timing, payload `Manual:70`.
   - **Expect:**
     - `observed_in_status` (or `not_observed_in_immediate_status`, then Manual
       at the next poll);
     - mode **Manual** at **70 °C**;
     - about +3 kW within 2 minutes if the reading is ≤62 °C;
     - the app shows Manual 70.
7. **Optional repeat:** after another poll, OFF again, then Manual:70 again, to
   check retention twice.
8. **Optional negative check:** publish outside the 20-s slot.
   - **Expect:** `dropped_status_older_than_60s`, with no request.
9. Set `commands_enabled: false` and restart the add-on, unless Stage C follows
   with approval.

**Pass:**
- both transitions behave as in the app, and 70 °C is kept on resume;
- about ±3 kW steps when the thermostat calls for heat;
- confirmation from observed status;
- request cost per command recorded (expected 2–4);
- no auth lock and no retries;
- OFF readback recorded.

**Fail:** wrong mode or target, no resume from OFF, an auth lock, or polling
failures while OFF. Stop and restore in the app (Manual 70, or ON). Set
commands disabled and report.

**Then, in HA:** set *Controller command topic* and switch on *Bridge commands
qualified (T3)*.

---

## Stage C — supervised controller trial

**Preconditions:** A and B have passed. Bridge `commands_enabled: true`. The
heater is in **OFF** or **Manual 70** (set it in the app; any other mode puts the
controller in owner override).

1. Optional: set the *Notification service*.
2. Turn on **Automatic heater control**.
   - *Check:* the state becomes `observing`, then `parked` or
     `heating_permitted` after the next poll.
3. **Review daily for 3–7 days:**
   - planned versus observed start and stop (meter steps);
   - readiness at the deadlines;
   - solar share and cost;
   - commands and requests per day;
   - any "protective heating while OFF" notices (antibacterial and frost; never
     interrupted).
4. **Test the owner controls once each:**
   - **Hold**, then **Resume**;
   - an app change (OFF → Manual or Manual → OFF) leads to `owner_override` and
     is not reversed.

**Pass:**
- readiness goals met, or correctly alerted;
- every command confirmed, with no controller-caused `fault_locked`;
- no peak-period grid heating beyond comfort fallbacks;
- no duplicates, and the request budget respected.

**Rollback:** switch control off (the heater stays in its current mode). Set the
mode you want in the app (Schedule returns to your native programme). Set bridge
commands disabled.

---

## Stage D — production

After C is reviewed and approved:
- leave control on, with notifications;
- keep the conservative defaults;
- review weekly for the first month.

Rollback as in C.

## Owner actions outstanding

1. Approve the 0.6.0 upgrade (Stage A).
2. Approve PR #12, update the add-on to 1.3.9 and run T3 (Stage B).
3. Approve the trial (Stage C), then production (Stage D).
4. Merge decisions for PRs #9–#14.
