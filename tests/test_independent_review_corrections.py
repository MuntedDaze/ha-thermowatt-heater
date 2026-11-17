"""Independent Astra review reproductions, real code with synthetic evidence."""

from dataclasses import replace
from datetime import timedelta
import importlib
from types import SimpleNamespace

import pytest

from test_next_major_policy import S, sp, TARIFFS, at, MON, MIN, snap, ctl, m
from test_audit_regressions_0_9_1 import controller_ready, observation, config, published
from test_integration_0_9_0 import Rig, hobart, drive, SERIAL, c
from test_existing_installation_upgrade import ct_free
from test_next_major_integration import smart

report = importlib.import_module(f"{m.__package__}.report")


@pytest.mark.parametrize(
    "step,duration,kind",
    [(130, 600, "import"), (130, 600, "export"), (120, 900, "pv"), (130, 1800, "sunset")],
)
def test_nondivisor_cadence_covers_actual_duration_without_early_or_missing_trigger(
    step, duration, kind
):
    now = at(MON, 12)
    p = sp.SimplePolicy(replace(S, meter_max_age=timedelta(seconds=180)), TARIFFS)

    def qualifies(t):
        if kind == "import":
            return p.importing_continuously(t)
        if kind == "export":
            return p.surplus_qualified(t)
        return p.pv_sustained(
            t, timedelta(seconds=duration), lambda kw: kw >= 0.5 if kind == "pv" else kw < 0.2
        )

    for seconds in range(0, duration + step + 1, step):
        t = now + timedelta(seconds=seconds)
        if kind in {"pv", "sunset"}:
            p.add_pv(t, 1 if kind == "pv" else 0.1)
        else:
            p.add_meter(t, 0.4 if kind == "import" else -4, heater_kw=0)
        assert qualifies(t) is (seconds >= duration)
    assert not qualifies(t + timedelta(seconds=181))


@pytest.mark.parametrize("kind", ["import", "export", "pv"])
def test_failed_intermediate_report_resets_continuous_evidence(kind):
    now = at(MON, 12)
    p = sp.SimplePolicy(S, TARIFFS)
    for second in (0, 100, 210, 320, 460, 590, 730):
        t = now + timedelta(seconds=second)
        if kind == "pv":
            p.add_pv(t, 0.1 if second == 320 else 1)
        else:
            kw = (
                (0.1 if second == 320 else 0.4)
                if kind == "import"
                else (-1 if second == 320 else -4)
            )
            p.add_meter(t, kw, heater_kw=0)
    assert not (
        p.pv_sustained(t, 10 * MIN, lambda kw: kw >= 0.5)
        if kind == "pv"
        else p.importing_continuously(t)
        if kind == "import"
        else p.surplus_qualified(t)
    )


def test_in_place_peak_adoption_requires_full_start_quality_and_records_no_command():
    now = at(MON, 18)
    p = sp.SimplePolicy(replace(S, boost_enabled=False, peak_policy=sp.PEAK_SOLAR), TARIFFS)
    for i in range(11):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    state = snap(
        now,
        sp.NORMAL,
        reading=50,
        heater_meter_valid=False,
        ct_free_solar_valid=True,
        optional_adoption_ready=True,
    )
    blocked = p.decide(
        replace(state, optional_start_quality="fresh_grid_inverter_and_house_readings_required")
    )
    assert (
        blocked.state == sp.OFF
        and blocked.plan["boost_reason"] == "fresh_grid_inverter_and_house_readings_required"
    )
    d = p.decide(state)
    assert d.state == sp.NORMAL and d.command is None and d.plan["adopt_solar_session"]
    controller = controller_ready(now, "Manual", 62)
    controller.solar_session_active = False
    obs = observation(now, "Manual", 62, poll_at=now)
    obs.bridge_transitions.append("off@62")
    cfg = replace(config(), four_state_qualified=True)
    assert controller.solar_adoption_ready(obs, cfg)
    effects = controller.step(obs, ctl.Want(d.state, d.reason, d.layer, d.plan), cfg)
    assert controller.solar_session_active and not published(effects) and not controller.intent
    assert controller.commands == []
    # Heater's consumption naturally removes initial full surplus. This does
    # not need requalification, nor does losing asynchronous AC/house freshness.
    p.add_meter(now + MIN, -0.4, heater_kw=0)
    d = p.decide(
        replace(
            state,
            now=now + MIN,
            optional_session_active=True,
            optional_start_quality="fresh_grid_inverter_and_house_readings_required",
        )
    )
    assert d.state == sp.NORMAL
    saved = controller.to_dict()
    restored = ctl.Controller.from_dict(saved)
    restored.restored(now + 2 * MIN)
    assert not restored.solar_session_active
    d = p.decide(replace(state, now=now + MIN, optional_adoption_ready=False))
    assert d.state == sp.OFF


@pytest.mark.parametrize(
    "margin,lead,valid",
    [(5, 5, False), (5, 10, False), (10, 10, False), (6, 5, True), (5, 2, True)],
)
def test_shared_validation_rejects_policy_constructor_conflicts(margin, lead, valid):
    from test_shadow_model import c

    opts = {"completion_margin_minutes": margin, "peak_command_lead_minutes": lead}
    if valid:
        c.parse_options(opts)
    else:
        with pytest.raises(ValueError, match="completion_margin_not_after_peak_lead"):
            c.parse_options(opts)


