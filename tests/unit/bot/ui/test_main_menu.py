"""Unit tests for bot.ui.main_menu."""

from __future__ import annotations

import pytest

from bot.ui.main_menu import get_main_menu_keyboard, get_main_menu_text


def _flatten_texts(markup) -> list[str]:  # noqa: ANN001
    return [btn.text for row in markup.inline_keyboard for btn in row]


@pytest.mark.unit
def test_main_menu_text_localized() -> None:
    assert "LeadCore" in get_main_menu_text("ru")
    assert "LeadCore" in get_main_menu_text("en")
    assert "Telegram chats" in get_main_menu_text("en")


@pytest.mark.unit
def test_main_menu_keyboard_ru() -> None:
    kb = get_main_menu_keyboard("ru")
    texts = _flatten_texts(kb)
    assert texts == ["📋 Мои программы", "🔥 Боли и контент", "💎 Подписка"]


@pytest.mark.unit
def test_main_menu_keyboard_en() -> None:
    kb = get_main_menu_keyboard("en")
    texts = _flatten_texts(kb)
    assert texts == ["📋 My Programs", "🔥 Pains & Content", "💎 Subscription"]
