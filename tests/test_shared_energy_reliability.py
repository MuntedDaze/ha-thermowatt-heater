"""Shared selector reports through the real runtime, policy and mocked bridge."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_cloud_outage_recovery import AvailabilityRig, advance
from test_controller_0_9_0 import ctl, local, obs, ready, want, cfg
from test_integration_0_9_0 import MON, Rig, drive, hobart


SOURCE = "sensor.synthetic_selector_source"
VALID = "binary_sensor.synthetic_selector_valid"
GRID = "sensor.selected_grid"
SOLAR = "sensor.selected_solar"
HOUSE = "sensor.selected_house"
CT = "sensor.synthetic_heater_w"


def shared_rig(tmp_path, monkeypatch, *, ct=False, start=None, mode="Manual", reading=54):
    rig = Rig(
        tmp_path, monkeypatch, start or hobart(MON, 12), mode=mode, setpoint=62, reading=reading
    )
    rig.entry.options.update(
        import_positive=True,
        normal_storage_c="62",
        forecast_enabled=False,
        ct_free_solar_verification="" if ct else f"{GRID}|W|import_positive|3",
        heater_meter_verification=f"{CT}|W" if ct else "",
    )
    rig.runtime.apply_options(
        rig.entry.options,
        {
            **rig.sources,
            "energy_source": SOURCE,
            "energy_data_valid": VALID,
            "grid": GRID,
            "pv": SOLAR,
            "pv_ac": SOLAR,
            "house": HOUSE,
            "heater_power": CT if ct else "",
        },
    )
    return rig


def powers(rig, source, observed=None, *, grid=-4500):
    rig.report(SOURCE, source)
    rig.report(VALID, "on")
    for entity, power in ((GRID, grid), (SOLAR, 5000), (HOUSE, 500)):
        rig.report(
            entity,
            power,
            {
                "unit_of_measurement": "W",
                "measurement_source": source,
                "measurement_observed_at": (observed or rig.now()).isoformat(),
            },
        )


def step(rig):
    rig.runtime.update(rig.now())
    drive(rig.executor.async_step(rig.now()))


def test_shared_fallback_and_recovery_each_restart_surplus_coverage(tmp_path, monkeypatch):
    rig = shared_rig(tmp_path, monkeypatch)
    policy = rig.executor.policy
    for source in ("primary", "fallback", "primary"):
        for minute in range(11):
            rig.t += 60
            powers(rig, source)
            step(rig)
            assert rig.runtime.grid_import_kw == -4.5
            assert rig.runtime._kw("house", rig.now()) == 0.5
            assert rig.runtime.grid_observed_at == rig.now()
            assert policy.surplus_qualified(rig.now()) is (minute == 10)
    rig.executor.controller.solar_session_active = True
    rig.report(VALID, "off")
    rig.runtime.sync_shared_energy(rig.now())  # selector transition captured before evaluation
    assert rig.runtime.solar_input_loss_pending and not policy.samples
    step(rig)
    assert rig.runtime.grid_import_kw is None
    assert rig.runtime._kw("house", rig.now()) is None
    assert rig.runtime._kw("pv", rig.now()) is None
    assert not rig.commands() and not rig.posts


def test_loss_of_both_energy_sources_preserves_required_weekday_storage(tmp_path, monkeypatch):
    rig = shared_rig(tmp_path, monkeypatch, start=hobart(MON, 10, 50), mode="Off", reading=42)
    rig.report(SOURCE, "unavailable")
    rig.report(VALID, "off")
    rig.enable()
    rig.run(hobart(MON, 16, 29))
    assert rig.runtime.grid_import_kw is None
    assert rig.commands() == ["Manual:62@off"]
    assert [post[2]["T_SetPoint"] for post in rig.posts if post[1] == "manual"] == [62]
    assert rig.executor.controller.state == "normal_storage_62"


@pytest.mark.parametrize("use_ct", [False, True])
def test_republished_template_or_ct_cannot_extend_old_physical_report(
    tmp_path, monkeypatch, use_ct
):
    rig = shared_rig(tmp_path, monkeypatch, ct=use_ct)
    rig.t += 60
    measured = rig.now()
    for seconds in range(15, 151, 15):
        rig.t = measured.timestamp() + seconds
        powers(rig, "fallback", measured)
        rig.report(CT, 0, {"unit_of_measurement": "W"})
        step(rig)
        assert len(rig.executor.policy.samples) <= 1
        if seconds <= 120:
            assert rig.runtime.grid_observed_at == measured
        else:
            assert rig.runtime.grid_import_kw is None
            assert rig.runtime._kw("house", rig.now()) is None
        assert not rig.executor.policy.surplus_qualified(rig.now())


def test_ct_pair_changes_do_not_create_two_votes_for_one_grid_report(tmp_path, monkeypatch):
    rig = shared_rig(tmp_path, monkeypatch, ct=True)
    rig.t += 60
    rig.report(CT, 0, {"unit_of_measurement": "W"})
    early_ct = rig.now()
    rig.t += 30
    measured = rig.now()
    powers(rig, "fallback", measured)
    step(rig)
    assert [sample[0] for sample in rig.executor.policy.samples] == [early_ct]
    rig.t += 15
    rig.report(CT, 0, {"unit_of_measurement": "W"})
    step(rig)
    assert [sample[0] for sample in rig.executor.policy.samples] == [early_ct]


def test_shared_mixed_source_and_invalid_timestamp_are_rejected(tmp_path, monkeypatch):
    rig = shared_rig(tmp_path, monkeypatch)
    powers(rig, "primary")
    rig.report(SOURCE, "fallback")
    step(rig)
    assert rig.runtime.grid_import_kw is None
    assert rig.runtime._kw("house", rig.now()) is None
    powers(rig, "fallback", rig.now() + timedelta(seconds=1))
    step(rig)
    assert rig.runtime.grid_import_kw is None
    powers(rig, "fallback")
    del rig.states[GRID].attributes["measurement_observed_at"]
    step(rig)
    assert rig.runtime.grid_import_kw is None
    rig.runtime.sources.pop("energy_data_valid")
    assert rig.runtime._kw("pv", rig.now()) is None  # partial setup also fails closed


def test_transient_source_loss_is_latched_even_when_metadata_recovers_before_tick(
    tmp_path, monkeypatch
):
    rig = shared_rig(tmp_path, monkeypatch)
    powers(rig, "primary")
    step(rig)
    rig.executor.controller.solar_session_active = True
    rig.report(VALID, "off")
    rig.runtime.sync_shared_energy(rig.now())
    assert rig.runtime.grid_import_kw is None and rig.runtime.power_budget is None
    rig.report(VALID, "on")
    rig.runtime.sync_shared_energy(rig.now())
    assert rig.runtime.solar_input_loss_pending
    assert not rig.executor.policy.samples


def test_startup_unknown_and_successful_recovery_are_quiet():
    now = local(hour=2)
    controller = ready(now, "Manual", 45)
    for minute in (0, 10, 30):
        at = now + timedelta(minutes=minute)
        evaluation = controller.step(
            obs(at, "Manual", 45, poll_at=None, cloud_health="unknown", bridge_starting=True),
            want("hold"),
            cfg(),
        )
        assert not [effect for effect in evaluation if effect.kind == "notify"]
    at = now + timedelta(minutes=31)
    evaluation = controller.step(obs(at, "Manual", 45), want("hold"), cfg())
    assert not [effect for effect in evaluation if effect.kind == "notify"]


def test_persistent_unknown_cloud_incident_deduplicates_through_restart_and_recurs():
    now = local(hour=2)
    controller = ready(now, "Manual", 45)
    for minutes, expected in ((0, []), (10, ["cloud_fault"]), (440, [])):
        at = now + timedelta(minutes=minutes)
        if minutes == 440:
            controller = ctl.Controller.from_dict(controller.to_dict())
            controller.restored(at)
        evaluation = controller.step(
            obs(at, "Manual", 45, poll_at=now - timedelta(hours=2), cloud_health="unknown"),
            want("hold"),
            cfg(),
        )
        assert [e.key for e in evaluation if e.kind == "notify"] == expected
    at = now + timedelta(minutes=441)
    recovery = controller.step(obs(at, "Manual", 45), want("hold"), cfg())
    assert [(e.kind, e.key) for e in recovery] == [("resolve", "cloud_fault")]
    at += timedelta(minutes=1)
    fault = controller.step(obs(at, "Manual", 45, cloud_health="auth_locked"), want("hold"), cfg())
    assert [(e.kind, e.key) for e in fault] == [("notify", "cloud_fault")]


def test_quota_cooldown_is_quiet_but_manual_intervention_alerts():
    now = local(hour=2)
    controller = ready(now, "Manual", 45)
    for minute, auth in [(0, "authorized"), (30, "authorized"), (31, "blocked")]:
        at = now + timedelta(minutes=minute)
        effects = controller.step(
            obs(at, "Manual", 45, cloud_health="quota_limited", auth_mode=auth),
            want("hold"),
            cfg(),
        )
        assert [e.key for e in effects if e.kind == "notify"] == (
            ["cloud_fault"] if auth == "blocked" else []
        )


def test_upgrade_preserves_open_legacy_status_notice_until_recovery():
    now = local(hour=2)
    controller = ready(now, "Manual", 45)
    legacy = {**controller.to_dict(), "alerts": {"status_stale": now.isoformat()}}
    controller = ctl.Controller.from_dict(legacy)
    controller.restored(now)
    still_stale = obs(now, "Manual", 45, poll_at=now - timedelta(hours=2))
    assert not controller.step(still_stale, want("hold"), cfg())
    assert controller.alerts == legacy["alerts"]
    healthy = obs(now + timedelta(minutes=1), "Manual", 45, poll_age=0)
    effects = controller.step(healthy, want("hold"), cfg())
    assert [(e.kind, e.key) for e in effects] == [("resolve", "status_stale")]


def test_publish_failure_notification_is_persisted_before_next_step():
    now = local(hour=2)
    controller = ready(now, "Manual", 45)
    assert [e.key for e in controller.publish_failed(now)] == ["fault_publish_failed"]
    controller = ctl.Controller.from_dict(controller.to_dict())
    controller.restored(now)
    assert not [
        e
        for e in controller.step(obs(now, "Manual", 45), want("hold"), cfg())
        if e.kind == "notify"
    ]


def test_overnight_alerts_respect_accepted_lease_despite_restart_reinspection(
    tmp_path, monkeypatch
):
    rig = AvailabilityRig(tmp_path, monkeypatch, hobart(MON, 0), mode="Manual", setpoint=45)
    rig.enable()
    advance(rig, hobart(MON, 3))
    last = rig.executor.last_observation
    assert last.passive_status_deadline is not None and last.passive_status_deadline > rig.now()
    rig.executor.last_decision = None
    observed = rig.executor.observe(rig.now())
    assert observed.passive_status_deadline == last.passive_status_deadline
    assert not rig.notifications
    state = rig.states[rig.sources["cloud_health"]]
    state.attributes["adaptive_polling"]["next_at"] = rig.t + 5000  # overdue summary can move
    state.attributes["adaptive_polling"]["interval_seconds"] = 30 * 60
    observed = rig.executor.observe(rig.now())
    assert observed.passive_status_deadline == observed.poll_at + timedelta(minutes=35)
    state.attributes["last_successful_poll"] = (
        observed.poll_at + timedelta(milliseconds=123)
    ).isoformat()
    assert (
        rig.executor.observe(rig.now()).passive_status_deadline == observed.passive_status_deadline
    )
    state.attributes["last_successful_poll"] = (observed.poll_at - timedelta(minutes=1)).isoformat()
    assert rig.executor.observe(rig.now()).passive_status_deadline is None


def test_shared_event_capture_rejects_mismatched_provenance(tmp_path, monkeypatch):
    rig = shared_rig(tmp_path, monkeypatch)
    powers(rig, "primary")
    rig.report(SOURCE, "fallback")
    event = SimpleNamespace(data={"entity_id": GRID, "new_state": rig.states[GRID]})
    rig.runtime.capture_input_report(event, rig.now())
    assert not rig.executor.policy.samples
