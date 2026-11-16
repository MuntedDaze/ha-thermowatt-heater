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
| No CT | smart | 234 | 22 | 6.4149 | 1 | 479.7 | 15.0 |
| No CT | minimum | 210 | 22 | 6.4149 | 1 | 568.7 | 105.0 |
| CT | fixed_30 | 734 | 28 | 5.8742 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 401 | 26 | 6.4315 | 0 | 60.7 | 45.0 |
| CT | smart | 274 | 28 | 5.9021 | 0 | 479.7 | 15.0 |
| CT | minimum | 253 | 28 | 5.9021 | 0 | 568.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 10 | 22 | 22 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 12 | 21 | 21 | 169 | 1 | 0 |
| No CT / smart | 165 | 1 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 141 | 1 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 327 | 15 | 28 | 28 | 335 | 1 | 0 |
| CT / fixed_60 | 160 | 16 | 26 | 26 | 172 | 1 | 0 |
| CT / smart | 182 | 6 | 28 | 28 | 29 | 1 | 0 |
| CT / minimum | 158 | 9 | 28 | 28 | 29 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Winter

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 718 | 22 | 6.7184 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 386 | 21 | 7.9300 | 1 | 60.7 | 45.0 |
| No CT | smart | 234 | 22 | 6.7177 | 1 | 479.7 | 15.0 |
| No CT | minimum | 211 | 22 | 6.7177 | 1 | 568.7 | 105.0 |
| CT | fixed_30 | 743 | 31 | 6.1966 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 404 | 26 | 7.3409 | 0 | 59.7 | 45.0 |
| CT | smart | 284 | 31 | 6.3242 | 0 | 479.7 | 15.0 |
| CT | minimum | 261 | 31 | 6.3242 | 0 | 568.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 11 | 22 | 22 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 13 | 21 | 21 | 170 | 1 | 0 |
| No CT / smart | 164 | 2 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 141 | 2 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 326 | 19 | 31 | 31 | 335 | 1 | 0 |
| CT / fixed_60 | 160 | 18 | 26 | 26 | 173 | 1 | 0 |
| CT / smart | 176 | 13 | 31 | 31 | 32 | 1 | 0 |
| CT / minimum | 153 | 13 | 31 | 31 | 32 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Dst And Failures

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 628 | 22 | 6.5217 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 339 | 21 | 7.4589 | 1 | 60.7 | 45.0 |
| No CT | smart | 223 | 22 | 6.5217 | 1 | 479.7 | 15.0 |
| No CT | minimum | 202 | 22 | 6.5217 | 1 | 568.7 | 105.0 |
| CT | fixed_30 | 647 | 29 | 5.9980 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 359 | 27 | 6.8070 | 0 | 60.7 | 45.0 |
| CT | smart | 264 | 29 | 6.0503 | 0 | 479.7 | 15.0 |
| CT | minimum | 244 | 29 | 6.0503 | 0 | 568.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 282 | 10 | 22 | 22 | 291 | 1 | 0 |
| No CT / fixed_60 | 137 | 12 | 21 | 21 | 147 | 1 | 0 |
| No CT / smart | 154 | 1 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 133 | 1 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 280 | 17 | 29 | 29 | 291 | 1 | 0 |
| CT / fixed_60 | 136 | 18 | 27 | 27 | 150 | 1 | 0 |
| CT / smart | 165 | 11 | 29 | 29 | 29 | 1 | 0 |
| CT / minimum | 148 | 8 | 29 | 29 | 29 | 1 | 0 |

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
| No CT | smart | 532 | 161 | 161 | 22 |
| No CT | minimum | 460 | 137 | 137 | 22 |
| CT | fixed_30 | 734 | 0 | 335 | 28 |
| CT | fixed_60 | 401 | 0 | 172 | 26 |
| CT | smart | 571 | 162 | 165 | 28 |
| CT | minimum | 502 | 138 | 141 | 28 |
