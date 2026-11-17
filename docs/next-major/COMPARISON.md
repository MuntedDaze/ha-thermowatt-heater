# Reproducible polling comparison

[Interpretation, limitations and validation](EVIDENCE.md). Every row is seven
synthetic days through the actual production policy, controller, bridge worker,
HTTP accounting and mocked MQTT/cloud. All strategies share weather/draw events
and initial tank conditions. Amounts are marginal heater grid cost plus forgone
export payment, adjusted to equal terminal stored energy; not a household bill.

## Summer

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 717 | 22 | 6.4154 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 384 | 21 | 7.0578 | 1 | 60.7 | 45.0 |
| No CT | smart | 214 | 22 | 6.4149 | 1 | 479.7 | 15.0 |
| No CT | minimum | 188 | 22 | 6.4149 | 1 | 718.7 | 105.0 |
| CT | fixed_30 | 734 | 28 | 5.8742 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 401 | 26 | 6.4315 | 0 | 60.7 | 45.0 |
| CT | smart | 254 | 28 | 5.9021 | 0 | 479.7 | 15.0 |
| CT | minimum | 231 | 28 | 5.9021 | 0 | 718.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 10 | 22 | 22 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 12 | 21 | 21 | 169 | 1 | 0 |
| No CT / smart | 145 | 1 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 119 | 1 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 327 | 15 | 28 | 28 | 335 | 1 | 0 |
| CT / fixed_60 | 160 | 16 | 26 | 26 | 172 | 1 | 0 |
| CT / smart | 162 | 6 | 28 | 28 | 29 | 1 | 0 |
| CT / minimum | 136 | 9 | 28 | 28 | 29 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Winter

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 718 | 22 | 6.7184 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 386 | 21 | 7.9300 | 1 | 60.7 | 45.0 |
| No CT | smart | 213 | 22 | 6.7177 | 1 | 479.7 | 15.0 |
| No CT | minimum | 188 | 22 | 6.7177 | 1 | 575.7 | 105.0 |
| CT | fixed_30 | 743 | 31 | 6.1966 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 404 | 26 | 7.3409 | 0 | 59.7 | 45.0 |
| CT | smart | 263 | 31 | 6.3242 | 0 | 479.7 | 15.0 |
| CT | minimum | 238 | 31 | 6.3242 | 0 | 575.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 11 | 22 | 22 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 13 | 21 | 21 | 170 | 1 | 0 |
| No CT / smart | 143 | 2 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 118 | 2 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 326 | 19 | 31 | 31 | 335 | 1 | 0 |
| CT / fixed_60 | 160 | 18 | 26 | 26 | 173 | 1 | 0 |
| CT / smart | 155 | 13 | 31 | 31 | 32 | 1 | 0 |
| CT / minimum | 130 | 13 | 31 | 31 | 32 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Dst And Failures

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 628 | 22 | 6.5217 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 339 | 21 | 7.4589 | 1 | 60.7 | 45.0 |
| No CT | smart | 212 | 22 | 6.5217 | 1 | 479.7 | 15.0 |
| No CT | minimum | 189 | 22 | 6.5217 | 1 | 658.7 | 105.0 |
| CT | fixed_30 | 647 | 29 | 5.9980 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 359 | 27 | 6.8070 | 0 | 60.7 | 45.0 |
| CT | smart | 254 | 29 | 6.0503 | 0 | 479.7 | 15.0 |
| CT | minimum | 232 | 29 | 6.0503 | 0 | 646.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 282 | 10 | 22 | 22 | 291 | 1 | 0 |
| No CT / fixed_60 | 137 | 12 | 21 | 21 | 147 | 1 | 0 |
| No CT / smart | 143 | 1 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 120 | 1 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 280 | 17 | 29 | 29 | 291 | 1 | 0 |
| CT / fixed_60 | 136 | 18 | 27 | 27 | 150 | 1 | 0 |
| CT / smart | 155 | 11 | 29 | 29 | 29 | 1 | 0 |
| CT / minimum | 136 | 8 | 29 | 29 | 29 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Synthetic20-minute session sensitivity

This TTL is an explicit model assumption, not vendor evidence. The same inputs
and real authentication/retry paths are used. Additional401 GETs are counted.

| Meter | Strategy | All HTTP | Expired status401 | Refresh POST | Commands |
|---|---|---:|---:|---:|---:|
| No CT | fixed_30 | 717 | 0 | 335 | 22 |
| No CT | fixed_60 | 384 | 0 | 169 | 21 |
| No CT | smart | 472 | 141 | 141 | 22 |
| No CT | minimum | 394 | 115 | 115 | 22 |
| CT | fixed_30 | 734 | 0 | 335 | 28 |
| CT | fixed_60 | 401 | 0 | 172 | 26 |
| CT | smart | 511 | 142 | 145 | 28 |
| CT | minimum | 436 | 116 | 119 | 28 |
