"""Unit tests for bot.handlers.program_create FSM steps."""

from __future__ import annotations

import pytest

from bot.handlers import program_create
from bot.states import ProgramCreate
from tests.unit.handlers.helpers import FakeCallback, FakeMessage, FakeState, FakeUser


@pytest.mark.unit
def test_get_step_keyboard_contains_back_and_cancel() -> None:
    kb = program_create.get_step_keyboard("name")
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "◀️ Back" in texts
    assert "❌ Cancel" in texts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_program_start_sets_state_and_text() -> None:
    callback = FakeCallback(FakeUser(id=1))
    state = FakeState()

    await program_create.create_program_start(callback, state)

    assert state.state == ProgramCreate.enter_name
    assert "Шаг 1 из 4" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_name_rejects_too_long() -> None:
    message = FakeMessage(FakeUser(id=2), text="a" * 101)
    state = FakeState()

    await program_create.enter_name(message, state)

    assert "слишком длинное" in message.answers[0][0]
    assert state.state is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_name_moves_to_niche_step() -> None:
    message = FakeMessage(FakeUser(id=2), text="My Program")
    state = FakeState()

    await program_create.enter_name(message, state)

    assert state.state == ProgramCreate.enter_niche_description
    assert state.data["name"] == "My Program"
    assert "Шаг 2 из 4" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_niche_description_moves_to_chat_step() -> None:
    message = FakeMessage(FakeUser(id=3), text="some niche")
    state = FakeState()
    await state.update_data(name="Prog")
    await state.set_state(ProgramCreate.enter_niche_description)

    await program_create.enter_niche_description(message, state)

    assert state.state == ProgramCreate.enter_chats
    assert state.data["niche_description"] == "some niche"
    assert "Шаг 3 из 4" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_chats_rejects_invalid_input() -> None:
    message = FakeMessage(FakeUser(id=4), text="not a chat")
    state = FakeState()
    await state.update_data(name="Prog")
    await state.set_state(ProgramCreate.enter_chats)

    await program_create.enter_chats(message, state)

    assert "Не нашёл валидных" in message.answers[0][0]
    assert state.state == ProgramCreate.enter_chats


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enter_chats_accepts_valid_and_moves_to_confirm() -> None:
    message = FakeMessage(FakeUser(id=4), text="@chat_one\nt.me/chat_two")
    state = FakeState()
    await state.update_data(name="Prog")
    await state.set_state(ProgramCreate.enter_chats)

    await program_create.enter_chats(message, state)

    assert state.state == ProgramCreate.confirm_settings
    assert state.data["chats"] == ["chat_one", "chat_two"]
    assert "Шаг 4 из 4" in message.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_creation_clears_state() -> None:
    callback = FakeCallback(FakeUser(id=5, language_code="en"))
    state = FakeState()
    await state.set_state(ProgramCreate.enter_name)

    await program_create.cancel_creation(callback, state)

    assert state.cleared is True
    assert "LeadCore" in callback.message.edits[0][0]
    assert "cancelled" in callback.answers[0][0]
