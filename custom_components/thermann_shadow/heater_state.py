"""Read-only estimate of whether the REAL 3 kW element is energised. No I/O.

Evidence, in order of strength:

1. A dedicated heater-circuit power reading, if one is mapped (verified).
2. House load below the element's own power: the element cannot be drawing
   3 kW if the whole house uses less than ~2.6 kW (strong evidence of OFF).
3. ``WaterHeaterSts`` bit 0 from the last cloud poll. Observed 32/33 changes
   matched measured +/-3 kW steps in 5 of 5 transitions (Stage 1 audit), so this
   is strong empirical evidence, NOT a manufacturer contract. It lags by up to
   one poll interval (~30 min).
4. A sustained +/-3 kW step in house load after that poll (catches the lag).

Unknown or contradictory evidence stays explicitly UNKNOWN. A planner
hypothetical is never evidence of physical heating.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

ELEMENT_KW = 3.0
STEP_KW = 2.4  # minimum sustained change accepted as the element switching
MIN_ON_HOUSE_KW = 2.6  # below this the element cannot be energised
STATUS_MAX_AGE = timedelta(minutes=35)
STEP_WINDOW = timedelta(minutes=5)


@dataclass
class HeaterState:
    state: str = "unknown"  # "on" | "off" | "unknown"
    confidence: str = "none"  # "verified" | "high" | "medium" | "low" | "none"
    basis: list[str] = field(default_factory=list)
    status_bit: int | None = None
    status_raw: int | None = None
    last_step: str | None = None
    last_step_at: datetime | None = None

    @property
    def element_kw(self) -> float | None:
        return {"on": ELEMENT_KW, "off": 0.0}.get(self.state)


def status_bit(raw: object) -> int | None:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value < 0 or value != int(value):
        return None
    return int(value) & 1


class HeaterStateEstimator:
    def __init__(self) -> None:
        self.samples: deque[tuple[datetime, float]] = deque(maxlen=60)
        self.last_step: str | None = None
        self.last_step_at: datetime | None = None
        self.on_level: float | None = None  # house load while the element was on
        self.dropped_since: datetime | None = None
        self.off_seen_at: datetime | None = None  # last time OFF was observed from load

    def reset(self) -> None:
        self.samples.clear()
        self.last_step = self.last_step_at = None
        self.on_level = self.dropped_since = self.off_seen_at = None

    def _detect_step(self, now: datetime) -> None:
        recent = [kw for at, kw in self.samples if now - STEP_WINDOW < at <= now]
        earlier = [kw for at, kw in self.samples if now - 2 * STEP_WINDOW < at <= now - STEP_WINDOW]
        if len(recent) < 2 or len(earlier) < 2:
            return
        change = sum(recent) / len(recent) - sum(earlier) / len(earlier)
        at = now - STEP_WINDOW
        if abs(change) < STEP_KW:
            return
        if self.last_step_at is not None and at - self.last_step_at < 2 * STEP_WINDOW:
            return  # same transition seen again
        self.last_step = "up" if change > 0 else "down"
        self.last_step_at = at

    def update(self, *args, **kwargs) -> HeaterState:
        result = self._update(*args, **kwargs)
        house = args[1] if len(args) > 1 else kwargs.get("house_kw")
        if result.state == "on" and result.confidence in {"verified", "high", "medium"}:
            if house is not None:
                self.on_level = (
                    house if self.on_level is None else max(min(self.on_level, house), house - 0.5)
                )
        elif result.state == "off":
            self.on_level = None
        return result

    def _update(
        self,
        now: datetime,
        house_kw: float | None,
        status_raw: object,
        status_at: datetime | None,
        in_native_window: bool | None,
        heater_power_kw: float | None = None,
    ) -> HeaterState:
        result = HeaterState()
        if house_kw is not None:
            if self.samples and now - self.samples[-1][0] > timedelta(minutes=3):
                self.samples.clear()  # a gap must not fabricate a step
            self.samples.append((now, house_kw))
            self._detect_step(now)
        else:
            self.samples.clear()
        result.last_step, result.last_step_at = self.last_step, self.last_step_at
        if heater_power_kw is not None:
            on = heater_power_kw > 2.0
            result.state, result.confidence = ("on" if on else "off"), "verified"
            result.basis.append("dedicated_heater_power_reading")
            return result
        fresh = status_at is not None and timedelta(0) <= now - status_at <= STATUS_MAX_AGE
        bit = status_bit(status_raw) if fresh else None
        result.status_bit = bit
        try:
            result.status_raw = int(float(status_raw)) if fresh else None  # type: ignore[arg-type]
        except (TypeError, ValueError):
            result.status_raw = None
        step_after_poll = (
            self.last_step is not None
            and self.last_step_at is not None
            and status_at is not None
            and self.last_step_at > status_at
        )
        if house_kw is not None and house_kw < MIN_ON_HOUSE_KW:
            self.off_seen_at = now
            result.state, result.confidence = "off", "high"
            result.basis.append("house_load_below_element_power")
            if bit == 1:
                result.basis.append("status_bit_on_contradicted_by_house_load")
            return result
        # Element turned off without a sharp step (another appliance masked
        # it): the load stays >= 2.4 kW below its level while heating.
        if (
            house_kw is not None
            and self.on_level is not None
            and house_kw < self.on_level - STEP_KW
        ):
            self.dropped_since = self.dropped_since or now
        else:
            self.dropped_since = None
        if (
            self.dropped_since is not None
            and now - self.dropped_since >= timedelta(minutes=2)
            and not (step_after_poll and self.last_step == "up")
        ):
            result.state, result.confidence = "off", "medium"
            result.basis.append("load_fell_3kW_below_heating_level")
            self.off_seen_at = now
            self.on_level = None
            self.last_step, self.last_step_at = "down", self.dropped_since
            return result
        if house_kw is not None and step_after_poll:
            if self.last_step == "up":
                result.state = "on"
                result.confidence = "medium" if in_native_window is not False else "low"
                result.basis.append("3kW_step_up_after_last_poll")
            else:
                result.state, result.confidence = "off", "medium"
                result.basis.append("3kW_step_down_after_last_poll")
            return result
        stale_bit = (
            bit == 1
            and self.off_seen_at is not None
            and status_at is not None
            and self.off_seen_at > status_at
            and not (
                self.last_step == "up"
                and self.last_step_at is not None
                and self.last_step_at > self.off_seen_at
            )
        )
        if stale_bit:
            # The poll's "on" predates a switch-off seen in the meter since then.
            result.state, result.confidence = "off", "medium"
            result.basis.append("status_bit_older_than_observed_switch_off")
            return result
        if bit == 1:
            result.state = "on"
            result.confidence = "high" if house_kw is not None else "low"
            result.basis.append("WaterHeaterSts_bit0_set")
            if house_kw is not None:
                result.basis.append("house_load_consistent_with_element")
            return result
        if bit == 0:
            result.state = "off"
            result.confidence = "medium" if house_kw is not None else "low"
            result.basis.append("WaterHeaterSts_bit0_clear")
            if house_kw is not None:
                result.basis.append("load_above_2.6kW_attributed_to_other_appliances")
            return result
        result.basis.append("no_fresh_status_bit_and_no_decisive_load_evidence")
        return result


def base_load(house_kw: float | None, state: HeaterState) -> tuple[float | None, float | None]:
    """Household load EXCLUDING the real element, as (low, high) bounds in kW."""
    if house_kw is None:
        return None, None
    if state.state == "on":
        value = max(0.0, house_kw - ELEMENT_KW)
        return value, value
    if state.state == "off" or house_kw < MIN_ON_HOUSE_KW:
        return house_kw, house_kw
    return max(0.0, house_kw - ELEMENT_KW), house_kw
