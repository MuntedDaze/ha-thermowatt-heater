"""Build the Lovelace dashboard from the entity map.

Built-in cards only (no HACS). The dashboard is read-only: it contains no
button, no service call and no control for the heater or any appliance. The
only editable entities are the four tariff-rate helpers.
"""

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

HEALTH = "sensor.em_monitoring_health"
PERIODS = (("day", "Today"), ("week", "This week"), ("month", "This month"), ("year", "This year"))
CARD_TYPES = frozenset(
    {
        "heading",
        "tile",
        "gauge",
        "markdown",
        "entities",
        "statistic",
        "statistics-graph",
        "history-graph",
        "energy-date-selection",
        "energy-distribution",
        "energy-usage-graph",
        "energy-solar-graph",
        "energy-sources-table",
        "energy-devices-graph",
    }
)


def heading(text, icon=None):
    card = {"type": "heading", "heading": text, "heading_style": "title"}
    if icon:
        card["icon"] = icon
    return card


def tile(entity, name, **more):
    if not entity:
        return note(f"{name}: not configured")
    return {"type": "tile", "entity": entity, "name": name, **more}


def note(text):
    return {"type": "markdown", "content": text}


def statistic(entity, name, period="day"):
    """A long-term-statistics total for the current calendar period."""
    if not entity:
        return note(f"{name}: not configured")
    return {
        "type": "statistic",
        "entity": entity,
        "name": name,
        "period": {"calendar": {"period": period}},
        "stat_type": "change",
    }


def periods(entity, label):
    return [statistic(entity, f"{label} · {title.lower()}", period) for period, title in PERIODS]


def bars(title, entities, period="day", days=30, stat="change", chart="bar"):
    entities = [(entity, name) for entity, name in entities if entity]
    if not entities:
        return note(f"{title}: not configured")
    return {
        "type": "statistics-graph",
        "title": title,
        "chart_type": chart,
        "period": period,
        "days_to_show": days,
        "stat_types": [stat],
        "entities": [{"entity": entity, "name": name} for entity, name in entities],
        "grid_options": {"columns": "full"},
    }


def history(title, entities, hours=24):
    entities = [(entity, name) for entity, name in entities if entity]
    if not entities:
        return note(f"{title}: not configured")
    return {
        "type": "history-graph",
        "title": title,
        "hours_to_show": hours,
        "entities": [{"entity": entity, "name": name} for entity, name in entities],
        "grid_options": {"columns": "full"},
    }


def rows(title, pairs):
    pairs = [(entity, name) for entity, name in pairs if entity]
    if not pairs:
        return note(f"{title}: not configured")
    return {
        "type": "entities",
        "title": title,
        "entities": [{"entity": entity, "name": name} for entity, name in pairs],
    }


def section(*cards, columns=None):
    grid = {"type": "grid", "cards": [card for card in cards if card]}
    if columns:
        grid["column_span"] = columns
    return grid


def view(title, path, icon, *sections):
    return {
        "title": title,
        "path": path,
        "icon": icon,
        "type": "sections",
        "max_columns": 4,
        "sections": list(sections),
    }


def controller_rows(config, keys):
    hot_water = config["hot_water"]
    return [(hot_water[key], label) for key, label in keys if hot_water.get(key)]


