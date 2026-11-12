# Commissioning

Automatic control is switched on in stages, each with your approval. At any stage, recovery is the same:
- **Thermann app:** Manual at 70 °C for hot water now, OFF to park, or Schedule for your normal programme.
- **Home Assistant:** turning off *Automatic heater control* never changes the heater.
- **Authentication locks:** never reset them to force anything.

| Stage | What | Status |
| --- | --- | --- |
| A | Controller installed, control off | Done; 0.6.2 installed. 0.7.0 is in review |
| B | Bridge command tests with the owner present (T3, T3b, T3c) | **Done 12–13 Nov 2026**; results below |
| C | Supervised trial with automatic control on | Needs approval |
| D | Normal operation | After reviewing C |

## Stage B results (bridge commands, owner present)

| Test | Bridge | Result |
| --- | --- | --- |
| T3 | 1.3.9 | `off` and `Manual:70` work physically. OFF reports `Cmd` 8 (not 16) and keeps the 70 °C target. Commands only worked within 60 s of a poll. Fixed in 1.3.10 |
| T3b | 1.3.10 | The one read before the command worked, and the heater went OFF, but the bridge reported "not observed": its only read came 2 s after the command, before the cloud updated. Fixed in 1.3.11 |
| T3c | 1.3.11 | `off` and `Manual:70` each confirmed at the 60 s follow-up read; a repeat while awaiting was refused with no request; a repeat when already OFF sent nothing. 4 cloud requests per command |

Measured: the cloud reports a change between about 2 s and 63 s after the command. The detailed procedures are in [docs/history/bridge/UPGRADING_1_3_11.md](../docs/history/bridge/UPGRADING_1_3_11.md).

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
- **Owner controls:** test once each: Hold then Resume, an app change (it should pause control), guest start and cancel, and a short holiday while you're home.

**Pass:**
- comfort goals met, or correctly reported;
- every command confirmed;
- no peak-grid heating beyond comfort needs;
- no duplicate commands.

**Rollback:** switch control off, set the mode you want in the app, and set the bridge's `commands_enabled: false`.

## Stage D: normal operation

Leave control on with notifications, keep the default settings, and review weekly for the first month.

The full 0.6 runbook is kept in [docs/history/controller/COMMISSIONING_0_6.md](../docs/history/controller/COMMISSIONING_0_6.md).
