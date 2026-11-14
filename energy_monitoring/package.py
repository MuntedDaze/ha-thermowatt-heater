"""Build the Home Assistant package (sensors and helpers) from the entity map.

Everything here is read-only monitoring: template, integration (Riemann),
utility_meter, history_stats and input_number entities. No service is called,
nothing is published to MQTT and no heater entity is written to.

Design notes
- Cumulative sensors (energy, cost) carry a state class so the Recorder keeps
  long-term statistics; day/week/month/year figures on the dashboard are read
  from those statistics rather than from extra per-period sensors.
- "Today" sensors that combine several meters have NO state class: they are
  display values and would otherwise create misleading statistics.
- Cost sensors accumulate ``energy delta x price at that moment``, so a later
  rate change never re-prices history.
"""

import re

from .mapping import (
    RATE_KEYS,
    active_circuits,
    circuit_energy,
    circuit_power,
    hot_water_circuit,
    is_overlapping,
    rate_entity,
    tracked_sources,
)

# A single meter update larger than this is treated as a glitch, not energy.
MAX_STEP_KWH = 20
TARIFF = "sensor.em_tariff_period"
IMPORT_PRICE = "sensor.em_import_price"
FEED_IN_PRICE = "sensor.em_feed_in_price"
ELEMENT = "binary_sensor.em_hot_water_element_on"
CYCLE_START = "sensor.em_hot_water_cycle_start"
THIS_ATTRIBUTES = (
    "{% set a = this.attributes if this is defined and this and this.attributes is defined"
    " else {} %}"
)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def sensor_id(name: str) -> str:
    return f"sensor.{slug(name)}"


def num(entity: str) -> str:
    return f"(states('{entity}') | float(0))"


def ok(*entities: str) -> str:
    return "{{ " + " and ".join(f"is_number(states('{entity}'))" for entity in entities) + " }}"


def unit_factor(entity: str, unit: str, factor) -> str:
    """Scale a reading whose source reports in ``unit`` instead of W or kWh."""
    return f"({factor} if state_attr('{entity}', 'unit_of_measurement') == '{unit}' else 1)"


def template_sensor(name, state, unit=None, device_class=None, state_class="measurement", **more):
    entity = {"name": name, "unique_id": slug(name), "state": state}
    if unit:
        entity["unit_of_measurement"] = unit
    if device_class:
        entity["device_class"] = device_class
    if state_class:
        entity["state_class"] = state_class
    entity.update({key: value for key, value in more.items() if value})
    return entity


def tariff_template(tariff: dict) -> str:
    clock = (
        f"utcnow() + timedelta(hours={tariff['utc_offset_hours']})"
        if tariff["clock"] == "standard"
        else "now()"
    )
    windows = " or ".join(
        f"(d in {window['days']} and {window['start']} <= m < {window['end']})"
        for window in tariff["peak_windows"]
    )
    return (
        f"{{% set t = {clock} %}}\n"
        "{% set m = t.hour * 60 + t.minute %}\n"
        "{% set d = t.weekday() %}\n"
        f"{{{{ 'peak' if {windows or 'false'} else 'off_peak' }}}}"
    )


def accumulator(name, factor, unit, device_class, state_class, digits, priced=False):
    """A cumulative total fed by the positive steps of the triggering meter.

    The last numeric reading is kept as an attribute, so an ``unavailable`` gap
    loses nothing: the next reading is compared with the last good one. A step
    that is negative (meter replaced or reset) or implausibly large only moves
    the baseline. ``factor`` is evaluated when the step arrives.
    """
    step = (
        f"{THIS_ATTRIBUTES}\n"
        "{% set last = a.get('last_reading') %}\n"
        "{% set new = trigger.to_state.state if trigger is defined and trigger.to_state is defined"
        " and trigger.to_state else none %}\n"
        "{% set d = (new | float(0)) - (last | float(0)) if is_number(new) and is_number(last)"
        " else 0 %}\n"
        f"{{% set d = d if 0 < d <= {MAX_STEP_KWH} else 0 %}}\n"
        f"{{% set f = {factor} %}}\n"
    )
    attributes = {"last_reading": step + "{{ new | float(0) if is_number(new) else last }}"}
    if priced:
        attributes["unpriced_kwh"] = (
            step + "{{ ((a.get('unpriced_kwh') | float(0)) + (d if f <= 0 else 0)) | round(3) }}"
        )
    return template_sensor(
        name,
        step + "{{ ((this.state | float(0) if this is defined and this else 0) + d * f)"
        f" | round({digits}) }}}}",
        unit,
        device_class,
        state_class,
        attributes=attributes,
    )