def overview(config):
    grid, solar = config["grid"], config["solar"]
    hot_water = config["hot_water"]
    circuit = hot_water_circuit(config)
    water = [heading("Hot water", "mdi:water-boiler")]
    water += [
        tile(entity, label)
        for entity, label in controller_rows(
            config,
            (
                ("mode", "Thermann mode"),
                ("target", "Target"),
                ("tank_temperature", "Tank reading (bottom sensor)"),
                ("control_state", "Controller"),
                ("next_heating_start", "Next heating start"),
            ),
        )
    ]
    if circuit:
        water.insert(1, tile(circuit_power(circuit), "Element power"))
    else:
        water.append(note("Element power appears here once the hot-water CT is mapped."))
    if hot_water.get("expected_completion"):
        water.append(tile(hot_water["expected_completion"], "Estimated finish (conditional)"))
    return view(
        "Overview",
        "overview",
        "mdi:view-dashboard",
        section(
            heading("Right now", "mdi:flash"),
            tile("sensor.em_solar_power", "Solar"),
            tile("sensor.em_house_power", "House"),
            tile("sensor.em_grid_import_power", "Grid import"),
            tile("sensor.em_grid_export_power", "Grid export"),
            tile("sensor.em_solar_self_consumed_power", "Solar used at home"),
            tile("sensor.em_untracked_power", "Other / untracked"),
            tile("sensor.em_tariff_period", "Tariff period"),
            tile("sensor.em_import_price", "Import price now"),
        ),
        section(
            heading("Today", "mdi:calendar-today"),
            statistic(solar["energy"], "Solar generated"),
            tile("sensor.em_house_energy_today", "House used"),
            statistic(grid["import_energy"], "Imported"),
            statistic(grid["export_energy"], "Exported"),
            tile("sensor.em_self_consumption_today", "Solar self-consumption"),
            tile("sensor.em_self_sufficiency_today", "Self-sufficiency"),
            tile("sensor.em_net_energy_cost_today", "Net cost incl. supply charge"),
            statistic("sensor.em_grid_export_earnings", "Feed-in earned"),
        ),
        section(*water),
        section(
            heading("Monitoring", "mdi:heart-pulse"),
            tile(HEALTH, "Monitoring health"),
            tile("sensor.em_monitoring_quality", "Sources reporting"),
        ),
        section(
            history(
                "Power · 24 h",
                [
                    ("sensor.em_solar_power", "Solar"),
                    ("sensor.em_house_power", "House"),
                    ("sensor.em_grid_import_power", "Import"),
                    ("sensor.em_grid_export_power", "Export"),
                ],
            ),
            columns=4,
        ),
    )


