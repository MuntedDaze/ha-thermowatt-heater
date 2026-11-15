"""English source for supported HA form translations (no runtime policy)."""

from .configuration import FIELDS, MENUS, PAGES, SOURCES, display_value
from .config import CLOUD_SOURCES

TITLES = {
    "init": "Settings",
    "hot_water": "Hot Water",
    "electricity": "Electricity Tariffs",
    "solar_meters": "Solar & Meters",
    "advanced": "Advanced/System",
    "prices": "Plan, prices and clock",
    "peak_times": "Two-peak example hours",
    "schedule": "Guided weekly and seasonal schedule",
    "tariff_json": "Advanced: raw schedule data",
    "solar": "Solar forecasts and grid meter",
    "sources": "Solar and meter readings",
    "equipment": "Equipment and economic assumptions",
    "polling": "Cloud checks and data freshness",
    "commissioning": "Advanced: commissioning and command safeguards",
    "bridge_sources": "Bridge status readings",
}
DESCRIPTIONS = {
    "init": "Everyday choices are in Hot Water. Electricity Tariffs describes your bill; Solar & Meters connects optional readings. Advanced/System is for experienced users and supervised commissioning. Turn off Automatic heater control before changing protected settings. Each page saves separately; closing without saving leaves it unchanged.",
    "hot_water": "Choose thermostat targets and permitted heating. Your saved temperatures are retained. The owner's agreed example is 45°C baseline / 62°C normal / 70°C optional solar, with peak OFF. It is not a universal hygiene recommendation. Follow the appliance instructions and your plumber's advice. {detail}",
    "electricity": "Use your actual retailer's usage prices and times, not a network tariff assumed to be your bill. Start with Plan, prices and clock. Flat plans need no time periods. The two-peak example and the guided custom schedule are alternative schedules for the same tariff model; the chosen plan type decides which is active.",
    "solar_meters": "Everything here is optional for basic tariff-based heating. Without a dedicated hot-water circuit meter, normal required heating uses conservative estimates; electrical ON/OFF is unverified and optional solar-only boost is unavailable. A missing previously commissioned meter remains a fault.",
    "advanced": "Engineering and commissioning settings. Leave qualifications, learning and adaptive control off until separately approved checks pass. These pages do not enable automatic heating. Existing command verification, fault locks and owner protections still apply.",
    "prices": "Prices below are Australian cents per kWh (25 means $0.25/kWh). Check the retail contract's tax basis consistently. Off-peak is usually cheaper, peak usually dearer, and shoulder is the period between them. Daily supply charges do not affect heating-window choices. Your saved values are prefilled, not replaced by example prices. {detail}",
    "peak_times": "These hours apply only when the Aurora-style two-peak example is selected. They are tariff-clock times, not necessarily the summer wall clock. Other plans should use the guided custom schedule. All four times must increase. {detail}",
    "tariff_json": "Expert alternative; most users should choose the guided schedule. This edits the saved custom table, but does not select Custom automatically. JSON rate overrides use dollars/kWh. Every day in every month needs complete coverage without overlaps. {detail}",
    "solar": "Forecasts predict future solar and household demand; they do not prove spare electricity. Basic tariff control needs neither solar nor EMHASS. Verified grid export can help choose required off-peak heating without a circuit meter; optional solar-only heating still requires one. {detail}",
    "sources": "Select existing Home Assistant readings, not device names. Leave optional fields blank when equipment is absent. This page only reads local states. Changing the hot-water power mapping clears its commissioning/learning qualification. Bridge status mappings are in Advanced/System.",
    "bridge_sources": "Required readings from the existing Thermann bridge. Selecting entities reads their states; it neither contacts the vendor nor sends heater commands. Change mappings only with automatic control off.",
    "equipment": "Advanced planning assumptions, not new heater qualifications. Use appliance-label ratings; estimates do not prove actual element operation or whole-tank temperature. Do not adjust assumptions just to make a prediction look better. {detail}",
    "polling": "Advanced: preview and actual adaptive checks are different. Longer quiet intervals reduce requests but delay noticing app changes. Default-off qualification gates and the original fixed fallback remain. A fresh command prior and confirmation are always required. {detail}",
    "commissioning": "Advanced; do not tick qualifications to bypass a warning. Follow separately approved supervised commissioning. Saving this form neither authorises physical tests nor turns on automatic control. Leave command address/CT record blank if not commissioned. {detail}",
}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
KINDS = {
    "off_peak": "Off-peak / low-cost",
    "shoulder": "Shoulder / intermediate",
    "peak": "Peak / restricted heating",
}
SELECT_LABELS = {
    "tariff_profile": {
        "flat": "Flat rate — one price all day",
        "aurora_93": "Aurora-style two-peak example (verify your contract)",
        "custom": "Custom weekly / seasonal schedule",
    },
    "tariff_clock": {
        "standard": "Fixed standard time — no daylight saving",
        "local": "Local time — follows daylight saving",
    },
    "days": {str(i): day for i, day in enumerate(DAYS)},
    "months": {str(i + 1): month for i, month in enumerate(MONTHS)},
    "period_kind": KINDS,
    "schedule_action": {
        "edit": "Edit a period",
        "add": "Add a period",
        "delete": "Remove a period",
        "save": "Save and use this custom schedule",
    },
}


