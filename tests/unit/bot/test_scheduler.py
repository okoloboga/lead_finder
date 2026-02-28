"""Unit tests for bot.scheduler."""

from __future__ import annotations

import pytest

from bot import scheduler as sched_mod


@pytest.mark.unit
def test_schedule_program_job_calls_add_job(monkeypatch) -> None:
    calls = {}

    class _Sched:
        def add_job(self, func, **kwargs):  # noqa: ANN001
            calls["func"] = func
            calls["kwargs"] = kwargs

    async def _fake_run_program_job(program_id: int, chat_id: int):  # noqa: ARG001
        return None

    monkeypatch.setattr(sched_mod, "scheduler", _Sched())
    # monkeypatch import in function body
    monkeypatch.setattr(
        "bot.services.program_runner.run_program_job",
        _fake_run_program_job,
    )

    sched_mod.schedule_program_job(program_id=5, chat_id=10, schedule_time="09:30")

    assert calls["kwargs"]["trigger"] == "cron"
    assert calls["kwargs"]["hour"] == 9
    assert calls["kwargs"]["minute"] == 30
    assert calls["kwargs"]["id"] == "program_5"
    assert calls["kwargs"]["kwargs"] == {"program_id": 5, "chat_id": 10}


@pytest.mark.unit
def test_remove_program_job_when_exists(monkeypatch) -> None:
    removed = []

    class _Sched:
        def get_job(self, job_id: str):
            return object() if job_id == "program_3" else None

        def remove_job(self, job_id: str):
            removed.append(job_id)

    monkeypatch.setattr(sched_mod, "scheduler", _Sched())
    sched_mod.remove_program_job(3)
    sched_mod.remove_program_job(99)

    assert removed == ["program_3"]
