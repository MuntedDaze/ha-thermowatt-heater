# Settings audit (0.7.0 → 0.7.1)

Audit of every user-editable setting of the controller (integration
`thermann_shadow`) and the relevant bridge app options, made on 12 Nov 2026
against controller 0.7.0 build `bbbc5f9` (installed, automatic control off).

**How settings reach the controller.** Number, switch, select, time and text
entities and the **Configure** form all write the same config-entry options.
Every save validates the *whole* resulting configuration first; an invalid
combination saves nothing. A saved change is applied at once, without a reload
or restart: the planner is rebuilt with the new values and re-evaluated, and the
controller picks up its own settings on its next step (within a minute).

**Who uses what.** Since 0.7.0 the production controller decides from the
*advisor* (`advisor.py`, `strategy.py`, `goals.py`, `forecast.py`) and the
economic permission (`permission.py`). The old shadow model (`model.py`) still
runs, but for the controller it only supplies the data gates (fresh status,
verified meter and tariff). `cycles.py`, `economics.py` and `decision.py` are
0.3-era simulation code no longer called by the integration. A setting read only
there does nothing in production.

Legend — **Use:** P = production controller, S = legacy shadow display only,
X = unused, B = bridge. **When:** "next eval" = within one minute.

## Safety-relevant findings

| # | Finding | Effect today | Class |
| --- | --- | --- | --- |
| F1 | Commissioning and safety settings (command topic, T3 qualification, budgets, dwell, confirmation timeout, latency, meter sign/verification, tariff contract, sensor mappings) can be edited **while automatic control is on** | A wrong topic sends commands nowhere (locks after the confirmation timeout); un-verifying the meter or tariff silently turns the planner off (hold only); a mapping change resets evidence mid-trial | **Safety, fix before Stage C** |
| F2 | The command topic is only checked for shape (`P/…/CMD/MODE`), not that it belongs to the mapped heater | A typo in the serial passes commissioning | **Safety, fix before Stage C** |
| F3 | The controller does not check the bridge's `command_policy`; with `legacy` the bridge drops its own Manual 70 / OFF state checks | Defence in depth lost if the app option is changed | **Safety, fix before Stage C** |
| F4 | An invalid notification service name (for example with `notify.` in front) is accepted and silently ignored | Fault alerts would reach only the HA notification list | Operational |
| F5 | Changing tariff or economic settings resets the planner's evidence but not the economic-permission samples and grant/withdraw timers | Up to 10 minutes of decisions priced with the old settings | Operational |
| F6 | *Minimum rest* up to 240 min also delays a **comfort** start, but the planner only reserves the execution latency (30 min) | A long rest could make the morning minimum late | Operational |
| F7 | *Maximum cloud poll age* allowed at 30 min with 30-minute polling | The planner gate would flap every cycle and keep resetting economic evidence | Operational |
| F8 | *Maximum forecast generation age* allowed at 15 min with EMHASS publishing every 30 min | Forecasts would be ignored half of the time | Operational |
| F9 | *Pause shadow planning* also makes an **active** controller hold (and still allows peak parks and the morning fail-safe) | Misleading: it is not a pause of automatic control (use Hold or the master switch) | Operational |
| F10 | Command and request budgets accept fractions (5.9 commands behaves as 5) | Display and behaviour differ | Operational |
| F11 | Restore recommended also resets dwell, budgets, confirmation timeout and latency | Safety timing changed by a "preferences" button | Operational |
| F12 | Five settings are described as working but are read only by legacy code (`min_solar_kw`, `export_headroom_kw`, `solar_window_minutes`, `switching_benefit_aud`, `solar_loss_minutes`); two described as "simulation only" do drive production planning (`minimum_cycle_minutes`, `minimum_gap_minutes`), as does `solar_hold_minutes` | Settings that appear to work but do nothing, and the reverse | Interface |
| F13 | Native-Schedule references, T-Comfort, expected native target and the legacy morning/shower times are still editable | Irrelevant once the controller runs (no native Schedule) | Interface |
| F14 | Required mappings `import_energy` / `export_energy` are not used | Confusing setup form | Interface |

No defect was found that makes Stage C unsafe **with the current live
settings** (all controller settings at their defaults, heater commands only
`Manual:70` / `off`). F1–F3 matter if anything is edited during the trial.

## Every setting

### Comfort (P unless noted)

