"""Comfort-constrained, cost-first heating strategies. Pure functions, no I/O.

Priorities: (1) manufacturer safety (never a setpoint below the native target;
the native thermostat stays in charge), (2) comfort deadlines, (3) minimum total
economic cost including foregone feed-in, (4) solar self-consumption when cost
is equal, (5) fewer heating blocks.

Incremental cost of running the fixed 3 kW element in a slot, relative to NOT
running it, with AC solar P and BASE household load B (the real element removed):

    s    = min(3, max(0, P - B))                # solar the element would absorb
    cost = hours * (feed_in * s + import_rate * (3 - s))

e.g. 1 kW exported while the heater is available: off-peak 1*0.09276 + 2*0.1702 =
$0.4332/h; peak 1*0.09276 + 2*0.361878 = $0.8165/h.

Every compared plan delivers the SAME required energy by each deadline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math

from .goals import Goal
from .model import ELEMENT_KW, HOBART, TANK_KWH_PER_C, Settings, Tariff, tariff_at

SLOT = timedelta(minutes=15)
FULL_SLOT_KWH = ELEMENT_KW * SLOT.total_seconds() / 3600
NEAR_TERM = timedelta(minutes=30)  # measured PV persistence horizon
MEASURED_BASE_HORIZON = timedelta(hours=2)
BLOCK_PENALTY_AUD = 0.01  # tie-breaker against fragmented plans, not a real cost
MAX_BLOCKS = 3


@dataclass
class Slot:
    start: datetime
    end: datetime
    hours: float
    rate: float
    pv50: float
    pv10: float
    base50: float
    base90: float
    measured: bool

    def solar(self, pessimistic: bool = False) -> float:
        pv, base = (self.pv10, self.base90) if pessimistic else (self.pv50, self.base50)
        return min(ELEMENT_KW, max(0.0, pv - base))

    def cost(self, feed_in: float, pessimistic: bool = False) -> float:
        s = self.solar(pessimistic)
        return self.hours * (feed_in * s + self.rate * (ELEMENT_KW - s))

    @property
    def capacity(self) -> float:
        return ELEMENT_KW * self.hours


@dataclass
class PlanResult:
    name: str
    feasible: bool
    blocks: list[tuple[datetime, datetime]] = field(default_factory=list)
    energy_kwh: float = 0.0
    cost_aud: float = 0.0
    pessimistic_cost_aud: float = 0.0
    solar_kwh: float = 0.0
    import_kwh: float = 0.0
    shortfall_kwh: float = 0.0
    objective: float = 0.0  # optimiser objective incl. tie-breakers (not a cost)

    @property
    def start(self) -> datetime | None:
        return self.blocks[0][0] if self.blocks else None

    @property
    def end(self) -> datetime | None:
        return self.blocks[-1][1] if self.blocks else None

    def summary(self) -> dict:
        return {
            "name": self.name,
            "feasible": self.feasible,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "blocks": [[a.isoformat(), b.isoformat()] for a, b in self.blocks],
            "energy_kwh": round(self.energy_kwh, 3),
            "cost_aud": round(self.cost_aud, 3),
            "pessimistic_cost_aud": round(self.pessimistic_cost_aud, 3),
            "solar_kwh": round(self.solar_kwh, 3),
            "import_kwh": round(self.import_kwh, 3),
            "solar_share": round(self.solar_kwh / self.energy_kwh, 3) if self.energy_kwh else 0.0,
            "shortfall_kwh": round(self.shortfall_kwh, 3),
        }


def series_value(series, at: datetime) -> float | None:
    """Step-held value of [(start, end, kW), ...] at `at`, else None (gap)."""
    for start, end, value in series:
        if start <= at < end:
            return value
    return None


def build_slots(
    now: datetime,
    horizon: datetime,
    settings: Settings,
    tariffs: tuple[Tariff, ...],
    pv_now_kw: float | None,
    base_now: tuple[float | None, float | None],
    base_p90_kw: float | None,
    pv_series=(),
    load_series=(),
) -> list[Slot]:
    """15-minute slots from `now` to `horizon` (first slot partial).

    PV: measured AC for the first 30 minutes, then the (corrected, clipped)
    forecast, else ZERO - never extrapolated. Base load: measured estimate for
    two hours, then per `base_load_source`. With an UNKNOWN element state the
    near-term base uses the LOW bound (heater assumed on), which makes heating
    now look cheaper: the robust choice against needless waiting.
    """
    limit = settings.pv_ac_limit_kw
    u = settings.forecast_uncertainty
    low, high = base_now
    base_mid = low if low is not None else (high if high is not None else 0.5)
    base_90 = max(base_p90_kw or 0.0, high if high is not None else base_mid)
    slots = []
    cursor = now
    first_end = now.replace(second=0, microsecond=0)
    first_end += timedelta(minutes=15 - first_end.minute % 15)
    while cursor < horizon:
        end = min(first_end if cursor == now else cursor + SLOT, horizon)
        if end <= cursor:
            end = min(cursor + SLOT, horizon)
        hours = (end - cursor).total_seconds() / 3600
        minutes = max(1, int(round(hours * 60)))
        rate = (
            sum(
                tariff_at(cursor + timedelta(minutes=step), tariffs, settings.tariff_clock).rate
                for step in range(minutes)
            )
            / minutes
        )
        middle = cursor + (end - cursor) / 2
        measured = cursor - now < NEAR_TERM and pv_now_kw is not None
        if measured:
            pv50 = min(limit, max(0.0, pv_now_kw))
        else:
            value = series_value(pv_series, middle)
            pv50 = min(limit, max(0.0, value)) if value is not None else 0.0
        pv10 = pv50 * (1 - u)
        if cursor - now < MEASURED_BASE_HORIZON or settings.base_load_source == "measured_only":
            b50, b90 = base_mid, base_90
        else:
            published = series_value(load_series, middle)
            if published is None or settings.base_load_source == "measured_only":
                b50, b90 = base_mid, base_90
            else:
                b50 = published
                b90 = published * (1 + u) + settings.forecast_house_margin_kw
        slots.append(Slot(cursor, end, hours, rate, pv50, pv10, b50, b90, measured))
        cursor = end
    return slots


def requirements(
    now: datetime, temperature: float, goals: list[Goal], settings: Settings
) -> list[tuple[Goal, float]]:
    """Energy needed (kWh) by each deadline, from the current reading.

    Each requirement is cumulative from now: heat delivered for the morning also
    counts towards the afternoon, minus standing loss and the expected morning
    draw when a morning deadline falls before the afternoon one. These draw/loss
    values are owner-editable ASSUMPTIONS, not measurements.
    """
    result = []
    for goal in goals:
        hours = max(0.0, (goal.deadline - now).total_seconds() / 3600)
        effective = temperature - settings.standing_loss_c_per_hour * hours
        if goal.kind == "afternoon" and any(
            other.kind == "morning" and now < other.deadline < goal.deadline for other in goals
        ):
            effective -= settings.expected_morning_draw_c
        result.append((goal, TANK_KWH_PER_C * max(0.0, goal.target_c - effective)))
    return result


def _deadline_index(slots: list[Slot], deadline: datetime) -> int:
    """Number of leading slots that END at or before the deadline."""
    count = 0
    for slot in slots:
        if slot.end <= deadline:
            count += 1
        else:
            break
    return count


def optimise(
    slots: list[Slot],
    needs: list[tuple[int, float]],
    feed_in: float,
    force_first: bool | None = None,
    max_blocks: int = MAX_BLOCKS,
    prefix_slots: int = 1,
) -> PlanResult | None:
    """Exact minimum-cost choice of slots (<= max_blocks contiguous blocks).

    needs: [(deadline_index, kWh)] cumulative from slot 0. Full slots carry
    FULL_SLOT_KWH; the first slot may be partial. The last chosen slot is
    trimmed so the plan delivers exactly the largest requirement.
    force_first=True forces the first `prefix_slots` slots on ("start now and
    keep going for a minimum cycle"), False forces slot 0 off, None is free.
    """
    if not slots:
        return None
    total = max((kwh for _, kwh in needs), default=0.0)
    if total <= 1e-9:
        return PlanResult("none", True)
    n = len(slots)
    best = None
    options = (True, False) if force_first is None else (force_first,)
    INF = float("inf")
    for first in options:
        prefix = min(n, max(1, prefix_slots)) if first else 1
        # Forced prefix (or a single forced-off slot 0) is decided up front.
        on_prefix = list(range(prefix)) if first else []
        credit = slots[0].capacity if first else 0.0
        initial_units = prefix - 1 if first else 0
        units: dict[int, int] = {}
        feasible = True
        for idx, kwh in needs:
            if idx <= prefix:
                delivered = sum(slots[k].capacity for k in on_prefix if k < idx)
                if delivered < kwh - 1e-9:
                    feasible = False
            need = max(0, math.ceil((kwh - credit) / FULL_SLOT_KWH - 1e-9))
            units[idx] = max(units.get(idx, 0), need)
        if not feasible:
            continue
        cap_units = max(units.values()) if units else 0
        start_cost = sum(slots[k].cost(feed_in) for k in on_prefix)
        state0 = (min(cap_units, initial_units), 1 if first else 0, first)
        states = {state0: (start_cost, None)}
        history = [states]
        for k in range(prefix, n):
            # Negligible tie-breakers never outweigh real cost: with solar,
            # prefer EARLIER (known sun beats forecast sun); without solar,
            # prefer LATER (less standing loss).
            tie = 1e-6 * k if slots[k].solar() > 0.05 else 1e-6 * (n - k)
            cost_on = slots[k].cost(feed_in) + tie
            nxt = {}
            for (d, b, on), (cost, _) in states.items():
                key = (d, b, False)
                if cost < nxt.get(key, (INF, None))[0]:
                    nxt[key] = (cost, (d, b, on, False))
                nb = b if on else b + 1
                if nb <= max_blocks:
                    key = (min(cap_units, d + 1), nb, True)
                    added = cost_on + (0.0 if on else BLOCK_PENALTY_AUD)
                    if cost + added < nxt.get(key, (INF, None))[0]:
                        nxt[key] = (cost + added, (d, b, on, True))
            for idx, need in units.items():
                if idx == k + 1:
                    nxt = {key: val for key, val in nxt.items() if key[0] >= need}
            states = nxt
            history.append(states)
            if not states:
                break
        if not states:
            continue
        final = {key: val for key, val in states.items() if key[0] >= cap_units}
        if not final:
            continue
        key = min(final, key=lambda item: final[item][0])
        chosen = [False] * n
        for k in on_prefix:
            chosen[k] = True
        for step in range(len(history) - 1, 0, -1):
            d, b, on, was_on = history[step][key][1]
            chosen[prefix + step - 1] = was_on
            key = (d, b, on)
        plan = _materialise(slots, chosen, total, feed_in)
        # Compare options on EXACT (trimmed) cost so unit rounding inside the
        # optimiser cannot decide between them; ties keep the tie-break rule.
        plan.objective = round(plan.cost_aud + BLOCK_PENALTY_AUD * len(plan.blocks), 3)
        if (
            best is None
            or plan.objective < best.objective
            or (
                plan.objective == best.objective
                and (plan.start > best.start) == (slots[0].solar() <= 0.05)
                and plan.start != best.start
            )
        ):
            best = plan
    return best


def _materialise(slots: list[Slot], chosen: list[bool], total: float, feed_in: float) -> PlanResult:
    delivered = sum(slot.capacity for slot, on in zip(slots, chosen, strict=True) if on)
    excess = max(0.0, delivered - total)
    plan = PlanResult("plan", True, energy_kwh=min(delivered, total))
    last = max((k for k, on in enumerate(chosen) if on), default=None)
    for k, (slot, on) in enumerate(zip(slots, chosen, strict=True)):
        if not on:
            continue
        fraction = 1.0
        end = slot.end
        if k == last and excess > 1e-9:
            fraction = max(0.0, 1 - excess / slot.capacity)
            end = slot.start + (slot.end - slot.start) * fraction
        plan.cost_aud += slot.cost(feed_in) * fraction
        plan.pessimistic_cost_aud += slot.cost(feed_in, True) * fraction
        solar = slot.solar() * slot.hours * fraction
        plan.solar_kwh += solar
        plan.import_kwh += slot.capacity * fraction - solar
        if plan.blocks and plan.blocks[-1][1] == slot.start:
            plan.blocks[-1] = (plan.blocks[-1][0], end)
        else:
            plan.blocks.append((slot.start, end))
    return plan


def continuous_from(
    slots: list[Slot], start_index: int, needs: list[tuple[int, float]], feed_in: float
) -> PlanResult:
    """Heat continuously from slot `start_index` until every requirement is met."""
    total = max((kwh for _, kwh in needs), default=0.0)
    chosen = [False] * len(slots)
    delivered = 0.0
    for k in range(start_index, len(slots)):
        if delivered >= total - 1e-9:
            break
        chosen[k] = True
        delivered += slots[k].capacity
    plan = _materialise(slots, chosen, total, feed_in)
    feasible = True
    for idx, kwh in needs:
        by = sum(slots[k].capacity for k in range(min(idx, len(slots))) if chosen[k])
        if by < kwh - 1e-6:
            feasible = False
            plan.shortfall_kwh = max(plan.shortfall_kwh, kwh - by)
    plan.feasible = feasible
    return plan


def fallback_start(deadline: datetime, kwh: float, allowance_minutes: float) -> datetime:
    """Latest start of a continuous full-power block that still meets `deadline`."""
    return deadline - timedelta(hours=kwh / ELEMENT_KW, minutes=allowance_minutes)


@dataclass
class Assessment:
    code: str
    label: str
    explanation: str
    confidence: str
    plans: dict[str, PlanResult]
    requirements: list[tuple[Goal, float]]
    fallback: dict[str, datetime]
    saving_by_waiting_aud: float | None
    heat_now_cost_aud: float | None
    best_cost_aud: float | None
    native: dict | None = None
    warnings: list[str] = field(default_factory=list)


LABELS = {
    "heat_now_cheapest": "HEAT NOW",
    "heat_now_saving_too_small": "HEAT NOW",
    "heat_now_comfort_fallback": "HEAT NOW",
    "native_heating_economical": "HEATING NOW (NATIVE)",
    "native_heating_costlier_than_waiting": "HEATING NOW (NATIVE)",
    "wait_cheaper_later": "WAIT - CHEAPER LATER",
    "flexible_no_cost_difference": "NO HURRY",
    "no_heating_needed": "NO HEATING NEEDED",
    "insufficient_time": "INSUFFICIENT TIME",
}


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.2f}"


def _local(at: datetime | None) -> str:
    return at.astimezone(HOBART).strftime("%a %H:%M") if at else "unknown"


def assess(
    now: datetime,
    temperature: float,
    goals: list[Goal],
    slots: list[Slot],
    settings: Settings,
    element_state: str,
    forecast_available: bool,
    native: dict | None = None,
    storage_satisfied: bool = False,
) -> Assessment:
    """Compare heat-now, single-block, split and fallback plans; decide honestly.

    storage_satisfied: the native thermostat switched the element off inside a
    permitted window (it controls from its own sensor; on 10 Nov it stopped with
    the reading at 63 °C). Storage goals then count as met until water is used.
    """
    feed_in = settings.feed_in_rate
    reqs = requirements(now, temperature, goals, settings)
    if storage_satisfied:
        reqs = [
            (goal, 0.0 if goal.kind == "afternoon" or temperature >= goal.target_c else kwh)
            for goal, kwh in reqs
        ]
    allowance = timedelta(minutes=settings.margin_minutes)
    # Physical feasibility uses the true deadlines; plans keep the allowance.
    needs_real = [(_deadline_index(slots, goal.deadline), kwh) for goal, kwh in reqs]
    needs = [(_deadline_index(slots, goal.deadline - allowance), kwh) for goal, kwh in reqs]
    total = max((kwh for _, kwh in needs), default=0.0)
    fallbacks = {
        goal.kind: fallback_start(goal.deadline, kwh, settings.margin_minutes)
        for goal, kwh in reqs
        if kwh > 1e-9
    }
    warnings = []
    plans: dict[str, PlanResult] = {}
    if total <= 1e-9:
        code = "native_heating_economical" if element_state == "on" else "no_heating_needed"
        text = (
            "The native thermostat switched the element off inside its window, so storage "
            "counts as ready (its own sensor reached the target) until water is used. "
            if storage_satisfied
            else "Both readiness goals are already met on the current reading. "
        ) + (
            "The native Schedule is heating anyway (its own 70 °C target)."
            if element_state == "on"
            else "No heating is needed before the next deadlines."
        )
        return Assessment(
            code, LABELS[code], text, "high", plans, reqs, fallbacks, None, None, None, native
        )
    now_plan = continuous_from(slots, 0, needs_real, feed_in)
    now_plan.name = "heat_now_continuous"
    plans["heat_now_continuous"] = now_plan
    if not now_plan.feasible:
        code = "insufficient_time"
        text = (
            f"Even heating continuously from now cannot meet every goal: about "
            f"{now_plan.shortfall_kwh:.1f} kWh ({now_plan.shortfall_kwh / TANK_KWH_PER_C:.0f} °C) "
            "short. Heat as early as possible and expect reduced comfort."
        )
        return Assessment(
            code,
            LABELS[code],
            text,
            "high",
            plans,
            reqs,
            fallbacks,
            None,
            now_plan.cost_aud,
            None,
            native,
        )
    best = optimise(slots, needs, feed_in)
    # "Heat now" means start now AND keep going for at least the minimum cycle;
    # a 15-minute token start then a wait would understate the saving.
    prefix = max(1, math.ceil(settings.minimum_cycle_minutes / 15))
    best_now = optimise(slots, needs, feed_in, force_first=True, prefix_slots=prefix)
    single = optimise(slots, needs, feed_in, max_blocks=1)
    single_later = optimise(slots, needs, feed_in, force_first=False, max_blocks=1)
    for name, plan in (
        ("best_overall", best),
        ("best_starting_now", best_now),
        ("best_single_block", single),
        ("best_single_block_later", single_later),
    ):
        if plan is not None:
            plan.name = name
            plans[name] = plan
    earliest_fallback = min(fallbacks.values()) if fallbacks else None
    heat_now_cost = best_now.cost_aud if best_now else now_plan.cost_aud
    best_cost = best.cost_aud if best else heat_now_cost
    saving = heat_now_cost - best_cost
    # The decision is "start now (for at least the minimum cycle) or not", so the
    # saving must be worthwhile per kWh that would otherwise be heated NOW.
    committed = min(total, sum(s.capacity for s in slots[:prefix]))
    threshold = settings.wait_benefit_aud_per_kwh * committed
    solar_now = slots[0].solar() if slots else 0.0
    if best is None or (earliest_fallback is not None and now >= earliest_fallback - SLOT):
        code = "heat_now_comfort_fallback"
        text = (
            f"The comfort fallback is due ({_local(earliest_fallback)} latest start with the "
            f"{settings.margin_minutes:g}-minute allowance). Heat now, whatever the forecast."
        )
        confidence = "high"
    elif best is not None and best.start is not None and best.start <= now:
        code = "heat_now_cheapest"
        share = best.solar_kwh / best.energy_kwh if best.energy_kwh else 0
        text = (
            f"Heating now is part of the cheapest plan: {_money(best.cost_aud)} for "
            f"{best.energy_kwh:.1f} kWh ({share:.0%} solar, including foregone feed-in)."
        )
        confidence = "high" if forecast_available else "medium"
    elif saving > threshold and best is not None:
        code = "wait_cheaper_later"
        later_robust = (best_now.pessimistic_cost_aud if best_now else heat_now_cost) - (
            best.pessimistic_cost_aud
        )
        confidence = (
            "high"
            if forecast_available and later_robust > threshold
            else "medium"
            if forecast_available
            else "low"
        )
        text = (
            f"Waiting until {_local(best.start)} saves about {_money(saving)} "
            f"({_money(best.cost_aud)} vs {_money(heat_now_cost)} starting now) for the same "
            f"{best.energy_kwh:.1f} kWh. Latest safe start: {_local(earliest_fallback)}."
        )
        if confidence != "high":
            text += " The saving depends on the forecast; the fallback still protects comfort."
    elif solar_now > 0.05:
        code = "heat_now_saving_too_small"
        text = (
            f"About {solar_now:.1f} kW of solar is available now and waiting would save only "
            f"{_money(max(0.0, saving))} (threshold {_money(threshold)} for the {committed:.1f} kWh heated first), "
            "so heating now is preferred for certainty."
        )
        confidence = "medium"
    else:
        code = "flexible_no_cost_difference"
        text = (
            f"No meaningful cost difference between heating now and later "
            f"({_money(max(0.0, saving))}). Heat any time before {_local(earliest_fallback)}; "
            "later loses less heat."
        )
        confidence = "medium"
    if element_state == "on":
        if code == "wait_cheaper_later":
            code = "native_heating_costlier_than_waiting"
            text = (
                f"The native Schedule is heating now. The planner's cheapest plan would wait "
                f"until {_local(best.start if best else None)}, saving about {_money(saving)}. "
                "Advisory only: nothing is sent to the heater."
            )
        else:
            code = "native_heating_economical"
            text = "The native Schedule is heating now, which matches the cheapest plan. " + text
    if not forecast_available:
        warnings.append("no_qualified_forecast_future_solar_assumed_zero")
    if element_state == "unknown":
        warnings.append("element_state_unknown_near_term_assumes_heater_load_may_be_present")
    return Assessment(
        code,
        LABELS[code],
        text,
        confidence,
        plans,
        reqs,
        fallbacks,
        round(saving, 3),
        round(heat_now_cost, 3),
        round(best_cost, 3),
        native,
        warnings,
    )


def native_outlook(
    now: datetime,
    temperature: float,
    goals: list[Goal],
    slots: list[Slot],
    settings: Settings,
    in_window,
    element_on: bool,
) -> dict:
    """Predict what the native Schedule will do: heat in permitted windows until
    its own target. Optimistic about the thermostat (it may not start within its
    hysteresis band); this is a comparison, not a forecast of the device."""
    feed_in = settings.feed_in_rate
    target = settings.expected_native_target_c
    need = TANK_KWH_PER_C * max(0.0, target - temperature)
    reqs = requirements(now, temperature, goals, settings)
    # The thermostat keeps reheating after draws, so cover the draw-inclusive
    # requirement too (whichever is larger).
    floor = max((kwh for _, kwh in reqs), default=0.0)
    delivered, cost, solar = 0.0, 0.0, 0.0
    chosen = []
    for k, slot in enumerate(slots):
        hours = (slot.end - now).total_seconds() / 3600
        need_now = max(floor, need + TANK_KWH_PER_C * settings.standing_loss_c_per_hour * hours)
        allowed = in_window(slot.start) or (k == 0 and element_on)
        if allowed and delivered < need_now - 1e-9:
            fraction = min(1.0, (need_now - delivered) / slot.capacity)
            delivered += slot.capacity * fraction
            cost += slot.cost(feed_in) * fraction
            solar += slot.solar() * slot.hours * fraction
            chosen.append((slot.start, slot.start + (slot.end - slot.start) * fraction))
    readiness = {}
    for goal, kwh in reqs:
        by = sum(
            (end - start).total_seconds() / 3600 * ELEMENT_KW
            for start, end in chosen
            if end <= goal.deadline
        )
        readiness[goal.kind] = {
            "deadline": goal.deadline.isoformat(),
            "required_kwh": round(kwh, 3),
            "native_delivered_kwh": round(by, 3),
            "met": by >= kwh - 1e-6,
        }
    return {
        "predicted_energy_kwh": round(delivered, 3),
        "predicted_cost_aud": round(cost, 3),
        "predicted_solar_kwh": round(solar, 3),
        "first_heating": chosen[0][0].isoformat() if chosen else None,
        "readiness": readiness,
        "assumption": "native heats in permitted windows until its own target; thermostat hysteresis may delay it",
    }


# Candidate native Schedule window sets for the read-only Schedule advisor.
# (days, start minute, end minute) in the native clock. Weekends keep 06-22.
WEEKEND = ((5, 6), 6 * 60, 22 * 60)
SCHEDULE_CANDIDATES = {
    "morning 04-07, solar 10-16": (
        ((0, 1, 2, 3, 4), 240, 420),
        ((0, 1, 2, 3, 4), 600, 960),
        WEEKEND,
    ),
    "morning 05-08, solar 11-16": (
        ((0, 1, 2, 3, 4), 300, 480),
        ((0, 1, 2, 3, 4), 660, 960),
        WEEKEND,
    ),
    "morning 03-06, solar 09-15": (
        ((0, 1, 2, 3, 4), 180, 360),
        ((0, 1, 2, 3, 4), 540, 900),
        WEEKEND,
    ),
}


def schedule_advice(now, temperature, goals, slots, settings, current_periods, clock, element_on):
    """Read-only: today's predicted cost/readiness for the current native windows
    and a few alternatives. A single-day estimate; Stage 3c backtesting must
    confirm any change before the owner edits the real Schedule."""
    from .native import scheduled_permission

    options = {"current reference": tuple(current_periods), **SCHEDULE_CANDIDATES}
    results = []
    for name, periods in options.items():
        outlook = native_outlook(
            now,
            temperature,
            goals,
            slots,
            settings,
            lambda at, periods=periods: scheduled_permission(at, periods, clock)
            == "within_reported_window",
            element_on,
        )
        results.append(
            {
                "name": name,
                "predicted_cost_aud": outlook["predicted_cost_aud"],
                "predicted_solar_kwh": outlook["predicted_solar_kwh"],
                "all_goals_met": all(item["met"] for item in outlook["readiness"].values()),
            }
        )
    meeting = [item for item in results if item["all_goals_met"]]
    best = min(meeting, key=lambda item: item["predicted_cost_aud"]) if meeting else None
    return {
        "candidates": results,
        "cheapest_meeting_goals": best["name"] if best else None,
        "basis": "today's forecast only; not a recommendation to change the Schedule",
    }
