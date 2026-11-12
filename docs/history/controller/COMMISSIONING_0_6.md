# Commissioning runbook — Thermann Hot Water Controller 0.6.2

**Method:** Manual 70 °C = heating permitted; Thermann software **OFF** =
parked. No native Schedule configuration is required, and none is changed.

Every stage needs the owner's **separate, explicit approval**. Each has
pass/fail criteria and a rollback. Nothing here has been performed by the
agent.

| Stage | What | Needs |
| --- | --- | --- |
| A | Install the controller with control **off** | 0.6.1 installed 13 Nov 2026 (control off). Next: upgrade to 0.6.2 ([UPGRADE_0_6_1_TO_0_6_2.md](UPGRADE_0_6_1_TO_0_6_2.md)) |
| B | **T3**: prove the bridge's `off` and `Manual:70` reproduce the app results | **Done 12 Nov 2026** with bridge 1.3.9; found OFF = `Cmd` 8 and the 60 s freshness problem |
| B2 | **T3b**: repeat with bridge 1.3.10, from stale status | **Done 13 Nov 2026, stopped**: refresh worked, the app showed OFF, but the bridge reported `not_observed_in_immediate_status` |
| B3 | **T3c**: bridge 1.3.11 bounded confirmation | Approval to merge the 1.3.11 PR, update the add-on and enable commands temporarily |
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

0.6.0 is installed with control off. Upgrade to 0.6.1 with
[UPGRADE_0_6_0_TO_0_6_1.md](UPGRADE_0_6_0_TO_0_6_1.md): replace one folder,
restart once. (From 0.5.0, the same steps apply; see
[UPGRADE_0_5_0_TO_0_6_0.md](UPGRADE_0_5_0_TO_0_6_0.md) for the removed setting.)

**Pass:**
- the control state is `disabled`, and *commissioning missing* lists 2 items
  (topic, T3);
- the bridge polls as before, `command: 0`;
- the app is unchanged.

**Rollback:** reinstall the 0.6.0 package and restart.

---

## Stage B — T3 bridge qualification (done 12 Nov 2026, bridge 1.3.9)

Owner present, commands enabled temporarily, MQTT published by hand:

| Step | Result |
| --- | --- |
| Manual 70 °C | `Cmd` 9, `WaterHeaterSts` 33, target 70 |
| `off` | heater OFF in the app; `Cmd` **8**, `WaterHeaterSts` 32, target **70** kept |
| `Manual:70` | Manual 70 °C restored, heating resumed |

Findings, fixed in bridge 1.3.10 (PR #15):
- 1.3.9 knew only `Cmd` 16 as OFF, so OFF showed as *Unknown* and a successful
  `off` was reported unconfirmed;
- commands were dropped as `dropped_status_older_than_60s` unless sent within a
  minute of the 30-minute poll (in T3 only after restarting the add-on).

OFF reports 70, so the OFF target rule allows the resume. `WaterHeaterSts`
32/33 matched OFF/Manual here but is **not** treated as element activity.

---

## Stage B2 result (13 Nov 2026)

Controller 0.6.1 disabled, bridge 1.3.10. A stale-status `off` gave one
pre-command read (`status_refresh: refreshed`, `command_refresh: 1`); the app
then showed OFF; the bridge reported `not_observed_in_immediate_status`. No
cloud or authentication error. The owner stopped the test, restored Manual
70 °C in the app, disabled bridge commands and restarted the add-on.

Root cause and fix: [UPGRADING_1_3_11.md](../bridge/UPGRADING_1_3_11.md). The steps
below are kept as the procedure; repeat them as **T3c** with bridge 1.3.11
(Stage B3).

---

## Stage B3 — T3c with bridge 1.3.11 (supervised)

Follow *Supervised validation (T3c)* in
[UPGRADING_1_3_11.md](../bridge/UPGRADING_1_3_11.md). It adds to T3b: watch
`last_command` for up to 6 minutes per command, record `status_reads`,
`followups_done` and the readback delay, and check that a repeated command while
awaiting is refused with no request. **Pass** needs `observed_in_status` for
both `off` and `Manual:70`. Any `not_confirmed_within_limit` or
`unexpected_state_after_command` is a stop.

---

## Stage B2 procedure — T3b with bridge 1.3.10 (supervised)

**Preconditions:**
- PR #15 approved and merged; the add-on updated to **1.3.10** with
  [UPGRADING_1_3_10.md](../bridge/UPGRADING_1_3_10.md) (commands disabled first);
- controller 0.6.1 installed, *Automatic heater control* **off**;
- the owner is present with the app open and the power reading visible;
- off-peak.

Follow the *Supervised validation (T3b)* steps in
[UPGRADING_1_3_10.md](../bridge/UPGRADING_1_3_10.md):
1. with status over 2 minutes old, publish `off`: expect `observed_in_status`
   with `status_refresh: refreshed`, vendor mode **Off** (`Cmd` 8), HA water
   heater **off**, the app OFF;
2. repeat `off` within 60 s: `already_in_requested_state`, no write;
3. publish `Eco`: `refused_by_policy`, no request;
4. with status over 2 minutes old, publish `Manual:70`: `observed_in_status`,
   Manual 70 °C, about +3 kW if the tank is below the restart point.

**Pass:**
- each step as expected, 70 °C kept throughout;
- three requests per stale-status command (refresh, write, confirmation);
- no auth lock and no retry.

**Stop** at any unexpected code, a target other than 70, an app/HA mismatch, or
power not following the mode. Set `commands_enabled: false` and report.

**Then, in HA:** set *Controller command topic* (`P/<serial>/CMD/MODE`, from
the water-heater discovery's `mode_command_topic`; keep it private) and switch
on *Bridge commands qualified (T3)*.

---

## Stage C — supervised controller trial

**Preconditions:** A, B and B3 have passed. Bridge 1.3.11 with
`commands_enabled: true`. The
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

1. Approve the 0.6.2 upgrade (Stage A).
2. Approve the 1.3.11 PR, update the add-on to 1.3.11 and run T3c (Stage B3).
3. Approve the trial (Stage C), then production (Stage D).
4. Merge decisions for PRs #9–#16.