def energy_total(name, factor):
    return accumulator(name, factor, "kWh", "energy", "total_increasing", 3)


def money_total(name, factor, currency):
    return accumulator(name, factor, currency, "monetary", "total", 4, priced=True)


def on_change(entity: str, sensors: list) -> dict:
    return {"triggers": [{"trigger": "state", "entity_id": entity}], "sensor": sensors}


def riemann(name: str, source: str) -> dict:
    return {
        "platform": "integration",
        "name": name,
        "unique_id": slug(name),
        "source": source,
        "unit_prefix": "k",
        "unit_time": "h",
        "round": 3,
        # "left" holds the previous reading until the next one: correct for a
        # load that switches between 0 and 3 kW; trapezoidal would smear it.
        "method": "left",
        "max_sub_interval": {"minutes": 5},
    }


def monitored_items(config: dict) -> list[tuple[str, str, int, int]]:
    """(entity, label, maximum age in seconds, 1 if a core measurement)."""
    age = config["freshness_seconds"]
    items = [
        (config["grid"]["power"], "Grid power", age["core"], 1),
        (config["grid"]["import_energy"], "Grid import energy", 0, 1),
        (config["grid"]["export_energy"], "Grid export energy", 0, 1),
        (config["house"]["power"], "House power", age["core"], 1),
    ]
    if not config["solar"]["zero_when_unavailable"]:
        items.append((config["solar"]["power"], "Solar power", age["core"], 1))
    for circuit in active_circuits(config):
        items.append((circuit["power"], f"{circuit['name']} circuit power", age["circuits"], 0))
        if circuit["energy"]:
            items.append((circuit["energy"], f"{circuit['name']} circuit energy", 0, 0))
    for appliance in config["appliances"]:
        if appliance["power"]:
            items.append((appliance["power"], f"{appliance['name']} power", age["appliances"], 0))
        if appliance["energy"]:
            items.append((appliance["energy"], f"{appliance['name']} energy", 0, 0))
    return items


def health_block(config: dict) -> dict:
    items = monitored_items(config)
    literal = ", ".join(f"('{e}', '{label}', {age}, {core})" for e, label, age, core in items)
    scan = (
        "{% set ns = namespace(missing=[], stale=[], core=0) %}\n"
        f"{{% for e, label, age, core in [{literal}] %}}\n"
        "{% set s = states[e] %}\n"
        "{% if s is none or s.state in ['unavailable', 'unknown', ''] %}\n"
        "{% set ns.missing = ns.missing + [label] %}{% set ns.core = ns.core + core %}\n"
        "{% elif age > 0 and (now() - (s.last_reported | default(s.last_updated)))"
        ".total_seconds() > age %}\n"
        "{% set ns.stale = ns.stale + [label] %}{% set ns.core = ns.core + core %}\n"
        "{% endif %}\n"
        "{% endfor %}\n"
    )
    rates = " and ".join(
        f"{num(rate_entity(config, key))} > 0" for key in RATE_KEYS if key != "daily_supply_charge"
    )
    attributes = {
        "missing": scan + "{{ ns.missing }}",
        "stale": scan + "{{ ns.stale }}",
        "rates_set": "{{ " + rates + " }}",
        "monitored": str(len(items)),
    }
    controller_tariff = config["hot_water"].get("current_tariff")
    if controller_tariff:
        attributes["tariff_matches_controller"] = (
            f"{{% set c = states('{controller_tariff}') %}}\n"
            f"{{{{ c == states('{TARIFF}') if c in ['peak', 'off_peak', 'shoulder'] else none }}}}"
        )
    return {
        "triggers": [
            {"trigger": "time_pattern", "minutes": "/1"},
            {"trigger": "homeassistant", "event": "start"},
        ],
        "sensor": [
            template_sensor(
                "EM monitoring health",
                scan + "{{ 'critical' if ns.core > 0 else 'degraded' if ns.missing or ns.stale"
                f" or not ({rates}) else 'ok' }}}}",
                state_class=None,
                icon="mdi:heart-pulse",
                attributes=attributes,
            ),
            template_sensor(
                "EM monitoring quality",
                scan + f"{{{{ (100 * ({len(items)} - (ns.missing | count) - (ns.stale | count))"
                f" / {len(items)}) | round(1) }}}}",
                "%",
                icon="mdi:gauge",
            ),
        ],
    }


