"""A small stand-in for Home Assistant's template environment (tests only).

Implements just the functions the generated package uses, with Home
Assistant's semantics where they differ from plain Jinja: ``float`` without a
default raises on a non-number, a missing entity reads ``unknown``, and a
rendered result is converted to a native type.
"""

import ast
from datetime import datetime, timedelta, timezone
import math
from types import SimpleNamespace

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

_MISSING = object()


def is_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _float(value, default=_MISSING):
    try:
        return float(value)
    except (TypeError, ValueError):
        if default is _MISSING:
            raise ValueError(f"float got invalid input {value!r} and no default") from None
        return default


def _as_datetime(value, default=_MISSING):
    """HA's ``as_datetime``: invalid input raises unless a default is given (then it is returned)."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        if default is _MISSING:
            raise ValueError(f"as_datetime got invalid input {value!r}") from None
        return default


class States:
    """``states('x')`` and ``states['x']`` over a dict of entity -> value.

    A value is either a plain state, or a dict with ``state`` and optionally
    ``attributes`` and ``age`` (seconds since the entity last reported).
    """

    def __init__(self, values: dict, now: datetime):
        self.values, self.now = values, now

    def _get(self, entity):
        value = self.values.get(entity, _MISSING)
        if value is _MISSING:
            return None
        if not isinstance(value, dict):
            value = {"state": value}
        reported = self.now - timedelta(seconds=value.get("age", 0))
        return SimpleNamespace(
            state=str(value["state"]),
            attributes=value.get("attributes", {}),
            last_reported=reported,
            last_updated=reported,
        )

    def __call__(self, entity):
        state = self._get(entity)
        return "unknown" if state is None else state.state

    def __getitem__(self, entity):
        return self._get(entity)

    def attribute(self, entity, name):
        state = self._get(entity)
        return None if state is None else state.attributes.get(name)


def render(template: str, states: dict | None = None, now: datetime | None = None, **variables):
    """Render like Home Assistant: strict about undefined names, native result."""
    now = now or datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc)
    lookup = States(states or {}, now)
    environment = SandboxedEnvironment(undefined=StrictUndefined)
    environment.filters.update(float=_float, as_datetime=_as_datetime)
    environment.globals.update(
        states=lookup,
        state_attr=lookup.attribute,
        is_number=is_number,
        as_datetime=_as_datetime,
        as_local=lambda value: value,
        is_state=lambda entity, expected: lookup(entity) == expected,
        now=lambda: now,
        utcnow=lambda: now.astimezone(timezone.utc),
        timedelta=timedelta,
    )
    text = environment.from_string(template).render(**variables).strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def previous(state="unknown", **attributes):
    """The ``this`` variable of a trigger-based template entity."""
    return SimpleNamespace(state=str(state), attributes=attributes)


def changed(to_state, trigger_id=None):
    """The ``trigger`` variable of a state trigger."""
    return SimpleNamespace(to_state=SimpleNamespace(state=str(to_state)), id=trigger_id)
