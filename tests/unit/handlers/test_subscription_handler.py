"""Unit tests for bot.handlers.subscription."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from bot.handlers import subscription as sub_h
from bot.models.user import User
from tests.unit.handlers.helpers import FakeCallback, FakeMessage, FakeSession, FakeUser


@pytest.mark.unit
def test_render_subscription_text_free_and_paid() -> None:
    free_user = User(telegram_id=1, username="u1", subscription_type="free")
    paid_user = User(
        telegram_id=2,
        username="u2",
        subscription_type="paid",
        subscription_expires_at=datetime.datetime(2026, 12, 31, 0, 0, 0),
    )

    free_text = sub_h._render_subscription_text(free_user)
    paid_text = sub_h._render_subscription_text(paid_user)

    assert "🆓 Free" in free_text
    assert "💚 Paid" in paid_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscription_menu_handler_user_not_found() -> None:
    callback = FakeCallback(FakeUser(id=11, language_code="en"))
    session = FakeSession(users={})

    await sub_h.subscription_menu_handler(callback, session=session)

    assert callback.answers
    assert callback.answers[-1][1] is True
    assert "Profile not found" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscription_menu_handler_success() -> None:
    user = User(telegram_id=12, username="u", subscription_type="free")
    callback = FakeCallback(FakeUser(id=12, language_code="ru"))
    session = FakeSession(users={12: user})

    await sub_h.subscription_menu_handler(callback, session=session)

    assert callback.message.edits
    assert "💎 Подписка" in callback.message.edits[0][0]
    assert session.commits == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_buy_subscription_handler_invalid_period() -> None:
    user = User(telegram_id=13, username="u", subscription_type="free")
    callback = FakeCallback(FakeUser(id=13, language_code="en"), data="buy_sub_bad")
    session = FakeSession(users={13: user})

    await sub_h.buy_subscription_handler(callback, session=session)

    assert callback.answers[-1][1] is True
    assert "Invalid subscription period" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_buy_subscription_handler_success_invoice() -> None:
    user = User(telegram_id=14, username="u", subscription_type="free")
    callback = FakeCallback(FakeUser(id=14, language_code="en"), data="buy_sub_1m")
    session = FakeSession(users={14: user})

    await sub_h.buy_subscription_handler(callback, session=session)

    assert callback.message.invoice_calls
    invoice = callback.message.invoice_calls[0]
    assert invoice["currency"] == "XTR"
    assert "LeadCore" in invoice["title"]
    assert callback.answers[-1][0] == "Invoice sent."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_payment_handler_bad_payload() -> None:
    message = FakeMessage(FakeUser(id=15, language_code="ru"))
    message.successful_payment = SimpleNamespace(invoice_payload="bad")
    session = FakeSession(users={})

    await sub_h.successful_payment_handler(message, session=session)

    assert "payload не распознан" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_payment_handler_success(monkeypatch) -> None:
    user = User(telegram_id=16, username="u", subscription_type="free")
    message = FakeMessage(FakeUser(id=16, language_code="en"))
    message.successful_payment = SimpleNamespace(
        invoice_payload="subscription:16:1m"
    )
    session = FakeSession(users={16: user})

    def _activate(u: User, period_key: str) -> datetime.datetime:
        u.subscription_type = "paid"
        dt = datetime.datetime(2026, 12, 31, 0, 0, 0)
        u.subscription_expires_at = dt
        return dt

    monkeypatch.setattr(sub_h, "activate_paid_subscription", _activate)

    await sub_h.successful_payment_handler(message, session=session)

    assert session.commits == 1
    assert any("Subscription activated" in text for text, _ in message.answers)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscription_support_handler() -> None:
    callback = FakeCallback(FakeUser(id=17), data="subscription_support")

    await sub_h.subscription_support_handler(callback)

    assert callback.answers[-1][1] is True
    assert "@devcore_dev" in callback.answers[-1][0]
