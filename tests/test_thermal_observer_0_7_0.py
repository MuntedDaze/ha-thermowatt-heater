"""0.7.0 read-only thermal observer: classification, evidence, persistence and
the guarantee that it cannot influence heater control. Offline only."""

import ast
from datetime import timedelta
from pathlib import Path

import importlib
from test_controller_0_9_0 import local, m

thermal = importlib.import_module(f"{m.__package__}.thermal")
PACKAGE = Path(thermal.__file__).parent


class Feed:
    """Minute-by-minute observer input with 30-minute polls."""

    def __init__(self, start, reading):
        self.observer = thermal.ThermalObserver()
        self.now, self.reading, self.poll_at = start, reading, start
        self.observer.update(start, reading, start, "off", "high", "Off")

    def run(self, minutes, element="off", mode="Manual", rate=0.0, poll_every=30):
        for _ in range(minutes):
            self.now += timedelta(minutes=1)
            self.reading += rate
            if (self.now - self.poll_at) >= timedelta(minutes=poll_every):
                self.poll_at = self.now
            self.observer.update(self.now, round(self.reading), self.poll_at, element, "high", mode)
        return self.observer


def test_a_stable_tank_yields_a_standing_loss_estimate_over_hours():
    feed = Feed(local(hour=0), 60.0)
    observer = feed.run(7 * 60, rate=-0.4 / 60)  # 0.4 °C/h, whole-degree readings
    assert observer.state == "stable"
    loss, samples = observer.standing_loss()
    assert samples >= 2 and abs(loss - 0.4) < 0.2


def test_a_sudden_drop_without_heating_is_a_suspected_draw_with_rebound():
    feed = Feed(local(hour=19), 62.0)
    feed.run(31)
    feed.reading = 40.0  # evening showers: cold water at the bottom sensor
    observer = feed.run(31)
    assert observer.state in {"draw_suspected", "settling_after_draw"}
    assert observer.last_draw["confidence"] == "high" and observer.last_draw["drop_c"] >= 8
    feed.reading = 44.0  # settles back
    observer = feed.run(30)
    assert observer.last_draw.get("rebound_c", 0) >= 1.5
    assert observer.summary(feed.now)["inferred"]["last_suspected_draw"]["basis"] == (
        "bottom_reading_fell_without_heating"
    )


def test_heating_after_a_draw_is_recorded_with_energy_and_performance():
    feed = Feed(local(hour=19), 62.0)
    feed.run(31)
    feed.reading = 40.0
    feed.run(31)
    observer = feed.run(90, element="on", rate=0.2)  # 12 °C/h = 4 °C per kWh at 3 kW
    assert observer.state == "heating_after_draw"
    observer = feed.run(35, element="off")
    assert observer.state == "settling_after_heating"
    session = observer.sessions[-1]
    assert session["after_draw"] and session["thermostat_satisfied"]
    assert abs(session["energy_kwh"] - 4.5) < 0.1
    assert session["observed_c_per_kwh"] > thermal.PHYSICAL_C_PER_KWH  # stratified tank
    summary = observer.summary(feed.now)
    assert summary["inferred"]["heating_after_draw"]["sessions"] == 1
    assert summary["affects_control"] is False


def test_drop_soon_after_heating_is_only_low_confidence():
    feed = Feed(local(hour=14), 50.0)
    feed.run(40, element="on", rate=0.15)
    feed.run(31, element="off")  # a poll after heating ended
    feed.reading -= 4  # bottom sensor falling back after heating
    observer = feed.run(31)
    assert observer.last_draw["confidence"] == "low"


def test_persistence_round_trip_and_bounded_writes():
    feed = Feed(local(hour=19), 62.0)
    feed.run(31)
    feed.reading = 40.0
    observer = feed.run(31)
    assert observer.should_save(feed.now)
    assert not observer.should_save(feed.now)  # nothing new
    restored = thermal.ThermalObserver.from_dict(observer.to_dict())
    assert restored.last_draw == observer.last_draw and len(restored.draws) == 1
    assert thermal.ThermalObserver.from_dict({"version": 9}).sessions == thermal.deque()
    assert len(observer.to_dict()["draws"]) <= thermal.MAX_DRAWS


def test_unknown_without_readings_and_labels_on_every_output():
    observer = thermal.ThermalObserver()
    observer.update(local(hour=1), None, None, "unknown", "none", None)
    summary = observer.summary(local(hour=1))
    assert summary["state"] == "unknown" and summary["confidence"] == "none"
    assert set(summary) >= {"measured", "estimated", "inferred", "affects_control"}


def test_no_control_module_imports_the_thermal_observer():
    for name in ("controller.py", "simple_policy.py", "executor.py"):
        tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "thermal" not in imported, name
