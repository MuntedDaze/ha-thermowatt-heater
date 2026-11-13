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
PREFERRED_DEADBAND_C = 1.0


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
        shortfall = max(0.0, goal.target_c - effective)
        if goal.hard_deadline is not None and goal.deadline < goal.hard_deadline:
            # 0.7.0 preferred morning reserve (soft): a shortfall under one
            # whole degree (the reading's resolution) starts no heating. The
            # hard minimum, after the preferred time, has no such deadband.
            if shortfall < PREFERRED_DEADBAND_C:
                shortfall = 0.0
        result.append((goal, TANK_KWH_PER_C * shortfall))
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


def block_rules(settings: Settings) -> tuple[int, int]:
    """Minimum block length and minimum gap, in 15-minute slots (>= 1)."""
    return (
        max(1, math.ceil(settings.minimum_cycle_minutes / 15 - 1e-9)),
        max(1, math.ceil(settings.minimum_gap_minutes / 15 - 1e-9)),
    )


def optimise(
    slots: list[Slot],
    needs: list[tuple[int, float]],
    feed_in: float,
    force_first: bool | None = None,
    max_blocks: int = MAX_BLOCKS,
    min_run: int = 1,
    min_gap: int = 1,
) -> PlanResult | None:
    """Exact minimum-cost choice of slots under physical/operational rules.

    needs: [(deadline_index, kWh)] cumulative from slot 0. Every block lasts at
    least `min_run` slots (unless the whole job is smaller than one minimum
    cycle), blocks are at least `min_gap` slots apart, and there are at most
    `max_blocks`. A partial first slot shorter than 7.5 minutes does not count
    towards a block's length. force_first=True starts now and runs for one full
    minimum cycle; False keeps slot 0 off; None leaves it free. The last chosen
    slot is trimmed so the plan delivers exactly the largest requirement, so the
    final block may end inside its last slot once the energy is delivered.
    """
    if not slots:
        return None
    total = max((kwh for _, kwh in needs), default=0.0)
    if total <= 1e-9:
        return PlanResult("none", True)
    n = len(slots)
    slot0_units = 1 if slots[0].hours >= SLOT.total_seconds() / 7200 else 0
    best = None
    options = (True, False) if force_first is None else (force_first,)
    INF = float("inf")
    for first in options:
        credit = slots[0].capacity if first else 0.0
        units: dict[int, int] = {}
        for idx, kwh in needs:
            need = max(0, math.ceil((kwh - credit) / FULL_SLOT_KWH - 1e-9))
            units[idx] = max(units.get(idx, 0), need)
        cap_units = max(units.values()) if units else 0
        run_min = max(1, min(min_run, cap_units + (slot0_units if first else 0)))
        cap_run = max(run_min, min_gap)
        if first:
            # Forced start: the first block covers a whole minimum cycle.
            prefix = min(n, 1 + max(0, run_min - slot0_units)) if force_first else 1
            run0 = min(cap_run, slot0_units + prefix - 1)
        else:
            prefix, run0 = 1, cap_run  # slot 0 off; no previous block to keep apart from
        on_prefix = list(range(prefix)) if first else []
        feasible = True
        for idx, kwh in needs:
            if idx <= prefix and kwh > 1e-9:
                delivered = sum(slots[k].capacity for k in on_prefix if k < idx)
                if delivered < kwh - 1e-9:
                    feasible = False
        if not feasible:
            continue
        start_cost = sum(slots[k].cost(feed_in) for k in on_prefix)
        state0 = (min(cap_units, max(0, prefix - 1)), 1 if first else 0, first, run0)
        states = {state0: (start_cost, None)}
        history = [states]
        for k in range(prefix, n):
            # Negligible tie-breakers never outweigh real cost: with solar,
            # prefer EARLIER (known sun beats forecast sun); without solar,
            # prefer LATER (less standing loss).
            tie = 1e-6 * k if slots[k].solar() > 0.05 else 1e-6 * (n - k)
            cost_on = slots[k].cost(feed_in) + tie
            nxt = {}

            def offer(key, value, origin, was_on, nxt=nxt):
                if value < nxt.get(key, (INF, None))[0]:
                    nxt[key] = (value, (*origin, was_on))

            for origin, (cost, _) in states.items():
                d, b, on, run = origin
                if on:
                    offer(
                        (min(cap_units, d + 1), b, True, min(cap_run, run + 1)),
                        cost + cost_on,
                        origin,
                        True,
                    )
                    if run >= run_min:
                        offer((d, b, False, 1), cost, origin, False)
                else:
                    offer((d, b, False, min(cap_run, run + 1)), cost, origin, False)
                    if b < max_blocks and (b == 0 or run >= min_gap):
                        offer(
                            (min(cap_units, d + 1), b + 1, True, 1),
                            cost + cost_on + BLOCK_PENALTY_AUD,
                            origin,
                            True,
                        )
            for idx, need in units.items():
                if idx == k + 1:
                    nxt = {key: val for key, val in nxt.items() if key[0] >= need}
            states = nxt
            history.append(states)
            if not states:
                break
        if not states:
            continue
        final = {
            key: val
            for key, val in states.items()
            if key[0] >= cap_units and (not key[2] or key[3] >= run_min)
        }
        if not final:
            continue
        key = min(final, key=lambda item: final[item][0])
        chosen = [False] * n
        for k in on_prefix:
            chosen[k] = True
        for step in range(len(history) - 1, 0, -1):
            d, b, on, run, was_on = history[step][key][1]
            chosen[prefix + step - 1] = was_on
            key = (d, b, on, run)
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


