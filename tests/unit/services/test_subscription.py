"""Unit tests for subscription business rules."""

from __future__ import annotations

import datetime

import pytest

from bot.services import subscription as sub


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeSession:
    def __init__(self, count: int) -> None:
        self.count = count
        self.execute_calls = 0

    async def execute(self, _query):  # noqa: ANN001
        self.execute_calls += 1
        return _ScalarResult(self.count)


@pytest.mark.unit
def test_normalize_subscription_expires_paid_user(user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    user = user_factory(
        subscription_type="paid",
        subscription_expires_at=now - datetime.timedelta(minutes=1),
    )

    sub.normalize_subscription(user)

    assert user.subscription_type == "free"
    assert user.subscription_expires_at is None


@pytest.mark.unit
def test_normalize_subscription_keeps_active_paid_user(user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    user = user_factory(
        subscription_type="paid",
        subscription_expires_at=now + datetime.timedelta(days=1),
    )

    sub.normalize_subscription(user)

    assert user.subscription_type == "paid"
    assert user.subscription_expires_at is not None


@pytest.mark.unit
def test_is_paid_user_false_after_expiry(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(
        subscription_type="paid",
        subscription_expires_at=now - datetime.timedelta(seconds=1),
    )

    assert sub.is_paid_user(user) is False
    assert user.subscription_type == "free"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_program_limit_paid_user_bypasses_db(user_factory) -> None:
    user = user_factory(subscription_type="paid")
    session = _FakeSession(count=100)

    allowed, reason = await sub.check_program_limit(session, user)

    assert allowed is True
    assert reason is None
    assert session.execute_calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_program_limit_free_user_under_limit(user_factory) -> None:
    user = user_factory(subscription_type="free")
    session = _FakeSession(count=0)

    allowed, reason = await sub.check_program_limit(session, user)

    assert allowed is True
    assert reason is None
    assert session.execute_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_program_limit_free_user_hits_limit(user_factory) -> None:
    user = user_factory(subscription_type="free")
    session = _FakeSession(count=1)

    allowed, reason = await sub.check_program_limit(session, user)

    assert allowed is False
    assert reason is not None
    assert "1 программа" in reason


@pytest.mark.unit
def test_check_weekly_analysis_limit_paid_user(user_factory) -> None:
    user = user_factory(subscription_type="paid")

    allowed, days_left = sub.check_weekly_analysis_limit(user)

    assert allowed is True
    assert days_left == 0


@pytest.mark.unit
def test_check_weekly_analysis_limit_no_history(user_factory) -> None:
    user = user_factory(subscription_type="free", last_analysis_at=None)

    allowed, days_left = sub.check_weekly_analysis_limit(user)

    assert allowed is True
    assert days_left == 0


@pytest.mark.unit
def test_check_weekly_analysis_limit_blocks_within_7_days(
    monkeypatch, user_factory
) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(
        subscription_type="free",
        last_analysis_at=now - datetime.timedelta(days=2, hours=1),
    )

    allowed, days_left = sub.check_weekly_analysis_limit(user)

    assert allowed is False
    assert days_left == 5


@pytest.mark.unit
def test_check_weekly_analysis_limit_allows_after_7_days(
    monkeypatch, user_factory
) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(
        subscription_type="free",
        last_analysis_at=now - datetime.timedelta(days=7),
    )

    allowed, days_left = sub.check_weekly_analysis_limit(user)

    assert allowed is True
    assert days_left == 0


@pytest.mark.unit
def test_mark_analysis_started_sets_current_time(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(last_analysis_at=None)

    sub.mark_analysis_started(user)

    assert user.last_analysis_at == now


@pytest.mark.unit
def test_add_months_caps_day_to_28() -> None:
    base = datetime.datetime(2026, 1, 31, 12, 0, 0)

    result = sub.add_months(base, 1)

    assert result.year == 2026
    assert result.month == 2
    assert result.day == 28


@pytest.mark.unit
def test_activate_paid_subscription_sets_expiry_from_now(
    monkeypatch, user_factory
) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(subscription_type="free", subscription_expires_at=None)

    expiry = sub.activate_paid_subscription(user, "1m")

    assert user.subscription_type == "paid"
    assert expiry == datetime.datetime(2026, 3, 28, 12, 0, 0)
    assert user.subscription_expires_at == expiry


@pytest.mark.unit
def test_activate_paid_subscription_extends_from_current_expiry(
    monkeypatch, user_factory
) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    current_expiry = datetime.datetime(2026, 6, 15, 9, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(
        subscription_type="paid",
        subscription_expires_at=current_expiry,
    )

    expiry = sub.activate_paid_subscription(user, "3m")

    assert expiry == datetime.datetime(2026, 9, 15, 9, 0, 0)
    assert user.subscription_expires_at == expiry
