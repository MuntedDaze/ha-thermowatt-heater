"""New owner settings through actual executor, persistence and mocked cloud."""

from datetime import timedelta

from test_integration_0_9_0 import Rig, hobart, MON
from test_existing_installation_upgrade import ct_free
from test_next_major_policy import ctl


def smart(rig):
    rig.entry.options.update(optional_solar_boost=False)  # polling follows the app (D2)
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    rig.bridge.options["polling_mode"] = "smart"
    rig.bridge.poll_schedule.smart_mode = "smart"
    rig.bridge.poll_schedule.enabled = True
    rig.bridge.publish_diagnostics(force=True)


def test_quiet_night_uses_few_reads_but_detects_owner_change_before_a_command(
    tmp_path, monkeypatch
):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(MON, 22),
        mode="Manual",
        setpoint=45,
        reading=45,
        pv=lambda local: 0,
    )
    ct_free(rig)
    smart(rig)
    rig.enable()
    rig.run(hobart(MON + 1, 2))
    count = rig.bridge.usage.total
    rig.tank.apply("Manual", 55, rig.t)
    changed = rig.now()
    rig.run(hobart(MON + 1, 7, 59))
    assert rig.executor.controller.state == "owner_override"
    assert rig.bridge.usage.total - count < 12
    assert rig.tank.setpoint == 55 and not rig.posts
    assert rig.now() - changed < timedelta(hours=8)


def test_weekend_day_latch_persists_and_the_18_00_end_is_not_undone_by_restart(
    tmp_path, monkeypatch
):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(14, 10),
        mode="Manual",
        setpoint=45,
        reading=45,
        pv=lambda local: 1,
    )
    ct_free(rig)
    rig.entry.options.update(optional_solar_boost=False)
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    rig.enable()
    rig.run(hobart(14, 10, 40))
    assert rig.tank.setpoint == 62
    saved = rig.executor.controller.to_dict()
    assert saved["weekend_heat_date"] == "2026-11-14"
    restored = ctl.Controller.from_dict(saved)
    restored.restored(rig.now())
    assert restored.weekend_heat_date == saved["weekend_heat_date"]
    rig.executor.controller = restored
    rig.pv = lambda local: 0
    rig.run(hobart(14, 17, 55))
    assert rig.tank.setpoint == 62  # 0.17.0: no PV no longer ends the window early
    rig.run(hobart(14, 18, 5))
    assert rig.tank.setpoint == 45
    saved = rig.executor.controller.to_dict()
    assert saved["weekend_end_date"] == "2026-11-14"
    rig.executor.controller = ctl.Controller.from_dict(saved)
    rig.executor.controller.restored(rig.now())
    rig.pv = lambda local: 5
    rig.run(hobart(14, 18, 40))
    assert rig.tank.setpoint == 45
    assert sum(payload.startswith("Manual:62") for payload in rig.commands()) == 1


def test_new_override_preserves_pending_legacy_intent_without_replaying():
    controller = ctl.Controller.from_dict(
        {
            "guest_until": "2026-11-18T10:00:00+00:00",
            "intent": {
                "target": "storage",
                "prior": "off",
                "payload": "Manual:70@off",
                "status": "submitted_awaiting_status",
            },
        }
    )
    intent = dict(controller.intent)
    expiry = controller.guest_until
    controller.restored(hobart(MON, 22))
    assert controller.intent == intent and controller.guest_until == expiry
    assert controller.guest_target_c == 70
