"""Unit tests for modules.pain_collector helper functions."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot.models.pain import Pain
from bot.models.program import Program  # noqa: F401
from modules import pain_collector as pc
from modules.pain_collector import (
    _normalize_category,
    _normalize_intensity,
    _normalize_text,
    _parse_llm_json,
    _parse_message_date,
    _render_prompt,
)


@pytest.mark.unit
def test_parse_llm_json_handles_plain_and_fenced() -> None:
    plain = '{"pains":[{"text":"a"}]}'
    fenced = "```json\n{\"pains\":[{\"text\":\"a\"}]}\n```"
    assert _parse_llm_json(plain)["pains"][0]["text"] == "a"
    assert _parse_llm_json(fenced)["pains"][0]["text"] == "a"


@pytest.mark.unit
def test_normalize_text_category_intensity() -> None:
    assert _normalize_text("  x  ") == "x"
    assert _normalize_text("", default="d") == "d"
    assert _normalize_category("sales") == "sales"
    assert _normalize_category("bad") == "other"
    assert _normalize_intensity("HIGH") == "high"
    assert _normalize_intensity("bad") == "low"


@pytest.mark.unit
def test_parse_message_date_converts_aware_to_utc_naive() -> None:
    dt = _parse_message_date("2026-02-28T12:00:00+03:00")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None
    assert dt == datetime(2026, 2, 28, 9, 0, 0)
    assert _parse_message_date("bad-date") is None
    assert _parse_message_date(None) is None


@pytest.mark.unit
def test_render_prompt_replaces_known_placeholders() -> None:
    template = "chat={chat_name};messages={messages};json={\"k\":\"v\"}"
    rendered = _render_prompt(
        template,
        chat_name="chat-1",
        messages="[1,2]",
    )
    assert "chat=chat-1" in rendered
    assert "messages=[1,2]" in rendered
    assert "json={\"k\":\"v\"}" in rendered


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(first=lambda: self._rows[0] if self._rows else None)


class _Session:
    def __init__(self) -> None:
        self.pains: list[Pain] = []
        self.added: list[Pain] = []
        self.no_autoflush = nullcontext()
        self.flush_calls = 0
        self.commit_calls = 0

    def add(self, pain: Pain) -> None:
        self.added.append(pain)

    async def execute(self, query):  # noqa: ANN001
        rows = self.pains + self.added
        source_message_id = None
        source_chat = None
        original_quote = None
        user_id = None
        for criterion in getattr(query, "_where_criteria", []):
            left = getattr(criterion, "left", None)
            right = getattr(criterion, "right", None)
            name = getattr(left, "name", None)
            value = getattr(right, "value", None)
            if name == "source_message_id":
                source_message_id = value
            elif name == "source_chat":
                source_chat = value
            elif name == "original_quote":
                original_quote = value
            elif name == "user_id":
                user_id = value
        found = [
            p
            for p in rows
            if p.source_message_id == source_message_id
            and p.source_chat == source_chat
            and p.original_quote == original_quote
            and p.user_id == user_id
        ]
        return _Result(found)

    async def flush(self) -> None:
        self.flush_calls += 1
        for idx, pain in enumerate(self.added, start=1):
            if getattr(pain, "id", None) is None:
                pain.id = idx

    async def commit(self) -> None:
        self.commit_calls += 1
        self.pains.extend(self.added)
        self.added.clear()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_collect_pains_disabled_and_empty(monkeypatch) -> None:
    session = _Session()
    monkeypatch.setattr(pc.config, "PAIN_COLLECTION_ENABLED", False)
    disabled = await pc.collect_pains([], 1, 1, "chat", session)
    assert disabled == 0

    monkeypatch.setattr(pc.config, "PAIN_COLLECTION_ENABLED", True)
    empty = await pc.collect_pains([], 1, 1, "chat", session)
    assert empty == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_collect_pains_happy_path_with_batching(monkeypatch) -> None:
    session = _Session()
    messages = [
        {
            "message_id": 1,
            "text": "m1",
            "date": "2026-02-28T10:00:00+00:00",
            "chat_username": "chat_a",
            "link": "t.me/a/1",
        },
        {
            "message_id": 2,
            "text": "m2",
            "date": "2026-02-28T11:00:00+00:00",
            "chat_username": "chat_a",
            "link": "t.me/a/2",
        },
        {
            "message_id": 3,
            "text": "m3",
            "date": None,
            "chat_username": "chat_a",
            "link": "t.me/a/3",
        },
    ]

    monkeypatch.setattr(pc.config, "PAIN_COLLECTION_ENABLED", True)
    monkeypatch.setattr(pc.config, "PAIN_BATCH_SIZE", 2)
    monkeypatch.setattr(pc, "_load_prompt", lambda: "prompt")
    sleep_calls: list[float] = []

    async def _sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(pc.asyncio, "sleep", _sleep)
    monkeypatch.setattr(pc.random, "uniform", lambda a, b: 0.0)  # noqa: ARG005

    batches = [
        [
            {
                "source_message_index": 0,
                "text": " pain-1 ",
                "original_quote": " quote-1 ",
                "category": "sales",
                "intensity": "HIGH",
                "business_type": " Retail ",
            },
            {"source_message_index": 99, "text": "x", "original_quote": "q"},
        ],
        [
            {
                "source_message_index": 0,
                "text": "pain-3",
                "original_quote": "quote-3",
                "category": "bad",
                "intensity": "bad",
            }
        ],
    ]

    async def _extract(batch, chat_name, prompt_template):  # noqa: ANN001
        return batches.pop(0)

    monkeypatch.setattr(pc, "_extract_pains_batch", _extract)

    inserted = await pc.collect_pains(messages, 10, 99, "chat_a", session)

    assert inserted == 2
    assert session.commit_calls == 1
    assert session.flush_calls == 2
    assert len(sleep_calls) == 1
    assert len(session.pains) == 2
    first = session.pains[0]
    assert first.text == "pain-1"
    assert first.original_quote == "quote-1"
    assert first.category == "sales"
    assert first.intensity == "high"
    assert first.business_type == "Retail"
