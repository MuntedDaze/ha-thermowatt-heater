"""Regression tests for fault lifecycle, acknowledgement, audit timestamps, and solar qualification.

Covers the 26 November 2026 post-commissioning findings:
1. Toggling Automatic control (disable/enable) or Hold/Resume must NEVER bypass a fault.
2. Persisted faults survive disable, restart, and upgrades from orphaned 0.18.2 state.
3. Owner acknowledgement works safely from both fault_locked and disabled states,
   records audit history (last_acknowledged_fault/at), and enforces fresh heater-state
   reinspection before acting.
4. Command audit metadata populates sent_at (only from bridge-proven POST posted_at)
   and confirmed_at (only on confirmed status readback), leaving them None when unsent
   or unconfirmed.
5. Solar qualification preserves the 10-minute continuity window and 3.3 kW startup
   threshold, while clearing an acknowledged fault allows solar_input_loss_pending
   and solar_adoption_ready to recover cleanly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib
import sys
from types import ModuleType
from zoneinfo import ZoneInfo

from test_controller_0_9_0 import cfg, ctl, obs
from test_integration_0_9_0 import MON, Rig, drive, hobart
from test_shadow_model import m

report = importlib.import_module(f"{m.__package__}.report")
HOBART = ZoneInfo("Australia/Hobart")
MIN = timedelta(minutes=1)


def _faulted_controller(now: datetime) -> ctl.Controller:
    c = ctl.Controller()
    c.set_enabled(True, now - 10 * MIN)
    c.step(obs(now - 9 * MIN, mode="Off", target_c=None), ctl.Want(ctl.OFF, "parked"), cfg())
    effects = c.step(
        obs(now - 8 * MIN, mode="Off", target_c=None),
        ctl.Want(ctl.BASELINE, "baseline"),
        cfg(),
    )
    assert any(e.kind == "publish" for e in effects)
    assert c.state == ctl.CONFIRMING
    c.step(
        obs(now, mode="Off", target_c=None, poll_at=now),
        ctl.Want(ctl.BASELINE, "baseline"),
        cfg(),
    )
    assert c.state == ctl.FAULT_LOCKED
    assert c.fault == "command_not_applied"
    assert c.heater is None
    return c


# ------------------------------------------------------------------ 1. Fault lifecycle & bypass guards
def test_disable_and_reenable_never_bypasses_fault_locked():
    now = datetime(2026, 11, 25, 23, 0, tzinfo=HOBART)
    c = _faulted_controller(now)

    # Owner disables Automatic control to manage heater manually via official app.
    c.set_enabled(False, now + MIN)
    assert c.state == ctl.DISABLED
    assert c.fault == "command_not_applied"
    assert c.heater is None
    effects = c.step(
        obs(now + 2 * MIN, mode="Manual", target_c=62, poll_at=now + 2 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert not [e for e in effects if e.kind == "publish"]
    assert c.state == ctl.DISABLED
    assert c.fault == "command_not_applied"

    # Re-enabling Automatic control without acknowledging MUST lock immediately into fault_locked.
    assert "fault_command_not_applied" in c.alerts
    assert not any(e.kind == "notify" for e in effects)
    c.set_enabled(True, now + 5 * MIN)
    assert c.enabled is True
    assert c.state == ctl.FAULT_LOCKED
    assert c.reason == "command_not_applied"
    assert c.fault == "command_not_applied"
    assert c.heater is None

    # Even with a fresh status poll and policy wanting OFF, NO command may be published.
    effects = c.step(
        obs(now + 6 * MIN, mode="Manual", target_c=62, poll_at=now + 6 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert not [e for e in effects if e.kind == "publish"]
    assert c.state == ctl.FAULT_LOCKED
    assert c.fault == "command_not_applied"
    assert not any(e.kind == "notify" for e in effects)
    # Subsequent tick must NOT spam duplicate notifications.
    effects_again = c.step(
        obs(now + 7 * MIN, mode="Manual", target_c=62, poll_at=now + 7 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert not [e for e in effects_again if e.kind == "notify"]


def test_hold_and_resume_never_bypass_fault_locked():
    now = datetime(2026, 11, 25, 23, 0, tzinfo=HOBART)
    c = _faulted_controller(now)

    c.set_hold(now + MIN)
    assert c.state == ctl.FAULT_LOCKED
    assert c.fault == "command_not_applied"
    assert not c.resume(now + 2 * MIN)
    assert c.state == ctl.FAULT_LOCKED
    assert not c.start_guest(now + 2 * MIN)
    assert c.refusal == "acknowledge_the_controller_fault_first"

    # If owner held AND then acknowledged, hold is still respected (owner_override, not acting).
    assert c.acknowledge(now + 3 * MIN) is True
    assert c.fault is None
    assert c.last_acknowledged_fault == "command_not_applied"
    assert c.last_acknowledged_at == (now + 3 * MIN).isoformat()
    assert c.state == ctl.OWNER_OVERRIDE
    effects = c.step(
        obs(now + 4 * MIN, mode="Manual", target_c=62, poll_at=now + 4 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert not [e for e in effects if e.kind == "publish"]


def test_orphaned_0_18_2_fault_heals_on_load_and_restore_and_can_be_acknowledged():
    now = datetime(2026, 11, 26, 9, 41, tzinfo=HOBART)
    legacy = _faulted_controller(now - timedelta(hours=10)).to_dict()
    # Simulate the exact broken 0.18.2 persisted state observed on live HA:
    # enabled=True, state="parked", fault="command_not_applied".
    legacy.update(enabled=True, state=ctl.PARKED, reason="off_confirmed", heater=ctl.OFF)

    loaded = ctl.Controller.from_dict(legacy)
    assert loaded.state == ctl.FAULT_LOCKED
    assert loaded.reason == "command_not_applied"
    assert loaded.fault == "command_not_applied"
    assert loaded.heater is None

    loaded.restored(now)
    assert loaded.state == ctl.FAULT_LOCKED
    assert loaded.fault == "command_not_applied"
    # Refuses commands until explicitly acknowledged.
    effects = loaded.step(
        obs(now + MIN, mode="Off", target_c=None, poll_at=now + MIN),
        ctl.Want(ctl.BASELINE, "baseline"),
        cfg(),
    )
    assert not [e for e in effects if e.kind == "publish"]
    assert loaded.state == ctl.FAULT_LOCKED

    # Owner acknowledges -> clears fault, records history, requires fresh post-acknowledge poll.
    assert loaded.acknowledge(now + 2 * MIN) is True
    assert loaded.fault is None
    assert loaded.last_acknowledged_fault == "command_not_applied"
    assert loaded.last_acknowledged_at == (now + 2 * MIN).isoformat()
    assert loaded.state == ctl.OBSERVING
    assert loaded.inspect_after == (now + 2 * MIN).isoformat()

    # Pre-acknowledge poll is rejected for inspection.
    stale_effects = loaded.step(
        obs(now + 3 * MIN, mode="Off", target_c=None, poll_at=now + MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert loaded.state == ctl.OBSERVING
    assert loaded.reason == "waiting_for_new_heater_status"
    assert not [e for e in stale_effects if e.kind == "publish"]

    # Fresh post-acknowledge poll settles cleanly and clears fault alerts.
    fresh_effects = loaded.step(
        obs(now + 4 * MIN, mode="Off", target_c=None, poll_at=now + 4 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert loaded.state == ctl.PARKED
    assert loaded.fault is None
    assert any(e.kind == "resolve" and e.key == "fault_command_not_applied" for e in fresh_effects)
    assert not any(e.kind == "notify" for e in fresh_effects)


def test_acknowledge_while_disabled_clears_fault_and_still_requires_fresh_poll_on_enable():
    now = datetime(2026, 11, 25, 23, 0, tzinfo=HOBART)
    c = _faulted_controller(now)
    c.set_enabled(False, now + MIN)
    # Persist across restart while disabled.
    reloaded = ctl.Controller.from_dict(c.to_dict())
    reloaded.restored(now + 2 * MIN)
    assert reloaded.state == ctl.DISABLED
    assert reloaded.fault == "command_not_applied"

    # Owner can acknowledge while disabled (e.g. after checking Thermann app).
    assert reloaded.acknowledge(now + 3 * MIN) is True
    assert reloaded.fault is None
    assert reloaded.last_acknowledged_fault == "command_not_applied"
    assert reloaded.last_acknowledged_at == (now + 3 * MIN).isoformat()
    assert reloaded.state == ctl.DISABLED
    # Idempotent: acknowledging again returns False.
    assert reloaded.acknowledge(now + 4 * MIN) is False

    # Re-enabling enters observing and requires a fresh status poll after enable.
    reloaded.set_enabled(True, now + 5 * MIN)
    assert reloaded.state == ctl.OBSERVING
    assert reloaded.inspect_after == (now + 5 * MIN).isoformat()
    reloaded.step(
        obs(now + 6 * MIN, mode="Manual", target_c=62, poll_at=now + 4 * MIN),
        ctl.Want(ctl.OFF, "peak_no_grid_heating"),
        cfg(),
    )
    assert reloaded.state == ctl.OBSERVING
    assert reloaded.reason == "waiting_for_new_heater_status"


def test_acknowledge_refused_while_confirming_and_when_healthy():
    now = datetime(2026, 11, 25, 23, 0, tzinfo=HOBART)
    c = ctl.Controller()
    assert c.acknowledge(now) is False
    c.set_enabled(True, now - 5 * MIN)
    c.step(obs(now - 4 * MIN, mode="Off", target_c=None), ctl.Want(ctl.OFF, "parked"), cfg())
    assert c.acknowledge(now - 3 * MIN) is False
    c.step(obs(now - 2 * MIN, mode="Off", target_c=None), ctl.Want(ctl.BASELINE, "baseline"), cfg())
    assert c.state == ctl.CONFIRMING
    assert c.acknowledge(now - MIN) is False


# ------------------------------------------------------------------ 2. Command audit metadata (sent_at & confirmed_at)
def test_confirmed_command_populates_sent_at_and_confirmed_at_in_history_and_report(
    tmp_path, monkeypatch
):
    start = hobart(MON, 9, 30)  # morning peak -> wants OFF from Manual 62
    rig = Rig(tmp_path, monkeypatch, start, reading=35, mode="Manual", setpoint=62)
    rig.enable()
    rig.run(start + timedelta(minutes=35))

    ctl_obj = rig.executor.controller
    assert ctl_obj.state == ctl.PARKED
    assert ctl_obj.fault is None
    assert ctl_obj.history, "expected confirmed OFF transition in history"
    last = ctl_obj.history[-1]
    assert last["status"] == "confirmed"
    assert last["created_at"] is not None
    assert last["sent_at"] is not None
    assert last["confirmed_at"] is not None
    assert last["resolved_at"] is not None
    assert last["created_at"] <= last["sent_at"] <= last["confirmed_at"] <= last["resolved_at"]

    diag = report.build(rig.runtime, rig.now(), "2026.11.1")
    cmd = diag["commands"]["last"]
    assert cmd["status"] == "confirmed"
    assert cmd["created_at"] == last["created_at"]
    assert cmd["sent_at"] == last["sent_at"]
    assert cmd["confirmed_at"] == last["confirmed_at"]
    assert cmd["resolved_at"] == last["resolved_at"]
    assert diag["controller"]["fault"] == "none"
    assert diag["controller"]["last_acknowledged_fault"] is None
    assert diag["controller"]["last_acknowledged_at"] is None


def test_unsent_fault_and_deferred_backoff_leave_sent_at_and_confirmed_at_null(
    tmp_path, monkeypatch
):
    now = datetime(2026, 11, 25, 22, 0, tzinfo=HOBART)
    # Case A: Never-sent command_not_applied -> sent_at and confirmed_at MUST stay None.
    c = _faulted_controller(now + timedelta(minutes=10))
    failed = c.history[-1]
    assert failed["status"] == "not_applied"
    assert failed["sent_at"] is None
    assert failed["confirmed_at"] is None

    # Case B: Transient cloud backoff refusal -> deferred without POST, sent_at/confirmed_at None,
    # then subsequent recovery command populates both sent_at and confirmed_at.
    start = hobart(MON, 21, 20)
    rig = Rig(tmp_path, monkeypatch, start, reading=25, mode="Off", setpoint=45)
    rig.enable()
    rig.run(hobart(MON, 21, 59))
    assert rig.executor.controller.state == ctl.PARKED

    # Trigger cloud_success_false right as 22:00 baseline is requested (after 21:55 poll succeeded).
    orig_cloud = rig.cloud
    fail_from = hobart(MON, 22, 0)
    fail_until = hobart(MON, 22, 3)

    def flaky_cloud(method, url, **kwargs):
        if fail_from <= rig.now() < fail_until and method == "GET":

            class _Resp:
                status_code = 200
                text = '{"success": false}'

                def json(self):
                    return {"success": False}

            return _Resp()
        return orig_cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = flaky_cloud
    # Ensure the 22:00 command publishes while cloud_health is still ok, hitting the
    # bridge's pre-command status refresh during cloud_success_false.
    rig.bridge.next_poll = hobart(MON, 22, 10).timestamp()
    rig.run(hobart(MON, 22, 2))
    # Bridge refused pre-command status refresh during outage -> deferred, no fault, no POST.
    deferred = [
        h for h in rig.executor.controller.history if h["status"] == "deferred_cloud_backoff"
    ]
    assert deferred, "expected deferred_cloud_backoff entry during cloud_success_false"
    assert deferred[-1]["sent_at"] is None
    assert deferred[-1]["confirmed_at"] is None
    assert rig.executor.controller.fault is None

    # After cloud recovers and backoff expires, baseline 45 confirms with full audit timestamps.
    rig.bridge.session.request.side_effect = orig_cloud
    rig.run(hobart(MON, 23, 35))
    assert rig.executor.controller.state == ctl.BASELINE_ACTIVE
    assert rig.executor.controller.fault is None
    confirmed = rig.executor.controller.history[-1]
    assert confirmed["status"] == "confirmed"
    assert confirmed["sent_at"] is not None
    assert confirmed["confirmed_at"] is not None


def test_fault_sensor_attributes_and_report_distinguish_active_vs_acknowledged_fault(
    tmp_path, monkeypatch
):
    start = hobart(MON, 9, 30)
    rig = Rig(tmp_path, monkeypatch, start, reading=25, mode="Off", setpoint=45)
    rig.enable()
    rig.run(start + timedelta(minutes=2))
    ctl_obj = rig.executor.controller
    ctl_obj.fault = "command_not_applied"
    ctl_obj.state = ctl.FAULT_LOCKED
    ctl_obj.reason = "command_not_applied"
    ctl_obj.heater = None

    sensor_stub = ModuleType("homeassistant.components.sensor")
    sensor_stub.SensorDeviceClass = type(
        "SensorDeviceClass", (), {"ENUM": "enum", "TIMESTAMP": "ts", "DURATION": "dur"}
    )
    sensor_stub.SensorEntity = type("SensorEntity", (), {})
    sensor_stub.SensorEntityDescription = lambda **kw: kw
    sensor_stub.SensorStateClass = type("SensorStateClass", (), {"MEASUREMENT": "measurement"})
    dev_stub = ModuleType("homeassistant.helpers.device_registry")
    dev_stub.DeviceInfo = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "homeassistant.components.sensor", sensor_stub)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", ModuleType("homeassistant.helpers"))
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.device_registry", dev_stub)
    monkeypatch.delitem(sys.modules, f"{m.__package__}.sensor", raising=False)
    sensor_mod = importlib.import_module(f"{m.__package__}.sensor")

    fault_sensor = sensor_mod.ControllerSensor(
        rig.runtime, rig.entry, "fault", "Controller fault", None
    )
    assert fault_sensor.native_value == "command_not_applied"
    assert fault_sensor.extra_state_attributes["last_acknowledged_fault"] is None

    # Acknowledge and observe fresh status.
    assert drive(rig.executor.async_owner_action("acknowledge")) is True
    assert fault_sensor.native_value == "none"
    assert fault_sensor.extra_state_attributes["last_acknowledged_fault"] == "command_not_applied"
    assert fault_sensor.extra_state_attributes["last_acknowledged_at"] is not None

    diag = report.build(rig.runtime, rig.now(), "2026.11.1")
    assert diag["versions"]["controller"] == "0.18.4"
    assert diag["controller"]["fault"] == "none"
    assert diag["controller"]["last_acknowledged_fault"] == "command_not_applied"
    assert (
        diag["controller"]["last_acknowledged_at"]
        == (fault_sensor.extra_state_attributes["last_acknowledged_at"])
    )


def test_end_to_end_live_0_18_2_persisted_fault_recovery_both_disabled_and_enabled(
    tmp_path, monkeypatch
):
    """Reproduces upgrading the live 0.18.2 installation (persisted command_not_applied)
    through real Store persistence, bridge polls, and owner acknowledgement."""
    # Path 1: Owner turns Automatic OFF before upgrade -> restarts on 0.18.3 ->
    # acknowledges while OFF -> turns Automatic ON -> waits for fresh poll -> acts safely.
    start = hobart(MON, 9, 30)  # morning peak
    rig = Rig(tmp_path, monkeypatch, start, reading=35, mode="Manual", setpoint=62)
    persisted = rig.executor.controller.to_dict()
    persisted.update(
        enabled=False,
        state=ctl.DISABLED,
        reason="automatic_control_disabled",
        fault="command_not_applied",
        heater=None,
    )
    rig.store[rig.executor.store.key] = persisted
    rig.executor = rig._executor()  # real Store load + Controller.from_dict + restored
    assert rig.executor.controller.state == ctl.DISABLED
    assert rig.executor.controller.fault == "command_not_applied"
    assert not rig.commands()

    # Acknowledge while Automatic control is OFF.
    assert drive(rig.executor.async_owner_action("acknowledge")) is True
    assert rig.executor.controller.state == ctl.DISABLED
    assert rig.executor.controller.fault is None
    assert rig.executor.controller.last_acknowledged_fault == "command_not_applied"
    assert rig.executor.controller.last_acknowledged_at is not None
    assert not rig.commands()

    # Enable Automatic control -> observing until a fresh status poll arrives after enable.
    rig.enable()
    assert rig.executor.controller.state == ctl.OBSERVING
    t1 = start + timedelta(minutes=1)
    rig.t = t1.timestamp()
    rig.runtime.update(t1)
    drive(rig.executor.async_step(t1))
    assert rig.executor.controller.state == ctl.OBSERVING
    assert rig.executor.controller.reason == "waiting_for_new_heater_status"
    assert not rig.commands()

    # Advance through a genuine bridge status poll -> classifies Manual 62 -> sends OFF -> confirms.
    rig.run(start + timedelta(minutes=35))
    assert rig.executor.controller.state == ctl.PARKED
    assert rig.executor.controller.fault is None
    assert rig.commands() == ["off@62"]
    last = rig.executor.controller.history[-1]
    assert last["status"] == "confirmed"
    assert last["sent_at"] is not None and last["confirmed_at"] is not None

    # Path 2: Upgraded with Automatic ON and orphaned state="parked" + fault="command_not_applied"
    # -> heals immediately into fault_locked and refuses all commands until acknowledged.
    orphaned = rig.executor.controller.to_dict()
    orphaned.update(
        enabled=True,
        state=ctl.PARKED,
        reason="off_confirmed",
        fault="command_not_applied",
        heater=ctl.OFF,
    )
    rig.store[rig.executor.store.key] = orphaned
    rig.executor = rig._executor()
    assert rig.executor.controller.state == ctl.FAULT_LOCKED
    assert rig.executor.controller.fault == "command_not_applied"
    assert rig.executor.controller.heater is None
    before_cmds = list(rig.commands())
    rig.run(start + timedelta(minutes=70))
    assert rig.commands() == before_cmds  # zero commands while fault_locked
    assert rig.executor.controller.state == ctl.FAULT_LOCKED
    assert drive(rig.executor.async_owner_action("acknowledge")) is True
    assert rig.executor.controller.state == ctl.OBSERVING
    assert rig.executor.controller.fault is None
    rig.run(start + timedelta(minutes=105))
    assert rig.executor.controller.state == ctl.PARKED
    assert rig.executor.controller.fault is None


# ------------------------------------------------------------------ 3. Solar qualification & fault interaction
def test_peak_4_25kw_export_waits_10_continuous_minutes_then_qualifies_preserving_thresholds(
    tmp_path, monkeypatch
):
    # Thursday 26 Nov 2026 morning peak (08:00-11:00 AEDT = 07:00-10:00 AEST fixed tariff).
    # Heater starts OFF at 09:35 AEDT after an upgrade/OFF transition; CT-free commissioned,
    # peak solar-only heating allowed, consistent site power with 4.25 kW export.
    boot_at = datetime(2026, 11, 26, 9, 4, tzinfo=HOBART).astimezone(m.UTC)
    rig = Rig(
        tmp_path,
        monkeypatch,
        boot_at,
        reading=30,
        mode="Off",
        setpoint=62,
        pv=lambda _loc: 0.5,
    )
    rig.sources["heater_power"] = ""
    rig.entry.options.update(
        {
            "peak_heating_policy": "Verified solar-only heating",
            "optional_solar_boost": True,
            "normal_storage_c": "62",
            "solar_boost_c": "70",
            "import_positive": True,
            "ct_free_solar_verification": f"{rig.sources['grid']}|W|import_positive|3",
            "heater_meter_verification": "",
        }
    )
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.runtime.boot = boot_at - timedelta(minutes=5)
    rig.executor.configure(rig.entry.options)
    rig.enable()
    start = datetime(2026, 11, 26, 9, 35, tzinfo=HOBART).astimezone(m.UTC)
    rig.run(start)
    assert rig.executor.controller.state == ctl.PARKED
    # Simulate clean post-restart/post-OFF sample window starting at 09:35 AEDT.
    rig.executor.policy.samples.clear()

    # Feed genuine consistent site readings: PV 5.0 kW, House 0.75 kW, Grid -4.25 kW (export).
    for minute in range(9):
        t = start + timedelta(minutes=minute)
        rig.t = t.timestamp()
        rig.report(rig.sources["pv_ac"], 5000, {"unit_of_measurement": "W"})
        rig.report(rig.sources["house"], 750, {"unit_of_measurement": "W"})
        rig.report(rig.sources["grid"], -4250, {"unit_of_measurement": "W"})
        rig.runtime.update(t)
        drive(rig.executor.async_step(t))

    # At 8 minutes of continuous 4.25 kW export: still < 10 min -> sustained_full_solar_required.
    assert rig.executor.last_decision.state == ctl.OFF
    assert rig.executor.last_decision.reason == "peak_no_grid_heating"
    assert rig.executor.last_decision.plan["boost_reason"] == "sustained_full_solar_required"
    assert rig.executor.last_decision.plan["boost_eligible"] is False

    # Feed minute 9 and 10 -> reaches 10 continuous measured minutes >= 3.3 kW -> qualifies!
    for minute in range(9, 11):
        t = start + timedelta(minutes=minute)
        rig.t = t.timestamp()
        rig.report(rig.sources["pv_ac"], 5000, {"unit_of_measurement": "W"})
        rig.report(rig.sources["house"], 750, {"unit_of_measurement": "W"})
        rig.report(rig.sources["grid"], -4250, {"unit_of_measurement": "W"})
        rig.runtime.update(t)
        drive(rig.executor.async_step(t))

    assert rig.executor.policy.surplus_qualified(start + timedelta(minutes=10)) is True
    assert rig.executor.last_decision.plan["boost_eligible"] is True
    assert rig.executor.last_decision.plan["boost_reason"] == "useful_solar_value_exceeds_margin"
    assert rig.commands() == ["Manual:70@off"]


def test_clearing_acknowledged_fault_unblocks_solar_input_loss_pending(tmp_path, monkeypatch):
    start = datetime(2026, 11, 26, 9, 35, tzinfo=HOBART).astimezone(m.UTC)
    rig = Rig(tmp_path, monkeypatch, start, reading=30, mode="Off", setpoint=62)
    rig.enable()
    rig.run(start + timedelta(minutes=2))

    # Simulate latched solar_input_loss_pending alongside an active fault.
    ctl_obj = rig.executor.controller
    ctl_obj.fault = "command_not_applied"
    ctl_obj.state = ctl.FAULT_LOCKED
    ctl_obj.reason = "command_not_applied"
    ctl_obj.heater = None
    rig.runtime.solar_input_loss_pending = True

    t3 = start + timedelta(minutes=3)
    rig.t = t3.timestamp()
    rig.runtime.update(t3)
    drive(rig.executor.async_step(t3))
    # While fault is active, solar_input_loss_pending remains latched.
    assert rig.runtime.solar_input_loss_pending is True

    # After owner acknowledges, the next saved step clears solar_input_loss_pending.
    assert drive(rig.executor.async_owner_action("acknowledge")) is True
    t4 = start + timedelta(minutes=4)
    rig.t = t4.timestamp()
    rig.runtime.update(t4)
    drive(rig.executor.async_step(t4))
    assert rig.executor.controller.fault is None
    assert rig.runtime.solar_input_loss_pending is False