def cycle_block(config: dict, circuit: dict) -> dict:
    """Record each element run as one state of ``EM hot water last cycle``.

    The Recorder keeps every completed cycle (state and attributes), which is
    the history the thermal-learning module can read: no separate database.
    """
    hot_water = config["hot_water"]
    energy = circuit_energy(circuit)
    snapshot = {
        "energy_kwh": energy,
        "grid_kwh": "sensor.em_hot_water_grid_energy",
        "solar_kwh": "sensor.em_hot_water_solar_energy",
    }
    if hot_water.get("tank_temperature"):
        snapshot["temperature_c"] = hot_water["tank_temperature"]
    if hot_water.get("status_age"):
        snapshot["status_age_s"] = hot_water["status_age"]
    keep = "(this.state if this is defined and this and this.state not in ['unknown', 'unavailable'] else none)"
    start = template_sensor(
        "EM hot water cycle start",
        f"{{{{ now().isoformat() if trigger.id == 'start' else {keep} }}}}",
        device_class="timestamp",
        state_class=None,
        attributes={
            key: f"{THIS_ATTRIBUTES}\n{{{{ states('{entity}') | float(none)"
            f" if trigger.id == 'start' else a.get('{key}') }}}}"
            for key, entity in snapshot.items()
        },
    )

    def began(key):
        return f"state_attr('{CYCLE_START}', '{key}')"

    def delta(key, digits=3):
        return (
            f"(({num(snapshot[key])} - ({began(key)} | float(0))) | round({digits})"
            f" if is_number(states('{snapshot[key]}')) and is_number({began(key)}) else none)"
        )

    minutes = (
        f"(((now() - (states('{CYCLE_START}') | as_datetime)).total_seconds() / 60) | round(1)"
        f" if states('{CYCLE_START}') not in ['unknown', 'unavailable'] else none)"
    )
    values = {
        "started": f"(states('{CYCLE_START}') if states('{CYCLE_START}') not in"
        " ['unknown', 'unavailable'] else none)",
        "ended": "now().isoformat()",
        "duration_minutes": minutes,
        "grid_kwh": delta("grid_kwh"),
        "solar_kwh": delta("solar_kwh"),
        "tariff_period_at_end": f"states('{TARIFF}')",
    }
    if "temperature_c" in snapshot:
        values["temperature_start_c"] = began("temperature_c")
        values["temperature_end_c"] = f"(states('{snapshot['temperature_c']}') | float(none))"
        values["temperature_rise_c"] = delta("temperature_c", 1)
    if "status_age_s" in snapshot:
        values["status_age_start_s"] = began("status_age_s")
        values["status_age_end_s"] = f"(states('{snapshot['status_age_s']}') | float(none))"
    # An "off" is recorded only against a start that has not been closed yet.
    # If the meter drops out so that a start is missed, the next "off" would
    # otherwise be paired with the previous run's start and invent a long cycle.
    closes = (
        f"trigger.id == 'end' and states('{CYCLE_START}') not in ['unknown', 'unavailable']"
        f" and a.get('started') != states('{CYCLE_START}')"
    )
    last = template_sensor(
        "EM hot water last cycle",
        f"{THIS_ATTRIBUTES}\n{{{{ {delta('energy_kwh')} if {closes} else {keep} }}}}",
        "kWh",
        state_class=None,
        icon="mdi:water-boiler",
        attributes={
            key: f"{THIS_ATTRIBUTES}\n{{{{ {value} if {closes} else a.get('{key}') }}}}"
            for key, value in values.items()
        },
    )
    return {
        "triggers": [
            {"trigger": "state", "entity_id": ELEMENT, "from": "off", "to": "on", "id": "start"},
            {"trigger": "state", "entity_id": ELEMENT, "from": "on", "to": "off", "id": "end"},
        ],
        "sensor": [start, last],
    }