| Setting | Default | What it controls | Use | Works / when | Risk | Action |
| --- | --- | --- | --- | --- | --- | --- |
| Morning preferred reserve (`morning_preferred_c`) | 45 °C | Preferred reading by the preferred time | P | Yes, next eval | Low | Keep — Everyday |
| Morning ready (preferred) (`morning_preferred_time`) | 06:00 | Preferred morning deadline (Hobart time) | P | Yes | Low | Keep — Everyday |
| Morning minimum (hard) (`morning_threshold_c`) | 42 °C | Minimum by the hard deadline; fail-safe and at-risk permits | P | Yes | Medium (comfort) | Keep — Everyday; ≤ preferred (validated) |
| Morning ready (hard deadline) (`morning_hard_time`) | 07:00 | Hard deadline; fail-safe window opens 4 h earlier | P | Yes | Medium | Keep — Everyday; a time after the morning peak start can import at peak price (comfort first) — documented |
| Afternoon storage target (`target_c`) | 70 °C | Afternoon goal; Manual 70 is still the command and the thermostat stops at 70 | P | Yes | Low | Keep — Everyday (65–70) |
| Afternoon comfort preference (`evening_time`) | 16:00 | Weekend (no-peak) afternoon ready time; weekdays use the peak start | P | Yes | Low | Keep — Everyday; rename "Weekend afternoon ready time" |
| Expected morning hot-water use (`expected_morning_draw_c`) | 10 °C | Reading drop allowed for when planning the afternoon target | P | Yes | Low | Keep — Advanced |
| Assumed standing heat loss (`standing_loss_c_per_hour`) | 0.2 °C/h | Planner losses; morning allowance uses max(0.5, this) | P | Yes | Low | Keep — Advanced |
| Heating time allowance (`margin_minutes`) | 30 min | Extra planned minutes when heat is needed | P | Yes | Low | Keep — Advanced |
| Legacy: weekend morning time (`morning_time`) | 08:00 | Nothing since 0.7.0 | X | No | Misleading | Retire (value kept) |
| Legacy: earlier weekday shower time / shower-ready time | off / 07:00 | Legacy shadow display only | S | No | Misleading | Retire (values kept) |
| Thermostat hysteresis | 8 °C (fixed) | Restart point used by the thermostat gate | P | — | — | Not a setting; stays fixed |
| Manual 70 °C command | fixed | The only permit command | P / B | — | — | Not a setting; never editable |

### Solar, forecasts and economics

| Setting | Default | What it controls | Use | Works / when | Risk | Action |
| --- | --- | --- | --- | --- | --- | --- |
| Minimum saving to recommend waiting (`wait_benefit_aud_per_kwh`) | 0.05 $/kWh | When the planner prefers later heating | P | Yes | Low | Keep — Advanced |
| Solar start qualification (`solar_hold_minutes`) | 10 min | How long a change between optional economic choices must persist | P | Yes | Low | Keep — Advanced; fix description |
| Minimum optional cycle (`minimum_cycle_minutes`) | 30 min | Shortest planned heating block | P | Yes | Low | Keep — Advanced; fix description ("simulation only" was wrong) |
| Minimum optional cycle gap (`minimum_gap_minutes`) | 30 min | Shortest gap between planned blocks | P | Yes | Low | Keep — Advanced; fix description |
| Minimum useful net surplus (`min_solar_kw`) | 0.1 kW | Legacy recent-export window | S | No | Misleading | Retire |
| Solar headroom (`export_headroom_kw`) | 0.3 kW | Legacy recent-export window | S | No | Misleading | Retire |
| Recent-export scenario horizon (`solar_window_minutes`) | 15 min | Legacy recent-export window | S | No | Misleading | Retire |
| Minimum economic switching benefit (`switching_benefit_aud`) | 0.10 $ | Legacy simulator | X | No | Misleading | Retire |
| Economic loss grace period (`solar_loss_minutes`) | 20 min | Legacy simulator | X | No | Misleading | Retire (production uses the fixed 10-min rolling median and hold) |
| Inverter AC output limit (`pv_ac_limit_kw`) | 5 kW | Clips measured and forecast PV | P | Yes | Low | Keep — Advanced |
| Household load basis (`base_load_source`) | measured only | Measured base load vs EMHASS load forecast | P | Yes | Low | Keep — Advanced (EMHASS load includes past heater runs) |
| Use published forecasts (`forecast_enabled`) | off (live: on) | EMHASS PV/load forecasts in planning | P | Yes | Low | Keep — Advanced |
| Forecast uncertainty margin (`forecast_uncertainty`) | 0.25 | Cuts PV, raises load forecasts | P | Yes | Low | Keep — Advanced |
| Extra forecast household load (`forecast_house_margin_kw`) | 0.3 kW | Added to forecast load | P | Yes | Low | Keep — Advanced |
| Maximum forecast generation age (`forecast_max_age_minutes`) | 120 min | Older forecasts ignored (no future solar assumed) | P | Yes | Low | **Restrict** to 35–360 (F8) |
| Economic permission constants | rolling 10 min, hold 10/5 min, tolerances | Grant/withdraw | P | — | — | Fixed in code; not settings |

### Tariff (contract)

| Setting | Default | What it controls | Use | Works / when | Risk | Action |
| --- | --- | --- | --- | --- | --- | --- |
| Tariff periods mode (`tariff_profile`) | aurora_93 | Built-in Aurora 93 periods or custom JSON | P | Yes | High if wrong | Keep — Advanced; **locked while control is on** |
| Tariff clock (`tariff_clock`) | standard | Fixed AEST; peaks show one hour later in summer | P | Yes | High | Keep — Advanced; locked while on |
| Use peak periods on weekends (`weekend_peak`) | off | Weekend peaks | P | Yes | Medium | Keep — Advanced; locked while on |
| Peak morning/evening start/end | 07–10, 16–21 | Peak periods (tariff clock) | P | Yes | High | Keep — Advanced; locked while on |
| Off-peak / peak / shoulder import price | 0.1702 / 0.361878 / 0.1702 | Prices for every decision | P | Yes | High | Keep — Advanced; locked while on; **restrict** to 0–2 $/kWh |
| Export compensation (`feed_in_rate`) | 0.09276 | Value of exported solar | P | Yes | High | Keep — Advanced; locked while on; restrict to 0–2 |
| Custom weekly tariff periods (`tariff_periods`) | Aurora table | Used only in custom mode; always validated | P | Yes | High | Keep — Configure only; locked while on |
| Tariff contract verified (`tariff_verified`) | on | Off = planner gated (hold only) | P (gate) | Yes | High | System; locked while on |

