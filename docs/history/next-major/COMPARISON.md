# Reproducible polling comparison

[Interpretation, limitations and validation](EVIDENCE.md). Every row is seven
synthetic days through the actual production policy, controller, bridge worker,
HTTP accounting and mocked MQTT/cloud. All strategies share weather/draw events
and initial tank conditions. Amounts are marginal heater grid cost plus forgone
export payment, adjusted to equal terminal stored energy; not a household bill.

## Summer

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 723 | 24 | 7.0021 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 389 | 23 | 7.6195 | 1 | 60.7 | 45.0 |
| No CT | smart | 231 | 24 | 7.0021 | 1 | 479.7 | 15.0 |
| No CT | minimum | 208 | 24 | 7.0021 | 1 | 718.7 | 105.0 |
| CT | fixed_30 | 738 | 30 | 6.5770 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 405 | 28 | 7.1123 | 0 | 60.7 | 45.0 |
| CT | smart | 272 | 30 | 6.6044 | 0 | 479.7 | 15.0 |
| CT | minimum | 252 | 30 | 6.6044 | 0 | 718.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 12 | 24 | 24 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 13 | 23 | 23 | 169 | 1 | 0 |
| No CT / smart | 155 | 3 | 24 | 24 | 24 | 1 | 0 |
| No CT / minimum | 132 | 3 | 24 | 24 | 24 | 1 | 0 |
| CT / fixed_30 | 327 | 15 | 30 | 30 | 335 | 1 | 0 |
| CT / fixed_60 | 160 | 16 | 28 | 28 | 172 | 1 | 0 |
| CT / smart | 175 | 6 | 30 | 30 | 30 | 1 | 0 |
| CT / minimum | 152 | 9 | 30 | 30 | 30 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Winter

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 723 | 24 | 7.3115 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 389 | 23 | 8.5087 | 1 | 60.7 | 45.0 |
| No CT | smart | 230 | 24 | 7.3115 | 1 | 479.7 | 15.0 |
| No CT | minimum | 207 | 24 | 7.3115 | 1 | 718.7 | 105.0 |
| CT | fixed_30 | 743 | 32 | 6.8953 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 410 | 30 | 8.0905 | 0 | 60.7 | 45.0 |
| CT | smart | 275 | 32 | 7.0215 | 0 | 479.7 | 15.0 |
| CT | minimum | 252 | 32 | 7.0215 | 0 | 718.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 327 | 12 | 24 | 24 | 335 | 1 | 0 |
| No CT / fixed_60 | 160 | 13 | 23 | 23 | 169 | 1 | 0 |
| No CT / smart | 154 | 3 | 24 | 24 | 24 | 1 | 0 |
| No CT / minimum | 131 | 3 | 24 | 24 | 24 | 1 | 0 |
| CT / fixed_30 | 326 | 17 | 32 | 32 | 335 | 1 | 0 |
| CT / fixed_60 | 159 | 18 | 30 | 30 | 172 | 1 | 0 |
| CT / smart | 166 | 12 | 32 | 32 | 32 | 1 | 0 |
| CT / minimum | 143 | 12 | 32 | 32 | 32 | 1 | 0 |

Full JSON includes grid/solar energy, opportunity cost, terminal replenishment,
peak exposure attribution, served/unserved draw, daily targets/shortfalls, stale
planning minutes, prediction errors, command/decision history and failure events.

## Dst And Failures

| Circuit meter | Strategy | All HTTP | Commands | Equal-end cost AUD | Missed weekday targets | Worst healthy age min | Owner change min |
|---|---|---:|---:|---:|---:|---:|---:|
| No CT | fixed_30 | 628 | 22 | 6.5674 | 1 | 29.7 | 15.0 |
| No CT | fixed_60 | 339 | 21 | 7.4589 | 1 | 60.7 | 45.0 |
| No CT | smart | 214 | 22 | 6.5674 | 1 | 479.7 | 15.0 |
| No CT | minimum | 193 | 22 | 6.5674 | 1 | 658.7 | 105.0 |
| CT | fixed_30 | 646 | 29 | 6.0142 | 0 | 29.7 | 15.0 |
| CT | fixed_60 | 358 | 27 | 6.7985 | 0 | 60.7 | 45.0 |
| CT | smart | 256 | 29 | 6.0665 | 0 | 479.7 | 15.0 |
| CT | minimum | 236 | 29 | 6.0665 | 0 | 646.7 | 105.0 |

### Actual HTTP categories

| Meter / strategy | Status GET | Command prior GET | Confirm GET | Command POST | Refresh POST | Login POST | Discovery GET |
|---|---:|---:|---:|---:|---:|---:|---:|
| No CT / fixed_30 | 281 | 11 | 22 | 22 | 291 | 1 | 0 |
| No CT / fixed_60 | 137 | 12 | 21 | 21 | 147 | 1 | 0 |
| No CT / smart | 144 | 2 | 22 | 22 | 23 | 1 | 0 |
| No CT / minimum | 123 | 2 | 22 | 22 | 23 | 1 | 0 |
| CT / fixed_30 | 280 | 16 | 29 | 29 | 291 | 1 | 0 |
| CT / fixed_60 | 136 | 17 | 27 | 27 | 150 | 1 | 0 |
| CT / smart | 157 | 11 | 29 | 29 | 29 | 1 | 0 |
| CT / minimum | 140 | 8 | 29 | 29 | 29 | 1 | 0 |

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
