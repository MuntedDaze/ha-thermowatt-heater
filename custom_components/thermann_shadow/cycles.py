"""Session-local counterfactual cycles. No executor, physical-state inference or I/O."""

from dataclasses import dataclass, field
from datetime import datetime

from .economics import compare, unit_cost
from .model import ELEMENT_KW, Forecast, Plan, Settings, Tariff, tariff_at


@dataclass
class CyclePolicy:
    active: bool = False  # SIMULATED only; never evidence the physical element is on
    started: datetime | None = None
    stopped: datetime | None = None
    last_tick: datetime | None = None
    last_sample: datetime | None = None
    advantage_since: datetime | None = None
    disadvantage_since: datetime | None = None
    goal: datetime | None = None
    goal_energy: float = 0.0
    last_observed_energy: float = 0.0
    delivered: float = 0.0
    starts: int = 0
    stops: int = 0
    suppressed_edges: int = 0
    previous_suppressed: str | None = None
    cost: float = 0.0
    grid_comparison_cost: float = 0.0
    previous_export: float = 0.0
    previous_rate: float = 0.0
    diagnostics: dict = field(default_factory=dict)

    def step(
        self,
        now: datetime,
        plan: Plan,
        settings: Settings,
        tariffs: tuple[Tariff, ...],
        forecast: tuple[Forecast, ...] = (),
        sample_at: datetime | None = None,
        override: str | None = None,
    ) -> dict:
        """One local update. Higher-priority conditions always cancel simulated dwell.

        Observed temperatures define the real-data plan. Delivered energy below
        is a separate ideal full-power scenario, never a substitute temperature.
        Restart/reload resets this scenario and requires new input qualification.
        """
        blocked = plan.state in {
            "shadow_blocked",
            "shadow_paused",
            "shadow_awaiting_validation",
            "shadow_native_intervention",
        }
        gap = (now - self.last_tick).total_seconds() if self.last_tick else 0.0
        interrupted = gap < 0 or gap > settings.grid_max_age_seconds
        if self.active and not blocked and not interrupted:
            amount = min(max(0.0, self.goal_energy - self.delivered), ELEMENT_KW * gap / 3600)
            cost, _ = unit_cost(self.previous_export, self.previous_rate, settings.feed_in_rate)
            self.delivered += amount
            self.cost += amount * cost
            self.grid_comparison_cost += amount * self.previous_rate
        self.last_tick = now
        export = plan.net_export_kw or 0.0
        self.previous_export = max(0.0, export - settings.export_headroom_kw)
        self.previous_rate = tariff_at(now, tariffs, settings.tariff_clock).rate
        if self.goal != plan.deadline and not blocked:
            self._stop(now)
            self.goal = plan.deadline
            self.goal_energy = (plan.modelled_heating_minutes or 0) * ELEMENT_KW / 60
            self.delivered = 0.0
            self.advantage_since = self.disadvantage_since = None
        observed_energy = (plan.modelled_heating_minutes or 0) * ELEMENT_KW / 60
        if not blocked:
            if (
                observed_energy > self.last_observed_energy + 0.3663
                and self.last_observed_energy > 0
            ):
                self._stop(now)
                self.goal_energy, self.delivered = observed_energy, 0.0
            self.goal_energy = min(self.goal_energy, self.delivered + observed_energy)
            self.last_observed_energy = observed_energy
        remaining = min(
            max(0.0, self.goal_energy - self.delivered),
            (plan.modelled_heating_minutes or 0) * ELEMENT_KW / 60,
        )
        now_quote = later = None
        benefit = None
        solar_benefit = None
        if not blocked and plan.deadline and remaining > 1e-7:
            now_quote, later = compare(
                now,
                plan.deadline,
                remaining,
                export,
                settings,
                tariffs,
                forecast,
                plan.grid_fallback_start,
            )
            if now_quote and later:
                benefit = later.cost - now_quote.cost
            grid_now, grid_later = compare(
                now, plan.deadline, remaining, 0, settings, tariffs, (), plan.grid_fallback_start
            )
            if now_quote and (grid_later or grid_now):
                solar_benefit = (grid_later or grid_now).cost - now_quote.cost
        urgent = bool(
            not blocked
            and remaining > 1e-7
            and (
                now_quote is None
                or (plan.grid_fallback_start and now >= plan.grid_fallback_start)
                or (plan.latest_start and now >= plan.latest_start)
            )
        )
        disadvantage = bool(benefit is not None and -benefit >= settings.switching_benefit_aud)
        opportunity = bool(
            solar_benefit is not None
            and solar_benefit >= settings.switching_benefit_aud
            and not disadvantage
            and export - settings.export_headroom_kw >= settings.min_solar_kw
        )
        new_sample = sample_at is not None and (
            self.last_sample is None or sample_at > self.last_sample
        )
        sample_gap = (
            (sample_at - self.last_sample).total_seconds() if new_sample and self.last_sample else 0
        )
        if blocked or interrupted or sample_gap > settings.grid_max_age_seconds:
            self.advantage_since = self.disadvantage_since = None
        if new_sample:
            self.last_sample = sample_at
            self.advantage_since = (self.advantage_since or sample_at) if opportunity else None
            self.disadvantage_since = (
                (self.disadvantage_since or sample_at) if disadvantage else None
            )
        elif not opportunity or not disadvantage:
            if not opportunity:
                self.advantage_since = None
            if not disadvantage:
                self.disadvantage_since = None
        permitted_override = override in {
            "thermostat_satisfied",
            "manufacturer_protection",
            "fault",
            "owner_intervention",
        }
        reason, suppressed = "wait_for_economic_opportunity", None
        if blocked or interrupted or permitted_override:
            self._stop(now)
            self.advantage_since = self.disadvantage_since = None
            reason = (
                override
                if permitted_override
                else "data_or_owner_gate"
                if blocked
                else "local_observation_gap"
            )
        elif remaining <= 1e-7 or plan.state == "shadow_no_modelled_topup":
            self._stop(now)
            reason = "simulated_target_satisfied_not_physical_thermostat"
        elif self.active:
            if urgent:
                self.disadvantage_since = None
                reason = "comfort_requires_continuing_simulation"
            elif disadvantage:
                dwell = (now - self.started).total_seconds() / 60 if self.started else 0
                loss = (
                    (self.last_sample - self.disadvantage_since).total_seconds() / 60
                    if self.last_sample and self.disadvantage_since
                    else 0
                )
                if dwell >= settings.minimum_cycle_minutes and loss >= settings.solar_loss_minutes:
                    self._stop(now)
                    reason = "sustained_cost_disadvantage_stop_simulation"
                else:
                    reason, suppressed = "continue_through_temporary_cost_disadvantage", "stop"
            else:
                self.disadvantage_since = None
                reason = "continue_existing_simulated_cycle"
        elif urgent:
            self._start(now)
            reason = "comfort_overrides_economic_hold_and_gap"
        elif opportunity:
            hold = (
                (self.last_sample - self.advantage_since).total_seconds() / 60
                if self.last_sample and self.advantage_since
                else 0
            )
            elapsed = (now - self.stopped).total_seconds() / 60 if self.stopped else float("inf")
            if hold >= settings.solar_hold_minutes and elapsed >= settings.minimum_gap_minutes:
                self._start(now)
                reason = "qualified_economic_opportunity_start_simulation"
            else:
                reason, suppressed = "qualifying_opportunity_or_optional_gap", "start"
        elif later:
            reason = "wait_for_cheaper_window_or_conservative_fallback"
        if suppressed and self.previous_suppressed != suppressed:
            self.suppressed_edges += 1  # episode count, not one prevented command per minute
        self.previous_suppressed = suppressed
        self.diagnostics = {
            "state": "suspended"
            if blocked or interrupted or permitted_override
            else "simulated_heating"
            if self.active
            else "simulated_satisfied"
            if remaining <= 1e-7
            else "simulated_waiting",
            "reason": reason,
            "physical_heating_state": "unverified",
            "simulated_cycle_count": self.starts,
            "simulated_stop_count": self.stops,
            "suppressed_switching_episodes": self.suppressed_edges,
            "simulated_delivered_kwh_this_goal": round(self.delivered, 4),
            "simulated_remaining_kwh": round(remaining, 4),
            "simulated_cost_aud_session": round(self.cost, 4),
            "same_energy_grid_cost_aud_session": round(self.grid_comparison_cost, 4),
            "simulated_solar_cost_difference_aud": round(self.grid_comparison_cost - self.cost, 4),
            "continuing_cost_aud": round(now_quote.cost, 4) if now_quote else None,
            "later_cost_aud": round(later.cost, 4) if later else None,
            "benefit_of_now_aud": round(benefit, 4) if benefit is not None else None,
            "benefit_vs_grid_alternative_aud": round(solar_benefit, 4)
            if solar_benefit is not None
            else None,
            "later_start": later.start.isoformat() if later else None,
            "estimated_completion": now_quote.end.isoformat()
            if self.active and now_quote
            else None,
            "scenario_net_grid_after_heater_kw": round(export - ELEMENT_KW, 3)
            if self.active
            else None,
            "measured_grid_is_not_adjusted_for_simulated_heating": True,
            "session_only_resets_on_restart": True,
        }
        return dict(self.diagnostics)

    def _start(self, now):
        self.active, self.started = True, now
        self.starts += 1
        self.advantage_since = self.disadvantage_since = None

    def _stop(self, now):
        if self.active:
            self.active, self.stopped = False, now
            self.stops += 1
        self.advantage_since = self.disadvantage_since = None


def baseline_export(measured_net_export: float, confirmed_heater_kw: float | None) -> float:
    """Future supervised traces only: de-embed a separately VERIFIED heater load.

    Runtime never supplies simulated activity as confirmed heater power. Without
    independent evidence, native Schedule's load cannot safely be de-embedded.
    """
    if confirmed_heater_kw is None:
        return measured_net_export
    if confirmed_heater_kw not in (0.0, ELEMENT_KW):
        raise ValueError("heater_power_unverified")
    return measured_net_export + confirmed_heater_kw
