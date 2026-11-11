"""Plain-language shadow decisions. Pure functions; never a command or physical state."""

LABELS = {
    "paused": "PAUSED",
    "owner_review_required": "OWNER REVIEW",
    "data_unavailable": "DATA UNAVAILABLE",
    "no_topup_required": "NO HEATING NEEDED",
    "insufficient_time": "INSUFFICIENT TIME",
    "heat_now_solar": "HEAT NOW",
    "heat_now_partial_solar": "HEAT NOW",
    "heat_now_grace_period": "HEAT NOW",
    "begin_grid_fallback": "GRID FALLBACK",
    "qualifying_solar": "WAIT FOR SOLAR",
    "wait_for_forecast_solar": "WAIT FOR SOLAR",
    "forecast_unavailable_conservative_fallback": "WAIT FOR PLANNED WINDOW",
    "wait_for_cheaper_window": "WAIT FOR PLANNED WINDOW",
}
BLOCKED = {"shadow_blocked", "shadow_awaiting_validation"}


def _money(value):
    return "unknown" if value is None else f"${value:.2f}"


def decide(plan, cycle, active, forecast_enabled, forecast_source, settings):
    """Return (code, label, explanation) for the SIMULATED recommendation.

    Order is the planning priority: owner/data gates, comfort, solar, cost.
    """
    if plan.state == "shadow_paused":
        code, text = "paused", "Shadow planning is paused by the owner. Native Schedule continues."
    elif plan.state == "shadow_native_intervention":
        code = "owner_review_required"
        text = (
            "The heater's native mode or target changed. Planning is latched for owner review; "
            "nothing is sent to the heater."
        )
    elif cycle["reason"] == "thermostat_satisfied":
        code = "no_topup_required"
        text = "The heater's own thermostat reports it is satisfied. No further heat is needed."
    elif cycle["reason"] in {"manufacturer_protection", "fault", "owner_intervention"}:
        code = "owner_review_required"
        text = "A protection, fault or owner action takes priority. Nothing is sent to the heater."
    elif plan.state in BLOCKED or cycle["state"] == "suspended":
        code = "data_unavailable"
        text = (
            "Fresh, healthy heater and meter readings are needed before a recommendation. "
            "Native Schedule remains the real comfort fallback."
        )
    elif cycle["state"] == "simulated_satisfied":
        code = "no_topup_required"
        target = plan.planning_target_c
        text = (
            f"The bottom sensor already meets the {target:g}°C goal for the next deadline."
            if target is not None
            else "No additional heat is modelled before the next deadline."
        )
    elif active and cycle["continuing_cost_aud"] is None:
        # Uses the cycle's OWN remaining energy (credited with heat delivered since
        # the last 30-minute poll), not the plan's stale-reading shortfall.
        code = "insufficient_time"
        text = (
            "There is not enough time left to reach the goal before the deadline, even heating "
            "continuously from now. Heat immediately (hypothetically) and expect a shortfall."
        )
    elif active:
        fraction = cycle["current_solar_fraction"]
        surplus = fraction * 3
        if fraction >= 0.999:
            code = "heat_now_solar"
            text = (
                f"About {surplus:.1f} kW of measured surplus covers the whole 3 kW element. "
                f"Estimated cycle cost {_money(cycle['continuing_cost_aud'])}."
            )
        elif fraction > 0:
            code = "heat_now_partial_solar"
            text = (
                f"About {surplus:.1f} kW of measured surplus covers {fraction:.0%} of the 3 kW "
                "element; the rest is imported. "
                + (
                    "Comfort requires heating now; solar reduces the import. "
                    if cycle["start_reason"] == "comfort"
                    else "Including foregone feed-in, this beats the grid alternative. "
                )
                + f"Estimated cycle cost {_money(cycle['continuing_cost_aud'])}."
            )
        elif cycle["start_reason"] == "comfort":
            code = "begin_grid_fallback"
            text = (
                "The conservative grid fallback is due: heat now to protect the comfort deadline, "
                "whatever the forecast says. "
                f"Estimated cost {_money(cycle['continuing_cost_aud'])}."
            )
        else:
            code = "heat_now_grace_period"
            text = (
                "Solar has dropped, but the cycle continues through the grace period or minimum "
                "cycle time rather than switching on every cloud."
            )
    elif cycle["economic_opportunity"]:
        code = "qualifying_solar"
        text = (
            f"A useful solar surplus must stay worthwhile for {settings.solar_hold_minutes:g} "
            "minutes (and respect the minimum gap) before a hypothetical cycle starts."
        )
    elif forecast_enabled and forecast_source != "published_pv_and_house_load":
        code = "forecast_unavailable_conservative_fallback"
        text = (
            "The solar/load forecast is unavailable or stale, so no future solar is assumed. "
            "Wait for the planned off-peak window; the grid fallback is reserved."
        )
    elif (
        forecast_source == "published_pv_and_house_load"
        and cycle["later_solar_kwh"]
        and cycle["later_solar_kwh"] > 0.01
    ):
        code = "wait_for_forecast_solar"
        text = (
            f"A later window is forecast to be cheaper ({_money(cycle['later_cost_aud'])} vs "
            f"{_money(cycle['continuing_cost_aud'])} now) using about "
            f"{cycle['later_solar_kwh']:.1f} kWh of solar. The grid fallback is still reserved."
        )
    else:
        code = "wait_for_cheaper_window"
        text = (
            "Heating now has no worthwhile advantage. Wait for the planned window; the "
            "conservative grid fallback is reserved and starts automatically when due."
        )
    return code, LABELS[code], text
