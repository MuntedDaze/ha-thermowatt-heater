"""Owner-reported Schedule reference, never inferred element power or reserve."""

import json
from datetime import date, datetime, time, timedelta

from .config import _minute
from .model import HOBART, STANDARD


def parse_native(raw):
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError("native_reference_invalid")
    data = json.loads(raw)
    if not isinstance(data, list) or not 1 <= len(data) <= 32:
        raise ValueError("native_reference_invalid")
    periods = []
    for item in data:
        if not isinstance(item, dict) or set(item) != {"days", "start", "end"}:
            raise ValueError("native_reference_invalid")
        days = item["days"]
        if (
            not isinstance(days, list)
            or not days
            or any(type(d) is not int or not 0 <= d <= 6 for d in days)
        ):
            raise ValueError("native_reference_invalid")
        periods.append((tuple(days), _minute(item["start"]), _minute(item["end"])))
    return tuple(periods)


def scheduled_permission(now, periods, clock):
    at = now.astimezone(HOBART if clock == "local" else STANDARD)
    minute = at.hour * 60 + at.minute
    for days, start, end in periods:
        today, previous = at.weekday() in days, (at.weekday() - 1) % 7 in days
        if (
            (start < end and today and start <= minute < end)
            or (start > end and ((today and minute >= start) or (previous and minute < end)))
            or (start == end and today)
        ):
            return "within_reported_window"
    return "outside_reported_window"


def permitted_minutes(now, deadline, periods, clock):
    total, cursor = 0.0, now
    while cursor < deadline:
        end = min(cursor.replace(second=0, microsecond=0) + timedelta(minutes=1), deadline)
        if scheduled_permission(cursor, periods, clock) == "within_reported_window":
            total += (end - cursor).total_seconds() / 60
        cursor = end
    return total


def clock_check_required(now, checked):
    """Manual device clock needs a new owner check after any DST transition."""
    if not checked:
        return True
    try:
        start = date.fromisoformat(checked)
    except (ValueError, TypeError):
        return True
    today = now.astimezone(HOBART).date()
    if not 0 <= (today - start).days <= 366:
        return True
    offset = datetime.combine(start, time(12), HOBART).utcoffset()
    while start <= today:
        if datetime.combine(start, time(12), HOBART).utcoffset() != offset:
            return True
        start += timedelta(days=1)
    return False