def build_package(config: dict) -> dict:
    grid, solar, house = config["grid"], config["solar"], config["house"]
    currency = config["currency"]
    price_unit = f"{currency}/kWh"
    sign = "-" if grid["export_positive"] else ""
    reverse = "" if grid["export_positive"] else "-"
    peak, off_peak, feed_in, supply = (rate_entity(config, key) for key in RATE_KEYS)

    sensors = [
        template_sensor(
            "EM grid import power",
            f"{{{{ [0, {sign}{num(grid['power'])}] | max | round(1) }}}}",
            "W",
            "power",
            availability=ok(grid["power"]),
        ),
        template_sensor(
            "EM grid export power",
            f"{{{{ [0, {reverse}{num(grid['power'])}] | max | round(1) }}}}",
            "W",
            "power",
            availability=ok(grid["power"]),
        ),
        template_sensor(
            "EM solar power",
            f"{{{{ [0, {num(solar['power'])}] | max | round(1) }}}}",
            "W",
            "power",
            availability=None if solar["zero_when_unavailable"] else ok(solar["power"]),
        ),
        template_sensor(
            "EM house power",
            f"{{{{ [0, {num(house['power'])}] | max | round(1) }}}}",
            "W",
            "power",
            availability=ok(house["power"]),
        ),
        template_sensor(
            "EM solar self consumed power",
            "{{ [0, "
            + num("sensor.em_solar_power")
            + " - "
            + num("sensor.em_grid_export_power")
            + "] | max | round(1) }}",
            "W",
            "power",
            availability=ok("sensor.em_solar_power", "sensor.em_grid_export_power"),
        ),
        template_sensor(
            "EM tariff period",
            tariff_template(config["tariff"]),
            state_class=None,
            icon="mdi:clock-time-four-outline",
        ),
        template_sensor(
            "EM import price",
            f"{{{{ {num(peak)} if states('{TARIFF}') == 'peak' else {num(off_peak)} }}}}",
            price_unit,
            availability=f"{{{{ {num(peak)} > 0 and {num(off_peak)} > 0 }}}}",
            icon="mdi:cash",
        ),
        template_sensor(
            "EM feed in price",
            f"{{{{ {num(feed_in)} }}}}",
            price_unit,
            availability=f"{{{{ {num(feed_in)} > 0 }}}}",
            icon="mdi:cash-plus",
        ),
    ]
    if solar["forecast_power"]:
        # State only: the EMHASS forecast array stays out of the Recorder.
        sensors.append(
            template_sensor(
                "EM solar forecast power",
                f"{{{{ {num(solar['forecast_power'])} | round(0) }}}}",
                "W",
                "power",
                availability=ok(solar["forecast_power"]),
            )
        )

    integrations = [
        riemann("EM house energy", "sensor.em_house_power"),
        riemann("EM solar self consumed energy", "sensor.em_solar_self_consumed_power"),
        riemann("EM untracked energy", "sensor.em_untracked_power"),
    ]
    for circuit in active_circuits(config):
        name = circuit["key"].replace("_", " ")
        sensors.append(
            template_sensor(
                f"EM {name} power",
                # abs(): a load circuit cannot export, so a reversed clamp still reads right.
                # W or kW: the units the controller's heater_power input accepts.
                f"{{{{ ({num(circuit['power'])} * {unit_factor(circuit['power'], 'kW', 1000)})"
                " | abs | round(1) }}",
                "W",
                "power",
                availability=ok(circuit["power"]),
            )
        )
        if circuit["energy"]:
            # Pass-through with a stable ID, so replacing the meter keeps the history.
            sensors.append(
                template_sensor(
                    f"EM {name} energy",
                    f"{{{{ ({num(circuit['energy'])}"
                    f" * {unit_factor(circuit['energy'], 'Wh', 0.001)}) | round(3) }}}}",
                    "kWh",
                    "energy",
                    "total_increasing",
                    availability=ok(circuit["energy"]),
                )
            )
        else:
            integrations.append(riemann(f"EM {name} energy", circuit_power(circuit)))

    sources = tracked_sources(config)
    tracked = " + ".join(num(source["power"]) for source in sources) or "0"
    available = " + ".join(f"(1 if is_number(states('{s['power']}')) else 0)" for s in sources)
    sensors += [
        template_sensor(
            "EM tracked power",
            f"{{{{ ({tracked}) | round(1) }}}}",
            "W",
            "power",
            attributes={
                "sources": str(len(sources)),
                "sources_available": f"{{{{ {available or '0'} }}}}",
            },
        ),
        template_sensor(
            "EM untracked power",
            f"{{{{ [0, {num('sensor.em_house_power')} - {num('sensor.em_tracked_power')}]"
            " | max | round(1) }}",
            "W",
            "power",
            availability=ok("sensor.em_house_power", "sensor.em_tracked_power"),
            # Persistently negative: a plug is counted twice, or the readings are misaligned.
            attributes={
                "raw_residual_w": f"{{{{ ({num('sensor.em_house_power')}"
                f" - {num('sensor.em_tracked_power')}) | round(1) }}}}"
            },
        ),
    ]

    binary_sensors = []
    triggered = [
        on_change(
            grid["import_energy"],
            [
                energy_total(
                    "EM grid import peak energy", f"1 if states('{TARIFF}') == 'peak' else 0"
                ),
                energy_total(
                    "EM grid import off peak energy",
                    f"1 if states('{TARIFF}') == 'off_peak' else 0",
                ),
                money_total("EM grid import cost", num(IMPORT_PRICE), currency),
            ],
        ),
        on_change(
            grid["export_energy"],
            [money_total("EM grid export earnings", num(FEED_IN_PRICE), currency)],
        ),
        on_change(
            "sensor.em_solar_self_consumed_energy",
            # What the self-consumed solar would have cost to import.
            [money_total("EM solar self consumption savings", num(IMPORT_PRICE), currency)],
        ),
    ]

    hot_water = hot_water_circuit(config)
    if hot_water:
        power = num(circuit_power(hot_water))
        both = ok(circuit_power(hot_water), "sensor.em_grid_import_power")
        sensors += [
            # Marginal attribution: the heater is the deferrable load, so it is
            # charged with the import it causes and credited the rest as solar.
            template_sensor(
                "EM hot water grid power",
                f"{{{{ [{power}, {num('sensor.em_grid_import_power')}] | min | round(1) }}}}",
                "W",
                "power",
                availability=both,
            ),
            template_sensor(
                "EM hot water solar power",
                f"{{{{ ({power} - [{power}, {num('sensor.em_grid_import_power')}] | min)"
                " | round(1) }}",
                "W",
                "power",
                availability=both,
            ),
        ]
        binary_sensors.append(
            {
                "name": "EM hot water element on",
                "unique_id": "em_hot_water_element_on",
                "state": f"{{{{ {power} > {hot_water['element_on_watts']} }}}}",
                "availability": ok(circuit_power(hot_water)),
                "delay_on": {"seconds": 30},
                "delay_off": {"seconds": 60},
                "icon": "mdi:water-boiler",
            }
        )
        integrations += [
            riemann("EM hot water grid energy", "sensor.em_hot_water_grid_power"),
            riemann("EM hot water solar energy", "sensor.em_hot_water_solar_power"),
            {
                "platform": "history_stats",
                "name": "EM hot water element runtime today",
                "unique_id": "em_hot_water_element_runtime_today",
                "entity_id": ELEMENT,
                "state": "on",
                "type": "time",
                "start": "{{ today_at() }}",
                "end": "{{ now() }}",
            },
            {
                "platform": "history_stats",
                "name": "EM hot water cycles today",
                "unique_id": "em_hot_water_cycles_today",
                "entity_id": ELEMENT,
                "state": "on",
                "type": "count",
                "start": "{{ today_at() }}",
                "end": "{{ now() }}",
            },
        ]
        triggered += [
            on_change(
                "sensor.em_hot_water_grid_energy",
                [money_total("EM hot water grid cost", num(IMPORT_PRICE), currency)],
            ),
            on_change(
                "sensor.em_hot_water_solar_energy",
                # Feed-in income forgone by heating from solar: an opportunity
                # cost, never added to the electricity bill.
                [money_total("EM hot water solar opportunity cost", num(FEED_IN_PRICE), currency)],
            ),
            cycle_block(config, hot_water),
        ]

    meters = {
        "em_grid_import_daily": (grid["import_energy"], "daily"),
        "em_grid_export_daily": (grid["export_energy"], "daily"),
        "em_solar_daily": (solar["energy"], "daily"),
        "em_grid_import_cost_daily": ("sensor.em_grid_import_cost", "daily"),
        "em_grid_export_earnings_daily": ("sensor.em_grid_export_earnings", "daily"),
        "em_grid_import_cost_monthly": ("sensor.em_grid_import_cost", "monthly"),
        "em_grid_export_earnings_monthly": ("sensor.em_grid_export_earnings", "monthly"),
    }
    imported, exported, generated = (
        num("sensor.em_grid_import_daily"),
        num("sensor.em_grid_export_daily"),
        num("sensor.em_solar_daily"),
    )
    balance = ok(
        "sensor.em_grid_import_daily", "sensor.em_grid_export_daily", "sensor.em_solar_daily"
    )
    used = f"({imported} + {generated} - {exported})"
    sensors += [
        template_sensor(
            "EM house energy today",
            f"{{{{ [0, {used}] | max | round(2) }}}}",
            "kWh",
            state_class=None,
            availability=balance,
            icon="mdi:home-lightning-bolt",
        ),
        template_sensor(
            "EM self consumption today",
            f"{{{{ ([0, [100, 100 * ({generated} - {exported}) / {generated}] | min] | max)"
            f" | round(1) if {generated} > 0.05 else none }}}}",
            "%",
            state_class=None,
            availability=balance,
            icon="mdi:solar-power",
        ),
        template_sensor(
            "EM self sufficiency today",
            f"{{{{ ([0, [100, 100 * (1 - {imported} / {used})] | min] | max) | round(1)"
            f" if {used} > 0.05 else none }}}}",
            "%",
            state_class=None,
            availability=balance,
            icon="mdi:home-battery",
        ),
        template_sensor(
            "EM net energy cost today",
            f"{{{{ ({num('sensor.em_grid_import_cost_daily')}"
            f" - {num('sensor.em_grid_export_earnings_daily')} + {num(supply)}) | round(2) }}}}",
            currency,
            state_class=None,
            availability=ok(
                "sensor.em_grid_import_cost_daily", "sensor.em_grid_export_earnings_daily"
            ),
            icon="mdi:cash-register",
        ),
        template_sensor(
            "EM net energy cost this month",
            f"{{{{ ({num('sensor.em_grid_import_cost_monthly')}"
            f" - {num('sensor.em_grid_export_earnings_monthly')}"
            f" + {num(supply)} * now().day) | round(2) }}}}",
            currency,
            state_class=None,
            availability=ok(
                "sensor.em_grid_import_cost_monthly", "sensor.em_grid_export_earnings_monthly"
            ),
            icon="mdi:cash-register",
        ),
    ]

    helpers = {}
    for key, label, unit, maximum in (
        ("peak_rate", "EM peak import rate", price_unit, 2),
        ("off_peak_rate", "EM off-peak import rate", price_unit, 2),
        ("feed_in_rate", "EM feed-in rate", price_unit, 2),
        ("daily_supply_charge", "EM daily supply charge", f"{currency}/day", 10),
    ):
        if not config["tariff"][f"{key}_entity"]:
            # No "initial": the value set in Home Assistant survives restarts.
            helpers[f"em_{key}"] = {
                "name": label,
                "min": 0,
                "max": maximum,
                "step": 0.000001,
                "mode": "box",
                "unit_of_measurement": unit,
                "icon": "mdi:currency-usd",
            }

    state_block = {"sensor": sensors}
    if binary_sensors:
        state_block["binary_sensor"] = binary_sensors
    package = {
        "template": [state_block, *triggered, health_block(config)],
        "sensor": integrations,
        "utility_meter": {
            key: {
                "name": key.replace("em_", "EM ", 1).replace("_", " "),
                "unique_id": key,
                "source": source,
                "cycle": cycle,
            }
            for key, (source, cycle) in meters.items()
        },
    }
    if helpers:
        package["input_number"] = helpers
    return package


def package_entities(config: dict) -> set[str]:
    """Every entity ID the package creates (used to check the dashboard)."""
    package = build_package(config)
    entities = set()
    for block in package["template"]:
        entities |= {sensor_id(item["name"]) for item in block.get("sensor", [])}
        entities |= {
            f"binary_sensor.{slug(item['name'])}" for item in block.get("binary_sensor", [])
        }
    entities |= {sensor_id(item["name"]) for item in package["sensor"]}
    entities |= {f"sensor.{key}" for key in package["utility_meter"]}
    entities |= {f"input_number.{key}" for key in package.get("input_number", {})}
    return entities


def overlapping_appliances(config: dict) -> list[dict]:
    return [a for a in config["appliances"] if a["power"] and is_overlapping(config, a)]
