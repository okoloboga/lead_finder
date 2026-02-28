"""Unit tests for bot.handlers.lead_viewer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import lead_viewer
from tests.unit.handlers.helpers import FakeCallback, FakeSession, FakeUser


class _LeadResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(
            all=lambda: list(self._rows),
            first=lambda: self._rows[0] if self._rows else None,
        )


class _LeadSession(FakeSession):
    def __init__(self, leads):
        super().__init__()
        self._leads = leads

    async def execute(self, query):  # noqa: ANN001
        return _LeadResult(self._leads)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_lead_page_no_leads() -> None:
    callback = FakeCallback(FakeUser(id=1), data="view_program_leads_1")
    session = _LeadSession(leads=[])

    await lead_viewer.show_lead_page(callback, session, program_id=1, page=0, edit=False)

    assert callback.answers[-1][1] is True
    assert "лиды еще не найдены" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_lead_page_invalid_page() -> None:
    callback = FakeCallback(FakeUser(id=1))
    session = _LeadSession(leads=[SimpleNamespace(id=1, status="new")])

    await lead_viewer.show_lead_page(callback, session, program_id=1, page=5, edit=False)

    assert callback.answers[-1][1] is True
    assert "Неверная страница" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_show_lead_page_edit_and_answer_paths(monkeypatch) -> None:
    monkeypatch.setattr(lead_viewer, "format_lead_card", lambda lead, i, t: "CARD")  # noqa: ARG005
    monkeypatch.setattr(
        lead_viewer,
        "get_lead_navigation_keyboard",
        lambda *args, **kwargs: "KB",  # noqa: ARG005
    )
    lead = SimpleNamespace(id=1, status="new")
    session = _LeadSession(leads=[lead])

    callback_a = FakeCallback(FakeUser(id=1))
    await lead_viewer.show_lead_page(callback_a, session, program_id=1, page=0, edit=False)
    assert callback_a.message.answers[0][0] == "CARD"

    callback_b = FakeCallback(FakeUser(id=1))
    await lead_viewer.show_lead_page(callback_b, session, program_id=1, page=0, edit=True)
    assert callback_b.message.edits[0][0] == "CARD"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_view_program_leads_and_pagination_handlers(monkeypatch) -> None:
    calls = []

    async def _show(callback, session, program_id, page, edit):  # noqa: ANN001
        calls.append((program_id, page, edit))

    monkeypatch.setattr(lead_viewer, "show_lead_page", _show)
    callback_view = FakeCallback(FakeUser(id=1), data="view_program_leads_10")
    callback_page = FakeCallback(FakeUser(id=1), data="lead_page_10_2")

    await lead_viewer.view_program_leads_handler(callback_view, session=None)
    await lead_viewer.lead_page_navigation_handler(callback_page, session=None)

    assert calls == [(10, 0, False), (10, 2, True)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_status_handlers(monkeypatch) -> None:
    lead = SimpleNamespace(id=7, status="new")
    session = FakeSession()

    async def _get_lead(sess, lead_id, user_id):  # noqa: ANN001, ARG001
        return lead

    monkeypatch.setattr(lead_viewer, "_get_lead", _get_lead)
    monkeypatch.setattr(lead_viewer, "get_lead_card_keyboard", lambda *a, **k: "KB")  # noqa: ARG005

    cb_contact = FakeCallback(FakeUser(id=1), data="lead_contacted_7")
    await lead_viewer.mark_lead_contacted(cb_contact, session)
    assert lead.status == "contacted"
    assert session.commits == 1

    cb_skip = FakeCallback(FakeUser(id=1), data="lead_skipped_7")
    await lead_viewer.mark_lead_skipped(cb_skip, session)
    assert lead.status == "skipped"
    assert session.commits == 2

    cb_restore = FakeCallback(FakeUser(id=1), data="lead_restore_7")
    await lead_viewer.restore_lead(cb_restore, session)
    assert lead.status == "new"
    assert session.commits == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_noop_handler() -> None:
    callback = FakeCallback(FakeUser(id=1), data="noop")
    await lead_viewer.noop_handler(callback)
    assert callback.answers[-1] == ("", False)