def hot_water_view(config):
    hot_water = config["hot_water"]
    circuit = hot_water_circuit(config)
    status = [heading("Heater", "mdi:water-boiler")]
    if hot_water.get("tank_temperature"):
        status.append(
            {
                "type": "gauge",
                "entity": hot_water["tank_temperature"],
                "name": "Tank reading (bottom sensor)",
                "min": 10,
                "max": 80,
                "needle": True,
            }
        )
    status += [
        tile(entity, label)
        for entity, label in controller_rows(
            config,
            (
                ("mode", "Thermann mode"),
                ("target", "Reported target temperature"),
                ("baseline_target", "Overnight baseline target"),
                ("normal_target", "Normal weekday target"),
                ("boost_target", "Optional solar target"),
                ("measurement_mode", "Circuit measurement mode"),
                ("measured_element_state", "Verified circuit element state"),
                ("peak_policy", "Heating during peak periods"),
                ("boost_enabled", "Optional solar boost enabled"),
                ("operating_mode", "Operating mode"),
                ("element_state", "Element (meter-inferred)"),
                ("controller_fault", "Controller fault"),
            ),
        )
    ]
    plan = controller_rows(
        config,
        (
            ("control_state", "Controller state"),
            ("control_reason", "Reason"),
            ("policy_state", "Policy wants"),
            ("desired_temperature", "Desired thermostat target"),
            ("heating_requirement", "Required / optional heating"),
            ("boost_eligibility", "Solar boost eligibility"),
            ("boost_reason", "Solar boost selected / rejected"),
            ("planned_heat", "Planned energy estimate (not metered)"),
            ("prediction_confidence", "Prediction confidence"),
            ("policy_mode", "Policy mode"),
            ("decision_code", "Decision code"),
            ("next_action", "Next intended action"),
            ("next_heating_start", "Next heating start"),
            ("next_heating_stop", "Next heating stop"),
            ("latest_start", "Latest continuous start"),
            ("soft_target_time", "Soft target time"),
            ("heating_time_needed", "Heating time needed"),
            ("expected_completion", "Estimated finish (conditional)"),
            ("nominal_heating_time", "Time if heating continuously"),
        ),
    )
    planning = [heading("Plan and decision", "mdi:robot-outline"), rows("Current plan", plan)]
    planning.append(
        note(
            "Without a commissioned hot-water meter, electrical ON/OFF and a completion clock "
            "are unknown. Nominal minutes assume continuous heating at the configured power; "
            "the native thermostat may wait, water use may change the estimate, and an old "
            "temperature expires. This is not a promise of ready hot water."
        )
    )
    if not hot_water.get("expected_completion"):
        planning.append(
            note(
                "**Estimated finish** is not mapped. Use `hot_water.expected_completion` "
                "only when the controller exposes its conditional estimate. Without CT, "
                "a completion clock is unknown; continuous-heating minutes are assumptions."
            )
        )
    cloud = controller_rows(
        config,
        (
            ("cloud_health", "Cloud health"),
            ("status_age", "Status age"),
            ("last_poll", "Last successful poll"),
            ("next_poll", "Next actual background poll"),
            ("next_adaptive_poll", "Next hypothetical shadow poll"),
            ("adaptive_status", "Adaptive polling status / reason"),
            ("request_budget", "Request budget remaining (rolling 24h)"),
            ("poll_interval", "Actual background poll interval"),
            ("last_cloud_error", "Last cloud error"),
            ("requests_24h", "Requests in last 24 h"),
            ("requests_per_hour", "Requests per hour"),
            ("request_attempts", "Request attempts (lifetime)"),
            ("commands_24h", "Commands in last 24 h"),
            ("last_command", "Last command"),
            ("last_command_result", "Last command result"),
        ),
    )
    polling = [
        heading("Cloud polling and requests", "mdi:cloud-sync"),
        rows("Thermann cloud", cloud),
    ]
    if hot_water.get("request_attempts"):
        polling.append(
            bars("Cloud requests per day", [(hot_water["request_attempts"], "Requests")], days=14)
        )
    sections = [section(*status), section(*planning), section(*polling)]
    learning = controller_rows(
        config,
        (
            ("learning_status", "Learning eligibility"),
            ("learning_sessions", "Clean sessions in current cohort"),
            ("learned_rate", "Learned rate (diagnostic)"),
            ("prediction_error", "Held-out prediction error"),
        ),
    )
    if learning:
        sections.append(
            section(
                heading("Heating history and prediction", "mdi:chart-timeline-variant"),
                rows("Learning readiness", learning),
            )
        )
    if hot_water.get("telemetry"):
        telemetry = hot_water["telemetry"]
        sections[1]["cards"].append(
            note(
                "{% set c = state_attr('"
                + telemetry
                + "', 'completion') or {} %}Conditional continuous-heating range: {{ c.get('earliest') or 'unavailable' }} to {{ c.get('latest') or 'unavailable' }}. A bottom-probe estimate is not a promised completion or hygiene measurement."
            )
        )

    if not circuit:
        sections.append(
            section(
                heading("Element power and energy", "mdi:flash"),
                note(
                    "**The hot-water CT is not mapped yet.** After the meter is installed, set "
                    "`circuits[hot_water].power` (and `energy` if the meter has one) in "
                    "`entity_map.yaml` and regenerate. This section then shows element watts, "
                    "kWh, runtime, heating cycles, the solar/grid split and cost."
                ),
            )
        )
        return view("Hot water", "hot-water", "mdi:water-boiler", *sections)

    energy = circuit_energy(circuit)
    sections += [
        section(
            heading("Element power and energy", "mdi:flash"),
            tile(circuit_power(circuit), "Element power"),
            tile("binary_sensor.em_hot_water_element_on", "Element drawing power"),
            tile("sensor.em_hot_water_element_runtime_today", "Runtime today"),
            tile("sensor.em_hot_water_cycles_today", "Heating cycles today"),
            *periods(energy, "Energy"),
        ),
        section(
            heading("Where the energy came from", "mdi:solar-power"),
            tile("sensor.em_hot_water_grid_power", "From grid now"),
            tile("sensor.em_hot_water_solar_power", "From solar now"),
            statistic("sensor.em_hot_water_grid_energy", "Grid · today"),
            statistic("sensor.em_hot_water_solar_energy", "Solar · today"),
            statistic("sensor.em_hot_water_grid_energy", "Grid · this month", "month"),
            statistic("sensor.em_hot_water_solar_energy", "Solar · this month", "month"),
        ),
        section(
            heading("Cost", "mdi:cash"),
            *periods("sensor.em_hot_water_grid_cost", "Imported"),
            *periods("sensor.em_hot_water_solar_opportunity_cost", "Solar opportunity"),
            note(
                "**Imported** is money paid for grid electricity. **Solar opportunity** is "
                "feed-in income given up by heating from solar instead of exporting; it is "
                "not on the bill and is never added to the imported cost."
            ),
        ),
        section(
            heading("Last heating cycle", "mdi:history"),
            {
                "type": "entities",
                "entities": [
                    {"entity": "sensor.em_hot_water_last_cycle", "name": "Energy"},
                    *[
                        {
                            "type": "attribute",
                            "entity": "sensor.em_hot_water_last_cycle",
                            "attribute": attribute,
                            "name": label,
                        }
                        for attribute, label in (
                            ("started", "Started"),
                            ("ended", "Ended"),
                            ("duration_minutes", "Duration (min)"),
                            ("grid_kwh", "From grid (kWh)"),
                            ("solar_kwh", "From solar (kWh)"),
                            ("temperature_start_c", "Reading at start (°C)"),
                            ("temperature_end_c", "Reading at end (°C)"),
                            ("temperature_rise_c", "Rise (°C)"),
                        )
                    ],
                ],
            },
            note(
                "The tank reading comes from the Thermann cloud and can be up to one poll "
                "interval old at each end of a cycle (`status_age_*_s` attributes)."
            ),
        ),
        section(
            history(
                "Element power and tank reading · 24 h",
                [(circuit_power(circuit), "Element")]
                + controller_rows(config, (("tank_temperature", "Tank reading"),)),
            ),
            bars(
                "Hot-water energy per day: grid and solar",
                [
                    ("sensor.em_hot_water_grid_energy", "Grid"),
                    ("sensor.em_hot_water_solar_energy", "Solar"),
                ],
            ),
            columns=4,
        ),
    ]
    return view("Hot water", "hot-water", "mdi:water-boiler", *sections)


