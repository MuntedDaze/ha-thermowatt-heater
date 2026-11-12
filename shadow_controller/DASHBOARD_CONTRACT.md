# Main dashboard: entity and data contract (Phase 3, not built yet)

Entity IDs were checked read-only against the live entity registry on 12 Nov 2026. The tables use these markers:

| Marker | Meaning |
| --- | --- |
| ✅ | exists |
| 🆕 | added by controller 0.7.0 (this branch, not installed) |
| ➕ | needs a helper, a template or a new integration (listed in the last section) |

**Design rules:**
- Standard cards only: tile, entity, glance, history-graph, statistics-graph, energy cards, conditional and markdown. Optionally the popular `power-flow-card-plus` from HACS for the animated flow; the built-in energy-distribution card is the no-HACS fallback.
- One overview page, with tap-through detail pages for Hot water, Energy, Appliances and Home.
- Minimal controls on the main screen.
- **No MQTT, `water_heater` or relay service calls from the dashboard.** The heater is commanded only by the controller.

## Hot water (overview tile → detail page)

| Shown | Entity | Notes |
| --- | --- | --- |
| Tank reading (bottom sensor) | ✅ `water_heater.home_boiler_home` attribute `current_temperature` | Label it "Tank reading (bottom sensor)", not "tank temperature" |
| Reading age | ✅ `sensor.home_status_age` (bridge diagnostic, seconds) or ✅ `sensor.home_last_successful_poll` | Show in minutes |
| Thermann mode | ✅ `sensor.home_boiler_home_vendor_mode` (`Off` / `Manual` / …) | |
| Element actually drawing power | ✅ `sensor.thermann_shadow_heater_element_state` + `sensor.thermann_shadow_heater_state_confidence` (meter-based estimate) | Never the Thermann "heating" binary sensor, which stays unverified |
| Operating mode | 🆕 `sensor.thermann_shadow_hot_water_operating_mode` (`automatic` / `guest` / `holiday` / `disabled`) | |
| Controller state / reason | ✅ `sensor.thermann_shadow_automatic_control_state`, `…_automatic_control_reason` | |
| Next heating start / stop | ✅ `sensor.thermann_shadow_next_heating_start`, `…_next_heating_stop` | |
| Morning / afternoon readiness | ✅ `sensor.thermann_shadow_morning_readiness`, `…_afternoon_readiness` (attributes: required kWh, deadline) | 0.7.0: morning is 45 °C by 06:00 (preferred) / 42 °C by 07:00 (hard) |
| Estimated heating duration / cost | ✅ `sensor.thermann_shadow_heating_time_estimate` (+ plan cost attributes); 🆕 `permission_economics` in the controller state attributes (cost now, alternative, solar share) | Shown as estimates |
| Fault / attention | ✅ `sensor.thermann_shadow_controller_fault`; persistent notifications | Conditional red card |
| Guest mode | 🆕 `button.thermann_shadow_start_guest_mode_12_h`, `button.thermann_shadow_cancel_guest_mode`, `sensor.thermann_shadow_guest_mode_ends` | Detail page only, with a confirmation dialog |
| Holiday | 🆕 `datetime.thermann_shadow_holiday_departure`, `datetime.thermann_shadow_holiday_return`, `button.thermann_shadow_cancel_holiday_mode` | Detail page |
| Thermal diagnostics | 🆕 `sensor.thermann_shadow_tank_thermal_state` (attributes listed below) | Separate "advanced" page |

**Thermal-model fields**, all estimates or inferences, labelled as such, from the attributes of `sensor.thermann_shadow_tank_thermal_state`:

| Field | Source |
| --- | --- |
| tank state + confidence | state; `confidence` |
| estimated remaining heating | `estimated.remaining_heating_minutes_physical_upper_bound` |
| energy delivered this session | `estimated.session_energy_kwh` |
| observed recent change | `measured.observed_change_c_per_hour` |
| estimated standing loss | `estimated.standing_loss_c_per_hour` (+ sample count) |
| last suspected water use | `inferred.last_suspected_draw` |
| predicted versus actual heating | `inferred.actual_vs_physical_minutes_median`, `inferred.heating_after_draw` / `heating_undisturbed` |
| last reading and age | `measured.last_reading_c`, `measured.reading_age_minutes` |
| predicted time to the next comfort target | ➕ template on the readiness attributes (required kWh ÷ 3 kW), labelled "physical-model estimate" |

## Energy

