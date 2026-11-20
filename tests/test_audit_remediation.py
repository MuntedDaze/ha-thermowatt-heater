"""PR36 independent findings: synthetic HTTP, persisted state and real clocks."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json

import pytest
import requests

from conftest import TOKENS, response, bridge_module
from test_cloud_and_commands import ready
from test_controller_0_9_0 import cfg, ctl, notices, obs, publishes, local
from test_simple_policy import sp, snap, at, MON, fc, TARIFFS
from test_shadow_model import c, m


def status(cmd=9, target=62, temperature=61):
    return {
        "result": {
            "T_Avg": str(temperature),
            "T_SetPoint": str(target),
            "Cmd": str(cmd),
            "WaterHeaterSts": "32",
        }
    }


def command_ready(factory, clock):
    b = factory(commands_enabled=True, legacy_confirmation=False, proactive_refresh=True)
    ready(b)
    b.token_obtained_at = clock() - 1150
    b.session.request.side_effect = [response(body=status())]
    b.tick()
    clock.advance(55)
    b.next_cloud = 0
    b.session.request.reset_mock(side_effect=True)
    return b


@pytest.mark.parametrize(
    "failure", [requests.Timeout(), requests.ConnectionError(), response(401), response(429)]
)
def test_pre_post_refresh_failure_is_a_refusal_not_an_uncertain_heater_post(
    factory, clock, failure
):
    b = command_ready(factory, clock)
    b.session.request.side_effect = [failure]
    b.commands.put((clock(), "TEST123", "MODE", "off@62"))
    b.tick()
    calls = b.session.request.call_args_list
    assert len(calls) == 1 and calls[0].args[1].endswith("/refresh")
    assert b.pending is None
    assert b.last_command["result"] == "refused_authentication_before_command"
    assert b.guard.state["mode"] in {"retry", "blocked"}
    restarted = factory(commands_enabled=True, legacy_confirmation=False, proactive_refresh=True)
    assert restarted.pending is None
    restarted.tick()
    restarted.session.request.assert_not_called()


def test_actual_post_timeout_remains_uncertain_and_is_never_repeated(factory, clock):
    b = command_ready(factory, clock)
    b.session.request.side_effect = [response(body=TOKENS), requests.Timeout()]
    b.commands.put((clock(), "TEST123", "MODE", "off@62"))
    b.tick()
    assert [call.args[1].rsplit("/", 1)[-1] for call in b.session.request.call_args_list] == [
        "refresh",
        "off",
    ]
    assert b.pending and b.last_command["result"] == "awaiting_confirmation"
    b.process_command((clock(), "TEST123", "MODE", "off@62"))
    assert len(b.session.request.call_args_list) == 2
    restarted = factory(commands_enabled=True, legacy_confirmation=False)
    assert restarted.pending
    restarted.session.request.assert_not_called()


def test_successful_but_slow_pre_post_authentication_does_not_authorise_old_prior(factory, clock):
    b = command_ready(factory, clock)

    def refresh(*args, **kwargs):
        clock.advance(70)
        return response(body=TOKENS)

    b.session.request.side_effect = refresh
    b.process_command((clock(), "TEST123", "MODE", "off@62"))
    assert (
        b.pending is None
        and b.last_command["result"] == "refused_status_expired_during_authentication"
    )
    assert b.session.request.call_count == 1


def test_empty_devices_use_fixed_rediscovery_and_recover_without_auth_lock(factory, clock):
    b = factory(
        adaptive_polling_enabled=True,
        adaptive_polling_qualified=True,
        event_aware_polling_qualified=True,
    )
    ready(b)
    b.session.request.side_effect = [response(body=status())]
    b.tick()
    b.mqtt_reconnected.set()
    clock.advance(b.poll_interval)
    b.session.request.reset_mock(side_effect=True)
    b.session.request.side_effect = [response(body={"result": {"termostati": []}})]
    b.tick()
    assert not b.active_devices and not b.discovered
    assert b.cloud_health == "no_devices" and b.last_error == "device_list_empty"
    assert b.guard.state["mode"] == "authorized" and b.failures == 0
    for _ in range(10):
        clock.advance(20)
        b.tick()
    assert b.session.request.call_count == 1
    clock.advance(b.poll_interval)
    b.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": "TEST123", "nome": "Synthetic"}]}}),
        response(body=status()),
    ]
    b.tick()
    assert b.active_devices == {"TEST123"} and b.discovered and b.cloud_health == "ok"


def test_first_adaptive_sync_failure_is_contained_without_authentication_lock(factory, monkeypatch):
    b = factory()
    ready(b)
    monkeypatch.setattr(b, "_adaptive_sync", lambda: (_ for _ in ()).throw(ValueError("synthetic")))
    b.tick()
    assert b.last_error == "internal_value_error" and b.guard.state["mode"] == "authorized"
    b.session.request.assert_not_called()


def test_empty_active_set_with_old_deadlines_cannot_raise_in_adaptive_sync(factory):
    b = factory(cloud_polling="smart")
    ready(b)
    b.cloud_health = "ok"
    b.next_background["TEST123"] = 1
    b.active_devices.clear()
    b._adaptive_sync()
    assert b.next_poll == b.clock() + b.poll_interval


def test_real_off_outage_backoff_restart_and_restore_never_bypass_peak(factory, clock):
    start = clock()
    b = factory(commands_enabled=True, legacy_confirmation=False)
    ready(b)
    model = {"cmd": 8}
    attempts, posts, notifications = [], [], []

    def http(method, url, **kwargs):
        elapsed = clock() - start
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "user-info":
            return response(body={"result": {"termostati": [{"seriale": "TEST123"}]}})
        if endpoint == "refresh":
            return response(body=TOKENS)
        if endpoint == "status":
            attempts.append(elapsed)
            if 0 < elapsed < 10 * 3600:
                raise requests.Timeout()
            return response(body=status(model["cmd"]))
        assert endpoint == "manual" and method == "POST"
        posts.append(elapsed)
        model["cmd"] = 9
        return response(204)

    b.session.request.side_effect = http
    b.tick()
    controller = ctl.Controller(enabled=True, state=ctl.PARKED, heater=ctl.OFF)
    configuration = cfg(four_state_qualified=True)
    for elapsed in range(0, 18 * 3600, 20):
        clock.now = start + elapsed
        if elapsed == 4 * 3600:
            b = factory(commands_enabled=True, legacy_confirmation=False)
            b.session.request.side_effect = http
            controller = ctl.Controller.from_dict(controller.to_dict())
            controller.restored(datetime.fromtimestamp(clock(), timezone.utc))
        b.tick()
        if elapsed % 60:
            continue
        stamp = datetime.fromtimestamp(clock(), timezone.utc)
        prior = b.confirmed.get("TEST123")
        observation = obs(
            stamp,
            mode=("Manual" if prior[1]["Cmd"] == 9 else "Off") if prior else None,
            target=62,
            poll_at=datetime.fromtimestamp(b.last_success["TEST123"], timezone.utc)
            if "TEST123" in b.last_success
            else None,
            cloud_health=b.cloud_health,
            auth_mode=b.guard.state["mode"],
            bridge_available=bool(prior),
            bridge_transitions=list(bridge_module.TRANSITIONS),
            consecutive_failures=b.failures,
            bridge_confirmation_pending=b.pending is not None,
            last_command=b.last_command,
        )
        # Synthetic peak windows relative to initial morning OFF: morning to
        # +3 h, evening +9..14 h. No heat may be requested during either peak.
        peak = elapsed < 3 * 3600 or 9 * 3600 <= elapsed < 14 * 3600
        effects = controller.step(
            observation,
            ctl.Want(ctl.OFF if peak else ctl.NORMAL, "peak_lockout" if peak else "required_heat"),
            configuration,
        )
        notifications.extend((elapsed, e.key) for e in effects if e.kind == "notify")
        for effect in effects:
            if effect.kind == "publish":
                b.commands.put((clock(), "TEST123", "MODE", effect.payload))
    assert [x for x in attempts if 0 < x < 10 * 3600] == [1800, 5400, 12600, 27000]
    assert any(t == 3.5 * 3600 and key == "parked_off_cannot_restore" for t, key in notifications)
    assert posts and min(posts) >= 15.5 * 3600  # actual persisted ladder, no early retry
    assert len(posts) == 1 and controller.heater == ctl.NORMAL
    assert "parked_off_cannot_restore" not in controller.active_alerts


@pytest.mark.parametrize("quiet_minutes", [60, 90])
def test_first_refresh_rejection_while_off_produces_restore_warning_without_more_http(
    factory, clock, quiet_minutes
):
    b = factory(commands_enabled=True, legacy_confirmation=False, proactive_refresh=True)
    ready(b)
    b.session.request.side_effect = [response(body=status(cmd=8))]
    b.tick()
    controller = ctl.Controller(enabled=True, state=ctl.PARKED, heater=ctl.OFF)
    stamp = datetime.fromtimestamp(clock(), timezone.utc)
    controller.step(obs(stamp), ctl.Want(ctl.OFF, "peak_lockout"), cfg())
    clock.advance(quiet_minutes * 60)
    b.session.request.reset_mock(side_effect=True)
    b.session.request.side_effect = [response(401)]
    b.tick()
    assert b.guard.state["mode"] == "blocked" and b.pending is None
    stamp = datetime.fromtimestamp(clock(), timezone.utc)
    wanted = ctl.Want(ctl.NORMAL, "required_heat")
    failed = obs(stamp, mode=None, cloud_health=b.cloud_health, bridge_available=False)
    controller.step(failed, wanted, cfg())
    for _ in range(31):
        clock.advance(60)
        b.tick()
        failed.now = datetime.fromtimestamp(clock(), timezone.utc)
        effects = controller.step(failed, wanted, cfg())
        assert not publishes(effects)
    assert b.session.request.call_count == 1
    assert "parked_off_cannot_restore" in controller.active_alerts


@pytest.mark.parametrize("fault", ["backoff", "auth_blocked", "unavailable"])
def test_parked_off_restore_alert_persists_restart_and_resolves_only_on_observed_heat(fault):
    now = local(hour=11)
    controller = ctl.Controller(enabled=True, state=ctl.PARKED, heater=ctl.OFF)
    controller.step(obs(now), ctl.Want(ctl.OFF, "peak_lockout"), cfg())
    wanted = ctl.Want(ctl.NORMAL, "storage_latest_start")
    failed = obs(now, mode=None, cloud_health=fault, bridge_available=False)
    assert "parked_off_cannot_restore" not in notices(controller.step(failed, wanted, cfg()))
    saved = ctl.Controller.from_dict(controller.to_dict())
    saved.restored(now + timedelta(minutes=15))
    later = replace(failed, now=now + timedelta(minutes=30))
    effects = saved.step(later, wanted, cfg())
    assert "parked_off_cannot_restore" in notices(effects) and not publishes(effects)
    assert "last observed" in next(
        e.message for e in effects if e.key == "parked_off_cannot_restore"
    )
    # Seeing an old OFF report at recovery does not clear the warning.
    assert saved.parked_off_restore_since
    recovered = obs(now + timedelta(minutes=31), "Manual", 62, poll_age=0)
    effects = saved.step(recovered, wanted, cfg())
    assert saved.parked_off_restore_since is None
    assert "parked_off_cannot_restore" not in saved.active_alerts
    assert not publishes(effects)


def test_intentional_peak_off_and_owner_hold_do_not_raise_restore_alarm():
    now = local()
    controller = ctl.Controller(enabled=True, state=ctl.PARKED, heater=ctl.OFF)
    for i in range(120):
        effects = controller.step(
            obs(now + timedelta(minutes=i)), ctl.Want(ctl.OFF, "peak_lockout"), cfg()
        )
        assert "parked_off_cannot_restore" not in notices(effects)
    controller.set_hold(now)
    effects = controller.step(obs(now + timedelta(hours=3)), ctl.Want(ctl.NORMAL, "storage"), cfg())
    assert "parked_off_cannot_restore" not in notices(effects) and not publishes(effects)


def test_no_ct_never_pauses_running_required_heat_based_on_self_contaminated_grid_export():
    now = at(MON, 12)
    policy = sp.SimplePolicy(
        replace(sp.PolicySettings(), boost_enabled=False, pause_min_saving=0.10), TARIFFS
    )
    for i in range(90):
        stamp = now + timedelta(minutes=i)
        decision = policy.decide(
            snap(
                stamp,
                sp.NORMAL,
                reading=45,
                heater_meter_valid=False,
                required_export_kw=0,
                forecast=fc(stamp, 8, 4),
            )
        )
        assert decision.state == sp.NORMAL and decision.command is None
        assert decision.reason == "storage_until_peak"


def test_owner_temperature_strategy_is_preserved_without_a_new_restrictive_gate():
    assert c.DEFAULT_OPTIONS["baseline_c"] == "45"
    assert c.DEFAULT_OPTIONS["normal_storage_c"] == "62"
    assert c.DEFAULT_OPTIONS["solar_boost_c"] == "70"
    assert "low_temperature_baseline_qualified" not in c.DEFAULT_OPTIONS
    policy = sp.SimplePolicy(replace(sp.PolicySettings(), boost_enabled=False), TARIFFS)
    for stamp in (at(MON, 23), at(15, 12)):
        decision = policy.decide(snap(stamp, sp.OFF, heater_meter_valid=False))
        assert decision.command == "Manual:45"
    decision = policy.decide(snap(at(MON, 16), sp.OFF, reading=40, heater_meter_valid=False))
    assert decision.command == "Manual:62"
    assert not cfg().missing_commissioning()


def test_watchdog_heartbeat_advances_only_after_completed_evaluation(tmp_path, monkeypatch):
    from test_integration_0_9_0 import Rig, drive

    rig = Rig(tmp_path, monkeypatch, at(MON, 12))
    assert rig.executor.values()["controller_evaluated_at"] is None
    drive(rig.executor.async_step(rig.now()))
    completed = rig.executor.values()["controller_evaluated_at"]
    assert completed == rig.now()
    rig.t += 60
    rig.runtime.update(rig.now())

    def failed(*args, **kwargs):
        raise RuntimeError("synthetic evaluation failure")

    monkeypatch.setattr(rig.executor.controller, "step", failed)
    with pytest.raises(RuntimeError, match="synthetic evaluation failure"):
        drive(rig.executor.async_step(rig.now()))
    assert rig.executor.values()["controller_evaluated_at"] == completed
    assert rig.commands() == []


@pytest.mark.parametrize(
    "day",
    [datetime(2026, 4, 4, 15, tzinfo=timezone.utc), datetime(2026, 10, 3, 15, tzinfo=timezone.utc)],
)
def test_both_dst_change_days_keep_fixed_standard_tariff_and_event_deadline_in_utc(day):
    rows = [
        {"days": list(range(7)), "start": a, "end": b, "kind": k}
        for a, b, k in [
            ("00:00", "02:00", "off_peak"),
            ("02:00", "04:00", "peak"),
            ("04:00", "00:00", "off_peak"),
        ]
    ]
    _, tariffs = c.parse_options(
        {"tariff_profile": "custom", "tariff_periods": json.dumps(rows), "tariff_clock": "standard"}
    )
    policy = sp.SimplePolicy(
        replace(
            sp.PolicySettings(),
            tariff_clock="standard",
            boost_enabled=False,
            peak_policy=sp.PEAK_NEVER,
        ),
        tariffs,
    )
    boundary = day.replace(hour=16)
    assert policy.next_peak(day) == boundary
    smart = importlib.import_module(f"{m.__package__}.adaptive").smart_plan
    plan = smart(day, day, stable_state="off", decision_at=boundary - timedelta(minutes=2))
    assert plan["delay_seconds"] == 58 * 60
    for i in range(181):
        stamp = day + timedelta(minutes=i)
        assert (m.tariff_at(stamp, tariffs, "standard").kind == "peak") == (
            boundary <= stamp < boundary + timedelta(hours=2)
        )
