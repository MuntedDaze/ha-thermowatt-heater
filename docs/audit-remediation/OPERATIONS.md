# Faults, storage evidence and additional commissioning

These are future observation/commissioning procedures requiring their own
approval. This development has made no live request or heater command.

## Parked OFF: strict lockout versus available hot water

Never-peak policy requests software OFF before each peak. Returning to Manual
requires functioning HA/MQTT/controller, bridge, authentication, internet and
vendor service. If any path fails, software cannot promise to restore heat. A selected Manual baseline cannot heat while software OFF. Native protections and physical/manual
intervention are independent; cloud OFF does not prove zero electrical power.

The new persisted warning uses the **last observed software OFF**, including
unavailable status and restart. When a permitted heating target has been wanted
for 30 minutes without observed restoration, it reports **parked OFF, cannot
restore heat**. It resets for deliberate peak/holiday OFF or owner hold/change,
and clears when a later genuine observation shows a supported Manual state.
It never invents measured element state, sends a fallback POST or relaxes peak,
exact-prior, confirmation, budget, owner or authentication protections.

Pre-boundary observation and existing readiness planning still apply. Extra
solar forecasts cannot guarantee water through a late draw or vendor outage.
The retry ladder remains deliberately unchanged: default60-minute minimum cloud
retry, exponential read backoff and persisted cooldown; authentication locks and
controller faults can require deliberate owner action. This phase does not
approve faster retries or a new generation. The owner must accept this strict
lockout/availability trade-off before unattended operation.

Recovery:

1. Read the phone/persistent warning and controller gate/fault details. Inspect
   last genuine mode/temperature/time, cloud guard and pending result. Unknown
   is not OFF/zero or permission to repeat a command.
2. Disable automatic control. It sends no OFF. Do not clear locks, bump generation,
   restart repeatedly or replay a pending command.
3. If the vendor app works, under the approved manual operating plan choose the
   owner-intended supported Manual target for the current operating plan and verify the resulting state. An intentional
   manual action can heat during peak and costs money; the controller does not
   authorise or perform it automatically. Follow native/manufacturer protections.
4. If internet/vendor control is unavailable, do not assume there is a local
   Manual selector: this project has not verified one, and the manufacturer
   describes changing mode/settings through the app. Use only a separately
   established manufacturer-supported recovery procedure or qualified service.
   Without an available approved path, hot-water restoration cannot be
   guaranteed; arrange alternatives. Never bypass protection, improvise wiring
   or power-cycle repeatedly to force a mode. HA cannot fix a vendor outage.
5. Once cloud/MQTT and actual appliance state are known, follow deliberate lock
   recovery; acknowledge controller faults or resume owner override only after
   inspection. Restart requires a new observation. Retain pending/usage history.
6. Supervise the next permitted heating cycle and both tariff boundaries. Return
   to fixed 30-minute polling/adaptive off until the incident is understood.

## Notification and independent watchdog

Before Never-policy automation, configure the actual owner notify service, send
a manual test through HA Actions, confirm receipt on the phone and record date,
service and delivery. Re-test after phone/service changes. Persistent HA notices
alone are not a tested phone alert. No notification has been sent by this work.

The additive **Controller last evaluated** sensor uses the last real executor
observation time, not the time a dashboard is opened. The optional example
`OWNER_WATCHDOG.yaml.example` checks its age independently of the component's
minute loop. Adapt actual entity/service names and test it separately. It sends
notifications only, never heater/control commands. It helps if the component
stops while HA remains running. Total HA/internet/power failure still requires an
external availability monitor or deliberate owner checks; no HA automation can
send from a dead HA system. Do not promise otherwise.

## Read-only inactivity qualification

**Hard gate for longer adaptive polling; all its enable/qualification flags stay
off until independently accepted evidence passes.** Synthetic sessions establish
no vendor lifetime. Existing20-minute request-driven refresh, session reuse,
cooldowns, retry/lockout and no-POST-replay behaviour are unchanged.

