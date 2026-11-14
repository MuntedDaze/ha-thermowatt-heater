"""Offline reproductions from Astra's 1b29be1 audit."""

from datetime import timedelta

from test_audit_regressions_0_9_1 import config, controller_ready, observation, published
from test_simple_policy import BASE, MIN, MON, OFF, S, SAT, STORE, TARIFFS, at, fc, snap, sp


def test_weekend_forecast_cannot_sustain_imported_optional_heat():
    p = sp.SimplePolicy(S, TARIFFS)
    start = at(SAT, 13)
    for minute in range(7):
        now = start + minute * MIN
        p.add_meter(now, 3.0, True)
    d = p.decide(snap(now, STORE, forecast=fc(now, 4, 4.0)))
    assert (d.state, d.reason, d.command) == (BASE, "solar_opportunity_import", "Manual:45")


def test_weekend_short_cloud_does_not_toggle_the_mode():
    p = sp.SimplePolicy(S, TARIFFS)
    start = at(SAT, 13)
    for minute in range(14):
        now = start + minute * MIN
        p.add_meter(now, -0.5 if minute < 11 else 3.0, True)
    assert p.decide(snap(now, STORE, forecast=fc(now, 4, 4.0))).state == STORE


def test_meter_outage_off_crosses_policy_and_executor_spacing_once():
    now = at(MON, 9)
    p = sp.SimplePolicy(S, TARIFFS)
    d = p.decide(snap(now, STORE, last_command_at=now - 3 * MIN))
    assert (d.reason, d.command) == ("peak_meter_unavailable", "off")
    controller = controller_ready(now, "Manual", 70.0)
    controller.commands = [(now - 3 * MIN).isoformat()]
    from test_audit_regressions_0_9_1 import ctl

    obs = observation(now, "Manual", 70.0)
    assert published(controller.step(obs, ctl.Want(d.state, d.reason), config())) == ["off@70"]
    assert not published(controller.step(obs, ctl.Want(d.state, d.reason), config()))


def test_priority_off_still_respects_auth_and_confirmation_guards():
    now = at(MON, 9)
    for changes in ({"cloud_health": "auth_locked"}, {"bridge_confirmation_pending": True}):
        controller = controller_ready(now, "Manual", 70.0)
        from test_audit_regressions_0_9_1 import ctl

        assert not published(
            controller.step(
                observation(now, "Manual", 70.0, **changes),
                ctl.Want(OFF, "peak_meter_unavailable"),
                config(),
            )
        )


def test_future_status_cannot_publish_or_poison_poll_watermark():
    from test_audit_regressions_0_9_1 import ctl

    now = at(MON, 12)
    controller = ctl.Controller()
    controller.set_enabled(True, now - MIN)
    want = ctl.Want(STORE, "storage_latest_start")
    effects = controller.step(observation(now, poll_at=now + timedelta(hours=1)), want, config())
    assert not published(effects)
    assert controller.last_poll_seen is None
    assert published(controller.step(observation(now, poll_at=now), want, config()))
