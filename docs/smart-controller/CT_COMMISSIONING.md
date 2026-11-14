# Generic circuit measurement: development acceptance sheet

Hardware is **not installed or commissioned**. This is an offline development
branch, not an instruction to deploy or operate the heater. The owner must
separately authorise all live installation and heater operation. An electrician
selects and installs the monitor; no brand, channel count or relay is required.

Map `heater_power` to one exclusive hot-water circuit active-power sensor, W or
kW. Optionally map `heater_energy` to cumulative import Wh or kWh on that same
circuit. A shared circuit cannot qualify the heater. Oven, AC and plug sensors
are not controller inputs. Fable owns monitoring packages and dashboards.

Leave `heater_meter_verification` empty until every applicable check is signed
off. Then record `sensor.actual_entity|W` (or `|kW`) under System. This records
installation knowledge, not an automatically discovered fact. Remapping clears
the record; different units invalidate it. Revalidate after replacing a device,
reusing an entity ID, changing firmware, wiring or a CT orientation.

| Check | Expected observation | Actual / date / owner |
|---|---|---|
| Channel identity | Only the hot-water circuit, no oven/AC/plugs included | Unverified |
| Physical idle | 0–100 W; selected Manual 70 does not imply element ON | Unverified |
| Physical heat | Positive normal resistive plateau, approximately 3 kW; accepted 2–3.8 kW | Unverified |
| Units and sign | W/kW conversion agrees with independent electrician measurement | Unverified |
| GoodWe sign | Import and daylight export, checked independently against counters | Unverified |
| Balance | Grid without heater = signed import − actual heater kW | Unverified |
| Manual 45 cycle | Native thermostat cut-in/out, target distinct from draw | Unverified |
| Manual 70 cycle | Native thermostat, cloud bits may lag actual watts | Unverified |
| Appliance edges | Oven/AC switching does not change measured hot-water watts | Unverified |
| Cadence | Reports including steady zero at least every 120 s; paired grid/CT skew ≤60 s | Unverified |
| Loss and unavailable | Primary state unknown; no inferred fallback; optional heat withdrawn | Unverified |
| Recovery / HA restart | New post-boot reports; full ten-minute qualification restored | Unverified |
| Counter restart/reset | New energy epoch; no negative energy or invented tariff allocation | Unverified |
| Independence | Local watts remain available when cloud status fails | Unverified |

Negative watts, 100–2000 W, above 3800 W, bad units, nonfinite, future,
restored, pre-boot and stale reports cannot qualify optional heating. These
conservative bounds suit the specified nominal 3 kW element; a different
installation requires code/settings review, not falsifying verification.

Peak metering loss requests one guarded OFF; weekend loss returns to native
45. Ordinary weekend spacing still applies. Essential off-peak heat can proceed
without CT, subject to existing ownership, cloud, confirmation and command
guards. Neither a local OFF reading nor a POST acknowledgement confirms a mode
command. Native protections remain untouched.

Rollback for this development branch: do not install it. Existing release
candidate, bridge files, authentication stores, saved flags and entity IDs are
unchanged. For any future separately approved commissioning, retain the backup
and rollback procedure in `shadow_controller/COMMISSIONING_SIMPLIFIED.md`.
