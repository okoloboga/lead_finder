"""Unit tests for bot.handlers.program_edit."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import program_edit
from tests.unit.handlers.helpers import FakeCallback, FakeMessage, FakeState, FakeUser


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return SimpleNamespace(
            first=lambda: self._rows[0] if self._rows else None,
            all=lambda: list(self._rows),
        )


class _Session:
    def __init__(self):
        self.queue: list[_Result] = []
        self.commits = 0

    async def execute(self, query):  # noqa: ANN001
        if not self.queue:
            raise AssertionError("No queued result")
        return self.queue.pop(0)

    async def commit(self):
        self.commits += 1

    def add(self, obj):  # noqa: ANN001
        return None


def _program() -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        user_id=1,
        name="Prog",
        niche_description="Niche",
        chats=[SimpleNamespace(chat_username="chat1")],
        min_score=5,
        max_leads_per_run=20,
        enrich=False,
        auto_collect_enabled=True,
        owner_chat_id=1,
        schedule_time="09:00",
    )


@pytest.mark.unit
def test_program_edit_keyboards() -> None:
    kb = program_edit.get_edit_menu_keyboard(10)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "📝 Название" in texts
    assert "⚙️ Настройки" in texts

    back = program_edit.get_back_keyboard(10)
    back_texts = [b.text for r in back.inline_keyboard for b in r]
    assert back_texts == ["◀️ Назад"]

    settings = program_edit.get_settings_keyboard(10, 5, 20, False, True)
    settings_texts = [b.text for r in settings.inline_keyboard for b in r]
    assert "5✅" in settings_texts
    assert "20✅" in settings_texts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_edit_menu_not_found() -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_program_10")
    state = FakeState()
    session = _Session()
    session.queue.append(_Result(rows=[]))

    await program_edit.show_edit_menu(callback, session, state)

    assert callback.answers[-1][1] is True
    assert "Программа не найдена" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_edit_menu_success() -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_program_10")
    state = FakeState()
    session = _Session()
    session.queue.append(_Result(rows=[_program()]))

    await program_edit.show_edit_menu(callback, session, state)

    assert state.cleared is True
    assert "Редактирование: Prog" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_name_flow() -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_name_10")
    state = FakeState()
    await program_edit.edit_name_start(callback, state)
    assert state.data["program_id"] == 10

    # empty name
    msg_empty = FakeMessage(FakeUser(id=1), text="")
    await program_edit.edit_name_save(msg_empty, state, _Session())
    assert "не может быть пустым" in msg_empty.answers[0][0]

    # valid save
    session = _Session()
    prog = _program()
    session.queue.append(_Result(rows=[prog]))
    msg = FakeMessage(FakeUser(id=1), text="NewName")
    await state.update_data(program_id=10)
    await program_edit.edit_name_save(msg, state, session)
    assert session.commits == 1
    assert prog.name == "NewName"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_niche_flow() -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_niche_10")
    state = FakeState()
    await program_edit.edit_niche_start(callback, state)
    assert state.data["program_id"] == 10

    msg_empty = FakeMessage(FakeUser(id=1), text="")
    await program_edit.edit_niche_save(msg_empty, state, _Session())
    assert "не может быть пустым" in msg_empty.answers[0][0]

    session = _Session()
    prog = _program()
    session.queue.append(_Result(rows=[prog]))
    msg = FakeMessage(FakeUser(id=1), text="New niche")
    await state.update_data(program_id=10)
    await program_edit.edit_niche_save(msg, state, session)
    assert session.commits == 1
    assert prog.niche_description == "New niche"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_chats_not_found_and_done() -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_chats_10")
    state = FakeState()
    session = _Session()
    session.queue.append(_Result(rows=[]))
    await program_edit.edit_chats_start(callback, state, session)
    assert "Программа не найдена" in callback.answers[-1][0]

    callback_done = FakeCallback(FakeUser(id=1), data="done_chats_10")
    await program_edit.edit_chats_done(callback_done, state)
    assert state.cleared is True
    assert "Что ещё изменить?" in callback_done.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_settings_show_and_toggles(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="edit_settings_10")
    state = FakeState()
    session = _Session()
    prog = _program()
    session.queue.append(_Result(rows=[prog]))

    await program_edit.edit_settings_show(callback, session, state)
    assert state.state is not None
    assert "Настройки программы" in callback.message.edits[0][0]

    cb_score = FakeCallback(FakeUser(id=1), data="set_score_10_4")
    await state.update_data(max_leads=20, enrich=False, auto_collect=True)
    await program_edit.set_min_score(cb_score, state)
    assert state.data["min_score"] == 4

    cb_max = FakeCallback(FakeUser(id=1), data="set_max_10_50")
    await state.update_data(min_score=4, enrich=False, auto_collect=True)
    await program_edit.set_max_leads(cb_max, state)
    assert state.data["max_leads"] == 50

    cb_enrich = FakeCallback(FakeUser(id=1), data="toggle_enrich_10")
    await state.update_data(min_score=4, max_leads=20, enrich=False, auto_collect=True)
    await program_edit.toggle_enrichment(cb_enrich, state)
    assert state.data["enrich"] is True

    cb_auto = FakeCallback(FakeUser(id=1), data="toggle_autocollect_10")
    await state.update_data(min_score=4, max_leads=20, enrich=False, auto_collect=True)
    await program_edit.toggle_auto_collect(cb_auto, state)
    assert state.data["auto_collect"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_settings_not_found_and_success(monkeypatch) -> None:
    # not found
    callback_nf = FakeCallback(FakeUser(id=1), data="save_settings_10")
    state = FakeState()
    await state.update_data(min_score=3, max_leads=10, enrich=True, auto_collect=False)
    session_nf = _Session()
    session_nf.queue.append(_Result(rows=[]))
    await program_edit.save_settings(callback_nf, state, session_nf)
    assert callback_nf.answers[-1][0] == "✅ Настройки сохранены"

    # success + schedule toggle paths
    callback_ok = FakeCallback(FakeUser(id=1), data="save_settings_10")
    state_ok = FakeState()
    await state_ok.update_data(min_score=3, max_leads=10, enrich=True, auto_collect=False)
    session_ok = _Session()
    prog = _program()
    session_ok.queue.append(_Result(rows=[prog]))
    removed = []
    monkeypatch.setattr(program_edit, "remove_program_job", lambda pid: removed.append(pid))
    monkeypatch.setattr(program_edit, "schedule_program_job", lambda *a, **k: None)
    await program_edit.save_settings(callback_ok, state_ok, session_ok)

    assert session_ok.commits == 1
    assert prog.min_score == 3
    assert prog.max_leads_per_run == 10
    assert prog.enrich is True
    assert prog.auto_collect_enabled is False
    assert removed == [10]
