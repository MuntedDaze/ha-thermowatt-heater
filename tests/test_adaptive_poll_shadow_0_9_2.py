"""Pure shadow advisory for adaptive Thermann cloud polling.

All recommendations remain informational; no bridge configuration or cloud
request is changed by these tests or the advisor module.
"""

from datetime import timedelta
import importlib

from test_controller_0_9_0 import local, m

advisor = importlib.import_module(f"{m.__package__}.polling_advisor")


def advice(**overrides):
    now = local(hour=12)
    base = dict(
        now=now,
        poll_at=now - timedelta(minutes=2),
        mode="Manual",
        temperature_c=40,
        target_c=70,
        heater_power_kw=2.9,
        heater_meter_configured=True,
        next_tariff_at=now + timedelta(hours=4),
        cloud_health="ok",
    )
    base.update(overrides)
    return advisor.recommend_poll(**base)


def test_long_metered_heating_recommends_bounded_60_minutes():
    result = advice()
    assert result["shadow_only"] is True
    assert result["recommended_interval_minutes"] == 60
    assert result["reason"] == "metered_heating_far_from_target"
    assert result["estimated_heating_minutes"] > 100


def test_near_target_shorter_poll_and_thermostat_idle_longer():
    near = advice(temperature_c=67)
    assert near["recommended_interval_minutes"] == 30
    assert near["reason"] == "metered_heating_near_target"

    idle = advice(heater_power_kw=0)
    assert idle["recommended_interval_minutes"] == 90
    assert idle["reason"] == "verified_element_idle"


def test_unknown_ct_and_override_keep_sensible_shorter_interval():
    assert advice(heater_power_kw=None)["recommended_interval_minutes"] == 30
    assert advice(heater_meter_configured=False)["recommended_interval_minutes"] == 30
    assert advice(owner_override=True)["recommended_interval_minutes"] == 30


def test_tariff_boundary_and_missing_cloud_status():
    now = local(hour=12)
    boundary = advice(next_tariff_at=now + timedelta(minutes=20))
    assert boundary["recommended_interval_minutes"] == 15
    assert boundary["reason"] == "tariff_boundary_approaching"
    assert advice(poll_at=None)["recommended_due_at"] == now.isoformat()


def test_cloud_failures_defer_retries_entirely_to_existing_bridge():
    blocked = advice(cloud_health="backoff")
    assert blocked["recommended_due_at"] is None
    assert blocked["recommended_interval_minutes"] is None
    assert blocked["reason"] == "cloud_unavailable_bridge_controls_retry"
