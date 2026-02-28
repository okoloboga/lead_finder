"""Unit tests for bot.handlers.auth."""

from __future__ import annotations

import pytest

from bot.handlers import auth
from tests.unit.handlers.helpers import FakeMessage, FakeState, FakeUser


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_auth_flow_no_phone(monkeypatch) -> None:
    monkeypatch.setattr(auth.config, "TELEGRAM_PHONE", "")
    message = FakeMessage(FakeUser(id=1), text=None)
    state = FakeState()

    await auth.start_auth_flow(message, state)

    assert "TELEGRAM_PHONE" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_auth_flow_success(monkeypatch) -> None:
    monkeypatch.setattr(auth.config, "TELEGRAM_PHONE", "+10000000000")

    calls = []

    async def _start_sign_in(phone: str) -> None:
        calls.append(phone)

    monkeypatch.setattr(auth.TelegramAuthManager, "start_sign_in", _start_sign_in)
    message = FakeMessage(FakeUser(id=1))
    state = FakeState()

    await auth.start_auth_flow(message, state)

    assert calls == ["+10000000000"]
    assert state.state is not None
    assert "Отправил код подтверждения" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_auth_flow_error(monkeypatch) -> None:
    monkeypatch.setattr(auth.config, "TELEGRAM_PHONE", "+10000000000")

    async def _start_sign_in(phone: str) -> None:  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(auth.TelegramAuthManager, "start_sign_in", _start_sign_in)
    message = FakeMessage(FakeUser(id=1))
    state = FakeState()

    await auth.start_auth_flow(message, state)

    assert "Не удалось отправить код" in message.answers[0][0]
    assert state.cleared is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_code_signed_in(monkeypatch) -> None:
    async def _submit_code(code: str) -> str:  # noqa: ARG001
        return "signed_in"

    monkeypatch.setattr(auth.TelegramAuthManager, "submit_code", _submit_code)
    message = FakeMessage(FakeUser(id=1), text="12345")
    state = FakeState()

    await auth.enter_code(message, state, bot=None)

    assert state.cleared is True
    assert "Авторизация пройдена успешно" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_code_password_needed(monkeypatch) -> None:
    async def _submit_code(code: str) -> str:  # noqa: ARG001
        return "password_needed"

    monkeypatch.setattr(auth.TelegramAuthManager, "submit_code", _submit_code)
    message = FakeMessage(FakeUser(id=1), text="12345")
    state = FakeState()

    await auth.enter_code(message, state, bot=None)

    assert state.state is not None
    assert "Требуется пароль" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_code_unknown_result(monkeypatch) -> None:
    async def _submit_code(code: str) -> str:  # noqa: ARG001
        return "unknown"

    monkeypatch.setattr(auth.TelegramAuthManager, "submit_code", _submit_code)
    message = FakeMessage(FakeUser(id=1), text="12345")
    state = FakeState()

    await auth.enter_code(message, state, bot=None)

    assert state.cleared is True
    assert "неизвестная ошибка" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_password_success(monkeypatch) -> None:
    async def _submit_password(password: str) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(auth.TelegramAuthManager, "submit_password", _submit_password)
    message = FakeMessage(FakeUser(id=1), text="pass")
    state = FakeState()

    await auth.enter_password(message, state, bot=None)

    assert state.cleared is True
    assert "Пароль принят" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_password_error(monkeypatch) -> None:
    async def _submit_password(password: str) -> None:  # noqa: ARG001
        raise RuntimeError("bad password")

    monkeypatch.setattr(auth.TelegramAuthManager, "submit_password", _submit_password)
    message = FakeMessage(FakeUser(id=1), text="pass")
    state = FakeState()

    await auth.enter_password(message, state, bot=None)

    assert state.cleared is True
    assert "Ошибка при вводе пароля" in message.answers[0][0]
