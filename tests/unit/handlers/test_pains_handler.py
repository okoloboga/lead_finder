"""Unit tests for bot.handlers.pains_handler."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from bot.handlers import pains_handler
from tests.unit.handlers.helpers import FakeCallback, FakeSession, FakeUser


class _Result:
    def __init__(self, *, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(
            all=lambda: list(self._rows),
            first=lambda: self._rows[0] if self._rows else None,
        )


class _Session(FakeSession):
    def __init__(self):
        super().__init__()
        self.queue: list[_Result] = []
        self.deletes: list[object] = []

    async def execute(self, query):  # noqa: ANN001
        if not self.queue:
            raise AssertionError("No queued execute result")
        return self.queue.pop(0)

    async def commit(self):
        self.commits += 1


def _async_return(value):
    async def _inner(*args, **kwargs):  # noqa: ANN002,ANN003
        return value

    return _inner


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pains_menu_handler_no_programs(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1))
    session = _Session()
    monkeypatch.setattr(pains_handler, "_get_program_ids_for_user", _async_return([]))

    await pains_handler.pains_menu_handler(callback, session)

    assert "нет программ" in callback.message.edits[0][0].lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pains_menu_handler_with_stats(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1))
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1, 2])
    )
    session.queue.extend([_Result(scalar=10), _Result(scalar=3), _Result(scalar=4)])

    await pains_handler.pains_menu_handler(callback, session)

    text = callback.message.edits[0][0]
    assert "Собрано болей: 10" in text
    assert "Кластеров: 3" in text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_top_pains_handler_no_programs(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="top_pains")
    monkeypatch.setattr(pains_handler, "_get_program_ids_for_user", _async_return([]))

    await pains_handler.top_pains_handler(callback, _Session())

    assert "нет программ" in callback.message.edits[0][0].lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_top_pains_handler_empty_clusters(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="top_pains")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.append(_Result(rows=[]))

    await pains_handler.top_pains_handler(callback, session)

    assert "Пока нет данных" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_top_pains_handler_with_clusters(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="top_pains_0")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    clusters = [
        SimpleNamespace(
            id=1,
            name="C1",
            pain_count=5,
            trend="stable",
            category="operations",
            avg_intensity=2.0,
            last_seen=None,
            post_generated=False,
        )
    ]
    session.queue.append(_Result(rows=clusters))

    await pains_handler.top_pains_handler(callback, session)

    assert "C1" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_detail_not_found(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="cluster_detail_2")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.append(_Result(rows=[]))

    await pains_handler.cluster_detail_handler(callback, session)

    assert callback.answers[-1][1] is True
    assert "Кластер не найден" in callback.answers[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_detail_found(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="cluster_detail_2")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    cluster = SimpleNamespace(
        id=2,
        name="Cluster",
        trend="stable",
        avg_intensity=2.0,
        category="ops",
        pain_count=1,
        description="desc",
    )
    session.queue.extend(
        [
            _Result(rows=[cluster]),
            _Result(rows=[SimpleNamespace(original_quote="quote", source_message_link=None)]),
        ]
    )

    await pains_handler.cluster_detail_handler(callback, session)
    assert "Cluster" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_my_drafts_no_programs_and_empty(monkeypatch) -> None:
    cb_no_prog = FakeCallback(FakeUser(id=1), data="my_drafts")
    monkeypatch.setattr(pains_handler, "_get_program_ids_for_user", _async_return([]))
    await pains_handler.my_drafts_handler(cb_no_prog, _Session())
    assert "нет программ" in cb_no_prog.message.edits[0][0].lower()

    cb_empty = FakeCallback(FakeUser(id=1), data="my_drafts")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.append(_Result(rows=[]))
    await pains_handler.my_drafts_handler(cb_empty, session)
    assert "Пока нет черновиков" in cb_empty.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_draft_handler(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="delete_draft_77")
    session = _Session()
    session.queue.append(_Result(rows=[]))

    called = {"my_drafts": 0}

    async def _my_drafts(cb, sess):  # noqa: ANN001
        called["my_drafts"] += 1

    monkeypatch.setattr(pains_handler, "my_drafts_handler", _my_drafts)

    await pains_handler.delete_draft_handler(callback, session)

    assert called["my_drafts"] == 1
    assert callback.answers[-1][0].startswith("🗑")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_main_menu_shortcut() -> None:
    callback = FakeCallback(FakeUser(id=1, language_code="en"), data="main_menu")
    await pains_handler.main_menu_shortcut(callback)
    assert "LeadCore" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_quotes_handler_happy_path(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="cluster_quotes_2_0")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.extend(
        [
            _Result(rows=[SimpleNamespace(id=2, name="C2")]),
            _Result(
                rows=[
                    SimpleNamespace(
                        id=10, original_quote="Q1", source_message_link=None
                    )
                ]
            ),
        ]
    )

    await pains_handler.cluster_quotes_handler(callback, session)

    assert callback.answers[-1] == ("", False)
    assert callback.message.edits


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_quotes_handler_not_found_and_no_quotes(monkeypatch) -> None:
    cb_not_found = FakeCallback(FakeUser(id=1), data="cluster_quotes_2_0")
    session_not_found = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session_not_found.queue.append(_Result(rows=[]))
    await pains_handler.cluster_quotes_handler(cb_not_found, session_not_found)
    assert cb_not_found.answers[-1] == ("Кластер не найден.", True)

    cb_no_quotes = FakeCallback(FakeUser(id=1), data="cluster_quotes_2_0")
    session_no_quotes = _Session()
    session_no_quotes.queue.extend([_Result(rows=[SimpleNamespace(id=2)]), _Result(rows=[])])
    await pains_handler.cluster_quotes_handler(cb_no_quotes, session_no_quotes)
    assert cb_no_quotes.answers[-1] == ("Нет цитат для этого кластера.", True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_post_menu_handler_no_clusters(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="generate_post_menu")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.append(_Result(rows=[]))

    await pains_handler.generate_post_menu_handler(callback, session)

    assert "Нет кластеров для генерации поста" in callback.message.edits[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_post_choose_type_success_and_error(monkeypatch) -> None:
    cb_ok = FakeCallback(FakeUser(id=1), data="generate_post_2")
    session_ok = _Session()
    cluster = SimpleNamespace(id=2, name="Cluster")
    session_ok.queue.append(_Result(rows=[cluster]))
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    monkeypatch.setattr(pains_handler, "format_draft", lambda post, _: f"DRAFT:{post.id}")  # noqa: ARG005
    async def _gen_ok(*args, **kwargs):  # noqa: ANN002,ANN003
        return SimpleNamespace(id=99)

    monkeypatch.setitem(
        sys.modules, "modules.content_generator", SimpleNamespace(generate_post=_gen_ok)
    )

    await pains_handler.generate_post_choose_type(cb_ok, session_ok)
    assert "DRAFT:99" in cb_ok.message.edits[-1][0]

    cb_err = FakeCallback(FakeUser(id=1), data="generate_post_2")
    session_err = _Session()
    session_err.queue.append(_Result(rows=[cluster]))

    async def _boom(*args, **kwargs):  # noqa: ANN002,ANN003
        raise RuntimeError("fail")

    monkeypatch.setitem(
        sys.modules, "modules.content_generator", SimpleNamespace(generate_post=_boom)
    )
    await pains_handler.generate_post_choose_type(cb_err, session_err)
    assert "Ошибка при генерации поста" in cb_err.message.edits[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_post_execute_cluster_not_found(monkeypatch) -> None:
    callback = FakeCallback(FakeUser(id=1), data="gen_scenario_7")
    session = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session.queue.append(_Result(rows=[]))

    await pains_handler.generate_post_execute(callback, session)

    assert callback.answers[-1] == ("Кластер не найден.", True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_view_draft_handler_not_found_and_found(monkeypatch) -> None:
    cb_not_found = FakeCallback(FakeUser(id=1), data="view_draft_10")
    session_not_found = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session_not_found.queue.append(_Result(rows=[]))
    await pains_handler.view_draft_handler(cb_not_found, session_not_found)
    assert cb_not_found.answers[-1] == ("Черновик не найден.", True)

    cb_ok = FakeCallback(FakeUser(id=1), data="view_draft_10")
    session_ok = _Session()
    post = SimpleNamespace(id=10, cluster_id=2)
    cluster = SimpleNamespace(id=2, name="C2")
    session_ok.queue.extend([_Result(rows=[post]), _Result(rows=[cluster])])
    monkeypatch.setattr(pains_handler, "format_draft", lambda p, c: f"{p.id}:{c}")  # noqa: ARG005
    await pains_handler.view_draft_handler(cb_ok, session_ok)
    assert "10:C2" in cb_ok.message.edits[-1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_regen_post_handler_success_and_not_found(monkeypatch) -> None:
    cb_not_found = FakeCallback(FakeUser(id=1), data="regen_post_5")
    session_not_found = _Session()
    monkeypatch.setattr(
        pains_handler, "_get_program_ids_for_user", _async_return([1])
    )
    session_not_found.queue.append(_Result(rows=[]))
    await pains_handler.regen_post_handler(cb_not_found, session_not_found)
    assert cb_not_found.answers[-1] == ("Кластер не найден.", True)

    cb_ok = FakeCallback(FakeUser(id=1), data="regen_post_5")
    session_ok = _Session()
    cluster = SimpleNamespace(id=5, name="C5")
    session_ok.queue.append(_Result(rows=[cluster]))
    async def _regen_ok(*args, **kwargs):  # noqa: ANN002,ANN003
        return SimpleNamespace(id=11)

    monkeypatch.setitem(
        sys.modules,
        "modules.content_generator",
        SimpleNamespace(generate_post=_regen_ok),
    )
    monkeypatch.setattr(pains_handler, "format_draft", lambda p, c: f"{p.id}:{c}")  # noqa: ARG005
    await pains_handler.regen_post_handler(cb_ok, session_ok)
    assert "11:C5" in cb_ok.message.edits[-1][0]