def constraint_violations(plan: PlanResult, settings: Settings, now: datetime) -> list[str]:
    """Independent check of the block rules on a materialised plan."""
    problems = []
    if not plan.blocks:
        return problems
    single_small = (
        len(plan.blocks) == 1
        and plan.energy_kwh < ELEMENT_KW * (settings.minimum_cycle_minutes / 60) - 1e-6
    )
    for index, (start, end) in enumerate(plan.blocks):
        minutes = (end - start).total_seconds() / 60
        allowance = 0.0
        if start == now:
            allowance += 7.5  # partial first slot
        if index == len(plan.blocks) - 1:
            allowance += 15.0  # completes when the energy is delivered
        if not single_small and minutes < settings.minimum_cycle_minutes - allowance - 1e-6:
            problems.append(f"block_{index}_shorter_than_minimum_cycle")
        if index:
            gap = (start - plan.blocks[index - 1][1]).total_seconds() / 60
            if gap < settings.minimum_gap_minutes - 1e-6:
                problems.append(f"gap_{index}_shorter_than_minimum_gap")
    if len(plan.blocks) > MAX_BLOCKS:
        problems.append("too_many_blocks")
    return problems


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
    heat_now_cost_range_aud: tuple[float, float] | None = None
    native_satisfied_goal: str | None = None  # goal kind whose need the thermostat ended
    plan_feasible: bool = True


