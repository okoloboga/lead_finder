"""Unit tests for bot.i18n helpers."""

from __future__ import annotations

import pytest

from bot import i18n


@pytest.mark.unit
def test_get_locale_prefers_english_prefix() -> None:
    assert i18n.get_locale("en") == "en"
    assert i18n.get_locale("en-US") == "en"
    assert i18n.get_locale("EN_gb") == "en"
    assert i18n.get_locale("ru") == "ru"
    assert i18n.get_locale(None) == "ru"


@pytest.mark.unit
def test_pick_returns_locale_variant() -> None:
    assert i18n.pick("ru", "RUS", "ENG") == "RUS"
    assert i18n.pick("en", "RUS", "ENG") == "ENG"


@pytest.mark.unit
def test_t_uses_fallback_table() -> None:
    assert "LeadCore" in i18n.t("main_menu_text", "ru")
    assert "LeadCore" in i18n.t("main_menu_text", "en")
    assert i18n.t("btn_back", "en") == "◀️ Back"


@pytest.mark.unit
def test_t_prefers_fluentogram_translation(monkeypatch) -> None:
    monkeypatch.setattr(
        i18n._fluentogram,  # noqa: SLF001
        "translate",
        lambda locale, key, **kwargs: "FLUENT-TEXT",
    )

    assert i18n.t("btn_back", "ru") == "FLUENT-TEXT"


@pytest.mark.unit
def test_t_unknown_key_returns_key() -> None:
    assert i18n.t("unknown.key", "en") == "unknown.key"
