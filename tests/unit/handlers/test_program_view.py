"""Unit tests for bot.handlers.program_view."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import program_view
from bot.models.user import User
from tests.unit.handlers.helpers import FakeCallback, FakeSession, FakeUser


class _Result:
    def __init__(self, rows=None, scalar=None, scalar_or_none=None):
        self._rows = rows or []
        self._scalar = scalar
        self._scalar_or_none = scalar_or_none

    def scalars(self):
        return SimpleNamespace(
            first=lambda: self._rows[0] if self._rows else None,
            all=lambda: list(self._rows),
        )

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar_or_none

    def all(self):
        return list(self._rows)


class _Session(FakeSession):
    def __init__(self):
        super().__init__()
        self.queue: list[_Result] = []
        self.deleted: list[object] = []

    async def execute(self, query):  # noqa: ANN001
        if not self.queue:
            raise AssertionError("No queued DB result for execute()")
        return self.queue.pop(0)

    async def delete(self, obj):  # noqa: ANN001
        self.deleted.append(obj)


@pytest.mark.unit
def test_program_view_keyboards() -> None:
    kb = program_view.get_program_card_keyboard(5, leads_count=2)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert any("Посмотреть лидов" in t for t in texts)
    assert "🗑 Очистить лидов" in texts

    del_kb = program_view.get_delete_confirmation_keyboard(5)
    del_texts = [b.text for r in del_kb.inline_keyboard for b in r]
    assert "🗑 Да, удалить" in del_texts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_program_handler_not_found() -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="show_program_7")
    session = _Session()
    session.queue.append(_Result(rows=[]))

    await program_view.show_program_handler(callback, session)

    assert "Program not found" in callback.message.edits[0][0]
    assert callback.answers[-1][1] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_handler_not_owned_program() -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=None))

    await program_view.run_program_handler(callback, session)

    assert callback.answers[-1][1] is True
    assert "Program not found" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_handler_user_missing() -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=7))

    await program_view.run_program_handler(callback, session)

    assert callback.answers[-1][1] is True
    assert "Profile not found" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_handler_free_limit_block(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=7))
    session.users[1] = User(telegram_id=1, username="u", subscription_type="free")

    monkeypatch.setattr(
        program_view,
        "check_weekly_analysis_limit",
        lambda user: (False, 3),  # noqa: ARG005
    )

    await program_view.run_program_handler(callback, session)

    assert callback.answers[-1][1] is True
    assert "Next run available in 3 day(s)" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_handler_success(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=7))
    session.users[1] = User(telegram_id=1, username="u", subscription_type="free")

    monkeypatch.setattr(
        program_view,
        "check_weekly_analysis_limit",
        lambda user: (True, 0),  # noqa: ARG005
    )
    scheduled = {}

    def _fake_create_task(coro):  # noqa: ANN001
        scheduled["called"] = True
        coro.close()
        return None

    monkeypatch.setattr(program_view.asyncio, "create_task", _fake_create_task)

    await program_view.run_program_handler(callback, session)

    assert scheduled.get("called") is True
    assert "Program started" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_program_confirmed_deleted_and_already_deleted(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="confirm_delete_7")
    session = _Session()
    prog = SimpleNamespace(name="P1")
    session.queue.append(_Result(rows=[prog]))  # first run: found
    removed = []
    monkeypatch.setattr(program_view, "remove_program_job", lambda pid: removed.append(pid))

    await program_view.delete_program_confirmed(callback, session)
    assert removed == [7]
    assert "Program “P1” deleted" in callback.message.edits[0][0]

    callback2 = FakeCallback(FakeUser(id=1, language_code="en"), data="confirm_delete_7")
    session2 = _Session()
    session2.queue.append(_Result(rows=[]))  # second run: not found
    await program_view.delete_program_confirmed(callback2, session2)
    assert "already been deleted" in callback2.message.edits[0][0]
