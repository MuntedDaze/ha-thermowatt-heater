# How the controller decides (0.9.0)

Technical reference for the current behaviour. The design and its reasoning
are in [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md); the user guide is
[README.md](README.md). Earlier references are under `docs/history/controller/`.

## One policy, three heater states

`simple_policy.py` is the only decision engine. Every minute, and on each new
bridge status, it chooses one of:

| State | Heater setting | Bridge payload (from → to) |
| --- | --- | --- |
| OFF | Thermann software OFF | `off@45`, `off@70` |
| BASELINE | Manual 45 °C | `Manual:45@off`, `Manual:45@70` |
| STORAGE | Manual 70 °C | `Manual:70@off`, `Manual:70@45` |

Thermann's thermostat decides when the element runs (on at about 8 °C below
the setpoint). Manual 70 °C is the *requested setpoint*; a reading of 63–69 °C
is "within the thermostat band", not "70 reached".

## Inputs (all local; no cloud request)

- **Thermann reading** and its poll time (up to 75 minutes old). A stale
  reading is assumed cold (37 °C).
- **GoodWe grid power**, signed by the owner's verified convention, every
  minute. Available surplus = export, plus 3 kW while the element estimate says
  it is on. If the meter direction is not verified, no measured solar is used.
- **EMHASS** PV and household-load forecasts, as net-export slots (with the
  configured uncertainty margins).
- **Tariff calendar** (Aurora 93, fixed AEST), feed-in rate.

## The rules (precedence highest first)

1. The heater's own protections are native, in every state; nothing to decide.
2. **Owner:** an app change or Hold (send nothing), holiday (OFF), 12hr
   Override (STORAGE).
3. **Guards** (may only block): cloud, authentication and freshness;
   15-minute command spacing; the reserved park slot.
4. **Peaks**, morning and evening alike, plus the 2 minutes before:
   - OFF, unless measured surplus of at least 3.3 kW held for 10 minutes;
   - withdraw after 5 minutes of import above 0.2 kW, or of surplus below
     the element (also while the element is off).
5. **Weekday before the evening peak:** reach 70 °C by the **soft target**
   (peak − 30 min) in the cheapest window, then keep heating until the peak.
   On weekday nights and weekends: Manual 45, plus solar STORAGE when it is
   worth it.
6. **Forecast economics:**
   - wait for a cheaper window, as long as it is feasible;
   - pause committed heating only for a later window that saves at least
     $0.30 and still finishes in time.

## The controller (safety shell)

`controller.py` never chooses a state. It sends one guarded payload when:

- the policy wants a different state;
- every gate passes:
  - commissioning: topic, three-state qualification;
  - MQTT;
  - the bridge: available, commands enabled, `automation` policy, cloud
    `ok`, authorised, no backoff, 1.3.13 transitions, no pending
    confirmation;
  - a status no older than 35 minutes, and the pre-command refresh budget;
  - the observed state equals the confirmed one;
  - 15-minute spacing;
  - the daily backstops: 6 commands that start or change heating (a park is
    never held back), and 220 requests.

It then supervises the confirmation:

- The bridge's outcome decides it, or the observed status does.
- An owner change (`refused_*_mismatch`, or an unexpected state) pauses control.
- `not_confirmed_within_limit` or a refusal locks it, for the owner to
  acknowledge.
- Nothing is ever re-sent.

After a restart, it re-inspects the heater from a NEW status first.

## Shadow observation

With automatic control off, the same policy runs on the observed heater state
and records the payload it would send (`policy_plan.shadow_log`, the *Shadow
command* sensor). Nothing is published.
