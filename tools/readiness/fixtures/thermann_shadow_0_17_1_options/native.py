"""Owner-reported Schedule reference, never inferred element power or reserve."""

import json

from .config import _minute


def parse_native(raw):
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError("native_reference_invalid")
    data = json.loads(raw)
    # [] is the owner-approved EMPTY weekly programme (the controller's park).
    if not isinstance(data, list) or not 0 <= len(data) <= 32:
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
