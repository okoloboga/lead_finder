"""Unit tests for bot.handlers.admin_panel."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from bot.handlers import admin_panel
from bot.models.user import User
from tests.unit.handlers.helpers import FakeCallback, FakeMessage, FakeState, FakeUser


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(
            first=lambda: self._rows[0] if self._rows else None,
            all=lambda: list(self._rows),
        )


class _Session:
    def __init__(self):
        self.queue: list[_Result] = []
        self.users: dict[int, User] = {}
        self.commits = 0

    async def execute(self, query):  # noqa: ANN001
        if not self.queue:
            raise AssertionError("No queued execute result")
        return self.queue.pop(0)

    async def get(self, model, key):  # noqa: ANN001
        return self.users.get(key)

    async def commit(self):
        self.commits += 1


@pytest.mark.unit
def test_admin_keyboards_and_admin_check(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel.config, "ADMIN_TELEGRAM_IDS", [1, 2])
    assert admin_panel._is_admin(1) is True
    assert admin_panel._is_admin(99) is False

    menu = admin_panel._admin_menu_keyboard()
    texts = [b.text for r in menu.inline_keyboard for b in r]
    assert "🔄 Обновить" in texts

    card = admin_panel._admin_user_card_keyboard(42)
    ctexts = [b.text for r in card.inline_keyboard for b in r]
    assert "➕ 1 мес" in ctexts
    assert "📋 Программы пользователя" in ctexts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_render_admin_dashboard() -> None:
    session = _Session()
    session.queue.extend(
        [
            _Result(scalar=10),  # users
            _Result(scalar=3),   # paid
            _Result(scalar=7),   # programs
            _Result(scalar=99),  # leads
            _Result(scalar=11),  # clusters
        ]
    )
    text = await admin_panel._render_admin_dashboard(session)
    assert "Пользователи: 10" in text
    assert "С подпиской: 3" in text
    assert "Программы: 7" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_panel_command_access_paths(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel, "_is_admin", lambda uid: uid == 1)
    state = FakeState()
    denied = FakeMessage(FakeUser(id=2), text="/admin_panel")
    await admin_panel.admin_panel_command(denied, _Session(), state)
    assert "Доступ запрещен" in denied.answers[0][0]

    allowed = FakeMessage(FakeUser(id=1), text="/admin_panel")
    session = _Session()
    session.queue.extend([_Result(scalar=1), _Result(scalar=0), _Result(scalar=1), _Result(scalar=0), _Result(scalar=0)])
    await admin_panel.admin_panel_command(allowed, session, state)
    assert "Админка" in allowed.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_panel_callback_denied(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel, "_is_admin", lambda uid: False)
    cb = FakeCallback(FakeUser(id=5), data="admin_panel")
    await admin_panel.admin_panel_callback(cb, _Session(), FakeState())
    assert cb.answers[-1][1] is True
    assert "Доступ запрещен" in cb.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_find_user_and_input_paths(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel, "_is_admin", lambda uid: True)
    cb = FakeCallback(FakeUser(id=1), data="admin_find_user")
    state = FakeState()
    await admin_panel.admin_find_user(cb, state)
    assert state.state is not None
    assert "Введите @username" in cb.message.edits[0][0]

    # empty query
    msg_empty = FakeMessage(FakeUser(id=1), text="")
    await admin_panel.admin_find_user_input(msg_empty, _Session(), state)
    assert "Пустой запрос" in msg_empty.answers[0][0]

    # not found by id
    msg_nf = FakeMessage(FakeUser(id=1), text="123")
    session_nf = _Session()
    await admin_panel.admin_find_user_input(msg_nf, session_nf, state)
    assert "Пользователь не найден" in msg_nf.answers[0][0]

    # found by id
    user = User(
        telegram_id=123,
        username="u123",
        subscription_type="free",
        created_at=datetime.datetime(2026, 1, 1),
        last_active_at=datetime.datetime(2026, 1, 1),
    )
    msg_ok = FakeMessage(FakeUser(id=1), text="123")
    session_ok = _Session()
    session_ok.users[123] = user
    session_ok.queue.extend([_Result(scalar=2), _Result(scalar=5)])
    await admin_panel.admin_find_user_input(msg_ok, session_ok, state)
    assert "@u123" in msg_ok.answers[0][0]
    assert "Программ: 2" in msg_ok.answers[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_grant_subscription_paths(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel, "_is_admin", lambda uid: True)
    cb_bad = FakeCallback(FakeUser(id=1), data="admin_grant_bad")
    await admin_panel.admin_grant_subscription(cb_bad, _Session())
    assert cb_bad.answers[-1][1] is True

    cb_bad_id = FakeCallback(FakeUser(id=1), data="admin_grant_1m_badid")
    await admin_panel.admin_grant_subscription(cb_bad_id, _Session())
    assert "Некорректный user_id" in cb_bad_id.answers[-1][0]

    cb_nf = FakeCallback(FakeUser(id=1), data="admin_grant_1m_999")
    await admin_panel.admin_grant_subscription(cb_nf, _Session())
    assert "Пользователь не найден" in cb_nf.answers[-1][0]

    user = User(telegram_id=7, username="u7", subscription_type="free")
    cb_ok = FakeCallback(FakeUser(id=1), data="admin_grant_1m_7")
    session_ok = _Session()
    session_ok.users[7] = user
    monkeypatch.setattr(
        admin_panel,
        "activate_paid_subscription",
        lambda u, p: datetime.datetime(2026, 12, 31),  # noqa: ARG005
    )
    await admin_panel.admin_grant_subscription(cb_ok, session_ok)
    assert "Подписка продлена" in cb_ok.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_user_programs_paths(monkeypatch) -> None:
    monkeypatch.setattr(admin_panel, "_is_admin", lambda uid: True)
    cb_bad = FakeCallback(FakeUser(id=1), data="admin_user_programs_bad")
    await admin_panel.admin_user_programs(cb_bad, _Session())
    assert "Некорректный user_id" in cb_bad.answers[-1][0]

    cb_none = FakeCallback(FakeUser(id=1), data="admin_user_programs_2")
    session_none = _Session()
    session_none.queue.append(_Result(rows=[]))
    await admin_panel.admin_user_programs(cb_none, session_none)
    assert "нет программ" in cb_none.answers[-1][0]

    cb_ok = FakeCallback(FakeUser(id=1), data="admin_user_programs_2")
    session_ok = _Session()
    session_ok.queue.append(
        _Result(
            rows=[
                SimpleNamespace(id=1, name="P1", min_score=5, auto_collect_enabled=True),
                SimpleNamespace(id=2, name="P2", min_score=6, auto_collect_enabled=False),
            ]
        )
    )
    await admin_panel.admin_user_programs(cb_ok, session_ok)
    assert "Программы пользователя 2" in cb_ok.message.edits[0][0]