def costs_view(config):
    rates = [
        (rate_entity(config, key), label)
        for key, label in zip(
            RATE_KEYS,
            ("Peak import rate", "Off-peak import rate", "Feed-in rate", "Daily supply charge"),
            strict=True,
        )
    ]
    if config["tariff"]["source"] == "controller":
        rates = [
            ("sensor.em_feed_in_price", "Feed-in price now"),
            (config["hot_water"]["tariff_verification"], "Controller tariff verification"),
            (rate_entity(config, "daily_supply_charge"), "Daily supply charge"),
        ]
    rate_title = (
        "Controller prices (configure tariffs in Thermann Controller)"
        if config["tariff"]["source"] == "controller"
        else "Rates (edit here when your tariff changes)"
    )
    return view(
        "Costs",
        "costs",
        "mdi:cash-multiple",
        section(
            heading("Tariff", "mdi:clock-time-four-outline"),
            tile("sensor.em_tariff_period", "Period now"),
            tile("sensor.em_import_price", "Import price now"),
            rows(rate_title, rates),
        ),
        section(
            heading("Grid import by tariff", "mdi:transmission-tower-import"),
            *periods("sensor.em_grid_import_peak_energy", "Peak"),
            *periods("sensor.em_grid_import_off_peak_energy", "Off-peak"),
            *periods("sensor.em_grid_import_shoulder_energy", "Shoulder"),
        ),
        section(
            heading("Spending and earnings", "mdi:cash"),
            *periods("sensor.em_grid_import_cost", "Import cost"),
            *periods("sensor.em_grid_export_earnings", "Feed-in earned"),
        ),
        section(
            heading("Net and solar value", "mdi:scale-balance"),
            tile("sensor.em_net_energy_cost_today", "Net cost today"),
            tile("sensor.em_net_energy_cost_this_month", "Net cost this month"),
            *periods("sensor.em_solar_self_consumption_savings", "Import avoided by solar"),
            note(
                "Net cost = import cost − feed-in earned + daily supply charge. Each kWh is "
                "priced at the rate in force when it was metered, so changing a rate does "
                "not re-price earlier energy."
            ),
        ),
        section(
            bars(
                "Import per day by tariff",
                [
                    ("sensor.em_grid_import_peak_energy", "Peak"),
                    ("sensor.em_grid_import_off_peak_energy", "Off-peak"),
                    ("sensor.em_grid_import_shoulder_energy", "Shoulder"),
                ],
            ),
            bars(
                "Cost and earnings per month",
                [
                    ("sensor.em_grid_import_cost", "Import cost"),
                    ("sensor.em_grid_export_earnings", "Feed-in earned"),
                ],
                period="month",
                days=365,
            ),
            columns=4,
        ),
    )