def test_raw_pv_dip_and_grid_reset_reports_survive_coalesced_evaluations(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(14, 12), mode="Manual", setpoint=45)
    ct_free(rig)
    p = rig.executor.policy
    now = rig.now()
    for i in range(16):
        p.add_pv(now - (15 - i) * MIN, 1)
    assert p.pv_sustained(now, 15 * MIN, lambda kw: kw >= 0.5)

    def captured(key, watts, seconds):
        when = now + timedelta(seconds=seconds)
        state = SimpleNamespace(
            state=str(watts), last_reported=when, attributes={"unit_of_measurement": "W"}
        )
        event = SimpleNamespace(data={"entity_id": rig.sources[key], "new_state": state})
        rig.runtime.capture_input_report(event, when)

    captured("pv", 100, 1)
    captured("pv", 1000, 2)
    assert not p.pv_sustained(now + timedelta(seconds=2), 15 * MIN, lambda kw: kw >= 0.5)
    p.samples.clear()
    for i in range(11):
        p.add_meter(now - (10 - i) * MIN, 0.4, heater_kw=0)
    assert p.importing_continuously(now)
    # Export-positive raw +100W = acceptable export, then back to400W import.
    captured("grid", 100, 1)
    captured("grid", -400, 2)
    assert not p.importing_continuously(now + timedelta(seconds=2))


def test_export_retains_solar_reason_override_and_real_transition_timestamps():
    now = at(MON, 12)
    event = report.event(
        {"at": now, "boost_eligible": False, "boost_reason": "sustained_full_solar_required"}
    )
    assert (
        event["boost_reason"] == "sustained_full_solar_required"
        and event["boost_eligible"] is False
    )
    assert (
        report.event({"boost_reason": "private_secret", "boost_eligible": "private_secret"})[
            "boost_reason"
        ]
        == "unreported"
    )
    assert report.code("12hr_override") == "12hr_override"
    command = report.command({"resolved_at": now, "since": now})
    assert command["resolved_at"] == command["since"] == now.isoformat()


def test_quiet_lease_supervision_requires_fresh_diagnostics_and_actual_deadline(
    tmp_path, monkeypatch
):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 2), mode="Manual", setpoint=45, reading=45)
    ct_free(rig)
    smart(rig)
    rig.enable()
    rig.run(hobart(MON, 2, 35))
    now = rig.now()
    obs = replace(rig.executor.last_observation, passive_status_deadline=None)
    plan = {
        "active": True,
        "plan_version": 3,
        "reason": "quiet_before_decision",
        "owner_check_seconds": 28800,
        "next_at": (now + 10 * MIN).timestamp(),
    }
    rig.executor._quiet_deadline(obs, plan)
    assert obs.passive_status_deadline == now + 15 * MIN
    obs = replace(obs, passive_status_deadline=None, bridge_available=False)
    rig.executor._quiet_deadline(obs, plan)
    assert obs.passive_status_deadline is None
    health = rig.states[rig.sources["cloud_health"]]
    health.last_reported = now - timedelta(seconds=121)
    obs = replace(obs, bridge_available=True)
    rig.executor._quiet_deadline(obs, plan)
    assert obs.passive_status_deadline is None


def test_confirmed_weekend_evening_baseline_can_use_quiet_polling(tmp_path, monkeypatch):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(14, 19),
        mode="Manual",
        setpoint=45,
        reading=45,
        pv=lambda local: 0,
    )
    ct_free(rig)
    smart(rig)
    rig.enable()
    rig.run(hobart(14, 19, 35))
    d = rig.executor.last_decision
    assert d.reason == "weekend_day_ended"
    assert rig.executor._quiet_state(rig.executor.last_observation, d) == "baseline"


def test_owner_setting_index_is_independent_of_installed_timezone_aliases(monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "tools/build_owner_settings.py"
    spec = importlib.util.spec_from_file_location("_owner_setting_index_test", path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    before = builder.build()
    catalog = dict(builder.settings.CATALOG)
    catalog["time_zone"] = replace(
        catalog["time_zone"], choices=("Australia/Hobart", "Some_OS_Alias")
    )
    monkeypatch.setattr(builder.settings, "CATALOG", catalog)
    assert builder.build() == before


@pytest.mark.parametrize("quality", ["missing", "inconsistent", "valid"])
def test_actual_executor_generates_safe_peak_adoption_from_raw_ct_free_inputs(
    tmp_path, monkeypatch, quality
):
    # Component evidence test: independent genuine HA reports with a cold cloud
    # probe, not a uniform-tank energy/cost simulation or physical ON/OFF claim.
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(MON, 16, 40),
        mode="Manual",
        setpoint=62,
        reading=50,
        pv=lambda local: 4,
    )
    ct_free(rig)
    rig.sources["pv_ac"] = c.DEFAULT_PV_AC
    rig.entry.options.update(optional_solar_boost=False)
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    rig.enable()
    for minute in range(18):
        rig.t += 60
        rig._meter()
        if quality == "missing":
            rig.report(c.DEFAULT_PV_AC, "unavailable", {"unit_of_measurement": "W"})
        elif quality == "inconsistent":
            rig.report(c.DEFAULT_PV_AC, 1000, {"unit_of_measurement": "W"})
        if minute in (0, 17):
            rig.bridge.poll_status(SERIAL)
        rig.runtime.update(rig.now())
        drive(rig.executor.async_step(rig.now()))
    d = rig.executor.last_decision
    if quality == "valid":
        assert d.state == sp.NORMAL and d.plan["adopt_solar_session"]
        assert rig.executor.controller.solar_session_active and not rig.commands()
        rig.t += 60
        rig._meter()
        rig.report(rig.sources["grid"], 400, {"unit_of_measurement": "W"})
        rig.runtime.update(rig.now())
        drive(rig.executor.async_step(rig.now()))
        assert rig.executor.last_decision.reason == "peak_solar_continues"
        assert not rig.commands()
    else:
        assert d.state == sp.OFF and d.reason == "peak_no_qualified_session"
        assert rig.commands() == ["off@62"]
