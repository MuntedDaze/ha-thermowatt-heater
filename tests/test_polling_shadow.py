"""Advisory scheduler bounds and absence of any transport effects."""

import importlib

import pytest

from test_shadow_model import m
from test_simple_policy import MIN, MON, at
from test_integration_0_9_0 import Rig, hobart

p = importlib.import_module(f"{m.__package__}.polling")
START = at(MON, 12)


def context(minute, **kw):
    return p.PollContext(
        START + minute * MIN, kw.pop("status_at", START), kw.pop("heating", False), **kw
    )


def test_disabled_flag_never_proposes_a_read():
    shadow = p.PollingShadow()
    for i in range(1440):
        assert not shadow.observe(context(i))
    assert shadow.would_polls == 0 and shadow.summary()["extra_cloud_requests"] == 0


@pytest.mark.parametrize("heating,cap", [(True, 60), (False, 90), (None, 15)])
def test_caps_and_duplicate_callbacks_cannot_delay_or_duplicate(heating, cap):
    s = p.PollingShadow(True)
    for i in range(cap):
        assert not s.observe(context(i, heating=heating))
        assert not s.observe(context(i, heating=heating))
    assert s.observe(context(cap, heating=heating))
    assert not s.observe(context(cap, heating=heating))
    assert s.would_polls == 1


def test_actual_fixed_polls_do_not_reset_the_counterfactual_clock():
    s = p.PollingShadow(True)
    requests = []
    for i in range(181):
        if s.observe(context(i, status_at=START + (i // 30) * 30 * MIN)):
            requests.append(i)
    assert requests == [90, 180]
    assert s.actual_statuses == 7


def test_imminent_decision_and_command_confirmation_reuse():
    s = p.PollingShadow(True)
    assert not s.observe(context(0, decision_at=START + 30 * MIN))
    assert s.observe(context(20, decision_at=START + 30 * MIN))
    assert not s.observe(context(21, command_at=START + 20 * MIN, status_at=START + 21 * MIN))
    assert s.reused_confirmations == 1
    assert not s.observe(context(80, heating=True))
    assert s.observe(context(81, heating=True))


def test_cloud_backoff_and_confirmation_remain_authoritative():
    for flag in ({"cloud_ready": False}, {"confirming": True}):
        s = p.PollingShadow(True)
        s.observe(context(0))
        for i in range(90, 95):
            assert not s.observe(context(i, **flag))
        assert s.blocked == 1 and s.would_polls == 0
        assert s.observe(context(95))


def test_future_status_not_accepted_and_unsafe_bounds_rejected():
    s = p.PollingShadow(True)
    s.observe(context(0, status_at=START + MIN))
    assert s.actual_seen is None
    for heating, stable in [(61, 90), (60, 91), (0, 90), (60, 0)]:
        with pytest.raises(ValueError):
            p.PollingShadow(True, heating, stable)


def test_comparison_does_not_add_cloud_requests_or_commands(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 11))
    rig.run(hobart(MON, 14))
    base = rig.bridge.usage.total
    # Compare an identical synthetic day with the explicit flag enabled.
    second = tmp_path / "second"
    second.mkdir()
    other = Rig(second, monkeypatch, hobart(MON, 11))
    other.entry.options["adaptive_polling_shadow"] = True
    other.executor.configure(other.entry.options)
    other.run(hobart(MON, 14))
    count = other.bridge.usage.total
    assert count == base and not other.posts and not rig.posts
    assert other.executor.poll_shadow.would_polls > 0
