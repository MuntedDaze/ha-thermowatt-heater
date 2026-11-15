"""Presentation invariants: no saved-price/temperature/protocol migrations."""

import importlib
import json

import pytest

from test_shadow_model import c, m, PACKAGE, ROOT

ui = importlib.import_module(f"{m.__package__}.configuration")
text = importlib.import_module(f"{m.__package__}.configuration_text")


def test_every_visible_field_has_inline_help_and_a_unique_home():
    steps = text.flow_text()["step"]
    keys = [key for page in ui.PAGES for key in ui.PAGES[page]]
    assert len(keys) == len(set(keys)) == len(ui.FIELDS)
    for step in steps.values():
        assert set(step.get("data", {})) == set(step.get("data_description", {}))
        assert all(len(v) > 50 for v in step.get("data_description", {}).values())
    assert set(ui.SOURCES) == set(c.DEFAULT_SOURCES) | set(c.OPTIONAL_SOURCES)
    for menu, children in ui.MENUS.items():
        assert set(steps[menu]["menu_options"]) == set(children)
    assert set(ui.PAGES["hot_water"]).isdisjoint(ui.PAGES["commissioning"])


@pytest.mark.parametrize("key", ui.SCALES)
@pytest.mark.parametrize("raw", [0, 0.0000123456789, 0.1702, 0.361878, 0.09276, 0.9, 1.23456789])
def test_display_round_trip_preserves_precise_saved_values(key, raw):
    values = {**c.DEFAULT_OPTIONS, key: raw}
    changes = ui.stored_changes(values, {key: ui.display_value(key, raw)})
    assert changes[key] is raw


def test_units_convert_only_deliberate_edits():
    changes = ui.stored_changes(
        c.DEFAULT_OPTIONS,
        {
            "peak_rate": 36.1878,
            "forecast_uncertainty": 30,
            "boost_useful_fraction": 80,
            "optional_heat_margin_aud_per_kwh": 2.5,
            "baseline_c": "45",
            "normal_storage_c": "62",
            "solar_boost_c": "70",
        },
    )
    assert changes == {
        "peak_rate": 0.361878,
        "forecast_uncertainty": 0.3,
        "boost_useful_fraction": 0.8,
        "optional_heat_margin_aud_per_kwh": 0.025,
        "baseline_c": "45",
        "normal_storage_c": "62",
        "solar_boost_c": "70",
    }
    assert ui.unit("peak_rate") == "c/kWh"
    assert ui.unit("forecast_uncertainty") == "%"


def test_native_time_selector_added_seconds_do_not_change_saved_times():
    values = {**c.DEFAULT_OPTIONS, "daytime_start": "09:00", "baseline_start": "21:00:00"}
    assert ui.stored_changes(values, {"daytime_start": "09:00:00", "baseline_start": "21:00"}) == {
        "daytime_start": "09:00",
        "baseline_start": "21:00:00",
    }
    changed = ui.stored_changes(values, {"daytime_start": "09:00:30"})
    with pytest.raises(ValueError):
        c.parse_options({**values, **changed})


def form_for(row):
    return {
        "days": [str(v) for v in row["days"]],
        "start": row["start"],
        "end": row["end"],
        "kind": row["kind"],
        "months": [str(v) for v in row.get("months", range(1, 13))],
        "use_rate": "rate" in row,
        "rate": ui.display_value("off_peak_rate", row.get("rate", 0)),
    }


def test_guided_noop_preserves_original_json_including_precise_overrides():
    row = {
        "days": list(range(7)),
        "start": "00:00",
        "end": "00:00",
        "kind": "off_peak",
        "rate": 0.123456789123,
    }
    raw = json.dumps([row], indent=3)
    edited = ui.period_from_form(form_for(row), row)
    assert edited == row
    values = {**c.DEFAULT_OPTIONS, "tariff_profile": "custom", "tariff_periods": raw}
    assert ui.schedule_changes(values, [edited]) == {
        "tariff_profile": "custom",
        "tariff_periods": raw,
    }
    assert "months" not in edited


def test_guided_noop_keeps_valid_legacy_seconds_and_month_order():
    row = {
        "days": [6, 5],
        "start": "10:00:00",
        "end": "12:00:00",
        "kind": "shoulder",
        "months": [12, 1, 2],
    }
    form = {**form_for(row), "start": "10:00", "end": "12:00"}
    assert ui.period_from_form(form, row) == row


def test_seasonal_weekday_midday_and_overnight_schedule_uses_existing_model():
    rows = []
    for months, rate in [(list(range(1, 7)), 0.15), (list(range(7, 13)), 0.20)]:
        for days in [list(range(5)), [5, 6]]:
            rows.extend(
                [
                    {
                        "days": days,
                        "months": months,
                        "start": "21:00",
                        "end": "07:00",
                        "kind": "off_peak",
                        "rate": rate,
                    },
                    {
                        "days": days,
                        "months": months,
                        "start": "07:00",
                        "end": "10:00",
                        "kind": "peak",
                    },
                    {
                        "days": days,
                        "months": months,
                        "start": "10:00",
                        "end": "16:00",
                        "kind": "shoulder",
                        "rate": 0.10,
                    },
                    {
                        "days": days,
                        "months": months,
                        "start": "16:00",
                        "end": "21:00",
                        "kind": "peak",
                    },
                ]
            )
    changes = ui.schedule_changes(c.DEFAULT_OPTIONS, rows)
    _, tariffs = c.parse_options({**c.DEFAULT_OPTIONS, **changes})
    assert len(tariffs) == 16
    assert "Monday" in text.SELECT_LABELS["days"].values()
    assert "all year" not in text.schedule_summary(rows, c.DEFAULT_OPTIONS)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"days": [0], "start": "00:00", "end": "00:00", "kind": "off_peak"}],
        [
            {
                "days": list(range(7)),
                "start": "00:00",
                "end": "00:00",
                "kind": "off_peak",
                "rate": 2.01,
            }
        ],
    ],
)
def test_guided_invalid_schedule_cannot_save(rows):
    with pytest.raises((ValueError, TypeError)):
        ui.schedule_changes(c.DEFAULT_OPTIONS, rows)


def test_generated_translations_and_legacy_generator_keep_form_help():
    source = json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8"))
    assert source == json.loads((PACKAGE / "translations/en.json").read_text(encoding="utf-8"))
    assert source["options"] == text.flow_text()
    assert (
        source["config"]["step"]["user"]["data_description"]["heater_power"]
        == ui.SOURCES["heater_power"][1]
    )
    legacy = (ROOT / "tools/build_shadow_dashboard.py").read_text(encoding="utf-8")
    assert "from build_configuration_strings import main" in legacy
