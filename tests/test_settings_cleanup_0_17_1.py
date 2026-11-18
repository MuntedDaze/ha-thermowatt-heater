"""Controller 0.17.1: behaviour-preserving configuration cleanup."""

import importlib

import pytest

from test_shadow_model import c, m, ROOT

ui = importlib.import_module(f"{m.__package__}.configuration")
text = importlib.import_module(f"{m.__package__}.configuration_text")
settings = importlib.import_module(f"{m.__package__}.settings")

LEGACY = {
    "adaptive_polling_enabled",
    "event_aware_polling_enabled",
    "owner_change_check_minutes",
    "adaptive_polling_shadow",
    "adaptive_poll_heating_minutes",
    "adaptive_poll_stable_minutes",
    "controller_three_state_qualified",
    "weekend_qualify_minutes",
    "weekend_sunset_kw",
    "weekend_sunset_minutes",
}


def test_every_submenu_ends_with_back_to_the_main_menu():
    steps = text.flow_text()["step"]
    for menu in ("electricity", "solar_meters", "advanced"):
        assert ui.MENUS[menu][-1] == "init"
        assert steps[menu]["menu_options"]["init"] == text.BACK
    assert "init" not in ui.MENUS["init"]


def test_polling_page_offers_one_obvious_choice():
    assert ui.PAGES["polling"] == ("polling_mode", "status_max_age_minutes", "grid_max_age_seconds")
    help_text = ui.FIELDS["polling_mode"][1]
    assert help_text.startswith("Smart is the recommended choice")
    assert "Thermann Hot Water app" in help_text


def test_legacy_settings_are_separated_but_kept():
    assert set(ui.PAGES["legacy"]) == LEGACY
    for page, keys in ui.PAGES.items():
        if page != "legacy":
            assert LEGACY.isdisjoint(keys), page
    # Stored keys, defaults and their native setting entities are unchanged.
    assert LEGACY <= set(c.DEFAULT_OPTIONS) and LEGACY <= set(settings.CATALOG)
    assert not LEGACY & settings.RETIRED
    for key in LEGACY:
        assert settings.CATALOG[key].group != "Retired"


def test_three_state_record_has_no_effect_on_command_gates():
    from dataclasses import replace

    ctl = importlib.import_module(f"{m.__package__}.controller")
    source = (ROOT / "custom_components/thermann_shadow/executor.py").read_text(encoding="utf-8")
    assert "requires_four_states=True," in source  # the only production configuration
    base = ctl.ControllerConfig(
        command_topic="P/X/CMD/MODE", requires_four_states=True, four_state_qualified=True
    )
    on, off = replace(base, three_state_qualified=True), replace(base, three_state_qualified=False)
    assert on.missing_commissioning() == off.missing_commissioning() == []


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
        "polling_mode",
        "ct_free_solar_verification",
        "tariff_clock",
    ],
)
def test_control_and_commissioning_settings_stay_locked(key):
    assert key in settings.LOCKED_WHILE_ACTIVE
    assert key not in settings.SAFE_WHILE_ACTIVE


def test_unused_definitions_are_removed():
    # Unreferenced since 0.9.0 (only the frozen 0.7.0 readiness fixture used
    # holiday_window); behaviour is covered by holiday_active/holiday tests.
    ctl = importlib.import_module(f"{m.__package__}.controller")
    model = importlib.import_module(f"{m.__package__}.model")
    assert not hasattr(ctl.Controller, "holiday_window")
    assert not hasattr(model, "_present")
