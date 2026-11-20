"""Seven days of mixed weather and demand, with and without forecasts.

Final owner instruction (20 Nov 2026, docs/OPERATING_POLICY.md §1.11): the
heater must keep working when every forecast disappears. Forecasts may choose
when required 62 °C heating starts, but never authorise a 70 °C boost, and
their loss must never stop required heating or cause an unsafe command.

Both runs use the real controller, policy, executor and app (bridge) worker
with a mocked cloud and synthetic tank; all external I/O is denied. The week
(tools/final_week_replay.py) has sunny, cloudy and patchy days, an optimistic
forecast, heavy draws, owner app changes, a Friday status outage, a Saturday
Home Assistant restart and a cloudy Sunday. CT-free, as installed.
"""

from datetime import timedelta
import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]


class Timed(list):
    """Records (time, topic, payload) for every MQTT publish made by HA."""

    def __init__(self, rig, items):
        super().__init__(items)
        self.rig, self.timed = rig, []

    def append(self, item):
        self.timed.append((self.rig.now(), *item))
        super().append(item)


def run(forecasts):
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        replay = importlib.import_module("final_week_replay")
    finally:
        sys.path.pop(0)
    base = replay.Week
    seen = {}

    class Week(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ha_publishes = Timed(self, self.ha_publishes)
            seen["week"] = self

        def _forecast(self, pv=None):
            if forecasts:
                return super()._forecast(pv)
            # Every forecast disappears: EMHASS entities unavailable.
            for entity in (replay.c.DEFAULT_SOURCES.get("forecast_pv"), *self._forecast_ids()):
                if entity:
                    self.report(entity, "unavailable", {})

        def _forecast_ids(self):
            from test_integration_0_9_0 import FORECAST_LOAD, FORECAST_PV

            return (FORECAST_PV, FORECAST_LOAD)

    report = replay.results([("fixed_30", "fixed_30", False, 60)], week_class=Week)
    (row,) = [r for r in report["runs"] if not r["ct"]]
    week = seen["week"]
    return row, week


@pytest.fixture(scope="module")
def runs():
    return {True: run(True), False: run(False)}


def commands(week):
    from test_integration_0_9_0 import TOPIC

    return [(at, payload) for at, topic, payload in week.ha_publishes.timed if topic == TOPIC]


def test_forecast_loss_never_stops_required_heating(runs):
    with_row, _ = runs[True]
    without_row, without = runs[False]
    assert without.runtime.forecast is None or not without.runtime.forecast.slots
    for row in (with_row, without_row):
        assert row["energy_kwh"]["unserved_draw"] == 0 and row["energy_kwh"]["served_draw"] == 45
    for day, stats in with_row["days"].items():
        other = without_row["days"][day]
        if stats["required_c"]:
            # Forecast loss never makes a weekday miss 62 that the forecast run reached.
            assert other["required_target_reached"] >= stats["required_target_reached"], day
            assert other["max_daytime_c"] >= 61.5 or not stats["required_target_reached"], day


def test_no_forecast_week_keeps_the_fixed_temperature_and_tariff_rules(runs):
    from test_integration_0_9_0 import m

    _, week = runs[False]
    sent = commands(week)
    assert sent, "basic heating stopped without forecasts"
    tariffs = week.runtime.tariffs
    for at, payload in sent:
        local = at.astimezone(m.STANDARD)
        kind = m.tariff_at(at, tariffs, "standard").kind
        target = payload.split("@")[0]
        if kind == "peak":
            assert target == "off", (at, payload)  # Never-during-peak policy
        if local.weekday() < 5 and (local.hour >= 21 or local.hour < 7):
            assert target in ("Manual:45", "off"), (at, payload)  # overnight 45, no top-up
        if target == "Manual:70":
            # Only measured surplus qualifies: PV must cover house 0.5 kW + 3.3 kW start.
            for minutes in range(0, 11):
                pv = week.weather((at - timedelta(minutes=minutes)).astimezone(m.HOBART))
                assert pv - 0.5 >= 3.3 - 0.01, (at, minutes, pv)
    # 0.18.1: measured surplus alone still qualifies boosts without forecasts.
    assert any(p.startswith("Manual:70@") for _, p in sent)
    weekend = [(at, p) for at, p in sent if at.astimezone(m.HOBART).weekday() >= 5]
    for day in (5, 6):
        days = [(at, p) for at, p in weekend if at.astimezone(m.HOBART).weekday() == day]
        assert any(p.startswith("Manual:62@") for _, p in days), day  # comfort window 62
        assert any(
            p.startswith("Manual:45@") and at.astimezone(m.HOBART).hour >= 18 for at, p in days
        ), day  # 18:00 return to 45


def test_forecasts_only_change_timing_not_the_safety_envelope(runs):
    from test_integration_0_9_0 import m

    _, with_week = runs[True]
    _, without_week = runs[False]
    for week in (with_week, without_week):
        for at, payload in commands(week):
            if m.tariff_at(at, week.runtime.tariffs, "standard").kind == "peak":
                assert payload.startswith("off@"), (at, payload)
    on = {p.split("@")[0] for _, p in commands(with_week)}
    off = {p.split("@")[0] for _, p in commands(without_week)}
    assert off <= on | {"Manual:45", "Manual:62", "off"}  # no new kind of command
