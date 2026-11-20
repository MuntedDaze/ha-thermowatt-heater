"""Controller 0.18.0: one authoritative policy (docs/OPERATING_POLICY.md).

Owner decisions of 20 November 2026:
* the 0.7.0 morning reserve (45 C by 06:00 / 42 C by 07:00) is cancelled;
* D1 low-water notification before the evening peak only;
* D2 one polling configuration: the controller follows the app's Smart choice;
* D3 0.3 kW solar start headroom is a constant (3.3 kW for 3 kW);
* retired settings are migrated into an unread record, never validated.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import importlib
from types import SimpleNamespace

import pytest

from test_shadow_model import c, m, ROOT
from test_simple_policy import MIN, MON, TARIFFS, at, sp

ui = importlib.import_module(f"{m.__package__}.configuration")
text = importlib.import_module(f"{m.__package__}.configuration_text")
settings = importlib.import_module(f"{m.__package__}.settings")
comfort = importlib.import_module(f"{m.__package__}.comfort")
solar = importlib.import_module(f"{m.__package__}.solar")
ctl = importlib.import_module(f"{m.__package__}.controller")
PACKAGE = ROOT / "custom_components/thermann_shadow"

LEGACY_POLLING = {
    "polling_mode",
    "adaptive_polling_enabled",
    "event_aware_polling_enabled",
    "owner_change_check_minutes",
    "adaptive_polling_shadow",
    "adaptive_poll_heating_minutes",
    "adaptive_poll_stable_minutes",
}
MORNING = {
    "morning_threshold_c",
    "morning_preferred_c",
    "morning_preferred_time",
    "morning_hard_time",
    "morning_time",
    "shower_time_enabled",
    "shower_time",
}


# --- retired settings are gone from the active configuration ------------------------------


def test_retired_settings_are_not_active_anywhere():
    assert len(c.RETIRED_OPTIONS) == 45 and len(c.DEFAULT_OPTIONS) == 55
    assert MORNING | LEGACY_POLLING | {"export_headroom_kw"} <= c.RETIRED_OPTIONS
    assert not c.RETIRED_OPTIONS & set(c.DEFAULT_OPTIONS)
    assert not c.RETIRED_OPTIONS & set(settings.CATALOG)
    assert not c.RETIRED_OPTIONS & set(ui.FIELDS)
    assert set(settings.GROUPS) >= {meta.group for meta in settings.CATALOG.values()}
    assert "legacy" not in ui.PAGES and "legacy" not in ui.MENUS["advanced"]
    assert ui.PAGES["polling"] == ("status_max_age_minutes", "grid_max_age_seconds")
    settings_obj, _ = c.parse_options({})
    for field in ("target_c", "morning_threshold_c", "morning_preferred", "export_headroom_kw"):
        assert not hasattr(settings_obj, field)


def test_every_remaining_setting_is_documented_on_one_form_and_in_settings_md():
    shown = [key for keys in ui.PAGES.values() for key in keys]
    assert sorted(shown) == sorted(settings.CATALOG) and len(shown) == len(set(shown))
    reference = (ROOT / "docs/SETTINGS.md").read_text(encoding="utf-8")
    for key, meta in settings.CATALOG.items():
        assert meta.explanation.strip(), key
        assert f"`{key}`" in reference, key
    for key in c.RETIRED_OPTIONS:
        assert f"`{key}`" not in reference.split("## Retired")[0], key


@pytest.mark.parametrize(
    "retired",
    [
        # Each of these made every settings save fail in 0.17.1 with an error
        # about a field the owner could neither see nor edit (audit finding F2).
        {"morning_preferred_time": "06:30", "morning_hard_time": "06:00"},
        {"morning_threshold_c": 50, "morning_preferred_c": 45},
        {"evening_time": "10:00"},
        {"controller_min_rest_minutes": 90, "controller_execution_latency_minutes": 0},
        {"native_schedule_periods": "not json"},
        {"native_clock_check_date": "yesterday"},
        {"t_comfort_reference_c": 80},
        {"target_c": "seventy"},
        {"polling_mode": "something_else", "owner_change_check_minutes": True},
    ],
)
def test_retired_values_never_block_an_active_setting_change(retired):
    saved = {**c.DEFAULT_OPTIONS, **retired}
    c.parse_options(saved)
    changed = settings.apply_changes(saved, {"low_water_warning_c": 30.0})
    c.parse_options(changed)
    assert all(changed[key] == value for key, value in retired.items())  # untouched


def test_active_values_are_still_fully_validated():
    for bad in (
        {"low_water_warning_c": 50},
        {"baseline_c": "70"},
        {"controller_max_commands_per_day": 4.5},
        {"weekend_end_time": "11:00"},
    ):
        with pytest.raises((ValueError, TypeError)):
            c.parse_options(bad)


# --- 1.5 -> 1.6 migration ---------------------------------------------------------------------


def test_migration_moves_retired_values_verbatim_and_is_idempotent():
    old = {
        **c.DEFAULT_OPTIONS,
        "morning_threshold_c": 42.0,
        "morning_hard_time": "07:00",
        "polling_mode": "smart",
        "weekend_qualify_minutes": 15.0,
        "export_headroom_kw": 0.3,
        "sources": {"heater": "water_heater.synthetic"},
        "restore_backup": {"forecast_uncertainty": 0.4, "margin_minutes": 45},
    }
    migrated, moved, kept = c.migrate_0_18_0(old)
    assert kept is None
    assert set(moved) == {
        "morning_threshold_c",
        "morning_hard_time",
        "polling_mode",
        "weekend_qualify_minutes",
        "export_headroom_kw",
    }
    assert migrated["retired_options"] == {
        "morning_threshold_c": 42.0,
        "morning_hard_time": "07:00",
        "polling_mode": "smart",
        "weekend_qualify_minutes": 15.0,
        "export_headroom_kw": 0.3,
        "restore_backup": {"margin_minutes": 45},
    }
    assert migrated["restore_backup"] == {"forecast_uncertainty": 0.4}
    assert migrated["sources"] == old["sources"]
    assert not c.RETIRED_OPTIONS & set(migrated)
    assert all(migrated[key] == old[key] for key in c.DEFAULT_OPTIONS)
    c.parse_options(migrated)
    settings.undo_restore(migrated)  # the remaining snapshot still undoes
    again, moved_again, _ = c.migrate_0_18_0(migrated)
    assert again == migrated and moved_again == []


def test_migration_never_overwrites_an_existing_record():
    migrated, _, _ = c.migrate_0_18_0(
        {"target_c": 66.0, "retired_options": {"target_c": 65.0, "paused": True}}
    )
    assert migrated["retired_options"] == {"target_c": 65.0, "paused": True}


@pytest.mark.parametrize(
    "stored,kept,threshold",
    [
        (None, None, 3.3),
        (0.3, None, 3.3),
        (0.30000000001, None, 3.3),
        (0.5, 0.5, 3.5),  # D3: an installed value that differs is not changed silently
        (0.0, 0.0, 3.0),
        ("bad", None, 3.3),  # 0.17.1 could not load this; nothing to preserve
        (9.0, None, 3.3),
    ],
)
def test_solar_start_headroom_migration_preserves_installed_qualification(stored, kept, threshold):
    old = dict(c.DEFAULT_OPTIONS)
    if stored is not None:
        old["export_headroom_kw"] = stored
    migrated, _, kept_value = c.migrate_0_18_0(old)
    assert kept_value == kept
    assert ("export_headroom_kw" in migrated) is (kept is not None)
    c.parse_options(migrated)
    element = c.DEFAULT_OPTIONS["element_kw"]
    assert element + c.solar_start_headroom_kw(migrated) == pytest.approx(threshold)


def test_solar_start_threshold_constant():
    assert solar.SOLAR_START_HEADROOM_KW == 0.3
    assert c.solar_start_headroom_kw({}) == 0.3
    assert sp.PolicySettings().peak_start_kw == pytest.approx(3.3)
    source = (PACKAGE / "executor.py").read_text(encoding="utf-8")
    assert "solar_start_headroom_kw(self.runtime.native_options)" in source


# --- D1: low-water notification before the evening peak only --------------------------------


def _assess(now, peak, reading=30.0):
    return comfort.pre_peak_availability(
        now,
        reading,
        now - 2 * MIN,
        comfort.evening_peak(peak, "Australia/Hobart"),
        threshold=35,
        lead_minutes=30,
    )


@pytest.mark.parametrize("month", [7, 11])  # AEST and Hobart daylight time
def test_low_water_is_never_assessed_before_the_morning_peak(month):
    # Owner's fixed-AEST tariff clock: 07:00 AEST is 07:00 (July) / 08:00 (November).
    morning = datetime(2026, month, 14 if month == 7 else 17, 7, tzinfo=m.STANDARD)
    assert _assess(morning - 20 * MIN, morning)["state"] == "not_due"
    evening = morning.replace(hour=16)
    assert _assess(evening - 20 * MIN, evening)["state"] == "low"
    assert _assess(evening - 20 * MIN, evening, reading=50)["state"] == (
        "latest_probe_above_warning"
    )


def test_low_water_alert_is_notification_only():
    """The alert never changes the wanted state or a command gate."""
    from test_controller_0_9_0 import cfg, obs, ready, want

    now = at(MON, 15, 40)
    controller = ready(now, "Manual", 62)
    observation = obs(now, "Manual", 62)
    observation.low_water_assessment = {
        "state": "low",
        "reading_c": 30,
        "observed_at": now.isoformat(),
    }
    effects = controller.step(observation, want("normal_storage"), cfg())
    assert any(e.key == "pre_peak_low_hot_water" for e in effects if e.kind == "notify")
    assert not any(e.kind == "publish" for e in effects)
    message = next(e.message for e in effects if e.key == "pre_peak_low_hot_water")
    assert "evening peak" in message


# --- cancelled morning reserve: no chase, no top-up ---------------------------------------------


def test_overnight_policy_never_chases_a_morning_bottom_probe_temperature():
    """After Monday's evening peak (22:00 AEDT) to Tuesday 10:30 with the probe
    falling to 30 C and no solar: Manual 45 overnight, OFF through the morning
    peak, never 62/70 before it."""
    policy = sp.SimplePolicy(sp.PolicySettings(tariff_clock="standard"), TARIFFS)
    state, reading = sp.BASELINE, 45.0
    now = at(MON, 22)
    end = at(MON + 1, 10, 30)
    seen = set()
    morning_peak = at(MON + 1, 8)  # 07:00 AEST during Hobart daylight time
    while now < end:
        decision = policy.decide(
            sp.Snapshot(now, state, reading, now - 5 * MIN, heater_meter_valid=False)
        )
        wanted = decision.state if decision.state != sp.HOLD else state
        if now < morning_peak - timedelta(minutes=2):
            assert wanted == sp.BASELINE, (now, decision.reason)
            assert decision.command in (None, "Manual:45")
        seen.add(decision.reason)
        if decision.command:
            state = wanted
        reading = max(30.0, reading - 0.25)
        now += 5 * MIN
    assert "peak_lockout" in seen
    assert not {r for r in seen if "morning" in r}


def test_no_morning_requirement_survives_in_active_code():
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for needle in ("morning_threshold", "morning_preferred", "morning_hard", "42 °C"):
            if needle in source:
                # Only the retired-key list and the old-entity registry clean-up.
                assert path.name in {"config.py", "naming.py"}, (path.name, needle)
    assert not hasattr(comfort, "morning_availability")


# --- D2: one polling configuration ------------------------------------------------------------


def test_controller_follows_the_app_polling_choice(tmp_path, monkeypatch):
    from test_integration_0_9_0 import Rig, hobart

    executor = Rig(tmp_path, monkeypatch, hobart(MON, 22)).executor
    for attrs, expected in (
        ({"polling_preference": "smart", "adaptive_plan_versions": [1, 3]}, True),
        ({"polling_preference": "smart", "adaptive_plan_versions": [3]}, True),
        ({"polling_preference": "fixed", "adaptive_plan_versions": [3]}, False),
        ({"polling_preference": "existing", "adaptive_plan_versions": [1]}, False),
        ({"polling_preference": "minimum", "adaptive_plan_versions": [1, 3]}, False),
        ({"polling_preference": "smart", "adaptive_plan_versions": [1]}, False),
        ({"polling_preference": "smart", "adaptive_plan_versions": [True]}, False),
        ({}, False),
    ):
        assert executor._bridge_smart(SimpleNamespace(attributes=attrs)) is expected, attrs
    assert executor._bridge_smart(None) is False


def test_controller_has_no_polling_setting_or_pre_smart_plans():
    adaptive = importlib.import_module(f"{m.__package__}.adaptive")
    assert not hasattr(adaptive, "make_plan") and not hasattr(adaptive, "event_plan")
    for name in ("executor.py", "runtime.py", "report.py", "config_flow.py"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        assert 'native_options["polling_mode"]' not in source, name
        assert "PollingShadow" not in source and "poll_shadow" not in source, name
    assert not (PACKAGE / "polling.py").exists()
    plan = adaptive.smart_plan(at(MON, 23), at(MON, 23), stable_state="baseline", overnight=True)
    assert plan["polling_mode"] == "smart" and plan["owner_check_seconds"] == 28800


# --- carried over from 0.17.1: navigation and locks ------------------------------------------


def test_every_submenu_ends_with_back_to_the_main_menu():
    steps = text.flow_text()["step"]
    for menu in ("electricity", "solar_meters", "advanced"):
        assert ui.MENUS[menu][-1] == "init"
        assert steps[menu]["menu_options"]["init"] == text.BACK
    assert "init" not in ui.MENUS["init"]


@pytest.mark.parametrize("key", sorted(settings.SAFE_WHILE_ACTIVE))
def test_harmless_preferences_save_while_automatic_is_on(key):
    before = dict(c.DEFAULT_OPTIONS)
    meta = settings.CATALOG[key]
    after = {**before, key: meta.high}
    assert settings.locked_changes(before, after) == []
    c.parse_options(after)  # still fully validated
    with pytest.raises(ValueError):
        c.parse_options({**before, key: meta.high + 1000})


@pytest.mark.parametrize(
    "key",
    [
        "controller_max_commands_per_day",
        "peak_heating_policy",
        "normal_storage_c",
        "weekend_pv_start_kw",
        "ct_free_solar_verification",
        "tariff_clock",
    ],
)
def test_control_and_commissioning_settings_stay_locked(key):
    assert key in settings.LOCKED_WHILE_ACTIVE
    assert key not in settings.SAFE_WHILE_ACTIVE


def test_four_state_qualification_is_the_only_command_qualification():
    base = ctl.ControllerConfig(command_topic="P/X/CMD/MODE", four_state_qualified=True)
    assert base.missing_commissioning() == []
    assert replace(base, four_state_qualified=False).missing_commissioning() == [
        "four_state_commands_not_qualified"
    ]
    for field in ("three_state_qualified", "bridge_commands_qualified", "requires_four_states"):
        assert not hasattr(base, field)
