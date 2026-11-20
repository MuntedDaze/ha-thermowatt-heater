"""Bridge 1.4.1 / controller 0.16.1: Smart plans survive Home Assistant's
whole-second timestamp state, and recovery stays guarded.

Production (0.16.0 / 1.4.0) showed 0 accepted and 38 rejected plans. Home
Assistant renders a timestamp sensor with ``isoformat(timespec="seconds")``, so
the controller echoed floor(read time) while the bridge compared it with its
sub-second ``time.time()`` read time within 0.01 s. Earlier tests used an
integer clock and echoed the bridge's own float, which hid the mismatch.
"""

from datetime import datetime, timezone
import importlib
import json
import math
from types import SimpleNamespace

import pytest

from conftest import STATUS, response
from test_cloud_and_commands import ready
from test_demand_refresh import publish
from test_existing_installation_upgrade import ct_free
from test_integration_0_9_0 import MON, Rig, hobart
from test_next_major_integration import smart
from test_shadow_model import m
from thermowatt_polling import AdaptiveSchedule, REJECTION_CODES

adaptive = importlib.import_module(f"{m.__package__}.adaptive")
report = importlib.import_module(f"{m.__package__}.report")
SERIAL = "TEST123"
FRACTION = 0.437219


def ha_state(epoch):
    """Exactly what HA stores for a device_class: timestamp MQTT sensor."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def ha_status_at(epoch):
    return datetime.fromisoformat(ha_state(epoch))


def schedule_at(wall, mode="smart"):
    clock = {"wall": wall, "mono": 10_000.0}
    s = AdaptiveSchedule(True, lambda: clock["wall"], lambda: clock["mono"], smart_mode=mode)

    def advance(seconds):
        clock["wall"] += seconds
        clock["mono"] += seconds

    return s, clock, advance


def plan_for(status_at, now, **kwargs):
    kwargs.setdefault("temperature_valid", True)
    return json.dumps(adaptive.smart_plan(now, status_at, **kwargs))


# --- the validator ------------------------------------------------------------------------


def test_whole_second_echo_of_the_current_read_is_accepted_and_never_later():
    wall = hobart(MON, 23, 3).timestamp() + FRACTION
    s, clock, advance = schedule_at(wall)
    s.observed(SERIAL, wall, 1800)
    advance(20)
    now = datetime.fromtimestamp(clock["wall"], timezone.utc)
    plan = plan_for(ha_status_at(wall), now, stable_state="baseline", overnight=True)
    assert s.accept(SERIAL, plan)
    # Deadline measured from the controller's status_at (floor of the read):
    # FRACTION earlier than from the bridge's read, never later.
    read_mono = clock["mono"] - 20
    assert s.deadline(SERIAL) == pytest.approx(read_mono - FRACTION + 28800)
    assert s.deadline(SERIAL) < read_mono + 28800
    summary = s.summary(SERIAL)
    assert summary["active"] and summary["reason"] == "stable_baseline"
    assert summary["rejection_reasons"] == {} and summary["last_rejection"] is None
    assert summary["last_acceptance"]["reason"] == "stable_baseline"


def test_released_comparison_rejected_the_same_plan():
    """Documents the production failure: 0.01 s cannot match a whole second."""
    wall = hobart(MON, 23, 3).timestamp() + FRACTION
    echoed = ha_status_at(wall).timestamp()
    assert abs(echoed - wall) > 0.01  # the 1.4.0 test that rejected every plan
    assert echoed == math.floor(wall)


@pytest.mark.parametrize(
    "status_at",
    [
        lambda wall: math.floor(wall) - 1,  # the previous second
        lambda wall: math.floor(wall) + 1,  # a later second
        lambda wall: math.floor(wall) + 0.5,  # sub-second but not this read
        lambda wall: wall - 0.02,  # just outside the exact tolerance
        lambda wall: wall - 1800,  # a previous observation
    ],
)
def test_other_observations_are_still_rejected_as_identity_mismatch(status_at):
    wall = hobart(MON, 23, 3).timestamp() + FRACTION
    s, clock, advance = schedule_at(wall)
    s.observed(SERIAL, wall, 1800)
    advance(5)
    plan = json.loads(
        plan_for(ha_status_at(wall), datetime.fromtimestamp(clock["wall"], timezone.utc))
    )
    plan["status_at"] = status_at(wall)
    assert not s.accept(SERIAL, json.dumps(plan))
    assert s.summary(SERIAL)["rejection_reasons"] == {"status_identity_mismatch": 1}
    assert s.deadline(SERIAL) == clock["mono"] - 5 + 1800  # fixed fallback


def test_exact_echo_still_matches_and_two_reads_in_one_second_need_it():
    wall = hobart(MON, 23, 3).timestamp() + 0.1
    s, clock, advance = schedule_at(wall)
    s.observed(SERIAL, wall, 1800)
    advance(0.5)
    s.observed(SERIAL, wall + 0.5, 1800)  # e.g. a confirmation read in the same second
    advance(1)
    now = datetime.fromtimestamp(clock["wall"], timezone.utc)
    truncated = plan_for(ha_status_at(wall), now, stable_state="baseline")
    assert not s.accept(SERIAL, truncated)  # ambiguous: could be the older read
    exact = plan_for(datetime.fromtimestamp(wall + 0.5, timezone.utc), now, stable_state="baseline")
    assert s.accept(SERIAL, exact)
    assert s.counts["accepted"] == 1 and s.rejections == {"status_identity_mismatch": 1}


def test_previous_observation_plan_is_rejected_after_a_new_read():
    first = hobart(MON, 23, 0).timestamp() + FRACTION
    s, clock, advance = schedule_at(first)
    s.observed(SERIAL, first, 1800)
    advance(1800)
    s.observed(SERIAL, clock["wall"], 1800)
    advance(10)
    now = datetime.fromtimestamp(clock["wall"], timezone.utc)
    assert not s.accept(SERIAL, plan_for(ha_status_at(first), now, stable_state="baseline"))
    assert s.rejections == {"status_identity_mismatch": 1}


def test_rejection_categories_are_closed_and_journal_format_is_unchanged(tmp_path):
    wall = hobart(MON, 23, 3).timestamp() + FRACTION
    writes = []
    clock = {"wall": wall}
    s = AdaptiveSchedule(
        True,
        lambda: clock["wall"],
        lambda: clock["wall"],
        tmp_path / "poll_state.json",
        lambda path, data: writes.append(data),
        smart_mode="smart",
    )
    now = datetime.fromtimestamp(wall, timezone.utc)
    good = plan_for(ha_status_at(wall), now, stable_state="baseline")
    assert not s.accept(SERIAL, good)  # no read yet (e.g. just after restart)
    s.observed(SERIAL, wall, 1800)
    assert not s.accept(SERIAL, b"\xff")
    assert not s.accept(SERIAL, b"[]")
    stale = json.loads(good)
    stale["issued_at"] -= 31
    assert not s.accept(SERIAL, json.dumps(stale))
    assert not s.accept(SERIAL, json.dumps({**json.loads(good), "version": 9}))
    assert not s.accept(SERIAL, json.dumps({**json.loads(good), "polling_mode": "minimum"}))
    assert not s.accept(SERIAL, json.dumps({**json.loads(good), "extra": 1}))
    assert not s.accept(SERIAL, json.dumps({**json.loads(good), "owner_check_seconds": 99999}))
    assert not s.accept(SERIAL, json.dumps({**json.loads(good), "delay_seconds": 10}))
    assert s.accept(SERIAL, good)
    assert not s.accept(SERIAL, good)  # same issued_at: not newer
    assert set(s.rejections) <= set(REJECTION_CODES)
    assert s.rejections == {
        "no_current_observation": 1,
        "invalid_payload": 2,
        "plan_stale_or_future": 1,
        "version_unsupported": 1,
        "mode_mismatch": 1,
        "fields_invalid": 1,
        "owner_check_invalid": 1,
        "delay_or_reason_invalid": 1,
        "plan_not_newer": 1,
    }
    assert s.counts["rejected"] == sum(s.rejections.values())
    s.save()
    assert writes[-1] == {"version": 1, "counts": s.counts}  # 1.4.0 can still read it


def test_a_1_4_0_journal_with_38_rejections_loads_and_keeps_counting(tmp_path):
    path = tmp_path / "poll_state.json"
    old = {"accepted": 0, "rejected": 38, "ordinary_reads": 12, "reused_reads": 3}
    path.write_text(json.dumps({"version": 1, "counts": old}), encoding="utf-8")
    s = AdaptiveSchedule(True, lambda: 0.0, lambda: 0.0, path, smart_mode="smart")
    assert s.active and s.counts == old and s.rejections == {}


# --- the bridge worker ----------------------------------------------------------------------


def smart_bridge(factory, clock, **options):
    clock.now += FRACTION  # production clocks are never whole seconds
    b = factory(polling_mode="smart", **options)
    ready(b)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    return b


def send_plan(b, clock, **kwargs):
    kwargs.setdefault("stable_state", "baseline")
    kwargs.setdefault("overnight", True)
    now = datetime.fromtimestamp(clock(), timezone.utc)
    payload = plan_for(ha_status_at(b.last_success[SERIAL]), now, **kwargs)
    b.on_mqtt_message(
        None,
        None,
        SimpleNamespace(topic=f"P/{SERIAL}/poll_plan", payload=payload.encode(), retain=False),
    )


def diagnostics(b):
    sent = [
        json.loads(call.args[1])
        for call in b.mqtt_client.publish.call_args_list
        if call.args[0] == f"P/{SERIAL}/DIAGNOSTICS"
    ]
    return sent[-1]


def test_worker_leaves_fixed_fallback_once_a_fresh_read_is_echoed(factory, clock):
    b = smart_bridge(factory, clock)
    assert diagnostics(b)["polling_mode"] == "fixed_fallback"
    assert diagnostics(b)["adaptive_plan_versions"] == [1, 3]
    read_at = b.last_success[SERIAL]
    for _ in range(5):  # the controller republishes every minute
        clock.advance(60)
        send_plan(b, clock)
        b.tick()
    b.publish_diagnostics(force=True)
    diag = diagnostics(b)
    assert diag["polling_mode"] == "adaptive" and diag["polling_reason"] == "stable_baseline"
    assert diag["adaptive_polling"]["counts"]["accepted"] == 5
    assert diag["adaptive_polling"]["counts"]["rejected"] == 0
    assert b.next_poll == pytest.approx(math.floor(read_at) + 28800)
    assert b.session.request.call_count == 1  # plans never request HTTP


def test_mqtt_reconnect_cannot_keep_a_discarded_eight_hour_deadline(factory, clock):
    b = smart_bridge(factory, clock)
    clock.advance(30)
    send_plan(b, clock)
    b.tick()
    assert b.next_poll > clock() + 7 * 3600
    clock.advance(30)
    b.mqtt_reconnected.set()
    b.tick()
    slot = (math.floor(clock() / 1800) + 1) * 1800
    assert b.next_poll <= slot and b.next_background[SERIAL] <= slot
    assert b.session.request.call_count == 1  # on-demand disabled: no extra read
    clock.now = slot
    b.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": SERIAL}]}}),
        response(body=STATUS),
    ]
    b.tick()
    assert b.session.request.call_count == 3 and b.availability[SERIAL] is True


def test_reconnect_read_is_single_spaced_and_survives_flapping(factory, clock):
    b = smart_bridge(factory, clock, on_demand_refresh_enabled=True)
    clock.advance(60)
    b.mqtt_reconnected.set()
    b.tick()
    assert b.session.request.call_count == 1  # last read 60 s ago: spacing first
    for _ in range(20):  # the broker flaps: still at most one deferred read
        clock.advance(10)
        b.mqtt_reconnected.set()
        b.tick()
    assert b.session.request.call_count == 1
    clock.advance(300 - 260)  # 300 s after the last status attempt
    b.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": SERIAL}]}}),
        response(body=STATUS),
    ]
    b.next_cloud = min(b.next_cloud, clock())
    b.tick()
    assert b.session.request.call_count == 3 and b.availability[SERIAL] is True
    assert diagnostics(b)["on_demand_refresh_activity"]["outcomes"] == {
        "reconnect_read_scheduled": 1
    }
    for _ in range(30):
        clock.advance(20)
        b.tick()
    assert b.session.request.call_count == 3  # not repeated


def test_reconnect_read_waits_for_cloud_cooldown(factory, clock):
    b = smart_bridge(factory, clock, on_demand_refresh_enabled=True)
    b.usage.cooldown(clock() + 3600, 1)
    b.next_cloud = clock() + 3600
    clock.advance(400)
    b.mqtt_reconnected.set()
    slot = (math.floor(clock() / 1800) + 1) * 1800
    assert slot < b.usage.cooldown_until
    while clock() < b.usage.cooldown_until - 20:  # through the fixed slot as well
        clock.advance(20)
        b.tick()
    assert b.session.request.call_count == 1  # next_cloud still holds the cooldown
    assert b.reconnect_refresh  # still owed, never spent during the cooldown


def test_refresh_outcomes_are_categorised_without_payloads(factory, clock):
    b = smart_bridge(factory, clock, on_demand_refresh_enabled=True)
    publish(b)  # just read: spacing
    publish(b, payload=b"SECRET")
    publish(b, serial="OTHER1")
    clock.advance(300)
    publish(b)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    activity = diagnostics(b)["on_demand_refresh_activity"]
    assert activity["outcomes"] == {
        "refused_min_spacing": 1,
        "refused_invalid_payload": 1,
        "refused_unknown_heater": 1,
        "queued": 1,
        "accepted_for_read": 1,
    }
    assert activity["last"]["result"] == "accepted_for_read"
    assert "SECRET" not in json.dumps(diagnostics(b))
    off = smart_bridge(factory, clock)
    publish(off)
    assert off.refresh_activity["outcomes"] == {"refused_disabled": 1}


# --- end to end: real bridge, real controller, HA-faithful timestamp state -------------------


class HaRig(Rig):
    """Rig whose 'Last successful poll' state is rendered as HA renders it."""

    def ha_mqtt(self, topic, payload, *args, **kwargs):
        super().ha_mqtt(topic, payload, *args, **kwargs)
        if topic.endswith("/DIAGNOSTICS"):
            stamp = json.loads(payload)["last_successful_poll"]
            if stamp is not None:
                epoch = datetime.fromisoformat(stamp).timestamp()
                self.report("sensor.home_last_successful_poll", ha_state(epoch))


def quiet_rig(tmp_path, monkeypatch, start):
    rig = HaRig(
        tmp_path,
        monkeypatch,
        start,
        mode="Manual",
        setpoint=45,
        reading=45,
        pv=lambda local: 0,
    )
    rig.t += FRACTION
    ct_free(rig)
    smart(rig)
    return rig


def test_post_upgrade_night_accepts_smart_plans_and_activates(tmp_path, monkeypatch):
    rig = quiet_rig(tmp_path, monkeypatch, hobart(MON, 22, 50))
    assert "." not in rig.states["sensor.home_last_successful_poll"].state  # HA precision
    rig.enable()
    rig.run(hobart(MON, 23, 10))
    controller = rig.executor.controller
    assert controller.state != "observing"  # Manual 45 classified after a fresh read
    assert controller.heater == "baseline"
    counts = rig.bridge.poll_schedule.counts
    assert counts["accepted"] > 0
    assert rig.bridge.poll_schedule.rejections.get("status_identity_mismatch", 0) == 0
    reads = rig.bridge.usage.counts.get("status", 0)
    rig.run(hobart(MON + 1, 5))
    assert rig.bridge.poll_schedule.summary(SERIAL)["active"]
    # Fixed polling would read about 12 times in these six hours.
    assert rig.bridge.usage.counts.get("status", 0) - reads <= 4
    assert not rig.posts  # nothing to change: Manual 45 overnight is the policy
    data = report.build(rig.runtime, rig.now(), "2026.11.1")["polling"]
    assert data["actual_mode"] == "adaptive" and data["bridge_preference"] == "smart"
    assert data["plans_accepted"] > 0 and data["plans_rejected"] == 0
    assert data["last_acceptance"]["reason"] == "stable_baseline"


def test_report_polling_section_filters_unknown_categories(tmp_path, monkeypatch):
    rig = quiet_rig(tmp_path, monkeypatch, hobart(MON, 22, 50))
    rig.enable()
    rig.run(hobart(MON, 23, 0))
    entity = rig.runtime.sources["cloud_health"]
    attrs = dict(rig.states[entity].attributes)
    attrs["adaptive_polling"] = {
        **attrs["adaptive_polling"],
        "rejection_reasons": {"status_identity_mismatch": 38, "PRIVATE_TEXT": 1},
        "last_rejection": {"reason": "PRIVATE_TEXT", "at": rig.t},
    }
    rig.report(entity, rig.states[entity].state, attrs)
    data = report.build(rig.runtime, rig.now(), "2026.11.1")["polling"]
    assert data["rejection_reasons_since_bridge_start"] == {"status_identity_mismatch": 38}
    assert data["last_rejection"]["reason"] == "unreported"
    assert "PRIVATE_TEXT" not in json.dumps(data)