def appliances_view(config):
    sources = tracked_sources(config)
    live = [heading("Power now", "mdi:flash")]
    live += [tile(source["power"], source["name"]) for source in sources]
    live.append(tile("sensor.em_untracked_power", "Other / untracked"))
    energies = [(source["energy"], source["name"]) for source in sources if source["energy"]]
    energies.append(("sensor.em_untracked_energy", "Other / untracked"))
    sections = [
        section(*live),
        section(
            heading("Energy today", "mdi:calendar-today"),
            *[statistic(entity, name) for entity, name in energies],
        ),
        section(
            heading("Energy this month", "mdi:calendar-month"),
            *[statistic(entity, name, "month") for entity, name in energies],
        ),
    ]
    children = [a for a in config["appliances"] if a["power"] and is_overlapping(config, a)]
    if children:
        names = {circuit["key"]: circuit["name"] for circuit in config["circuits"]}
        sections.append(
            section(
                heading("Inside a monitored circuit", "mdi:sitemap"),
                *[tile(a["power"], f"{a['name']} (on {names[a['circuit']]})") for a in children],
                note(
                    "These plugs are downstream of a CT. They are shown for detail only and "
                    "are not added to the tracked total, so nothing is counted twice."
                ),
            )
        )
    unmapped = [c["name"] for c in config["circuits"] if not c["power"]]
    if unmapped:
        sections.append(
            section(
                heading("Not mapped yet", "mdi:help-circle-outline"),
                note(
                    "No CT is mapped for: **"
                    + ", ".join(unmapped)
                    + "**. Until then their consumption is part of *Other / untracked*."
                ),
            )
        )
    sections.append(
        section(
            bars("Energy per day by appliance", energies, days=14),
            bars("Energy per month by appliance", energies, period="month", days=365),
            history("Appliance power · 24 h", [(s["power"], s["name"]) for s in sources]),
            columns=4,
        )
    )
    return view("Appliances", "appliances", "mdi:power-plug", *sections)


def history_view(config):
    grid, solar = config["grid"], config["solar"]
    flows = [
        (solar["energy"], "Solar generated"),
        ("sensor.em_house_energy", "House used"),
        (grid["import_energy"], "Imported"),
        (grid["export_energy"], "Exported"),
        ("sensor.em_solar_self_consumed_energy", "Solar used at home"),
    ]
    totals = [
        section(heading(title, "mdi:sigma"), *[statistic(e, name, period) for e, name in flows])
        for period, title in PERIODS
    ]
    graphs = [
        bars("Daily · last 30 days", flows),
        bars("Weekly · last 26 weeks", flows, period="week", days=182),
        bars("Monthly · last 12 months", flows, period="month", days=365),
        bars("Monthly · last 5 years (annual trend)", flows, period="month", days=1825),
    ]
    if solar["forecast_power"]:
        graphs.append(
            bars(
                "Solar forecast and actual · hourly mean, 7 days",
                [
                    ("sensor.em_solar_forecast_power", "Forecast"),
                    ("sensor.em_solar_power", "Actual"),
                ],
                period="hour",
                days=7,
                stat="mean",
                chart="line",
            )
        )
    return view("History", "history", "mdi:chart-bar", *totals, section(*graphs, columns=4))


