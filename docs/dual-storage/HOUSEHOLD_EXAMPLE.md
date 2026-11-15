# Household example, not universal defaults

This is the owner's requested design example. It is not a commissioning record,
a tariff-price recommendation or a claim that the new candidate is installed.
Other users must verify their appliance, local installation requirements, tariff
contract, native protections and temperature strategy independently.

| Component / choice | Example |
|---|---|
| Appliance / planning model | Thermann Smart Electric 315 L; 3 kW resistive element |
| Solar / meter | GoodWe GW5000-DNS-30, 6.6 kW PV, HK1000 grid meter |
| Forecasts | EMHASS PV plus household load, with genuine generation timestamps |
| Tariff | Aurora Tariff 93 example; fixed AEST (UTC+10), not Hobart daylight time |
| Weekday peak | 07:00–10:00 and 16:00–21:00 AEST |
| Weekend | All off-peak |
| Baseline / normal / optional solar | Manual 45°C / Manual 62°C / Manual 70°C |
| Preferred completion | 30 minutes before afternoon peak; 15:30 AEST |
| Peak policy initially | Never schedule heating during peak |
| Dedicated heater CT | Future installation; not assumed present or commissioned |
| Other CT channels | Optional oven/air conditioning; reporting only, independent of hot water |

During Hobart daylight saving, those fixed-AEST peaks appear at 08:00–11:00 and
17:00–22:00 local. The controller must use `tariff_clock: standard`, with the
actual contract verified. The source grid sign is tested with a known load:
this household's historic export-positive HK1000 choice is not applied to new
users. Rates in the repository are illustrative and must match the actual bill.

The 45°C overnight/weekend baseline lets the native thermostat maintain the
agreed baseline during permitted windows. The weekday 62°C target stores normal
evening heat without requiring the roughly 2.93 kWh uniform-tank increment to
70°C every cloudy day. That energy is a physics reference, not a shower-volume
or tank-wide temperature measurement.

On a cloudy day, required 62°C heating uses the practical cheapest off-peak window
that can finish before peak, or the latest-start fallback without a valid
forecast. It does not buy extra electricity merely to reach optional 70°C.
On strong sunny days, once a real heater CT is commissioned and measurements
and forecasts qualify, the planner can request 70°C directly. After a normal
62°C cycle, a later useful solar opportunity can justify a 70°C top-up. On mixed
days, current measured import/loss can withdraw optional boost back to required
normal storage, while small forecast changes alone do not cause switching.

Before the future CT is installed and validated, the installation is CT-free:
normal off-peak storage remains supported, physical element status stays unknown
and optional boost remains unavailable. Nominal 3 kW never earns solar authority.
The default Never policy requests OFF two minutes before each peak regardless
of solar. Later selecting verified solar-only peak heating is a separate owner
choice; it requires all circuit/grid/economic guards and does not bypass the
explicit override, authentication or native protections.

Map actual bridge entities first. Potential GoodWe mappings include native
signed grid power, DC PV power, AC inverter output and household load; units and
sign must be verified. These names are user-selected, not prefilled in fresh
setup. Map the future raw hot-water CT channel to both the controller's
`heater_power` and Fable's `circuits[hot_water].power`; map its raw cumulative
counter similarly when available. Never substitute an absolute-value dashboard
wrapper. Oven/AC absence cannot affect the heater policy.

[Fable's PR #32](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/32)
provides independent read-only monitoring/reporting. Review that branch's own
installation instructions and [entity contract](https://github.com/MuntedDaze/ha-thermowatt-heater/blob/4c078f0802faaafc5d5fcc4264af7894b28fc95c/energy_monitoring/ENTITY_CONTRACT.md).
The backend [telemetry contract](TELEMETRY_INTERFACE.md) supplies four-state and
prediction entities for a future mapping update; this candidate neither copies
nor installs the dashboard package. Both PRs remain independent drafts.
