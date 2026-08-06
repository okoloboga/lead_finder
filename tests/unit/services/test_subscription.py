"""Unit tests for subscription business rules."""

from __future__ import annotations

import datetime

import pytest

from bot.services import subscription as sub


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
def test_normalize_subscription_keeps_active_paid_user(
    monkeypatch, user_factory
) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
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
def test_trial_expires_one_week_after_registration(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(created_at=now)

    assert sub.trial_expires_at(user) == now + datetime.timedelta(days=7)


@pytest.mark.unit
def test_trial_expires_now_for_unflushed_user(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory()
    user.created_at = None

    assert sub.is_trial_active(user) is True


@pytest.mark.unit
def test_trial_active_on_last_day(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(created_at=now - datetime.timedelta(days=6, hours=23))

    assert sub.is_trial_active(user) is True
    assert sub.has_full_access(user) is True


@pytest.mark.unit
def test_trial_over_after_seven_days(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(created_at=now - datetime.timedelta(days=7))

    assert sub.is_trial_active(user) is False
    assert sub.has_full_access(user) is False


@pytest.mark.unit
def test_paid_user_keeps_access_after_trial(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(
        subscription_type="paid",
        subscription_expires_at=now + datetime.timedelta(days=30),
        created_at=now - datetime.timedelta(days=90),
    )

    assert sub.is_trial_active(user) is False
    assert sub.has_full_access(user) is True


@pytest.mark.unit
def test_trial_days_left_rounds_up(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(created_at=now - datetime.timedelta(days=4, hours=12))

    assert sub.trial_days_left(user) == 3


@pytest.mark.unit
def test_trial_days_left_zero_when_over(monkeypatch, user_factory) -> None:
    now = datetime.datetime(2026, 2, 28, 12, 0, 0)
    monkeypatch.setattr(sub, "_utc_now", lambda: now)
    user = user_factory(created_at=now - datetime.timedelta(days=10))

    assert sub.trial_days_left(user) == 0


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