1. First complete the initial seven-day fixed 30-minute polling read-only soak and fixed 30-minute polling
   supervised/automatic qualification. Choose a safe owner-controlled heater
   state; automatic control and bridge commands must be off for inactivity work.
2. Obtain separate approval for read-only vendor observation. Record versions,
   account/guard health without secrets, unchanged generation, polling plan and
   actual request categories. Do not operate a second account client or extra
   app/dashboard refreshes that hide inactivity. Record unavoidable app use.
3. Set fixed 60-minute polling with all adaptive flags off. Observe **at least seven consecutive
   complete days**. Use local HA diagnostics to record each actual operation,
   longest no-request interval, successful subsequent refresh/status, all HTTP
   failures, guard transitions, restarts and owner-change delays. Do not publish
   tokens/raw responses or use sensitive vendor traffic captures.
4. Pass requires **zero refresh rejections, zero auth locks, no hidden keepalive
   or extra reads**, successful observations after real60-minute gaps, and
   accepted service/request/detection outcomes. Ordinary network failures must be
   explained and independently accepted; interrupted/contaminated evidence does
   not qualify the full interval. Never reset a guard/generation to pass.
5. Independent reviewer/owner records the exact duration/evidence and accepts
   up-to60-minute healthy external-change delay, longer under outage and missed
   brief changes. Only then may the separate v2 qualification/enable gates be
   deliberately selected in a separately approved supervised adaptive60 trial.
6. **Repeat the same seven-day read-only test at fixed 90-minute polling** before choosing 90.
   A successful60 test does not qualify90.90 is not the initial recommendation.
7. Restore fixed 30-minute polling before returning to automation. Any rejection/failure blocks
   longer-poll qualification and uses deliberate conservative recovery. Do not
   extend token lifetimes, lower retry safeguards or add keepalives to claim a pass.

Read-only missing passive temperatures and app-delay bounds must be understood.
Existing night tests exercise changes just after a successful read at30/60/90;
command-specific prior/confirmation is never replaced by this qualification.

## Storage-temperature requirements and the owner's strategy

The fixed household requirement remains **Manual 45°C overnight/weekends,
Manual 62°C normal weekday storage, optional economical Manual 70°C boost, and
software OFF during configured peak periods under the existing policy**. The
owner discussed variable-temperature operation with a plumber and deliberately
chose periodic62°C or potentially70°C heating. This remediation does not replace
45 with62, add a temperature permission gate, change saved role defaults or
redesign holiday/thermal control.

Tasmania's [official heated-water guidance](https://buildingstandards.tas.gov.au/topics/technical-regulation/plumbing-standards/heated-water)
publishes a minimum 60°C storage-temperature setting and separate delivery/scald
protection requirements. **This project has not independently established
compliance of the chosen variable-temperature strategy.** The plumber discussion
is owner context, not a compliance assessment performed by the software.
Manufacturer instructions and applicable plumbing requirements remain relevant.

The appliance retains its own thermostat and native protections. The
[manufacturer's guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
(printed p10, PDF page16) describes an antibacterial cycle across modes, including
app OFF, when its conditions apply; it also notes model algorithms can differ.
That behaviour, its timing, whole-tank exposure and adequacy for
this household have not been independently verified on the actual heater. Do not
claim an assumed native cycle makes45°C compliant. Cloud OFF is a software
request, not proof protections are disabled or electrical draw is zero.

A bottom probe, one high report or a commanded62/70 target cannot prove whole-tank
temperature, exposure duration, useful hot-water volume or disinfection. Nominal
planning and CT measurements likewise do not certify hygiene. Retain the guarded
supported setpoint protocol and the owner's strategy; review actual native
behaviour and appliance/plumbing requirements during separately approved physical
commissioning. No new hygiene sensor, reminder-based heating rule, restrictive
gate or automatic post-holiday command has been added for F8.