# ECONOMIC decisions. The live physical heater state is applied afterwards by
# compose_with_heater(), so it is never delayed by the decision stabiliser.
LABELS = {
    "heat_now_cheapest": "HEAT NOW",
    "heat_now_saving_too_small": "HEAT NOW",
    "heat_now_comfort_fallback": "HEAT NOW",
    "wait_cheaper_later": "WAIT - CHEAPER LATER",
    "flexible_no_cost_difference": "NO HURRY",
    "no_heating_needed": "NO HEATING NEEDED",
    "insufficient_time": "INSUFFICIENT TIME",
    "native_heating_economical": "HEATING NOW (NATIVE)",
    "native_heating_costlier_than_waiting": "HEATING NOW (NATIVE)",
    "native_heating_not_needed": "HEATING NOW (NATIVE)",
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
    satisfied_deadline: datetime | None = None,
    pessimistic_slots: list[Slot] | None = None,
) -> Assessment:
    """Compare heat-now, best, single-block and fallback plans (all under the same
    block rules and for the same energy); return an ECONOMIC decision.

    satisfied_deadline: the native thermostat switched the element off inside a
    permitted window before THIS afternoon deadline. It controls from its own
    sensor (10 Nov: off at a 63 °C reading), so no further heat can be bought for
    that goal; it is reported as "satisfied by the thermostat", not as the
    reported target being reached. Only the goal with exactly this deadline is
    affected; a later day's goal never is.

    pessimistic_slots: the same slots with the HIGH base-load bound (heater state
    unknown), used to bound the heat-now cost.
    """
    feed_in = settings.feed_in_rate
    reqs = requirements(now, temperature, goals, settings)
    satisfied_kind = None
    if satisfied_deadline is not None:
        adjusted = []
        for goal, kwh in reqs:
            if goal.kind == "afternoon" and goal.deadline == satisfied_deadline and kwh > 1e-9:
                satisfied_kind = goal.kind
                kwh = 0.0
            adjusted.append((goal, kwh))
        reqs = adjusted
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
    if satisfied_kind:
        warnings.append("afternoon_need_ended_by_native_thermostat_reading_below_target")
    if total <= 1e-9:
        code = "no_heating_needed"
        if satisfied_kind:
            target = next(goal.target_c for goal, _ in reqs if goal.kind == satisfied_kind)
            text = (
                f"The native thermostat switched the element off inside its window with the "
                f"reading at {temperature:.0f} °C (configured target {target:.0f} °C). Its own "
                "sensor decided storage is full, so no more heat can be added for this "
                "afternoon; the reported target was not necessarily reached."
            )
        else:
            text = "The readiness goals are already met on the current reading."
        return Assessment(
            code,
            LABELS[code],
            text,
            "high",
            plans,
            reqs,
            fallbacks,
            None,
            None,
            None,
            native,
            warnings,
            native_satisfied_goal=satisfied_kind,
        )
    min_run, min_gap = block_rules(settings)
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
            warnings,
            native_satisfied_goal=satisfied_kind,
            plan_feasible=False,
        )
    rules = {"min_run": min_run, "min_gap": min_gap}
    best = optimise(slots, needs, feed_in, **rules)
    # "Heat now" = start now AND run a whole minimum cycle (a token 15-minute
    # start followed by a wait would understate the saving).
    best_now = optimise(slots, needs, feed_in, force_first=True, **rules)
    single = optimise(slots, needs, feed_in, max_blocks=1, **rules)
    single_later = optimise(slots, needs, feed_in, force_first=False, max_blocks=1, **rules)
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
    cost_range = None
    if pessimistic_slots is not None:
        high_now = optimise(pessimistic_slots, needs, feed_in, force_first=True, **rules)
        if high_now is not None:
            cost_range = (round(heat_now_cost, 3), round(max(heat_now_cost, high_now.cost_aud), 3))
    # The decision is "start now (for at least the minimum cycle) or not", so the
    # saving must be worthwhile per kWh that would otherwise be heated NOW.
    # Committed now = one minimum cycle from now (a partial first slot under
    # 7.5 minutes does not count), never the whole first block of a plan.
    slot0_units = 1 if slots[0].hours >= SLOT.total_seconds() / 7200 else 0
    cycle_slots = 1 + max(0, min_run - slot0_units)
    committed = min(total, sum(slot.capacity for slot in slots[:cycle_slots]))
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
            f"{_money(max(0.0, saving))} (threshold {_money(threshold)} for the "
            f"{committed:.1f} kWh heated first), so heating now is preferred for certainty."
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
    if element_state == "unknown":
        warnings.append("element_state_unknown_costs_are_bounded")
        if cost_range is not None and cost_range[1] - cost_range[0] > 0.005:
            text += (
                f" Heater state unknown: heating now costs between {_money(cost_range[0])} "
                f"and {_money(cost_range[1])}."
            )
            spread = cost_range[1] - cost_range[0]
            confidence = (
                "low"
                if spread > max(threshold, 0.05)
                else min(confidence, "medium", key=["low", "medium", "high"].index)
            )
    if not forecast_available:
        warnings.append("no_qualified_forecast_future_solar_assumed_zero")
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
        heat_now_cost_range_aud=cost_range,
        native_satisfied_goal=satisfied_kind,
    )


def compose_with_heater(
    decision: tuple[str, str, str, str],
    heater_state: str,
    best_start: datetime | None,
    heater_confidence: str = "high",
) -> tuple[str, str, str, str]:
    """Overlay the LIVE physical heater state on a (possibly stabilised) economic
    decision. Physical state is never held back by the stabiliser: once the
    element stops, the native-heating label disappears on the same tick. A
    medium/low-confidence ON says "HEATING LIKELY", never "HEATING NOW"."""
    code, label, text, confidence = decision
    likely = heater_confidence not in {"verified", "high"}
    if heater_state != "on" or code in {
        "insufficient_time",
        "data_unavailable",
        "paused",
        "owner_review_required",
    }:
        if code == "insufficient_time" and heater_state == "on":
            text = "The native Schedule is heating now. " + text
        return code, label, text, confidence
    prefix = (
        f"The native Schedule is probably heating ({heater_confidence} confidence). "
        if likely
        else "The native Schedule is heating now. "
    )
    native_label = "HEATING LIKELY (NATIVE)" if likely else "HEATING NOW (NATIVE)"
    if code == "wait_cheaper_later":
        return (
            "native_heating_costlier_than_waiting",
            native_label,
            prefix + "The cheapest plan would wait until "
            f"{_local(best_start)}: {text} Advisory only; nothing is sent to the heater.",
            confidence,
        )
    if code == "no_heating_needed":
        return (
            "native_heating_not_needed",
            native_label,
            prefix + "It heats towards its own target although the planner's readiness goals "
            "are met. " + text,
            confidence,
        )
    return (
        "native_heating_economical",
        native_label,
        prefix + "This is consistent with the cheapest plan. " + text,
        confidence,
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
