"""One common tariff model: zones, seasonal windows, no-solar/CT-free control."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import pytest
from zoneinfo import ZoneInfo

from test_shadow_model import m, c
from test_simple_policy import sp, snap
from test_integration_0_9_0 import Rig, hobart
from test_simple_policy import MON
from test_public_dual_installation import install


def table(rows):
    return json.dumps(rows)


def period(start="00:00", end="00:00", kind="off_peak", **extra):
    return {"days": list(range(7)), "start": start, "end": end, "kind": kind, **extra}


@pytest.mark.parametrize(
    "zone,summer_standard,summer_local",
    [
        ("Australia/Perth", 8, 8),
        ("Australia/Adelaide", 9.5, 10.5),
        ("Australia/Sydney", 10, 11),
        ("Pacific/Auckland", 12, 13),
        ("Europe/London", 0, 0),
    ],
)
def test_iana_zone_and_separate_standard_clock(zone, summer_standard, summer_local):
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert (
        now.astimezone(m.tariff_zone(now, "standard", zone)).utcoffset().total_seconds() / 3600
        == summer_standard
    )
    assert (
        now.astimezone(m.tariff_zone(now, "local", zone)).utcoffset().total_seconds() / 3600
        == summer_local
    )


def test_same_utc_minute_can_have_different_tariffs_in_different_zones():
    _, tariffs = c.parse_options({"tariff_clock": "standard"})
    now = datetime(2026, 11, 16, 6, tzinfo=timezone.utc)
    assert m.tariff_at(now, tariffs, "local", "Australia/Perth").kind == "off_peak"
    assert m.tariff_at(now, tariffs, "local", "Australia/Sydney").kind == "peak"


def test_seasonal_rates_full_coverage_and_midnight_month_boundary():
    rows = [period(months=list(range(1, 7)), rate=0.2), period(months=list(range(7, 13)), rate=0.4)]
    _, tariffs = c.parse_options(
        {"tariff_profile": "custom", "tariff_periods": table(rows), "time_zone": "Australia/Perth"}
    )
    for month, rate in [(6, 0.2), (7, 0.4), (12, 0.4), (1, 0.2)]:
        now = datetime(2026, month, 1, tzinfo=ZoneInfo("Australia/Perth"))
        assert m.tariff_at(now, tariffs, "local", "Australia/Perth").rate == rate
    for bad in (rows[:1], [period(), period(months=[1])], [period(months=[0])]):
        with pytest.raises(ValueError):
            c.parse_options({"tariff_profile": "custom", "tariff_periods": table(bad)})


def test_flat_rate_without_forecasts_or_ct_still_requests_normal_weekday_storage():
    opts = {
        **install.fresh_options("Australia/Perth"),
        "off_peak_rate": 0.3,
        "tariff_verified": True,
    }
    settings, tariffs = c.parse_options(opts)
    policy = sp.SimplePolicy(
        replace(
            sp.PolicySettings(),
            time_zone=settings.time_zone,
            tariff_clock="local",
            boost_enabled=False,
        ),
        tariffs,
    )
    now = datetime(2026, 11, 16, 14, tzinfo=ZoneInfo(settings.time_zone))
    decision = policy.decide(snap(now, sp.OFF, reading=40, heater_meter_valid=False, forecast=()))
    assert decision.command == "Manual:62" and decision.plan["heating_role"] == "required"
    assert policy.next_peak(now) is None
    after = now.replace(hour=21, minute=1)
    assert policy.decide(snap(after, sp.NORMAL, heater_meter_valid=False)).command == "Manual:45"
    weekend = now + timedelta(days=5)
    assert policy.decide(snap(weekend, sp.OFF, heater_meter_valid=False)).command == "Manual:45"


def test_known_midday_discount_is_used_without_solar_or_a_forecast():
    rows = [
        period("00:00", "12:00", rate=0.4),
        period("12:00", "15:00", kind="shoulder", rate=0.08),
        period("15:00", "00:00", rate=0.4),
    ]
    _, tariffs = c.parse_options(
        {"tariff_profile": "custom", "tariff_periods": table(rows), "time_zone": "Australia/Perth"}
    )
    policy = sp.SimplePolicy(
        replace(
            sp.PolicySettings(),
            time_zone="Australia/Perth",
            tariff_clock="local",
            boost_enabled=False,
        ),
        tariffs,
    )
    noon = datetime(2026, 11, 16, 12, tzinfo=ZoneInfo("Australia/Perth"))
    before = policy.decide(
        snap(noon - timedelta(hours=2), sp.OFF, reading=45, heater_meter_valid=False)
    )
    assert before.command is None and before.plan["best_start"].hour == 12
    assert (
        policy.decide(snap(noon, sp.OFF, reading=45, heater_meter_valid=False)).command
        == "Manual:62"
    )


def test_cloud_only_no_solar_enable_keeps_actual_command_guards(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 13, 50), reading=40)
    options = {
        **rig.entry.options,
        "normal_storage_c": "62",
        "tariff_profile": "flat",
        "forecast_enabled": False,
        "optional_solar_boost": False,
    }
    rig.entry.options.update(options)
    rig.sources = {k: v for k, v in rig.sources.items() if k in c.CLOUD_SOURCES}
    rig.runtime.apply_options(options, rig.sources)
    rig.executor.configure(options)
    rig.enable()
    rig.run(hobart(MON, 14, 5))
    assert rig.commands() == ["Manual:62@off"]
    assert rig.executor.last_observation.element == "unknown"
    assert rig.executor.last_observation.forecast_available is None


@pytest.mark.parametrize(
    "options",
    [
        {"time_zone": "not/a_zone"},
        {"daytime_start": "17:00"},
        {"storage_ready_time": "23:00"},
        {"baseline_start": "08:00"},
    ],
)
def test_invalid_common_configuration_is_atomic(options):
    with pytest.raises(ValueError):
        c.parse_options(options)