### Meter and data freshness

| Setting | Default | What it controls | Use | Works / when | Risk | Action |
| --- | --- | --- | --- | --- | --- | --- |
| Positive grid means import (`import_positive`) | off | Meter sign (load-tested) | P | Yes | **High** | System; locked while on |
| Meter sign and units verified (`meter_verified`) | on | Off = planner gated | P (gate) | Yes | High | System; locked while on |
| Maximum cloud poll age (`status_max_age_minutes`) | 45 min | Planner freshness gate | P | Yes | Medium | **Restrict** to 35–90 (F7); System |
| Maximum power reading age (`grid_max_age_seconds`) | 120 s | Meter freshness gate | P | Yes | Medium | Keep — System (30–300) |
| Sensor mappings (Configure, first page) | GoodWe / bridge entities | All measurements | P | Yes, rebuilds evidence | High | Advanced; locked while on; energy totals marked "not used" (F14) |

### Controller and commissioning (all P)

| Setting | Default | What it controls | Risk | Action |
| --- | --- | --- | --- | --- |
| Controller command topic | blank | MQTT destination | **High** | System; locked while on; **must match the mapped heater** (F2) |
| Bridge commands qualified (T3) | off | Commissioning gate | High | System; locked while on |
| Minimum heating period | 30 min (30–180) | Dwell before a park (thermostat stop and urgent peak park excepted) | Medium | System; locked while on |
| Minimum rest period | 30 min (30–240) | Dwell before any permit, comfort included | Medium | System; locked while on; **must be ≤ latency reserve + 30 min** (F6) |
| Maximum commands per day | 6 (4–10), 2 reserved for comfort | Rolling 24 h command limit | Medium | System; locked while on; whole numbers only |
| Command confirmation timeout | 65 min | Lock if no confirming status | Medium | System; locked while on |
| Cloud request budget per day | 220 (160–400) | No command once reached | Medium | System; locked while on; whole numbers only |
| Execution latency reserve | 30 min | Deadlines and pre-peak park brought forward | Medium | System; locked while on |
| Notification service | blank | Phone alerts in addition to HA notifications | Low | System; editable any time; **name validated** (F4) |
| Restore recommended preferences / Undo | — | Resets preferences only | Medium | Keep — Advanced; **no longer touches controller safety settings** (F11) |

### Legacy and reference

| Setting | Use | Action |
| --- | --- | --- |
| Pause shadow planning (`paused`) | S, and made an active controller hold | Retire; ignored while control is active (F9) |
| Expected native target (`expected_native_target_c`) | S (shadow review check, native comparison) | Retire |
| Native schedule reference / clock / clock checked / check date | S (comparison display) | Retire |
| T-Comfort reference | S | Retire |

Retiring removes the control from the interface only. Stored values stay in
the config entry, are still validated and are restored by a rollback.

### Other controls

| Control | Action |
| --- | --- |
| Automatic heater control | Keep — Everyday; refuses to turn on until commissioning is complete |
| Hold / Resume automatic control, Acknowledge fault | Keep — Everyday |
| Guest mode (12 h) buttons and end time | Keep — Everyday; rename **12hr Override** (behaviour unchanged) |
| Holiday departure / return, Cancel holiday | Keep — Everyday |

### Bridge app options (Settings → Apps → Thermann Hot Water)

| Option | Recommended | Notes |
| --- | --- | --- |
| `commands_enabled` | on only after T3 (on now) | The controller refuses commands if off or unknown |
| `command_policy` | `automation` | **The controller now refuses to command under `legacy`** (F3) |
| `poll_interval_minutes` / `poll_interval_unit` | 30 minutes | The controller reads the interval for its status-freshness gate |
| `on_demand_refresh_enabled` | off | Not needed; the bridge does one bounded read before a command |
| `min_cloud_retry_minutes`, `auth_retry_generation`, credentials | unchanged | Authentication safety; never changed by the controller |

## Interface after the changes

- **Everyday:** automatic control, Hold/Resume, 12hr Override, holiday, morning
  preferred and minimum with their times, afternoon target, weekend afternoon
  time.
- **Advanced:** tariff, forecasts, economic and model assumptions, sensor
  mappings, restore and undo.
- **System (commissioning):** command topic, T3 qualification, budgets, dwell,
  confirmation timeout, latency, meter verification and sign, tariff
  verification, freshness limits, notification service. Editing any of these
  except the notification service requires automatic control to be **off**.
