"""Small read-only configuration and local-attempt ledger; no cloud client."""

from collections.abc import Callable, Mapping
import json
import logging
import math
import os
from pathlib import Path
from typing import cast

LOG = logging.getLogger("thermowatt")
KINDS = ("password_login", "token_refresh", "discovery", "status", "command", "confirmation")


def poll_seconds(options: Mapping[str, object]) -> int:
    # Retain the numeric key for upgrades; the form labels it 'Polling interval'.
    value = options.get("poll_interval_minutes", 30)
    unit = options.get("poll_interval_unit", "minutes")
    if type(value) is not int or unit not in ("seconds", "minutes"):
        raise ValueError("poll_interval_invalid")
    seconds = value * (60 if unit == "minutes" else 1)
    if not 60 <= seconds <= 7200:
        raise ValueError("poll_interval_invalid")
    return seconds


def daily_limit(body: object) -> bool:
    """Exact confirmed error field only; no substring or unrelated-error guessing."""
    return isinstance(body, dict) and body.get("error") == "Daily request limit exceeded"


class RequestUsage:
    """Lifetime local attempts, durably counted before I/O where storage permits.

    No identifiers, response content, vendor quota or calendar-day reset. A crash
    after recording may overcount an unsent request. Storage failure degrades
    accounting only, never authorises or denies authentication/commands.
    """

    def __init__(
        self,
        path: Path,
        clock: Callable[[], float],
        writer: Callable[[Path, object], None],
    ) -> None:
        self.path = path
        self.writer = writer
        self.counts = {kind: 0 for kind in KINDS}
        self.since = clock()
        self.complete = True
        self.persistent = False
        self.cooldown_until = 0.0
        self.failures = 0
        self.last_error: str | None = None
        try:
            if path.exists():
                if path.stat().st_size > 8192:
                    raise ValueError
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or set(data) != {
                    "version",
                    "since",
                    "counts",
                    "complete",
                    "cooldown_until",
                    "failures",
                    "last_error",
                }:
                    raise ValueError
                counts = data["counts"]
                if (
                    data["version"] != 1
                    or not isinstance(counts, dict)
                    or set(counts) != set(KINDS)
                ):
                    raise ValueError
                if any(type(v) is not int or not 0 <= v < 2**63 for v in counts.values()):
                    raise ValueError
                since = data["since"]
                if type(since) not in (int, float) or not math.isfinite(since) or since < 0:
                    raise ValueError
                if type(data["complete"]) is not bool:
                    raise ValueError
                self.counts = cast(dict[str, int], counts)
                self.since = since
                self.complete = data["complete"]
                deadline = data["cooldown_until"]
                failures = data["failures"]
                if (
                    type(deadline) not in (int, float)
                    or not math.isfinite(deadline)
                    or deadline < 0
                ):
                    raise ValueError
                if type(failures) is not int or not 0 <= failures <= 5:
                    raise ValueError
                self.cooldown_until = deadline
                self.failures = failures
                error = data["last_error"]
                if error is not None and not isinstance(error, str):
                    raise ValueError
                self.last_error = error
                os.chmod(path, 0o600)
        except (OSError, ValueError, TypeError):
            self.complete = False
            LOG.warning("Request accounting: code=usage_history_invalid.")
        self.save()

    def save(self) -> None:
        try:
            self.writer(
                self.path,
                {
                    "version": 1,
                    "since": self.since,
                    "counts": self.counts,
                    "complete": self.complete,
                    "cooldown_until": self.cooldown_until,
                    "failures": self.failures,
                    "last_error": self.last_error,
                },
            )
            self.persistent = True
        except OSError:
            if self.persistent or self.complete:
                LOG.warning("Request accounting: code=usage_storage_unavailable.")
            self.persistent = False
            self.complete = False

    def record(self, kind: str) -> None:
        if kind not in self.counts:
            raise ValueError("usage_category_invalid")
        self.counts[kind] += 1
        self.save()

    def cooldown(self, deadline: float, failures: int) -> None:
        self.cooldown_until = deadline
        self.failures = failures
        self.save()

    @property
    def total(self) -> int:
        return sum(self.counts.values())
