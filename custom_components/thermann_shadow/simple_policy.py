"""Simplified heating policy: DESIGN DRAFT, not used by the installed controller.

Nothing imports this module yet. It is the reviewable core of the proposed
simplification (see shadow_controller/SIMPLIFIED_STRATEGY.md). Wiring it into
the controller needs owner approval, and so does the bridge change it depends
on: today the bridge accepts only ``Manual:70`` and ``off``.

Three heater states, chosen from the tariff calendar, the Thermann reading, the
EMHASS forecast and LOCAL meter samples (GoodWe, about once a minute; never a
cloud request):

  OFF       Thermann software OFF.
  BASELINE  Manual 45 °C, the owner's agreed baseline: weekday nights after the
            evening peak, and weekends. Never in a peak.
  STORAGE   Manual 70 °C: heat stored for the evening, or solar heating.

The heater runs its own protections (antibacterial cycle, frost protection) in
every state (Thermann guide p10). This policy does not detect, schedule or
replace them.

The tariff calendar decides the mode:

  PEAK         a peak period, or the last ``peak_lead`` before one (the shortest
               lead the bridge timing allows). OFF, or STORAGE while MEASURED
               solar qualifies. The same rule applies to every peak.
  DEADLINE     weekday off-peak before the evening peak. Heat to 70 °C in the
               cheapest window that finishes by the SOFT target (peak minus
               ``soft_target_margin``), using the EMHASS forecast, the measured
               surplus and the tariff. Start at once when waiting would miss
               the soft target. Once started, keep heating until the peak
               unless a later window saves at least ``pause_min_saving``, can
               still finish by the soft target, and leaves room for the extra
               command. The soft target is a planning buffer: heating that has
               not finished by then continues until the peak.
  OPPORTUNITY  every other off-peak time: weekday nights and whole weekends.
               BASELINE, plus STORAGE while measured solar (at least
               ``solar_floor_kw``) makes heating worth it now and no cheaper
               window is forecast later that day. A worthwhile session ends only
               when both the measured surplus and the next hour's forecast have
               faded, not on a passing cloud.

Precedence, highest first:

  1. The heater's own protections: native, in every state (no decision here).
  2. Owner: app change / hold (HOLD), holiday (OFF), 12hr Override (STORAGE).
  3. Cloud, authentication, freshness, command spacing and the reserved peak
     command slot: may only BLOCK sending, never choose a state.
  4. Peak import restriction (PEAK mode).
  5. Hot water before the evening peak, and the baseline (DEADLINE / OPPORTUNITY).
  6. Forecast economics (only ever moves an off-peak start or pauses for a
     clearly cheaper window).

Shared safeguards: one solar qualification (10 min), one withdrawal (5 min),
one command spacing (15 min) and the peak lead (2 min). No minimum run, minimum
rest or fallback timer: the thermostat, not this policy, switches the element.

Pure: no Home Assistant, no I/O. One instance per controller keeps the meter
samples; ``decide`` is deterministic for a given history.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from statistics import median

from .model import ELEMENT_KW, HOBART, TANK_KWH_PER_C, Forecast, Tariff, tariff_at

OFF, BASELINE, STORAGE, HOLD = "off", "baseline", "storage", "hold"
STATES = (OFF, BASELINE, STORAGE)
PEAK, DEADLINE, OPPORTUNITY = "peak", "deadline", "opportunity"
PRICE_TOLERANCE = 0.005  # $/kWh: a later window must beat "now" by this much
SLOT = timedelta(minutes=5)  # planning grid
MEASURED_SPAN = timedelta(minutes=30)  # the measured surplus stands in for the forecast
SCAN_STEP = timedelta(minutes=15)
SCAN_HORIZON = timedelta(days=4)
SAMPLE_SLACK = timedelta(seconds=30)  # timer drift allowed at the start of a sample window
# A protective OFF when solar is lost or peak grid metering disappears must
# not be held by spacing after a recent solar start. Every other command,
# including restarting solar heating, still observes the 15-minute spacing.
SPACING_EXEMPT_REASONS = frozenset(
    {"peak_solar_withdrawn", "peak_meter_unavailable", "peak_heater_power_unavailable"}
)


@dataclass(frozen=True)
class PolicySettings:
    baseline_c: int = 45  # owner's agreed baseline (compliance note: SIMPLIFIED_STRATEGY.md §3)
    storage_c: int = 70
    hysteresis_c: float = 8.0  # Thermann guide p9: reheats about 8 °C below the target
    element_kw: float = ELEMENT_KW
    kwh_per_c: float = TANK_KWH_PER_C
    feed_in_rate: float = 0.09276
    tariff_clock: str = "standard"
    peak_start_kw: float = 3.3  # element 3.0 kW + 0.3 kW buffer
    peak_import_tolerance_kw: float = 0.2
    solar_floor_kw: float = 1.0  # least measured surplus for optional (weekend) heating
    optional_heat_margin: float = 0.02  # $/kWh saving needed for heat not otherwise needed
    pause_min_saving: float = 0.30  # $ a later window must save to justify a pause
    qualify: timedelta = timedelta(minutes=10)
    withdraw: timedelta = timedelta(minutes=5)
    command_spacing: timedelta = timedelta(minutes=15)
    # One decision tick (1 min) plus the bridge's pre-command refresh, POST and
    # the measured cloud readback (about 2-63 s, T3c).
    peak_lead: timedelta = timedelta(minutes=2)
    soft_target_margin: timedelta = timedelta(minutes=30)  # planning buffer, not a shutdown
    evening_peak_from_hour: int = 12  # a peak starting at/after this is an evening peak
    reading_max_age: timedelta = timedelta(minutes=75)
    meter_max_age: timedelta = timedelta(minutes=3)

    def __post_init__(self) -> None:
        if not 40 <= self.baseline_c <= 65 or not 60 <= self.storage_c <= 70:
            raise ValueError("policy_targets_out_of_range")
        if self.storage_c - self.baseline_c < self.hysteresis_c:
            raise ValueError("policy_targets_too_close")
        if self.peak_start_kw < self.element_kw or self.solar_floor_kw <= 0:
            raise ValueError("policy_solar_thresholds_invalid")
        if not timedelta(minutes=1) <= self.peak_lead <= self.command_spacing:
            raise ValueError("policy_peak_lead_invalid")
        if self.soft_target_margin <= self.peak_lead:
            raise ValueError("policy_soft_target_inside_peak_lead")


@dataclass(frozen=True)
class Snapshot:
    """What the caller knows now. Heater state is the CONFIRMED one."""

    now: datetime
    heater_state: str | None  # OFF / BASELINE / STORAGE, or None when anything else
    reading_c: float | None = None  # Thermann bottom-sensor reading
    reading_at: datetime | None = None  # bridge poll time of that reading
    forecast: tuple[Forecast, ...] = ()  # EMHASS net export (after household load)
    last_command_at: datetime | None = None
    heating_c_per_hour: float | None = None  # observed reading rise while heating
    # Precedence layers 2-3, decided by the existing controller and bridge.
    owner_override: bool = False
    holiday: bool = False
    override_12h: bool = False
    cloud_ready: bool = True
    # A configured dedicated heater-power sensor is missing or invalid. For
    # optional solar heating we never rely on the aggregate-load estimator.
    heater_power_ready: bool = True


@dataclass(frozen=True)
class Decision:
    state: str  # desired heater state, or HOLD (keep whatever it is)
    reason: str
    layer: int
    command: str | None = None  # MQTT MODE payload to send now, if any
    plan: dict = field(default_factory=dict)


class SimplePolicy:
    def __init__(self, settings: PolicySettings, tariffs: tuple[Tariff, ...]):
        self.s = settings
        self.tariffs = tariffs
        # (at, import_kw, available_kw, element_on); available EXCLUDES the element.
        self.samples: deque[tuple[datetime, float, float, bool]] = deque()
        self._peak_cache: tuple[datetime, datetime | None, datetime] | None = None

    # --- local meter ---------------------------------------------------------------

    def add_meter(
        self,
        at: datetime,
        grid_kw: float,
        element_on: bool | None,
        *,
        measured_heater_kw: float | None = None,
    ) -> None:
        """One local sample: positive grid means import. When available, an
        actual circuit reading takes precedence over a nominal 3 kW estimate.
        The caller must never supply an inferred value as measured watts."""
        if measured_heater_kw is not None:
            if (
                not math.isfinite(measured_heater_kw)
                or not 0 <= measured_heater_kw <= self.s.element_kw * 1.4
            ):
                raise ValueError("heater_power_out_of_range")
            credit_kw = measured_heater_kw
            on = measured_heater_kw > 2.0
        else:
            credit_kw = self.s.element_kw if element_on else 0.0
            on = bool(element_on)
        available = -grid_kw + credit_kw
        self.samples.append((at, max(0.0, grid_kw), available, on))
        cutoff = at - 2 * max(self.s.qualify, self.s.withdraw)
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def _window(self, now: datetime, window: timedelta):
        return [smp for smp in self.samples if now - window <= smp[0] <= now]

    def meter_fresh(self, now: datetime) -> bool:
        return bool(self.samples) and now - self.samples[-1][0] <= self.s.meter_max_age

    def sustained(self, now: datetime, window: timedelta, test) -> bool:
        """``test`` held for the WHOLE ``window`` (0.9.1): the sample at the
        start of the window (to within half a minute) and the latest sample
        both pass, the samples between have no gap above the meter age limit,
        and at least 80 % of them pass (a kettle or a passing cloud for a
        minute does not reset it). With one sample a minute, 10 minutes is 11
        samples spanning the full 10 minutes, and 5 minutes is 6 spanning 5:
        the condition can never be met sooner than the stated time."""
        recent = self._window(now, window + SAMPLE_SLACK)
        if not recent or not self.meter_fresh(now) or recent[0][0] > now - window + SAMPLE_SLACK:
            return False
        if any(
            b[0] - a[0] > self.s.meter_max_age for a, b in zip(recent, recent[1:], strict=False)
        ):
            return False
        if not (test(recent[0]) and test(recent[-1])):
            return False
        return sum(1 for smp in recent if test(smp)) >= 0.8 * len(recent)

    def typical_available(self, now: datetime) -> float | None:
        """Median measured surplus over the qualification window (fresh meter only)."""
        recent = self._window(now, self.s.qualify)
        if not recent or not self.meter_fresh(now):
            return None
        return median(smp[2] for smp in recent)

    # --- tariff calendar --------------------------------------------------------------

    def _kind(self, at: datetime) -> str:
        return tariff_at(at, self.tariffs, self.s.tariff_clock).kind

    def next_peak(self, now: datetime) -> datetime | None:
        """Start of the next peak strictly after ``now`` (``now`` not in a peak)."""
        cached = self._peak_cache  # (computed at, result, valid until)
        if cached and cached[0] <= now < cached[2]:
            return cached[1]
        at, found = now, None
        while at - now < SCAN_HORIZON:
            at += SCAN_STEP
            if self._kind(at) == "peak":
                found = at
                while self._kind(found - timedelta(minutes=1)) == "peak" and found > now:
                    found -= timedelta(minutes=1)
                break
        self._peak_cache = (now, found, found or now + timedelta(hours=1))
        return found

    # --- heating arithmetic --------------------------------------------------------------

    def _rate_c_per_hour(self, observed: float | None) -> float:
        physics = self.s.element_kw / self.s.kwh_per_c  # about 8.2 °C/h for 315 L, 3 kW
        if observed is None or observed <= 0:
            return physics
        return min(max(observed, 0.5 * physics), 1.5 * physics)

    def mixed_cost(self, surplus_kw: float, grid_rate: float) -> float:
        """$/kWh of heat when ``surplus_kw`` of solar covers part of the element."""
        solar = min(max(surplus_kw, 0.0), self.s.element_kw)
        return (solar * self.s.feed_in_rate + (self.s.element_kw - solar) * grid_rate) / (
            self.s.element_kw
        )

    @staticmethod
    def surplus_profile(now, end, forecast, measured_kw: float | None) -> list[float]:
        """Expected surplus (kW) for each 5-minute slot in [now, end). The measured
        surplus stands in for the first 30 minutes; after that the EMHASS
        forecast. A slot the forecast does not cover counts as no surplus, so a
        missing forecast never makes waiting look cheaper."""
        slots = sorted(forecast, key=lambda f: f.start)
        starts = [f.start for f in slots]
        out, at = [], now
        while at < end:
            if measured_kw is not None and at - now < MEASURED_SPAN:
                out.append(measured_kw)
            else:
                mid = at + SLOT / 2
                j = bisect_right(starts, mid) - 1
                out.append(slots[j].export_kw if j >= 0 and slots[j].end > mid else 0.0)
            at += SLOT
        return out

    def _windows(self, profile: list[float], grid_rate: float, slots: int):
        """Mean $/kWh of each window of ``slots`` consecutive slots, by start index."""
        prefix = [0.0]
        for kw in profile:
            prefix.append(prefix[-1] + self.mixed_cost(kw, grid_rate))
        return [(prefix[i + slots] - prefix[i]) / slots for i in range(len(profile) - slots + 1)]

    @staticmethod
    def _cheapest(costs: list[float], first: int = 0) -> int | None:
        """Earliest start from ``first`` whose cost no later start beats by more
        than the tolerance (ties go to the earliest: more slack, same price)."""
        best = None
        for i in range(first, len(costs)):
            if best is None or costs[i] < costs[best] - PRICE_TOLERANCE:
                best = i
        return best

    # --- the decision ----------------------------------------------------------------------

    def setpoint(self, state: str | None) -> int | None:
        """The Manual setpoint a policy state requests (None for OFF/unknown)."""
        return {BASELINE: self.s.baseline_c, STORAGE: self.s.storage_c}.get(state)

    def decide(self, snap: Snapshot) -> Decision:
        # 1. The heater's own protections are native in every state: nothing to decide.
        # 2. The owner.
        if snap.owner_override:
            return Decision(HOLD, "owner_override", 2)
        if snap.heater_state not in STATES:
            return Decision(HOLD, "heater_state_not_controlled", 2)
        if snap.holiday:
            return self._send(snap, OFF, "holiday", 2, {})
        if snap.override_12h:
            return self._send(snap, STORAGE, "12hr_override", 2, {})
        desired, reason, layer, plan = self._policy(snap)
        # 3. Reserve the command slot for the peak transition: in the spacing
        # before the peak lead, send nothing that would need another command
        # (the park) at the boundary.
        peak = plan.get("next_peak")
        if (
            desired not in (OFF, snap.heater_state)
            and peak is not None
            and peak - self.s.peak_lead - self.s.command_spacing
            <= snap.now
            < peak - self.s.peak_lead
        ):
            return Decision(
                snap.heater_state, "peak_command_reserved", 3, None, {**plan, "wanted": desired}
            )
        return self._send(snap, desired, reason, layer, plan)

    def _send(self, snap, desired, reason, layer, plan) -> Decision:
        spacing_exempt = desired == OFF and reason in SPACING_EXEMPT_REASONS
        if desired == snap.heater_state:
            return Decision(desired, reason, layer, None, plan)
        # 3. Cloud and command guards may only block a command, never choose one.
        if not snap.cloud_ready:
            return Decision(HOLD, "cloud_or_freshness_gate", 3, None, {**plan, "wanted": desired})
        if (
            not spacing_exempt
            and snap.last_command_at is not None
            and snap.now - snap.last_command_at < self.s.command_spacing
        ):
            return Decision(HOLD, "command_spacing", 3, None, {**plan, "wanted": desired})
        payload = {
            OFF: "off",
            BASELINE: f"Manual:{self.s.baseline_c}",
            STORAGE: f"Manual:{self.s.storage_c}",
        }[desired]
        return Decision(desired, reason, layer, payload, plan)

    def _policy(self, snap: Snapshot):
        s, now, state = self.s, snap.now, snap.heater_state
        fresh = (
            snap.reading_c is not None
            and snap.reading_at is not None
            and now - snap.reading_at <= s.reading_max_age
        )
        # A stale or missing reading is assumed to be just above the baseline's
        # reheat point: storage then starts earlier, never later.
        reading = snap.reading_c if fresh else s.baseline_c - s.hysteresis_c
        would_heat = reading <= s.storage_c - s.hysteresis_c
        in_peak = self._kind(now) == "peak"
        peak = None if in_peak else self.next_peak(now)
        # The REQUESTED setpoint is not the ACHIEVED temperature. Manual 70 holds
        # the tank between about 62 and 70 °C (Thermann's 8 °C hysteresis); a
        # reading inside that band has not reached 70, but the thermostat will
        # not heat until 62 and nothing here forces it to.
        plan = {
            "reading_c": reading,
            "reading_fresh": fresh,
            "next_peak": peak,
            "setpoint_c": self.setpoint(state),
            "storage_target_c": s.storage_c,
            "target_reached": fresh and reading >= s.storage_c,
            "thermostat_would_heat_at_storage": would_heat,
        }

        # 4. Peak (and the short lead before it): measured solar only.
        if in_peak or (peak is not None and now >= peak - s.peak_lead):
            plan["mode"] = PEAK
            qualified = self.sustained(now, s.qualify, lambda x: x[2] >= s.peak_start_kw)
            if state == STORAGE:
                if not snap.heater_power_ready:
                    return OFF, "peak_heater_power_unavailable", 4, plan
                if not self.meter_fresh(now):
                    return OFF, "peak_meter_unavailable", 4, plan
                if not in_peak and not qualified:
                    return OFF, "peak_ahead_no_qualified_solar", 4, plan  # the park
                # Import above the tolerance, or the surplus no longer covering the
                # element (checked even while the thermostat has it off).
                lost = s.element_kw - s.peak_import_tolerance_kw
                if self.sustained(
                    now, s.withdraw, lambda x: x[1] > s.peak_import_tolerance_kw or x[2] < lost
                ):
                    return OFF, "peak_solar_withdrawn", 4, plan
                return STORAGE, "peak_solar_continues", 4, plan
            if not snap.heater_power_ready:
                return OFF, "peak_no_verified_heater_power", 4, plan
            if would_heat and qualified:
                return STORAGE, "peak_solar_qualified", 4, plan
            return OFF, "peak_no_grid_heating", 4, plan

        rate = self._rate_c_per_hour(snap.heating_c_per_hour)
        grid_rate = tariff_at(now, self.tariffs, s.tariff_clock).rate
        measured = self.typical_available(now)
        hours = max(0.0, s.storage_c - reading) / rate if would_heat else 0.0
        need = max(1, math.ceil(hours * 60 / 5))  # slots of heating
        plan.update(heating_hours=round(hours, 2), measured_kw=measured)
        local = now.astimezone(HOBART)
        evening = (
            peak is not None
            and peak.astimezone(HOBART).date() == local.date()
            and peak.astimezone(HOBART).hour >= s.evening_peak_from_hour
        )

        # 5/6. Weekday off-peak before the evening peak: 70 °C by the soft target.
        if evening:
            plan["mode"] = DEADLINE
            soft = peak - s.soft_target_margin
            latest = soft - timedelta(hours=hours)
            plan.update(soft_target=soft, latest_start=latest)
            if not would_heat:
                # Inside the thermostat band (or at 70): no heat would flow now,
                # so no command. Reported as reached only at the setpoint itself.
                reason = (
                    "storage_target_reached"
                    if plan["target_reached"]
                    else "storage_within_thermostat_band"
                )
                return state, reason, 5, plan
            if now >= latest:
                # Running late (or a draw): heat now and keep heating to the peak.
                if state == STORAGE:
                    return STORAGE, "storage_until_peak", 5, plan
                late = now + timedelta(hours=hours) > soft + SLOT
                return (
                    STORAGE,
                    "storage_target_may_be_missed" if late else "storage_latest_start",
                    5,
                    plan,
                )
            costs = self._windows(
                self.surplus_profile(now, soft, snap.forecast, measured), grid_rate, need
            )
            if state == STORAGE:
                # Committed: pause only for a clearly cheaper later window that
                # leaves room for the restart command and still finishes in time.
                first = math.ceil(s.command_spacing / SLOT)
                best = self._cheapest(costs, first)
                if best is not None:
                    saving = (costs[0] - costs[best]) * hours * s.element_kw
                    plan.update(best_start=now + best * SLOT, pause_saving=round(saving, 2))
                    if saving >= s.pause_min_saving:
                        return OFF, "storage_paused_for_cheaper_window", 6, plan
                return STORAGE, "storage_until_peak", 5, plan
            best = self._cheapest(costs)
            plan.update(
                best_start=now + best * SLOT,
                cost_now=round(costs[0], 4),
                cost_best=round(costs[best], 4),
            )
            if best == 0:
                if not snap.forecast and costs[0] > grid_rate - PRICE_TOLERANCE:
                    # 0.9.1 (audit M4): no published forecast and no measured
                    # solar worth having. Nothing says now is cheaper than
                    # later, so grid-only heating waits for the latest start
                    # (measured solar can still start it sooner). Without this
                    # a missing forecast silently became grid heating as soon
                    # as the morning peak ended.
                    plan["waiting_for"] = "latest_start_no_forecast"
                    return state, "storage_waiting_no_forecast", 6, plan
                return STORAGE, "storage_cheapest_now", 6, plan
            return state, "storage_waiting_for_cheaper_window", 6, plan

        # Opportunity: weekday nights and weekends.
        plan["mode"] = OPPORTUNITY
        if state == STORAGE:
            if not snap.heater_power_ready:
                return BASELINE, "solar_opportunity_heater_power_unavailable", 5, plan
            if measured is None:
                return BASELINE, "solar_opportunity_ended", 5, plan
            # This is discretionary heating, unlike the weekday deadline.
            # A forecast of returning sun must not permit prolonged near-full
            # element import. Allow the part-load grid import implicit in the
            # economic 1 kW solar floor, plus the shared 0.2 kW tolerance.
            max_import = max(0.0, s.element_kw - s.solar_floor_kw + s.peak_import_tolerance_kw)
            if self.sustained(now, s.withdraw, lambda x: x[1] > max_import):
                plan["optional_max_grid_import_kw"] = round(max_import, 2)
                return BASELINE, "solar_opportunity_import_withdrawn", 5, plan
            faded = self.sustained(now, s.withdraw, lambda x: x[2] < s.solar_floor_kw)
            ahead = self.surplus_profile(now, now + timedelta(hours=1), snap.forecast, None)
            returns = sum(ahead) / len(ahead) >= s.solar_floor_kw
            plan["forecast_next_hour_kw"] = round(sum(ahead) / len(ahead), 2)
            if faded and not returns:
                return BASELINE, "solar_opportunity_ended", 5, plan
            return STORAGE, "solar_opportunity_continues", 5, plan
        finish_by = None if peak is None else peak - s.soft_target_margin
        if (
            would_heat
            and snap.heater_power_ready
            and (finish_by is None or now + timedelta(hours=hours) <= finish_by)
            and self.sustained(now, s.qualify, lambda x: x[2] >= s.solar_floor_kw)
        ):
            midnight = datetime.combine(
                local.date() + timedelta(days=1), datetime.min.time(), HOBART
            )
            horizon = min(finish_by or midnight, midnight)
            profile = self.surplus_profile(now, horizon, snap.forecast, measured)
            costs = self._windows(profile, grid_rate, min(need, len(profile)))
            best = self._cheapest(costs)
            plan.update(cost_now=round(costs[0], 4), best_start=now + best * SLOT)
            if costs[0] > grid_rate - s.optional_heat_margin:
                plan["waiting_for"] = "more_solar"
            elif best > 0:
                plan["waiting_for"] = "cheaper_window_later"
            else:
                return STORAGE, "solar_opportunity", 5, plan
        return BASELINE, "baseline", 5, plan
