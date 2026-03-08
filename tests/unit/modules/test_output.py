"""Unit tests for modules.output helpers."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest

from modules import output


@pytest.mark.unit
def test_make_json_serializable_converts_nested_datetimes() -> None:
    obj = {
        "dt": datetime.datetime(2026, 2, 28, 12, 0, 0),
        "nested": [
            {"at": datetime.datetime(2026, 2, 27, 1, 2, 3)},
            "ok",
        ],
    }

    result = output._make_json_serializable(obj)

    assert result["dt"] == "2026-02-28T12:00:00"
    assert result["nested"][0]["at"] == "2026-02-27T01:02:03"


@pytest.mark.unit
def test_append_to_jsonl_writes_line(tmp_path: Path) -> None:
    out_file = tmp_path / "leads.jsonl"
    lead = {"id": 1, "created_at": datetime.datetime(2026, 2, 28, 12, 0, 0)}

    output.append_to_jsonl(lead, str(out_file))

    raw = out_file.read_text(encoding="utf-8").strip()
    row = json.loads(raw)
    assert row["id"] == 1
    assert row["created_at"] == "2026-02-28T12:00:00"


@pytest.mark.unit
def test_format_messages_with_links_includes_open_link_and_emoji() -> None:
    messages = [
        {
            "freshness": "hot",
            "age_display": "2 дня назад",
            "text": "A" * 200,
            "link": "t.me/chat/1",
            "chat_username": "chat",
        },
        {
            "freshness": "warm",
            "age_display": "5 дней назад",
            "text": "short",
            "chat_username": "chat",
        },
    ]

    block = output._format_messages_with_links(messages)

    assert "🔥" in block
    assert "https://t.me/chat/1" in block
    assert "..." in block


@pytest.mark.unit
def test_format_lead_summary_with_indicators() -> None:
    lead = {
        "contact": {"telegram_username": "@user"},
        "qualification_result": {"qualification": {"score": 4}},
        "has_fresh_message": True,
        "messages_with_links": [{"text": "x"}],
    }

    summary = output.format_lead_summary(lead)

    assert "@user" in summary
    assert "⭐4" in summary
    assert "🔥" in summary
    assert "💬" in summary


@pytest.mark.unit
def test_initialize_markdown_file_creates_header(tmp_path: Path) -> None:
    md = tmp_path / "report.md"

    output.initialize_markdown_file(str(md), "niche")

    text = md.read_text(encoding="utf-8")
    assert "# 🎯 LeadCore Report" in text
    assert "**Источник:** niche" in text


@pytest.mark.unit
def test_get_timestamped_filename_format() -> None:
    name = output.get_timestamped_filename("my_niche", "md")
    assert re.match(r"^leads_my_niche_\d{8}_\d{6}\.md$", name)


@pytest.mark.unit
def test_format_lead_as_markdown_full_and_fallback_paths() -> None:
    lead = {
        "contact": {
            "telegram_username": "@alice",
            "telegram_channel": "@alice_channel",
        },
        "qualification_result": {
            "qualification": {"score": 5},
            "identification": {
                "business_type": "Agency",
                "business_scale": "SMB",
            },
            "identified_pains": ["No pipeline"],
            "product_idea": {
                "idea": "CRM Bot",
                "pain_addressed": "No pipeline",
                "estimated_value": "10h/week",
            },
            "outreach": {"message": "Hi\nLet's talk"},
            "freshness_summary": {"can_reply_in_chat": True},
        },
        "enrichment_data": {"channel_data": {"entity_data": {"participants_count": 123}}},
        "messages_with_links": [
            {
                "freshness": "hot",
                "age_display": "1 day",
                "text": "Need automation now",
                "link": "t.me/chat/10",
                "chat_username": "chat",
            }
        ],
        "has_fresh_message": True,
    }

    md = output.format_lead_as_markdown(lead, 1)
    assert "Лид #1 🔥 — Оценка: 5/5" in md
    assert "@alice_channel (123 подписчиков)" in md
    assert "💬 Сообщения из чатов" in md
    assert "CRM Bot" in md
    assert "> Hi" in md
    assert "https://t.me/alice" in md
    assert "рекомендуется" in md

    md_fallback = output.format_lead_as_markdown({}, 2)
    assert "Лид #2 — Оценка: N/A/5" in md_fallback
    assert "Боли не выявлены." in md_fallback
    assert "Идеи не сгенерированы." in md_fallback
    assert "Сообщение не сгенерировано." in md_fallback


@pytest.mark.unit
def test_initialize_markdown_file_does_not_overwrite_existing(tmp_path: Path) -> None:
    md = tmp_path / "report.md"
    md.write_text("custom", encoding="utf-8")

    output.initialize_markdown_file(str(md), "ignored")

    assert md.read_text(encoding="utf-8") == "custom"


@pytest.mark.unit
def test_append_to_markdown_appends_block(tmp_path: Path) -> None:
    md = tmp_path / "report.md"
    lead = {"contact": {"telegram_username": "@u"}}

    output.append_to_markdown(lead, 1, str(md))

    text = md.read_text(encoding="utf-8")
    assert "Лид #1" in text
