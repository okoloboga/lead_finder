"""Shared pytest fixtures and test helpers."""

from __future__ import annotations

import datetime

import pytest

from bot.models.user import User


@pytest.fixture
def user_factory():
    """Build user model instances for unit tests."""

    def _build(
        *,
        telegram_id: int = 1,
        username: str | None = "tester",
        services_description: str | None = None,
        subscription_type: str = "free",
        subscription_expires_at: datetime.datetime | None = None,
        last_analysis_at: datetime.datetime | None = None,
        created_at: datetime.datetime | None = None,
    ) -> User:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        return User(
            telegram_id=telegram_id,
            username=username,
            services_description=services_description,
            subscription_type=subscription_type,
            subscription_expires_at=subscription_expires_at,
            last_analysis_at=last_analysis_at,
            created_at=created_at or now,
            last_active_at=now,
        )

    return _build
