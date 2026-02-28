"""Unit tests for bot.ui.lead_card."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.models.lead import Lead
from bot.ui.lead_card import (
    format_lead_card,
    get_lead_card_keyboard,
    get_lead_navigation_keyboard,
)


def _flatten(markup) -> list[str]:  # noqa: ANN001
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _build_lead(status: str = "new") -> Lead:
    lead = Lead(
        user_id=1,
        program_id=10,
        telegram_username="alice",
        status=status,
        qualification_score=4,
        business_summary="Seller",
        pains_summary="• pain",
        solution_idea="Bot",
        recommended_message="Hi there",
        raw_qualification_data={
            "qualification": {"reasoning": "good fit"},
            "identification": {"business_scale": "small"},
            "product_idea": {
                "pain_addressed": "manual work",
                "estimated_value": "10h/week",
            },
        },
        raw_user_profile_data={
            "source_chat_username": "@chat",
            "messages_in_chat": 2,
            "messages_with_metadata": [
                {
                    "text": "<b>Need help</b>",
                    "freshness": "hot",
                    "age_display": "1 дн. назад",
                    "link": "t.me/chat/1",
                }
            ],
        },
        raw_llm_input="prompt",
    )
    lead.program = SimpleNamespace(name="Program X")
    return lead


@pytest.mark.unit
def test_get_lead_card_keyboard_new_status() -> None:
    kb = get_lead_card_keyboard(lead_id=7, status="new")
    texts = _flatten(kb)
    assert "✅ Написал" in texts
    assert "❌ Пропустить" in texts


@pytest.mark.unit
def test_get_lead_card_keyboard_skipped_status() -> None:
    kb = get_lead_card_keyboard(lead_id=7, status="skipped")
    texts = _flatten(kb)
    assert texts == ["↩️ Вернуть"]


@pytest.mark.unit
def test_get_lead_navigation_keyboard_middle_page() -> None:
    kb = get_lead_navigation_keyboard(
        program_id=10,
        current_page=1,
        total_pages=3,
        lead_id=77,
        lead_status="new",
    )
    texts = _flatten(kb)
    assert "◀️ Назад" in texts
    assert "Вперёд ▶️" in texts
    assert "2/3" in texts
    assert "◀️ К программе" in texts


@pytest.mark.unit
def test_format_lead_card_contains_expected_sections_and_escapes_html() -> None:
    lead = _build_lead(status="contacted")

    card = format_lead_card(lead, index=1, total=3)

    assert "🎯 Лид #1 из 3" in card
    assert "Программа: Program X" in card
    assert "✅ Написал" in card
    assert "&lt;b&gt;Need help&lt;/b&gt;" in card
    assert "https://t.me/chat/1" in card
    assert "✅ Решает: manual work" in card
    assert "💰 Ценность: 10h/week" in card
