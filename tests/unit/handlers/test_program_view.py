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
async def test_run_program_handler_trial_over_block(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=7))
    session.users[1] = User(telegram_id=1, username="u", subscription_type="free")

    monkeypatch.setattr(
        program_view,
        "has_full_access",
        lambda user: False,  # noqa: ARG005
    )

    await program_view.run_program_handler(callback, session)

    assert callback.answers[-1][1] is True
    assert "free trial week is over" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_handler_success(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="run_program_7")
    session = _Session()
    session.queue.append(_Result(scalar_or_none=7))
    session.users[1] = User(telegram_id=1, username="u", subscription_type="free")

    monkeypatch.setattr(
        program_view,
        "has_full_access",
        lambda user: True,  # noqa: ARG005
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_program_handler_success() -> None:
    callback = FakeCallback(FakeUser(id=1), data="show_program_9")
    session = _Session()
    program = SimpleNamespace(
        id=9,
        user_id=1,
        name="Prog",
        niche_description="Niche",
        chats=[SimpleNamespace(chat_username="chat1")],
        auto_collect_enabled=True,
        schedule_time="09:00",
        min_score=5,
        max_leads_per_run=20,
        enrich=False,
    )
    session.queue.extend(
        [
            _Result(rows=[program]),
            _Result(scalar=2),
            _Result(rows=[(1, 9, "u1"), (2, 9, "u2")]),
        ]
    )

    await program_view.show_program_handler(callback, session)

    text = callback.message.edits[-1][0]
    assert "📁 Prog" in text
    assert "Всего найдено: 2 лидов" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_program_confirmation_found_and_missing() -> None:
    cb_missing = FakeCallback(FakeUser(id=1), data="delete_program_7")
    session_missing = _Session()
    session_missing.queue.append(_Result(rows=[]))

    await program_view.delete_program_confirmation(cb_missing, session_missing)
    assert cb_missing.answers[-1] == ("Программа уже удалена.", True)

    cb_found = FakeCallback(FakeUser(id=1), data="delete_program_7")
    session_found = _Session()
    session_found.queue.append(_Result(rows=[SimpleNamespace(name="ToDelete")]))

    await program_view.delete_program_confirmation(cb_found, session_found)
    assert "Точно удалить" in cb_found.message.edits[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_leads_confirmation_paths() -> None:
    cb_not_found = FakeCallback(FakeUser(id=1), data="clear_leads_5")
    session_not_found = _Session()
    session_not_found.queue.append(_Result(rows=[]))
    await program_view.clear_leads_confirmation(cb_not_found, session_not_found)
    assert cb_not_found.answers[-1] == ("Программа не найдена.", True)

    cb_empty = FakeCallback(FakeUser(id=1), data="clear_leads_5")
    session_empty = _Session()
    session_empty.queue.extend(
        [
            _Result(rows=[SimpleNamespace(id=5, name="P")]),
            _Result(scalar=0),
        ]
    )
    await program_view.clear_leads_confirmation(cb_empty, session_empty)
    assert cb_empty.answers[-1] == ("Нет лидов для удаления.", True)

    cb_ok = FakeCallback(FakeUser(id=1), data="clear_leads_5")
    session_ok = _Session()
    session_ok.queue.extend(
        [
            _Result(rows=[SimpleNamespace(id=5, name="P")]),
            _Result(scalar=3),
        ]
    )
    await program_view.clear_leads_confirmation(cb_ok, session_ok)
    assert "Найдено лидов: 3" in cb_ok.message.edits[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_leads_confirmed_paths(monkeypatch) -> None:
    cb_missing = FakeCallback(FakeUser(id=1), data="confirm_clear_leads_5")
    session_missing = _Session()
    session_missing.queue.append(_Result(rows=[]))
    await program_view.clear_leads_confirmed(cb_missing, session_missing)
    assert cb_missing.answers[-1] == ("Программа не найдена.", True)

    called = {"show": 0}

    async def _show(cb, sess):  # noqa: ANN001
        called["show"] += 1

    monkeypatch.setattr(program_view, "show_program_handler", _show)

    cb_ok = FakeCallback(FakeUser(id=1), data="confirm_clear_leads_5")
    session_ok = _Session()
    session_ok.queue.extend(
        [
            _Result(rows=[SimpleNamespace(id=5, name="P")]),
            _Result(scalar=4),
            _Result(rows=[]),
        ]
    )
    await program_view.clear_leads_confirmed(cb_ok, session_ok)

    assert session_ok.commits == 1
    assert called["show"] == 1
    assert cb_ok.answers[-1] == ("✅ Удалено лидов: 4", True)
