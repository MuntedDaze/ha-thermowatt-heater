# Commissioning

> **Superseded for 0.9.0** by [COMMISSIONING_SIMPLIFIED.md](COMMISSIONING_SIMPLIFIED.md) (app 1.3.13, three-state commands). This page records the 0.6–0.7 stages and the Stage C history.

Automatic control is switched on in stages, each with your approval. At any stage, recovery is the same:
- **Thermann app:** Manual at 70 °C for hot water now, OFF to park, or Schedule for your normal programme.
- **Home Assistant:** turning off *Automatic heater control* never changes the heater.
- **Authentication locks:** never reset them to force anything.

| Stage | What | Status |
| --- | --- | --- |
| A | Controller installed, control off | Done; **0.7.0 installed 12 Nov 2026**, control off. The corrected build `bbbc5f9` replaced `9dcf7fa` the same afternoon |
| B | Bridge command tests with the owner present (T3, T3b, T3c) | **Done 12 Nov 2026**; results below |
| C | Supervised trial with automatic control on | **Not begun.** Read-only preflight done and corrected build installed 12 Nov 2026; needs three settings and your approval |
| D | Normal operation | After reviewing C |

## Stage B results (bridge commands, owner present)

| Test | Bridge | Result |
| --- | --- | --- |
| T3 | 1.3.9 | `off` and `Manual:70` work physically. OFF reports `Cmd` 8 (not 16) and keeps the 70 °C target. Commands only worked within 60 s of a poll. Fixed in 1.3.10 |
| T3b | 1.3.10 | The one read before the command worked, and the heater went OFF, but the bridge reported "not observed": its only read came 2 s after the command, before the cloud updated. Fixed in 1.3.11 |
| T3c | 1.3.11 | `off` and `Manual:70` each confirmed at the 60 s follow-up read; a repeat while awaiting was refused with no request; a repeat when already OFF sent nothing. 4 cloud requests per command |

Measured: the cloud reports a change between about 2 s and 63 s after the command. The detailed procedures are in [docs/history/bridge/UPGRADING_1_3_11.md](../docs/history/bridge/UPGRADING_1_3_11.md).

## Stage C preflight (12 Nov 2026, read-only)

Nothing was changed and no command was sent. Automatic control stayed off.

**Passed:**
- **Bridge 1.3.11** (Settings → Apps → Thermann Hot Water, shown as Thermowatt Smart Boiler before app 1.3.12): authorised, healthy, no failures or cooldown, 30-minute polling, on-demand refresh off. `commands_enabled` is still **on** from T3c, with `command_policy: automation`. No confirmation pending; the last command (`Manual:70`, T3c) was confirmed.
- **Heater:** Manual 70 °C, which the controller accepts as its own permitted state.
- **Tariff:** Aurora 93 rates and peaks on the fixed AEST clock, so peaks show at 08–11 and 17–22 during daylight saving; weekends off-peak.
- **Meter and solar:** GoodWe/HK1000 readings under a minute old, with the meter sign consistent with PV minus house load.
- **EMHASS:** forecasts a few minutes old, and the base load is measured only (the EMHASS load forecast includes past heater runs).
- **Morning goals:** 45 °C by 06:00 preferred, 42 °C by 07:00 minimum.
- **Limits:** defaults intact (6 commands a day, 30/30-minute dwell, 220 cloud requests a day).
- **Conflicts:** no other automation, script or MQTT publisher targets the heater.

**Found and fixed in the corrected build (`bbbc5f9`):** with control on, a heater in Manual or OFF still tripped the old shadow-planner check for the native Schedule. The planner would then have reported *owner review required*, and the controller would only ever have held, parked for peaks or used the morning fail-safe. The corrected build was installed on 12 Nov 2026 (only `model.py` and `runtime.py` changed; settings, entities and the bridge unchanged). A read-only replay of the installed code on recorded live readings, with control simulated on, gave normal advice in both Manual 70 and OFF; with control off the old shadow review state is unchanged, as intended.

**To set before C** (Settings → Devices & services → Integrations → Thermann Controller, shown as Thermann Shadow Planner before 0.8.0 → Configure):
- *Controller command topic*: `P/<serial>/CMD/MODE`; keep the serial private;
- *Bridge commands qualified (T3)*: on;
- *Notification service*: recommended, for faults and unconfirmed commands. Without it, alerts are persistent notifications only.

**Notes:**
- The default Overview dashboard shows the heater card. Choosing **off** there publishes a real `off`, which the controller treats as an owner override. Don't use the card during the trial.
- The Home Assistant log (Settings → System → Logs) can't be read from outside Home Assistant, so it was not reviewed. Check it before starting C.

## Stage C: supervised trial

**Before starting:**
1. **Bridge add-on:** `commands_enabled: true`, `command_policy: automation`.
2. **Controller settings:**
   - *Controller command topic* = `P/<serial>/CMD/MODE`;
   - *Bridge commands qualified (T3)* = on;
   - optionally, a *Notification service*.
3. Put the heater in **OFF** or **Manual 70** in the app. Any other mode makes the controller wait for you.
4. Turn on **Automatic heater control**. The state goes to `observing`, then `parked` or `heating_permitted` after the next poll.

**Review daily for 3–7 days:**
- **Heating:** planned versus actual heating (power steps on the meter), whether Manual stays on after the thermostat is satisfied, and the decisions before each peak.
- **Comfort:** the morning readings at 06:00 and 07:00, and afternoon readiness.
- **Traffic:** commands and cloud requests per day; at most 6 commands.
- **Notices:** any protective heating while OFF, which is never interrupted.
- **Owner controls:** test once each: Hold then Resume, an app change (it should pause control), 12hr Override start and cancel, and a short holiday while you're home.

**Pass:**
- comfort goals met, or correctly reported;
- every command confirmed;
- no peak-grid heating beyond comfort needs;
- no duplicate commands.

**Rollback:** switch control off, set the mode you want in the app, and set the bridge's `commands_enabled: false`.

## Stage D: normal operation

Leave control on with notifications, keep the default settings, and review weekly for the first month.

The full 0.6 runbook is kept in [docs/history/controller/COMMISSIONING_0_6.md](../docs/history/controller/COMMISSIONING_0_6.md).