| Shown | Entity | Status |
| --- | --- | --- |
| Live solar | `sensor.goodwe_inverter_pv_power` (W) | ✅ |
| Live household consumption | `sensor.goodwe_inverter_house_consumption` (W) | ✅ |
| Live grid import/export | `sensor.goodwe_inverter_meter_active_power` (W; owner-verified sign: export positive) | ✅ (template split ➕ for the flow card) |
| Today's solar | `sensor.goodwe_inverter_today_s_pv_generation` (kWh) | ✅ |
| Today's import / export | `sensor.goodwe_inverter_meter_total_energy_import` / `_export` (total kWh) | ➕ `utility_meter` daily cycle |
| Today's consumption | — | ➕ derived as import + PV − export (template, `total_increasing`) or an integration sensor of house power |
| Today's cost | — | ➕ template from daily import split by tariff period (Tariff 93 peak/off-peak, fixed AEST) minus export × feed-in; or HA Energy dashboard prices |
| Solar → home → grid flow | the three live power sensors | ✅ (`power-flow-card-plus` or the energy-distribution card) |
| Solar forecast today/tomorrow | `sensor.p_pv_forecast` (EMHASS, 48 × 30 min, refreshed every 30 min; verified fresh) | ✅ (24 h horizon only) |
| Weather today/tomorrow | — | ➕ **no `weather.*` entity exists**: add Met.no (built in) or the BOM integration |

Notes:
- **The EMHASS load forecast includes past 3 kW heater runs.** The controller uses measured base load (`base_load_source: measured_only`) and must keep doing so.
- **Energy dashboard:** configure grid import/export, solar and individual devices (the Tapo energy sensors) to get long-term statistics without extra Recorder load.

## Appliances (Tapo plugs, all ✅)

| Appliance | Live power | Today | Month | Switch |
| --- | --- | --- | --- | --- |
| Dryer | `sensor.dryer_current_consumption` | `sensor.dryer_today_s_consumption` | `…_this_month_s_consumption` | `switch.dryer` |
| Washing machine | `sensor.washing_machine_current_consumption` | `sensor.washing_machine_today_s_consumption` | ✅ | `switch.washing_machine` |
| Dishwasher | `sensor.dishwasher_current_consumption` | `sensor.dishwasher_today_s_consumption` | ✅ | `switch.dishwasher` |
| Server, network cupboard, jrig, garage | `sensor.*_current_consumption` | `sensor.*_today_s_consumption` | ✅ | (infrastructure: no dashboard switch) |

**Still needed:**
- **Typical running watts** (excluding standby/off): ➕ a `statistics` or template sensor per appliance, averaging power only while above a running threshold, for example 20 W.
- **Running cost:** ➕ today's kWh × the current tariff rate (approximate).
- **Trends:** statistics-graph on the energy sensors (long-term statistics already exist).
- **"Run now?" hint:** ➕ template comparing the current solar surplus (`sensor.thermann_shadow_hypothetical_solar_surplus_if_heater_off`) with the typical running watts.

**Do not put switches for always-on infrastructure** (server, network cupboard) on the dashboard.

## Home controls

| Shown | Entity | Status / rule |
| --- | --- | --- |
| Bathroom fans | `switch.main_fan`, `switch.ensuite_fan` | ✅ manual switching OK |
| Towel rails | `switch.main_towel_rail`, `switch.ensuite_towel_rail` | ✅ manual switching OK |
| Front door | `binary_sensor.front_door_door` | ✅ status only |
| Garage door status | `binary_sensor.garage_door` | ✅ status |
| Garage operation | `switch.garage` (Tapo relay) + `binary_sensor.garage_door` | ➕ **template `cover`** (below); never expose the raw relay |

**Tapo Smart Actions:** these run in the Tapo cloud and hub, independently of HA. Both write the same plug state, so **the last command wins.**
- An HA "off" can be undone by a Tapo action firing later.
- A Tapo timer (`number.*_turn_off_in`, `switch.*_auto_off_enabled`) can switch off a plug that HA turned on.
- **Rule:** the dashboard shows the true state (the plug's own reported state) and offers only manual on/off. It never creates HA automations that fight Tapo Smart Actions. Any HA automation for the same plug needs an explicit owner decision about which system owns it.

**Garage cover (to verify before building):**
- **Confirm first:** whether `switch.garage` is a momentary pulse (auto-off) or a latch, and how `garage_button` relates to it.
- **The cover:**
  - state comes from `binary_sensor.garage_door` (open/closed);
  - `open` acts only when closed, `close` only when open, each sending one pulse;
  - no toggle;
  - shows unavailable when the door sensor or relay is offline;
  - the dashboard asks for confirmation.

## Controller actions (all via the integration, never MQTT)

| Action | Entity |
| --- | --- |
| Automatic control on/off | ✅ `switch.thermann_shadow_automatic_heater_control` |
| Hold / Resume / Acknowledge fault | ✅ `button.thermann_shadow_hold_heater_owner_override`, `…_resume_automatic_control`, `…_acknowledge_controller_fault` |
| Guest mode start / cancel | 🆕 buttons as above |
| Holiday dates / cancel | 🆕 datetime entities and button as above |

## Helpers and integrations to add later (owner approval each)

1. `utility_meter` daily for grid import and export.
2. A template for daily consumption and an approximate cost; or the HA Energy dashboard with Tariff 93 prices.
3. A template split of meter power into import/export, for the flow card.
4. Per-appliance "typical running watts" statistics sensors.
5. A weather integration (Met.no or BOM).
6. The template garage `cover`, after relay verification.
7. Optional HACS: `power-flow-card-plus`.
