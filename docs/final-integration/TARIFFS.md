# Household time and electricity plans

Public distribution is deferred. This is practical configuration for the
combined development candidate, not a retailer recommendation or a promise of
bill savings. Use the actual **retail contract** and verify its periods, rates,
clock, meter requirements and conditions before marking the tariff verified.

## One tariff model

The controller has one time-window model used by required heating, optional
solar economics and its deadline/peak guards. All public options are configured
in Home Assistant; supported common changes do not require Python edits.

| Setting | Behaviour |
|---|---|
| Household time zone | Select an IANA zone; a fresh entry starts from HA's configured zone |
| Tariff clock | `local` follows that zone including daylight saving; `standard` removes its daylight-saving offset and stays on its fixed standard clock |
| Flat plan | One import rate, no invented peak. The off-peak rate field is the flat energy rate |
| Custom TOU | Editable full-week JSON rows, with peak/off-peak/shoulder and optional per-row rates |
| Legacy Aurora example | The existing editable two-peak example; not a new-user default or universally verified tariff |
| Seasonal rows | Optional calendar-month lists; every month and weekday must have exactly one matching row at every minute |
| Weekday storage window | Local start, ready time and return to baseline; used when there is no afternoon peak on that day |

For a flat/no-afternoon-peak weekday, the normal target is still required. The
default local service window starts at 09:00, aims to finish at 16:00 minus the
configured completion margin, and returns to the baseline at 21:00. It creates
no artificial electrical peak or mandatory OFF. Weekends retain baseline plus
qualified optional solar. With an afternoon TOU peak, the existing real boundary
and completion buffer apply. Never-peak policy still overrides a cheap/free rate
if the user classifies that period as peak.

New installations choose their own sources and start unverified, with a flat
placeholder rate of zero, forecasts/optional boost disabled and an initial
62°C baseline/normal selection awaiting appliance/compliance verification. Zero
is an unset placeholder until the contract is verified, not an assertion of free
electricity. Historical entries preserve their saved values and previous
Hobart/Aurora effective configuration. The owner's 45/62/70 example is unchanged.

Basic tariff operation needs no solar, inverter, grid CT or EMHASS. Missing
forecasts remain a notified outage only when the feature is configured. Known
future retail prices still inform scheduling; missing solar forecasts never
invent future generation. Every automatic command still needs commissioning,
healthy authentication, a fresh exact prior, persisted intent, budgets and
observed cloud confirmation. CT-free physical element state remains unknown.

## Editable windows

This synthetic example has expensive weekday evenings, a low-cost midday
window, different weekend prices and complete coverage. Prices are **examples**
in AUD/kWh, not current offers. `days` uses 0=Monday to 6=Sunday.

```json
[
  {"days":[0,1,2,3,4],"start":"00:00","end":"10:00","kind":"off_peak","rate":0.25},
  {"days":[0,1,2,3,4],"start":"10:00","end":"15:00","kind":"shoulder","rate":0.08},
  {"days":[0,1,2,3,4],"start":"15:00","end":"21:00","kind":"peak","rate":0.40},
  {"days":[0,1,2,3,4],"start":"21:00","end":"00:00","kind":"off_peak","rate":0.25},
  {"days":[5,6],"start":"00:00","end":"00:00","kind":"off_peak","rate":0.22}
]
```

Omitting `rate` uses the corresponding peak/off-peak/shoulder setting. Multiple
windows may share a kind with different rates; costing uses each future slot's
price, not today's price repeated into tomorrow. Equal start/end covers a full
day; an overnight row belongs to its start weekday. Seasonal rows add, for
example, `"months":[1,2,3,10,11,12]`; provide complementary months for the rest
of the year. The current tariff-clock month selects the season at midnight,
including overnight tails. Gaps, overlaps and malformed periods are rejected
atomically. DST skips/repeated hours follow the chosen clock and IANA zone.

## Australian tariff distinctions, researched 2026-11-15

Flat, TOU and demand-based pricing are different retail structures; controlled
load can require separate metering/wiring and supply restrictions. A controller
cannot assume a general-purpose heater receives a controlled-load price.
[Australian Government pricing guide](https://www.energy.gov.au/solar/financial-benefits-solar/electricity-pricing-plans-and-tariffs),
[Energy Made Easy controlled-load guide](https://www.energymadeeasy.gov.au/hot-topics/understanding-controlled-loads).

Network tariffs charge the retailer for network use. The retailer decides its
customer offers, which can differ from the underlying network structure. Enter
the contract's retail marginal usage prices, not a network schedule copied from
a distributor website.
[Ergon network tariff explanation](https://www.ergon.com.au/network/manage-your-energy/tariffs/residential-tariffs).

Midday “solar sponge” pricing can reward shifting consumption even without
household solar. The network's example window does not prove a customer's retail
eligibility, price or clock. Retail offers can also have seasonal periods and
time-varying export rates.
[SA Power Networks explanation](https://www.sapowernetworks.com.au/data/322742/how-to-get-the-most-out-of-your-solar-energy-system/),
[EnergyAustralia rate-structure explanation](https://www.energyaustralia.com.au/home/help-and-support/faqs/rate-changes).

Some free-hour offers require a smart meter and have fair-use conditions. A zero
per-kWh row models an unconditional marginal price only; it does not implement
an offer's caps or eligibility rules.
[OVO Free 4 conditions](https://pages.ovoenergy.com.au/the-free-4-plan),
[OVO fair-use policy](https://www.ovoenergy.com.au/terms/fair-use).

## Deliberately unsupported billing structures

| Structure | Safe extension point / missing evidence |
|---|---|
| Conditional free-energy allowance | Requires household interval consumption, remaining allowance, eligibility and reset rules before a marginal price can be trusted |
| Block/tier usage rates | Requires accumulated billing-period consumption and verified tier/reset boundaries |
| Controlled load / supply interruption | Requires actual circuit/meter assignment and available-supply evidence; software cannot switch network supply |
| Time-varying feed-in rates | Needs a timestamped export-price schedule and validated forecasting coverage; current opportunity cost is the configured constant rate |
| Demand charges | Requires aligned demand intervals, running monthly maxima/ratchets and a household-wide counterfactual; a per-kWh approximation is not accurate |
| Wholesale/negative-price live products | No live price feed or contract-fee model is integrated; do not claim bill optimisation for them |

Future support should extend the same tariff quote with a basis, validity,
required history and uncertainty, rather than adding a competing heater planner.
Until implemented and tested, these products need a separately verified simple
compatible usage-rate interpretation or must remain unsupported. Fixed supply
charges can be displayed in household reporting but are not avoided by moving
a heating cycle.

## Temperature compliance

The exact-prior protocol remains closed to OFF / Manual45 / Manual62 / Manual70.
Supported role selectors require baseline ≤ normal ≤ boost. Arbitrary 60/65°C
commands are not exposed; no new physical evidence qualifies them in this work.
Selecting a value in the UI does not qualify the heater or prove the water
reached it. The owner's 45°C example is not a universal safe/compliant storage
recommendation. Follow the appliance instructions and applicable plumbing/storage
and delivery-temperature requirements, with qualified advice for the actual
installation. Native protective cycles remain independent and untouched.
