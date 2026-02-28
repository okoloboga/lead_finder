"""Unit tests for bot.handlers.start."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import start
from bot.models.user import User
from tests.unit.handlers.helpers import (
    FakeCallback,
    FakeMessage,
    FakeSession,
    FakeState,
    FakeUser,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_channel_member_true_and_false() -> None:
    class _Bot:
        async def get_chat_member(self, channel: str, user_id: int):  # noqa: ARG002
            return SimpleNamespace(status="member")

    class _BotLeft:
        async def get_chat_member(self, channel: str, user_id: int):  # noqa: ARG002
            return SimpleNamespace(status="left")

    assert await start._is_channel_member(_Bot(), 1) is True
    assert await start._is_channel_member(_BotLeft(), 1) is False


@pytest.mark.unit
def test_render_settings_text_localized() -> None:
    ru = start._render_settings_text(None, "ru")
    en = start._render_settings_text(None, "en")
    assert "Не заполнено" in ru
    assert "Not set" in en


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_handler_access_closed(monkeypatch) -> None:
    async def _not_member(bot, user_id):  # noqa: ANN001, ARG001
        return False

    monkeypatch.setattr(start, "_is_channel_member", _not_member)
    message = FakeMessage(FakeUser(id=1, language_code="en"))

    await start.start_handler(message, bot=None, session=FakeSession(), state=FakeState())

    assert len(message.answers) == 1
    assert "Access Restricted" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_handler_member_calls_continue(monkeypatch) -> None:
    async def _member(bot, user_id):  # noqa: ANN001, ARG001
        return True

    called = {"ok": False}

    async def _continue(user, send_fn, session, state):  # noqa: ANN001
        called["ok"] = True

    monkeypatch.setattr(start, "_is_channel_member", _member)
    monkeypatch.setattr(start, "_continue_onboarding", _continue)
    message = FakeMessage(FakeUser(id=2, language_code="ru"))

    await start.start_handler(message, bot=None, session=FakeSession(), state=FakeState())

    assert called["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_channel_subscription_not_member(monkeypatch) -> None:
    async def _not_member(bot, user_id):  # noqa: ANN001, ARG001
        return False

    monkeypatch.setattr(start, "_is_channel_member", _not_member)
    callback = FakeCallback(FakeUser(id=3, language_code="en"))

    await start.check_channel_subscription_handler(
        callback, bot=None, session=FakeSession(), state=FakeState()
    )

    assert callback.answers
    assert callback.answers[-1][1] is True
    assert "not subscribed" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_channel_subscription_member(monkeypatch) -> None:
    async def _member(bot, user_id):  # noqa: ANN001, ARG001
        return True

    called = {"ok": False}

    async def _continue(user, send_fn, session, state):  # noqa: ANN001
        called["ok"] = True

    monkeypatch.setattr(start, "_is_channel_member", _member)
    monkeypatch.setattr(start, "_continue_onboarding", _continue)
    callback = FakeCallback(FakeUser(id=4, language_code="ru"))

    await start.check_channel_subscription_handler(
        callback, bot=None, session=FakeSession(), state=FakeState()
    )

    assert callback.message.deleted is True
    assert called["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_main_menu_callback_handler(monkeypatch) -> None:
    async def _touch_user(user, session):  # noqa: ANN001
        return User(telegram_id=user.id, username=user.username)

    monkeypatch.setattr(start, "_touch_user", _touch_user)
    callback = FakeCallback(FakeUser(id=5, language_code="en"))
    state = FakeState()

    await start.main_menu_callback_handler(callback, session=FakeSession(), state=state)

    assert state.cleared is True
    assert "LeadCore" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_services_description_short_text() -> None:
    message = FakeMessage(FakeUser(id=6, language_code="en"), text="short")
    state = FakeState()

    await start.save_services_description_handler(
        message, state=state, session=FakeSession()
    )

    assert "too short" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_services_description_onboarding(monkeypatch) -> None:
    async def _touch_user(user, session):  # noqa: ANN001
        return User(
            telegram_id=user.id,
            username=user.username,
            services_description=None,
        )

    monkeypatch.setattr(start, "_touch_user", _touch_user)
    message = FakeMessage(
        FakeUser(id=7, language_code="en"),
        text="I build bots for SMBs",
    )
    state = FakeState()
    await state.update_data(profile_flow="onboarding")
    session = FakeSession()

    await start.save_services_description_handler(message, state=state, session=session)

    assert state.cleared is True
    assert any("saved" in text for text, _ in message.answers)
    assert session.commits == 1
