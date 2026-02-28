"""Unit tests for bot.handlers.program_list."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import program_list
from tests.unit.handlers.helpers import FakeCallback, FakeUser


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, query):  # noqa: ANN001
        return _Result(self.rows)


@pytest.mark.unit
def test_get_my_programs_keyboard_empty() -> None:
    kb = program_list.get_my_programs_keyboard([], language_code="en")
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "➕ Create Program" in texts
    assert "◀️ Back" in texts


@pytest.mark.unit
def test_get_my_programs_keyboard_with_programs() -> None:
    prog = SimpleNamespace(id=1, name="P1")
    kb = program_list.get_my_programs_keyboard([prog], language_code="ru")
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "📁 P1" in texts
    assert "➕ Создать ещё" in texts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_my_programs_handler_no_programs() -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"))
    session = _Session(rows=[])

    await program_list.my_programs_handler(callback, session)

    text = callback.message.edits[0][0]
    assert "My Programs" in text
    assert "don't have any programs" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_my_programs_handler_with_programs() -> None:
    programs = [
        SimpleNamespace(
            id=1,
            name="Alpha",
            chats=[1, 2],
            min_score=5,
            auto_collect_enabled=True,
            schedule_time="09:00",
        )
    ]
    callback = FakeCallback(FakeUser(id=1, language_code="ru"))
    session = _Session(rows=programs)

    await program_list.my_programs_handler(callback, session)

    text = callback.message.edits[0][0]
    assert "📋 Мои программы" in text
    assert "Alpha" in text
    assert "скор ≥5" in text
