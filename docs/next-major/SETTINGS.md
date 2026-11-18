# Every Thermowatt setting

[Handbook](OWNER_HANDBOOK.md) · [Screens/report](INTERFACE.md)

Generated from the same catalogue and form-unit conversion used by the integration.
Current saved values always take precedence. Defaults below are schema fallbacks for
missing historical fields, not permission to overwrite the household. Fresh setup
separately starts with flat/unverified tariffs, HA's zone, local clock,62°C baseline/
normal and optional boost off. Existing45/62/70 and all mappings/IDs are retained.

Open Settings → Devices & services → Thermann Controller → Configure.
Each page saves separately. Closing without Submit changes nothing. Prices are
cents/kWh here, percentages are0–100; native entity units/IDs remain compatible.

## Index

- [Hot Water](#hot-water)
- [Weekend and heating preferences](#heating-preferences)
- [Plan, prices and clock](#prices)
- [Two-peak example hours](#peak-times)
- [Advanced schedule data](#tariff-json)
- [Solar forecasts and grid meter](#solar)
- [Equipment and savings](#equipment)
- [Cloud checks and data age](#polling)
- [Legacy and developer settings](#legacy)
- [Commissioning and safeguards](#commissioning)
- [Sensor mappings](#sensor-mappings)
- [Retired settings](#retired-settings)

<a id="hot-water"></a>
## Hot Water

Choose thermostat targets and permitted heating. Your saved temperatures are retained. The owner's agreed example is 45°C baseline / 62°C normal / 70°C optional solar, with peak OFF. It is not a universal hygiene recommendation. Follow the appliance instructions and your plumber's advice.

### Night and weekend temperature

Stored key: `baseline_c`. Default: `45`. Allowed: 45 / 62. Units: °C. Turn Automatic off before changing.

Thermostat target during permitted baseline hours. Your saved household choice is retained. Only supported temperatures are offered; a setpoint does not prove whole-tank temperature or hygiene compliance. Follow appliance and plumbing requirements.

### Normal weekday storage temperature

Stored key: `normal_storage_c`. Default: `62`. Allowed: 62 / 70. Units: °C. Turn Automatic off before changing.

Required weekday thermostat target, for example 62°C in the owner's agreed strategy. It must be at least the baseline. This is a target, not a guarantee of hot-water quantity.

### Optional solar storage temperature

Stored key: `solar_boost_c`. Default: `70`. Allowed: 62 / 70. Units: °C. Turn Automatic off before changing.

Upper target for worthwhile extra solar heating, for example 70°C. Must be at least normal storage. Equal targets avoid a separate top-up; choosing a target alone does not enable boosting.

### Enable optional solar boost

Stored key: `optional_solar_boost`. Default: `True`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Allow extra storage with either a commissioned dedicated hot-water circuit meter (CT) or the separately configured experimental CT-free GoodWe grid-meter setup. Turning this switch on alone does not start boosting: automatic control must be enabled, and measurement, solar surplus, cost, peak-policy and safety checks must all pass. Required storage still works without a CT; the separate 12-hour Override is unchanged.

### Heating during peak periods

Stored key: `peak_heating_policy`. Default: `Never schedule heating during peak`. Allowed: Never schedule heating during peak / Verified solar-only heating. Units: none. Turn Automatic off before changing.

Never schedule heating takes priority even with high solar export. The solar-only choice requires a commissioned circuit meter or separately qualified CT-free grid-only operation and every command safeguard. Owner overrides and native protective cycles remain possible. Cloud OFF is not proof of zero electricity use.

### Aim to finish heating this much early

Stored key: `completion_margin_minutes`. Default: `30.0`. Allowed: 5–120. Units: min. Turn Automatic off before changing.

Minutes reserved before the required finish time; 30 minutes is a useful planning starting point. Required heating may continue to the hard peak boundary. This is a planning allowance, not extra permission to heat during peak.

### Weekday heating window starts

Stored key: `daytime_start`. Default: `09:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Household local time, for example 09:00. Used when the plan has no peak deadline. Must be before the ready time. Tariff peak boundaries take priority on time-of-use plans. Leave seconds at 00 if Home Assistant shows them.

### Weekday hot water ready by

Stored key: `storage_ready_time`. Default: `16:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Household local time, for example 16:00, when there is no peak deadline. After the window starts and before the baseline returns. A planning goal, not a temperature or hygiene guarantee. Leave seconds at 00 if Home Assistant shows them.

### Return to night temperature at

Stored key: `baseline_start`. Default: `21:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Household local time, for example 21:00, when there is no peak deadline. Must follow the ready time. The peak policy still applies. Leave seconds at 00 if Home Assistant shows them.

<a id="heating-preferences"></a>
## Weekend and heating preferences

Weekend normal storage deliberately allows off-peak grid assistance. Solar-only boosts still need verified local surplus. Changing preferences does not qualify hardware.

### Weekend solar-led normal storage

Stored key: `weekend_solar_heating`. Default: `True`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Use measured PV to open a weekend comfort window. 62 normal storage is planned to the storage-ready time with off-peak grid assistance allowed; it is not solar-only heating.

### Weekend daylight trigger

Stored key: `weekend_pv_start_kw`. Default: `0.5`. Allowed: 0.1–3.6. Units: kW. Turn Automatic off before changing.

Measured PV production in kW. The first fresh report at or above this opens the weekend window until the end time; 0.5 kW means 500 W.

### Weekend latest return to baseline

Stored key: `weekend_end_time`. Default: `18:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Household local clock: the weekend window ends and the thermostat target returns to baseline at this time. This does not cool stored water.

### Wait after confirmed solar withdrawal

Stored key: `solar_cooldown_minutes`. Default: `10.0`. Allowed: 10–60. Units: min. Turn Automatic off before changing.

Minutes after confirmed withdrawal OFF before another optional solar start. Fresh qualification can overlap this wait. Ordinary 15-minute command spacing also applies.

### Check hot water before peak

Stored key: `pre_peak_observation_minutes`. Default: `30.0`. Allowed: 5–60. Units: min. Existing active-control guard applies where relevant.

Minutes before a configured peak to arrange a meaningful status observation and low-water assessment. Tariff-clock/DST conversion is automatic.

### Request peak OFF this much early

Stored key: `peak_command_lead_minutes`. Default: `2.0`. Allowed: 1–10. Units: min. Turn Automatic off before changing.

Minutes reserved for local evaluation, cloud command and confirmation before peak. Must be shorter than the heating completion margin in Hot Water. This is not a guaranteed electrical cutoff.

### Low bottom-temperature warning

Stored key: `low_water_warning_c`. Default: `35.0`. Allowed: 20–45. Units: °C. Existing active-control guard applies where relevant.

Warn only on a fresh bottom-probe reading below this temperature near peak. It is not a thermostat target, whole-tank measurement or automatic emergency.

<a id="prices"></a>
## Plan, prices and clock

Prices below are Australian cents per kWh (25 means $0.25/kWh). Check the retail contract's tax basis consistently. Off-peak is usually cheaper, peak usually dearer, and shoulder is the period between them. Daily supply charges do not affect heating-window choices. Your saved values are prefilled, not replaced by example prices.

### Electricity plan type

Stored key: `tariff_profile`. Default: `aurora_93`. Allowed: flat / aurora_93 / custom. Units: none. Turn Automatic off before changing.

Flat rate uses the off-peak/flat price all day, with no peak periods. The Aurora example uses the editable two-peak schedule; verify it against your retail contract. Custom uses the guided weekly/seasonal schedule. Selecting a plan does not verify it.

### Household time zone

Stored key: `time_zone`. Default: `Australia/Hobart`. Allowed: A supported IANA zone, for example Australia/Hobart. Units: none. Turn Automatic off before changing.

Search for your IANA zone, for example Australia/Hobart or Australia/Perth. New setup uses Home Assistant's zone. Household times follow this zone; the separate tariff clock decides whether electricity periods follow daylight saving.

### Clock used by your electricity contract

Stored key: `tariff_clock`. Default: `local`. Allowed: standard / local. Units: none. Turn Automatic off before changing.

Local time follows daylight saving in the chosen zone. Fixed standard time keeps its standard UTC offset all year (for example AEST UTC+10 in Hobart). During summer those tariff times can differ from the wall clock. Check your retailer's contract.

### Off-peak or flat electricity price

Stored key: `off_peak_rate`. Default: `17.02`. Allowed: 0–200. Units: c/kWh. Turn Automatic off before changing.

Australian cents per kWh imported from the grid, for example 25 means $0.25/kWh. Off-peak is the usually cheaper period; on a flat plan this price applies all day. Use your actual retail usage price, not the daily supply charge or a network tariff.

### Peak electricity price

Stored key: `peak_rate`. Default: `36.1878`. Allowed: 0–200. Units: c/kWh. Turn Automatic off before changing.

Australian cents per kWh during peak periods, usually the expensive hours. Example: 40 means $0.40/kWh. Used only by periods marked peak; the peak-heating policy still applies even if another price happens to be cheaper.

### Shoulder electricity price

Stored key: `shoulder_rate`. Default: `17.02`. Allowed: 0–200. Units: c/kWh. Turn Automatic off before changing.

Australian cents per kWh in periods between peak and off-peak, if your contract has them. Example: 30 means $0.30/kWh. Used only by custom periods marked shoulder; otherwise retained without effect.

### Payment for exported solar electricity

Stored key: `feed_in_rate`. Default: `9.276`. Allowed: 0–200. Units: c/kWh. Turn Automatic off before changing.

Australian cents per kWh your retailer pays for exported solar, for example 8 means $0.08/kWh. Using solar for hot water gives up this payment, so the controller includes it as a cost. Use your contract's rate; time-varying export prices are not modelled.

### I have checked my electricity contract

Stored key: `tariff_verified`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Confirm only after checking retail prices, every period, weekends, seasons, time zone and tariff clock. Automatic control needs this verification. Saving a form is not verification; changing a price does not check the bill for you.

<a id="peak-times"></a>
## Two-peak example hours

These hours apply only when the Aurora-style two-peak example is selected. They are tariff-clock times, not necessarily the summer wall clock. Other plans should use the guided custom schedule. All four times must increase.

### Morning peak starts

Stored key: `peak_morning_start`. Default: `07:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Only for the Aurora-style two-peak plan. Time uses your tariff clock, which may differ from the household wall clock in summer. All four times must increase in order. Check your retail contract; custom plans use the guided schedule instead. Leave seconds at 00 if Home Assistant shows them.

### Morning peak ends

Stored key: `peak_morning_end`. Default: `10:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Only for the Aurora-style two-peak plan. Time uses your tariff clock, which may differ from the household wall clock in summer. All four times must increase in order. Check your retail contract; custom plans use the guided schedule instead. Leave seconds at 00 if Home Assistant shows them.

### Afternoon peak starts

Stored key: `peak_evening_start`. Default: `16:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Only for the Aurora-style two-peak plan. Time uses your tariff clock, which may differ from the household wall clock in summer. All four times must increase in order. Check your retail contract; custom plans use the guided schedule instead. Leave seconds at 00 if Home Assistant shows them.

### Afternoon peak ends

Stored key: `peak_evening_end`. Default: `21:00`. Allowed: 24-hour local/tariff time as described. Units: none. Turn Automatic off before changing.

Only for the Aurora-style two-peak plan. Time uses your tariff clock, which may differ from the household wall clock in summer. All four times must increase in order. Check your retail contract; custom plans use the guided schedule instead. Leave seconds at 00 if Home Assistant shows them.

### Apply the example peak hours on weekends too

Stored key: `weekend_peak`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Only affects the Aurora-style two-peak plan. Off means all weekend hours are off-peak. Follow your actual contract; custom schedules specify weekdays separately.

<a id="tariff-json"></a>
## Advanced schedule data

Expert alternative; most users should choose the guided schedule. This edits the saved custom table, but does not select Custom automatically. JSON rate overrides use dollars/kWh. Every day in every month needs complete coverage without overlaps.

### Advanced schedule data (JSON)

Stored key: `tariff_periods`. Default: `[{"days":[0,1,2,3,4],"start":"00:00","end":"07:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"07:00","end":"10:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"10:00","end":"16:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"16:00","end":"21:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"21:00","end":"00:00","kind":"off_peak"},{"days":[5,6],"start":"00:00","end":"00:00","kind":"off_peak"}]`. Allowed: validated schedule table. Units: none. Turn Automatic off before changing.

Expert alternative to the guided schedule editor. Days are 0=Monday to 6=Sunday; months are 1–12; start/end are HH:MM. kind is off_peak, shoulder or peak. Optional rate is dollars/kWh, not the cents shown elsewhere. Every minute of every day/month must be covered exactly once. Nothing saves if invalid.

<a id="solar"></a>
## Solar forecasts and grid meter

Forecasts predict future solar and household demand; they do not prove spare electricity. Basic tariff control needs neither solar nor EMHASS. Verified grid export can help choose required off-peak heating without a circuit meter; optional solar-only heating requires a separately qualified CT-free record or commissioned circuit meter.

### Use solar and household forecasts

Stored key: `forecast_enabled`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Use timestamped predictions of solar production and household demand to choose economical required heating windows. Optional: leave off without solar/EMHASS. Missing or old forecasts cause conservative nominal planning, not assumed free solar. Optional boost requires a commissioned circuit meter or separately qualified CT-free grid-only operation.

### Forecast safety allowance

Stored key: `forecast_uncertainty`. Default: `25.0`. Allowed: 0–90. Units: %. Existing active-control guard applies where relevant.

Percentage to subtract from predicted solar and add to predicted household demand. Example: 25% is stored as 0.25. Larger values are more cautious; forecasts never guarantee surplus electricity.

### Extra allowance for household appliances

Stored key: `forecast_house_margin_kw`. Default: `0.3`. Allowed: 0–5. Units: kW. Existing active-control guard applies where relevant.

Additional kW reserved for competing appliances beyond the forecast. Example: 0.3 kW is 300 W. Higher values reduce assumed solar available for heating.

### Ignore forecasts older than

Stored key: `forecast_max_age_minutes`. Default: `120.0`. Allowed: 35–360. Units: min. Existing active-control guard applies where relevant.

Minutes since the forecast was generated, not when an old forecast was republished. For 30-minute EMHASS updates use at least 35 minutes; 120 is a starting example. Old forecasts are ignored rather than treated as future solar.

### Maximum usable inverter output

Stored key: `pv_ac_limit_kw`. Default: `5.0`. Allowed: 1–30. Units: kW. Existing active-control guard applies where relevant.

Combined AC output limit in kW for the inverter represented by your solar readings. Example: a 5 kW inverter can have more than 5 kW of panels. Forecast output above this limit is clipped; use the inverter rating, not panel capacity.

### Grid meter readings have been checked

Stored key: `meter_verified`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Confirm only after checking net grid power, units, sign and freshness with a known load/export test. This verifies the grid meter, not the separate hot-water circuit meter. Never turn it on merely to clear a warning.

### Positive grid power means buying electricity

Stored key: `import_positive`. Default: `True`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

On: positive net power is grid import and negative is export. Off: positive is export. Verify using a known household load and your meter's documentation; a reversed sign can make costly import look like surplus solar.

<a id="equipment"></a>
## Equipment and savings

Advanced planning assumptions, not new heater qualifications. Use appliance-label ratings; estimates do not prove actual element operation or whole-tank temperature. Do not adjust assumptions just to make a prediction look better.

### Hot-water tank capacity

Stored key: `tank_litres`. Default: `315.0`. Allowed: 50–500. Units: L. Turn Automatic off before changing.

Nominal litres from the appliance label, for example 315 L. Used for conservative heating estimates, not measured hot-water availability. Changing it clears learned-planning hardware qualification.

### Heater element rating

Stored key: `element_kw`. Default: `3.0`. Allowed: 2–3.6. Units: kW. Turn Automatic off before changing.

Nominal electrical kW from the appliance label, for example 3 kW. Without a circuit meter this estimates heating time only; it never proves the element is on. Changing it clears learned-planning hardware qualification.

### Extra stored heat likely to be used

Stored key: `boost_useful_fraction`. Default: `90.0`. Allowed: 0–100. Units: %. Turn Automatic off before changing.

Estimated percentage of extra boosted heat used before the next cheap heating opportunity. Example: 90%. Lower values make extra boosting less attractive; 0% prevents it. This assumption is not learned evidence.

### Minimum saving for an extra solar boost

Stored key: `boost_min_saving_aud`. Default: `0.1`. Allowed: 0–2. Units: AUD. Turn Automatic off before changing.

Australian dollars expected to be saved per boost, for example $0.10. Avoids extra commands for trivial benefit. The per-kWh margin and all measured-power guards also apply.

### Minimum saving per unit of optional heat

Stored key: `optional_heat_margin_aud_per_kwh`. Default: `2.0`. Allowed: 0–20. Units: c/kWh. Turn Automatic off before changing.

Australian cents per kWh saved against off-peak grid heating, including lost solar export income. Example: 2 means $0.02/kWh. This does not relax measurement-qualification or grid-import checks.

### Minimum saving before waiting for a better window

Stored key: `pause_min_saving_aud`. Default: `0.3`. Allowed: 0.1–2. Units: AUD. Turn Automatic off before changing.

Australian dollars a later window must save, for example $0.30. Heating must still fit before the planning deadline. Increasing this reduces changes for small estimated savings.

<a id="polling"></a>
## Cloud checks and data age

One choice: Cloud polling mode (Smart recommended). Select the same mode in the Thermann Hot Water app options; the app owns every cloud request. A fresh command prior and confirmation are always required.

### Cloud polling mode

Stored key: `polling_mode`. Default: `existing`. Allowed: existing / smart / fixed_30 / minimum. Units: none. Turn Automatic off before changing.

Smart is the recommended choice: reads are arranged for useful decisions with bounded quiet checks. Minimum makes fewer requests but notices app changes later. Fixed 30 minutes and Keep existing (legacy adaptive switches on the Legacy page) retain compatibility. Choose the same mode in the Thermann Hot Water app options.

### Maximum age of temperature used for planning

Stored key: `status_max_age_minutes`. Default: `45.0`. Allowed: 35–90. Units: min. Turn Automatic off before changing.

Minutes before a cloud heater observation is too old for temperature-sensitive planning; 45 is the existing starting value for 30-minute fixed checks. This does not schedule a refresh or relax the bridge's exact-prior command checks. Quiet holds use separate bounded rules.

### Maximum age of local power readings

Stored key: `grid_max_age_seconds`. Default: `120.0`. Allowed: 30–300. Units: s. Turn Automatic off before changing.

Seconds before local grid observations are considered stale; 120 is an example. Missing or stale data resets economic holds and cannot authorise solar-only heating. Changing this does not trigger cloud requests.

<a id="legacy"></a>
## Legacy and developer settings

Settings kept only so existing saved options, entities and a rollback are unchanged. None of them is needed in the recommended configuration, and each description says when it still has an effect. Changing them never qualifies hardware or authorises heater operation.

### Allow adaptive cloud checks

Stored key: `adaptive_polling_enabled`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Pre-Smart adaptive hints, default off. Requires the bridge's separate enabled/qualified options. Legacy: only used when Cloud polling mode is Keep existing; no effect with Smart, Minimum or Fixed 30 minutes.

### Allow longer checks during quiet periods

Stored key: `event_aware_polling_enabled`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Pre-Smart quiet-period hints, default off. Requires adaptive hints and a qualified bridge. Legacy: only used when Cloud polling mode is Keep existing; no effect with Smart, Minimum or Fixed 30 minutes.

### Longest quiet-period check interval

Stored key: `owner_change_check_minutes`. Default: `60.0`. Allowed: 30–90. Units: min. Turn Automatic off before changing.

Minutes, 30–90, for pre-Smart quiet-period hints. Legacy: only used when Cloud polling mode is Keep existing; no effect with Smart, Minimum or Fixed 30 minutes. Smart uses its own bounded quiet intervals.

### Preview adaptive cloud checks

Stored key: `adaptive_polling_shadow`. Default: `False`. Allowed: On / Off. Units: none. Existing active-control guard applies where relevant.

Developer comparison only: record when the old adaptive model would read the cloud. Never changes actual bridge requests, polling or heating.

### Preview: longest check interval while heating

Stored key: `adaptive_poll_heating_minutes`. Default: `60.0`. Allowed: 15–60. Units: min. Existing active-control guard applies where relevant.

Developer comparison only: minutes, up to 60, for the old advisory model. Never changes actual cloud reads.

### Preview: longest check interval while stable

Stored key: `adaptive_poll_stable_minutes`. Default: `90.0`. Allowed: 30–90. Units: min. Existing active-control guard applies where relevant.

Developer comparison only: minutes, up to 90, for the old advisory model. Never changes actual cloud reads.

### Legacy OFF / 45 / 70 command tests completed

Stored key: `controller_three_state_qualified`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Legacy record kept for existing installations. Has no effect: commands require the four-state (OFF/45/62/70) qualification. Changing it never authorises heater operation.

### Weekend daylight qualification

Stored key: `weekend_qualify_minutes`. Default: `15.0`. Allowed: 5–60. Units: min. Existing active-control guard applies where relevant.

Not used since 0.17.0: one fresh PV report opens the weekend window. Kept so saved settings and a rollback are unchanged.

### Weekend late-day PV threshold

Stored key: `weekend_sunset_kw`. Default: `0.2`. Allowed: 0–1. Units: kW. Existing active-control guard applies where relevant.

Not used since 0.17.0: low late-day PV no longer ends the weekend window early. Kept so saved settings and a rollback are unchanged.

### Weekend low-PV ending delay

Stored key: `weekend_sunset_minutes`. Default: `30.0`. Allowed: 10–120. Units: min. Existing active-control guard applies where relevant.

Not used since 0.17.0: low late-day PV no longer ends the weekend window early. Kept so saved settings and a rollback are unchanged.

<a id="commissioning"></a>
## Commissioning and safeguards

Advanced; do not tick qualifications to bypass a warning. Follow separately approved supervised commissioning. Saving this form neither authorises physical tests nor turns on automatic control. Leave command address/CT record blank if not commissioned.

### CT-free solar commissioning record

Stored key: `ct_free_solar_verification`. Default: ``. Allowed: as described. Units: none. Turn Automatic off before changing.

Written for you by Solar & Meters → Set up experimental CT-free solar; use that page rather than typing here. Clear this field to withdraw CT-free solar. Format, for reference: grid entity|W or kW|import_positive or export_positive|rated kW, matching this installation. Grid-only decisions do not prove element operation; a configured CT fault cannot fall back to this record.

### Bridge command address (MQTT topic)

Stored key: `controller_command_topic`. Default: ``. Allowed: as described. Units: none. Turn Automatic off before changing.

Commissioning only. Copy the exact mode-command topic announced by your existing bridge. Blank prevents controller commands. Do not guess it or point at another appliance; keep automatic control off while changing it.

### OFF / 45 / 62 / 70 command tests completed

Stored key: `controller_four_state_qualified`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Commissioning only, default off. Set only after separately approved supervised testing of every required transition and refusal case. This record does not itself authorise automatic control or physical operation.

### Hot-water meter commissioning record

Stored key: `heater_meter_verification`. Default: ``. Allowed: as described. Units: none. Turn Automatic off before changing.

Expert commissioning record: verified_entity_id|W or verified_entity_id|kW. Requires an exclusive circuit, correct signed units, reporting cadence and OFF/ON/outage tests. Leave blank for CT-free operation. A saved record is not proof the meter is currently available; remapping clears it.

### Use qualified heating-performance learning

Stored key: `learned_planning_enabled`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Advanced, default off. Requires real independent measured sessions, held-out accuracy and hardware qualification. A conservative learned rate may start required heating earlier; it cannot delay heating beyond nominal/live-power planning. Learning cannot establish whole-tank temperature.

### Meter and heater checked for learning

Stored key: `learning_hardware_qualified`. Default: `False`. Allowed: On / Off. Units: none. Turn Automatic off before changing.

Commissioning gate, default off. Confirm only using real qualified measurements, never synthetic tests. Changing the power mapping, its commissioned units, tank capacity or element rating clears this gate.

### Optional command budget per 24 hours

Stored key: `controller_max_commands_per_day`. Default: `6.0`. Allowed: 4–10. Units: none. Turn Automatic off before changing.

Whole commands in a rolling 24 hours; 6 is the existing starting value. Optional solar starts stop at this budget. Essential transitions have the existing extra allowance, and OFF is not blocked by this optional budget. This is not a new permission to issue commands.

### Cloud request budget per 24 hours

Stored key: `controller_max_requests_per_day`. Default: `220.0`. Allowed: 160–400. Units: none. Turn Automatic off before changing.

Whole locally accounted HTTP attempts in a rolling 24 hours; 220 is the existing starting value. Commands are refused when this safety budget is exhausted. Polling, authentication and confirmation all cost requests; this setting does not bypass bridge limits.

### Time allowed to confirm a command

Stored key: `controller_confirmation_timeout_minutes`. Default: `65.0`. Allowed: 35–120. Units: min. Turn Automatic off before changing.

Minutes before an unconfirmed command fault-locks automatic control; 65 is the existing starting value. Allow at least a normal poll interval plus margin. A timeout does not prove that a command failed or safely permit a blind retry.

### Phone notification service

Stored key: `controller_notify_service`. Default: ``. Allowed: as described. Units: none. Existing active-control guard applies where relevant.

Optional Home Assistant notify service name, for example mobile_app_jacobs_phone, without notify. in front. Blank keeps Home Assistant's persistent notifications only. Choose an existing notification service; saving this field sends no message.

## Sensor mappings

Bridge sources are in Advanced/System → Bridge status readings; other sources
are in Solar & Meters → Solar and meter readings. Map actual existing entities.

### Heater temperature and target

Mapping key: `heater`. Select the existing Thermann bridge water-heater entity. Reads its temperature attributes only; selecting it sends no command. Cloud status does not prove physical element ON/OFF.

### Heater's reported operating mode

Mapping key: `mode`. Select the bridge's vendor-mode sensor, which distinguishes Manual, OFF and other native modes. Required for owner-change protection and exact-prior checks; do not substitute an inferred power status.

### Last successful cloud check

Mapping key: `last_poll`. Select the bridge's last-successful-poll timestamp sensor. It must describe a real successful observation, not a template's update time. An old observation cannot be treated as fresh.

### Bridge cloud connection status

Mapping key: `cloud_health`. Select the existing bridge cloud-health sensor. Faults and outages conservatively restrict control; choosing a different label cannot clear a real fault.

### Bridge's total cloud request attempts

Mapping key: `requests`. Select the bridge local-lifetime request-attempt sensor, including persistent/complete accounting attributes. Used by request budgets; not a manually reset daily counter.

### Net power bought from or sent to the grid

Mapping key: `grid`. Optional signed W or kW net grid sensor. Verify its positive direction below. Buying and exporting must have opposite signs; an unsigned consumption sensor is unsuitable. Basic tariff operation can run without it.

### Solar panel production

Mapping key: `pv`. Optional solar-production W/kW sensor, for display and forecast correction. Panel/DC production is not evidence of usable AC surplus and cannot verify the heater element.

### Whole-house electricity use

Mapping key: `house`. Optional household W/kW consumption sensor, for display. This does not replace net grid power or the dedicated hot-water circuit meter.

### Total electricity bought from the grid

Mapping key: `import_energy`. Optional cumulative kWh import sensor retained for reference. It does not authorise heater commands or prove current circuit power.

### Total electricity sent to the grid

Mapping key: `export_energy`. Optional cumulative kWh export sensor retained for reference. It does not prove current solar surplus.

### Forecast solar production

Mapping key: `forecast_pv`. Optional EMHASS solar-forecast series, or supported buffered Forecast.Solar watts, with its original forecast_generated_at timestamp. Predicts future production, not guaranteed spare power. Leave unmapped when forecasts are off.

### Forecast household electricity use

Mapping key: `forecast_load`. Optional timestamped EMHASS household-load forecast or supported measured baseline. Used with solar forecasts; neither forecast is required for basic tariff heating. Stale forecasts are ignored.

### Inverter's usable AC output

Mapping key: `pv_ac`. Optional W/kW AC-output sensor, consistent with the grid meter. Existing unmapped installations retain the legacy GoodWe total-power fallback; map your actual inverter for other equipment. Do not substitute panel/DC power.

### Dedicated hot-water circuit power (optional)

Mapping key: `heater_power`. Optional raw signed W/kW active-power entity for the exclusive heater circuit, from any validated meter. Do not use sensor.em_hot_water_power or a dashboard template. Leave unmapped before the CT is installed. Required storage still works; optional solar-only boost needs commissioning. A failed commissioned meter is a fault, not measured zero.

### Dedicated hot-water circuit energy (optional)

Mapping key: `heater_energy`. Optional raw cumulative import-energy Wh/kWh entity for the same circuit. Keep the power sign unchanged; energy must be validated cumulative import. This improves measurements and does not control a relay.

## Retired settings

Retained for upgrade/rollback compatibility; they do not add competing control policies.

- `morning_threshold_c` — Morning minimum (hard): Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Minimum reading (bottom-of-tank T_Avg) by the hard morning deadline, every day. Protected over savings when at risk. A planning threshold, NEVER a heater setpoint or hygiene temperature.
- `morning_preferred_c` — Morning preferred reserve: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Preferred reading by the preferred morning time, every day: extra reserve before showers, aimed for when reasonably achievable. Once that time passes unmet, only the hard minimum is pursued. Not lower than the minimum.
- `morning_preferred_time` — Morning ready (preferred): Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Hobart local, every day. Aim to reach the morning threshold by this time.
- `morning_hard_time` — Morning ready (hard deadline): Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Hobart local, every day (showers). If the preferred time is missed, heating continues for this deadline; it is never abandoned. Must not be earlier than the preferred time.
- `morning_time` — Legacy: weekend morning time: Not used by automatic control since 0.7.0 (see the two morning ready times). Kept so saved settings are unchanged; only the legacy shadow display uses it.
- `shower_time_enabled` — Legacy: earlier weekday shower time: Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.
- `shower_time` — Legacy: weekday shower-ready time: Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.
- `expected_morning_draw_c` — Expected morning hot-water use: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Reading drop assumed for morning showers when planning the afternoon target. An assumption (about 11 °C was seen on 11 Nov), not a measurement.
- `standing_loss_c_per_hour` — Assumed standing heat loss: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Reading drop per hour with no use or heating. Not yet measured for this tank.
- `target_c` — Afternoon storage target: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Selected model target is never silently reduced. 65–70°C is a planning range, not a newly qualified command limit.
- `evening_time` — Weekend afternoon ready time: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Weekend (no-peak) afternoon ready time, Hobart local, after noon. Weekdays use the evening peak start automatically: 16:00 standard time, 17:00 daylight time.
- `margin_minutes` — Heating time allowance: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Extra full-power model minutes when heat is required. Uncalibrated; comfort overrides optional dwell.
- `min_solar_kw` — Minimum useful net surplus: Partial solar can be worthwhile. Economic comparison must also pass; never a variable-power command.
- `export_headroom_kw` — Solar headroom: Deduct from measured surplus for uncertain household loads.
- `solar_hold_minutes` — Solar start qualification: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. How long the planner's choice between optional economic options (heat now, wait, no difference) must persist before it changes, so a passing cloud does not flip the plan. Comfort, data gates and peak decisions are never delayed by it.
- `solar_loss_minutes` — Economic loss grace period: Sustained cost disadvantage before a SIMULATED optional stop; short clouds do not stop a cycle.
- `minimum_cycle_minutes` — Minimum optional cycle: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest heating block the planner schedules. The controller's own minimum heating and rest periods still apply on top.
- `minimum_gap_minutes` — Minimum optional cycle gap: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest gap the planner leaves between two scheduled heating blocks (it merges closer blocks).
- `switching_benefit_aud` — Minimum economic switching benefit: FUTURE CONTROL ONLY: minimum benefit per heater switch. The 0.4.0 advisor uses the per-kWh waiting threshold instead.
- `wait_benefit_aud_per_kwh` — Minimum saving to recommend waiting: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Waiting is only recommended if it saves at least this much per kWh that would otherwise be heated now (first minimum cycle; 0.05 = 7.5 c for 30 min) and the comfort fallback stays viable. Solar later vs off-peak grid now is 7.7 c/kWh.
- `paused` — Pause shadow planning: Pauses only hypothetical decisions; native Schedule continues.
- `base_load_source` — Household load basis: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. measured_only: de-embedded measured base load (heater removed). measured_then_published also uses the published load forecast after 2 h; today's EMHASS load includes heater cycles.
- `solar_window_minutes` — Recent-export scenario horizon: Bounded assumption for current export, never a daily forecast or guaranteed solar.
- `expected_native_target_c` — Expected native target: Reference only. Different observed mode/target latches intervention; never sets the heater.
- `native_schedule_clock` — Native schedule clock reference: Reference only; never adjusts the device clock or native Schedule.
- `native_schedule_clock_verified` — Native clock checked: Owner observation only; restore preserves this verification.
- `t_comfort_reference_c` — T-Comfort reference: Reference only; 10°C is not a useful comfort reserve. Never changes T-Comfort.
- `native_clock_check_date` — Native clock check date: Owner check date YYYY-MM-DD, blank if unknown; reference only.
- `native_schedule_periods` — Native schedule reference: Reported approximate times in JSON, for comparison only; NEVER changes the heater programme.
- `controller_bridge_qualified` — Bridge commands qualified (T3): Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Commissioning Stage B: ON only after the supervised T3 test showed the bridge's Manual:70 (from OFF) and off (from Manual 70) reproduce the app results. Requires Thermowatt add-on 1.3.9 or later.
- `controller_min_heating_minutes` — Minimum heating period: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest time Manual (heating permitted) is kept before parking, unless the thermostat has already stopped the element.
- `controller_min_rest_minutes` — Minimum rest period: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest time parked before heating is permitted again, comfort starts included. At most the execution latency reserve plus 30 minutes, so a comfort start is never delayed beyond what the planner reserves.
- `controller_execution_latency_minutes` — Execution latency reserve: Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Comfort deadlines are planned this much earlier, and the pre-peak park is brought forward by it. With bridge 1.3.10 a command normally reaches the heater within about a minute; the 30-minute default is a conservative margin you may reduce after the supervised trial.

## Practical starting choices

Use the household's verified contract and appliance settings. Jacob retains45/62/70,
fixedAEST, verified Aurora periods and export-positive GoodWe; these are examples,
not universal defaults. Weekend500W/15min, sunset200W/30min, end18:00 and cooldown10min
are editable starting preferences. Minimum15-minute ordinary command spacing remains.
Keep physical qualifications truthful; new polling modes and experimental CT-free
permission are explicit choices. Do not change token/lockout state to clear a warning.
