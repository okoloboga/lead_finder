"""Unit tests for modules.pain_collector helper functions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