def schedule_summary(rows, values):
    lines = [
        f"Active plan: {SELECT_LABELS['tariff_profile'][values['tariff_profile']]}. Draft periods:"
    ]
    for i, row in enumerate(rows):
        days = ", ".join(DAYS[d][:3] for d in row["days"])
        months = row.get("months", list(range(1, 13)))
        season = "all year" if len(months) == 12 else ", ".join(MONTHS[m - 1][:3] for m in months)
        rate = row.get("rate", values[f"{row['kind']}_rate"])
        price = display_value("off_peak_rate", rate)
        lines.append(
            f"- {i + 1}. {days}; {season}; {row['start']}–{row['end']}; {KINDS[row['kind']]}; {price:g} c/kWh"
        )
    return "\n".join(lines)


def flow_text():
    steps = {
        k: {"title": TITLES[k], "description": DESCRIPTIONS[k]} for k in TITLES if k != "schedule"
    }
    for page, keys in PAGES.items():
        steps[page].update(
            data={k: FIELDS[k][0] for k in keys},
            data_description={k: FIELDS[k][1] for k in keys},
        )
    for page in ("sources", "bridge_sources"):
        keys = [k for k in SOURCES if (k in CLOUD_SOURCES) == (page == "bridge_sources")]
        steps[page].update(
            data={k: SOURCES[k][0] for k in keys},
            data_description={k: SOURCES[k][1] for k in keys},
        )
    for menu, children in MENUS.items():
        steps[menu]["menu_options"] = {k: TITLES[k] for k in children}
    steps["schedule"] = {
        "title": TITLES["schedule"],
        "description": "Edits stay in this draft until you choose Save and use. Closing cancels the draft. Save selects Custom but never verifies your contract. Cover every minute of all weekdays and months exactly once, up to 32 periods. Midnight to midnight means all day; an end earlier than the start crosses midnight. Month selection follows the current tariff-clock date, including overnight tails.\n\n{periods}\n\n{detail}",
        "data": {"action": "What would you like to do?", "period": "Period to edit or remove"},
        "data_description": {
            "action": "Add or edit periods as needed, then explicitly Save and use. Invalid schedules save nothing. Removal needs confirmation.",
            "period": "Choose a numbered period from the draft above. Not needed when adding or saving. Rates shown use the prices saved on the Prices page unless the period has its own override.",
        },
    }
    steps["period"] = {
        "title": "Edit an electricity period",
        "description": "This changes the draft only. Use your retailer's actual periods, including weekends and seasonal differences. All months are selected initially. The full schedule is validated on final Save; gaps and overlaps must be fixed before anything is stored.",
        "data": {
            "days": "Days this period starts",
            "start": "Starts at",
            "end": "Ends at",
            "kind": "Type of period",
            "months": "Months when this period applies",
            "use_rate": "Use a different price for this period",
            "rate": "This period's electricity price",
        },
        "data_description": {
            "days": "Select one or more weekdays. An overnight period continues into the next day; provide complete coverage of every day.",
            "start": "Time on the selected tariff clock. Same start and end means a full day, not zero hours.",
            "end": "End is exclusive: 07:00–10:00 ends as 10:00 begins. An earlier end crosses midnight. Use 00:00 for midnight.",
            "kind": "Off-peak means permitted low-cost hours, shoulder intermediate hours, and peak invokes your peak-heating policy. A cheap price does not cancel a peak restriction.",
            "months": "Select all 12 for year-round service. For seasonal plans, every day of every month must still be covered. Overnight month matching follows the current tariff-clock date.",
            "use_rate": "Leave off to use the matching off-peak, shoulder or peak price from the Prices page. On allows a midday discount or seasonal override. No additional pricing engine is created.",
            "rate": "Australian cents/kWh, for example 15 means $0.15/kWh. Ignored when the separate-price switch is off. Limited to the same supported non-negative retail-price range.",
        },
        "submit": "Update draft",
    }
    steps["delete_period"] = {
        "title": "Remove this draft period?",
        "description": "Removal changes this draft only. Replace any uncovered hours before the final Save; the stored schedule stays unchanged until then.",
        "data": {"confirm": "Remove the selected period"},
        "data_description": {
            "confirm": "Leave off to keep it and return to the draft. Closing the whole flow discards all draft changes."
        },
    }
    return {
        "step": steps,
        "error": {
            "invalid_settings": "Nothing saved. {detail}",
            "locked_while_active": "{detail}",
            "choose_period": "Choose a period to edit/remove, or add a period (maximum 32).",
            "invalid_period": "Choose at least one day and month, valid times and a supported price. The draft was not changed.",
        },
    }