def energy_view():
    cards = [
        {"type": "energy-date-selection"},
        {"type": "energy-distribution", "link_dashboard": True},
        {"type": "energy-usage-graph"},
        {"type": "energy-solar-graph"},
        {"type": "energy-sources-table"},
        {"type": "energy-devices-graph"},
    ]
    return view(
        "Energy",
        "energy",
        "mdi:lightning-bolt",
        section(
            note(
                "These are Home Assistant's own Energy cards. They stay empty until the "
                "Energy dashboard is configured (README, step 5)."
            ),
            *[{**card, "grid_options": {"columns": "full"}} for card in cards],
            columns=4,
        ),
    )


def health_view(config):
    grid, solar, house = config["grid"], config["solar"], config["house"]
    core = [
        (grid["power"], "Grid power"),
        (grid["import_energy"], "Grid import energy"),
        (grid["export_energy"], "Grid export energy"),
        (solar["power"], "Solar power"),
        (solar["energy"], "Solar energy"),
        (house["power"], "House power"),
    ]
    measured = [(c["power"], f"{c['name']} circuit") for c in active_circuits(config)]
    measured += [(a["power"], a["name"]) for a in config["appliances"] if a["power"]]
    pending = [f"{c['name']} CT" for c in config["circuits"] if not c["power"]]
    pending += [
        label
        for key, label in (
            ("expected_completion", "Controller: expected completion"),
            ("next_poll", "Controller: next poll time"),
            ("poll_interval", "Controller: poll interval"),
        )
        if not config["hot_water"].get(key)
    ]

    def freshness(title, pairs):
        return {
            "type": "entities",
            "title": title,
            "entities": [
                {"entity": entity, "name": name, "secondary_info": "last-updated"}
                for entity, name in pairs
                if entity
            ],
        }

    summary = (
        f"{{% set missing = state_attr('{HEALTH}', 'missing') or [] %}}\n"
        f"{{% set stale = state_attr('{HEALTH}', 'stale') or [] %}}\n"
        "**Missing or unavailable:** {{ missing | join(', ') if missing else 'none' }}\n\n"
        "**Stale:** {{ stale | join(', ') if stale else 'none' }}\n\n"
        f"**Tariff rates set:** {{{{ 'yes' if state_attr('{HEALTH}', 'rates_set') else"
        " 'NO: costs are not being counted' }}\n\n"
        "**Untracked residual:** "
        "{{ state_attr('sensor.em_untracked_power', 'raw_residual_w') }} W "
        "(persistently negative means a load is counted twice)"
    )
    return view(
        "Health",
        "health",
        "mdi:heart-pulse",
        section(
            heading("Monitoring health", "mdi:heart-pulse"),
            tile(HEALTH, "Status"),
            tile("sensor.em_monitoring_quality", "Sources reporting"),
            note(summary),
        ),
        section(heading("Core meters", "mdi:meter-electric"), freshness("Freshness", core)),
        section(
            heading("Circuits and appliances", "mdi:power-plug"), freshness("Freshness", measured)
        ),
        section(
            heading("Waiting for", "mdi:timer-sand"),
            note("\n".join(f"- {item}" for item in pending) or "Nothing: every source is mapped."),
            bars(
                "Sources reporting · hourly mean, 7 days",
                [("sensor.em_monitoring_quality", "Quality")],
                period="hour",
                days=7,
                stat="mean",
                chart="line",
            ),
        ),
    )


def build_dashboard(config: dict) -> dict:
    return {
        "title": "Energy",
        "views": [
            overview(config),
            hot_water_view(config),
            costs_view(config),
            appliances_view(config),
            history_view(config),
            energy_view(),
            health_view(config),
        ],
    }


def walk_cards(dashboard: dict):
    for page in dashboard["views"]:
        for grid in page["sections"]:
            yield from grid["cards"]


def referenced_entities(dashboard: dict) -> set[str]:
    found = set()
    for card in walk_cards(dashboard):
        if "entity" in card:
            found.add(card["entity"])
        for row in card.get("entities", []):
            found.add(row["entity"] if isinstance(row, dict) else row)
    return found
