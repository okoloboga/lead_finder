"""Unit tests for bot.main startup wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import main as bot_main


class _BeginCtx:
    def __init__(self):
        self.run_sync_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def run_sync(self, fn):  # noqa: ANN001
        self.run_sync_calls += 1


class _SessionCtx:
    def __init__(self, result_rows):
        self.result_rows = result_rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    async def execute(self, query):  # noqa: ANN001
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: self.result_rows)
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_tables_runs_metadata_create(monkeypatch) -> None:
    begin = _BeginCtx()
    monkeypatch.setattr(bot_main, "engine", SimpleNamespace(begin=lambda: begin))

    await bot_main.create_tables()

    assert begin.run_sync_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_scheduled_jobs_restores_only_missing(monkeypatch) -> None:
    programs = [
        SimpleNamespace(id=1, name="P1", owner_chat_id=10, schedule_time="09:00"),
        SimpleNamespace(id=2, name="P2", owner_chat_id=20, schedule_time="10:00"),
    ]
    monkeypatch.setattr(bot_main, "async_session", lambda: _SessionCtx(programs))

    restored = []
    monkeypatch.setattr(
        bot_main,
        "schedule_program_job",
        lambda pid, chat_id, t: restored.append((pid, chat_id, t)),
    )
    monkeypatch.setattr(
        bot_main,
        "scheduler",
        SimpleNamespace(
            get_job=lambda jid: object() if jid == "program_2" else None
        ),
    )

    await bot_main.restore_scheduled_jobs()

    assert restored == [(1, 10, "09:00")]


class _FakeDispatcher:
    def __init__(self, **kwargs):  # noqa: ANN003
        self.kwargs = kwargs
        self.middlewares = []
        self.routers = []
        self.shutdown_registered = []
        self.polled = False
        self.update = SimpleNamespace(
            middleware=lambda mw: self.middlewares.append(mw)
        )
        self.shutdown = SimpleNamespace(
            register=lambda fn: self.shutdown_registered.append(fn)
        )

    def include_router(self, router):  # noqa: ANN001
        self.routers.append(router)

    async def start_polling(self, bot):  # noqa: ANN001
        self.polled = True


class _FakeBot:
    def __init__(self, token: str, parse_mode: str):  # noqa: ARG002
        self.token = token
        self.webhook_deleted = False

    async def delete_webhook(self, drop_pending_updates: bool):  # noqa: ARG002
        self.webhook_deleted = True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_main_wires_dispatcher_and_starts_polling(monkeypatch) -> None:
    calls = {"create_tables": 0, "restore": 0, "scheduler_start": 0}

    async def _create_tables():
        calls["create_tables"] += 1

    async def _restore():
        calls["restore"] += 1

    monkeypatch.setattr(bot_main, "create_tables", _create_tables)
    monkeypatch.setattr(bot_main, "restore_scheduled_jobs", _restore)

    fake_dp = _FakeDispatcher()
    monkeypatch.setattr(bot_main, "Dispatcher", lambda **kwargs: fake_dp)
    monkeypatch.setattr(bot_main, "Bot", _FakeBot)

    fake_scheduler = SimpleNamespace(
        start=lambda: calls.__setitem__("scheduler_start", calls["scheduler_start"] + 1),
        shutdown=lambda: None,
    )
    monkeypatch.setattr(bot_main, "scheduler", fake_scheduler)

    await bot_main.main(bot_token="TOKEN")

    assert calls["create_tables"] == 1
    assert calls["restore"] == 1
    assert calls["scheduler_start"] == 1
    assert fake_dp.polled is True
    assert len(fake_dp.routers) >= 5
