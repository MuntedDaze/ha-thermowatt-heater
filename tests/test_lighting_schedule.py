"""The optional evening lights schedule: on two hours before local sunset, off at 01:00, never fighting manual use.

The file is optional and NOT loaded by anything: it does nothing until the owner copies it into place. Home
Assistant evaluates the sun trigger and the time trigger itself, so these tests check the configuration, then
prove the two timing claims on a model of the real calendar (Australia/Hobart, daylight saving included).
"""

from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "homeowner/optional/evening_lights_schedule.yaml"
HOBART = ZoneInfo("Australia/Hobart")


def automations():
    data = yaml.safe_load(FILE.read_text(encoding="utf-8"))
    assert set(data) == {"automation"}
    return {a["alias"]: a for a in data["automation"]}


def test_exactly_two_automations_with_the_documented_triggers():
    found = automations()
    assert set(found) == {"Evening lights on", "Evening lights off"}
    on, off = found["Evening lights on"], found["Evening lights off"]
    assert on["triggers"] == [{"trigger": "sun", "event": "sunset", "offset": "-02:00:00"}]
    assert off["triggers"] == [{"trigger": "time", "at": "01:00:00"}]
    assert on["actions"][0]["action"] == "homeassistant.turn_on"
    assert off["actions"][0]["action"] == "homeassistant.turn_off"


def test_the_schedule_never_fights_manual_changes():
    for automation in automations().values():
        assert "conditions" not in automation and "condition" not in automation
        # no trigger reacts to a light changing, so a manual change is never reverted or re-applied
        assert [t["trigger"] for t in automation["triggers"]] in (["sun"], ["time"])
        assert automation["mode"] == "single"
        # nothing here turns an automation off: manual use leaves the schedule untouched
        assert "automation." not in yaml.safe_dump(automation["actions"])


def test_lights_come_from_a_label_not_from_a_list_of_entity_ids():
    for automation in automations().values():
        target = automation["actions"][0]["target"]
        assert target == {"label_id": "evening_lights"}
    text = FILE.read_text(encoding="utf-8")
    assert "light." not in yaml.safe_dump(yaml.safe_load(text))  # no invented entity IDs


def test_the_file_is_optional_nothing_loads_it():
    # not under a loaded directory, and no other file includes it
    assert FILE.parent.name == "optional"
    for name in (
        "thermowatt.yaml",
        "home_energy_package.yaml",
    ):  # the files that ARE loaded as packages
        assert "evening_lights" not in (ROOT / "homeowner" / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the calendar model
def sunset_utc(day: date, lat=-42.88, lon=147.33) -> datetime:
    """NOAA sunset (UTC) for a place: a stand-in for Home Assistant's own astral calculation."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    phi = math.radians(lat)
    ha = math.degrees(
        math.acos(
            math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl))
            - math.tan(phi) * math.tan(decl)
        )
    )
    minutes = (
        720 - 4 * (lon - ha) - eqtime
    )  # UTC minutes after midnight (sunset; longitude east-positive)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_on_time_follows_the_seasons_and_always_precedes_the_01_00_off():
    on_times = []
    for offset in range(0, 365, 7):
        day = date(2026, 6, 1) + timedelta(days=offset)
        on = sunset_utc(day) - timedelta(hours=2)
        local_on = on.astimezone(HOBART)
        on_times.append(local_on.hour + local_on.minute / 60)
        # the next 01:00 local after the "on" event is hours later: the lights are on for a real window
        off = datetime(day.year, day.month, day.day, 1, 0, tzinfo=HOBART) + timedelta(days=1)
        window = (off - local_on).total_seconds() / 3600
        assert 5 < window < 12, (day, window)
    # winter on-times are mid-afternoon, summer ones are evening: the trigger moves by hours across the year
    assert min(on_times) < 15 and max(on_times) > 18


def test_one_oclock_exists_exactly_once_every_local_day_including_daylight_saving_changes():
    # Tasmania moves its clocks at 02:00/03:00 (first Sundays of October and April): 01:00 is never skipped or repeated
    start, end = date(2026, 9, 1), date(2027, 5, 1)
    day = start
    while day <= end:
        first = datetime(day.year, day.month, day.day, 1, 0, tzinfo=HOBART, fold=0)
        second = first.replace(fold=1)
        assert first.utcoffset() == second.utcoffset(), day  # not an ambiguous (repeated) time
        assert first.astimezone(timezone.utc).astimezone(HOBART).hour == 1, (
            day
        )  # not a skipped time
        day += timedelta(days=1)


def test_daylight_saving_shifts_the_clock_time_of_sunset_but_not_the_rule():
    # the rule is "sunset minus two hours" in Home Assistant's time zone, so the clock time shifts with the offset
    before = sunset_utc(date(2026, 10, 3)).astimezone(HOBART)  # standard time (UTC+10)
    after = sunset_utc(date(2026, 10, 5)).astimezone(HOBART)  # daylight time (UTC+11)
    assert before.utcoffset() == timedelta(hours=10) and after.utcoffset() == timedelta(hours=11)
    clock = lambda d: d.hour + d.minute / 60  # noqa: E731
    assert 0.8 < clock(after) - clock(before) < 1.3  # the same rule, an hour later by the clock
