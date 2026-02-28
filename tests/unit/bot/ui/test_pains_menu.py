"""Unit tests for bot.ui.pains_menu."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot.ui.pains_menu import (
    cluster_score,
    format_cluster_detail,
    format_draft,
    format_pains_summary,
    format_quotes_page,
    format_top_pains,
    get_cluster_keyboard,
    get_pains_menu_keyboard,
    get_quotes_keyboard,
    get_top_pains_keyboard,
)


def _texts(markup) -> list[str]:  # noqa: ANN001
    return [btn.text for row in markup.inline_keyboard for btn in row]


@pytest.mark.unit
def test_cluster_score_accounts_for_freshness_and_penalty() -> None:
    now = datetime.now(timezone.utc)
    fresh = SimpleNamespace(
        pain_count=5,
        last_seen=now - timedelta(days=1),
        avg_intensity=3,
        post_generated=False,
    )
    stale_posted = SimpleNamespace(
        pain_count=5,
        last_seen=now - timedelta(days=10),
        avg_intensity=3,
        post_generated=True,
    )

    assert cluster_score(fresh) > cluster_score(stale_posted)


@pytest.mark.unit
def test_format_pains_summary_contains_stats() -> None:
    text = format_pains_summary(10, 3, 2)
    assert "Собрано болей: 10" in text
    assert "Кластеров: 3" in text
    assert "Постов сгенерировано: 2" in text


@pytest.mark.unit
def test_format_top_pains_empty_state() -> None:
    text = format_top_pains([])
    assert "Пока нет данных" in text


@pytest.mark.unit
def test_format_top_pains_with_clusters() -> None:
    cluster = SimpleNamespace(
        name="Проблема A",
        pain_count=4,
        trend="growing",
        category="operations",
        avg_intensity=2.6,
        last_seen=datetime.now(timezone.utc) - timedelta(days=1),
    )
    text = format_top_pains([cluster], page=0, total_pages=1, total_clusters=1)
    assert "Проблема A" in text
    assert "📈 Растёт" in text
    assert "высокая" in text


@pytest.mark.unit
def test_format_cluster_detail_and_quotes_page() -> None:
    cluster = SimpleNamespace(
        name="Cluster A",
        trend="stable",
        avg_intensity=2.0,
        category="sales",
        pain_count=2,
        description="desc",
    )
    pains = [
        SimpleNamespace(original_quote="Quote 1", source_message_link="https://t.me/a/1"),
        SimpleNamespace(original_quote="Quote 2", source_message_link=None),
    ]
    detail = format_cluster_detail(cluster, pains)
    page = format_quotes_page(cluster, pains, page=0, page_size=1)
    assert "Cluster A" in detail
    assert "Quote 1" in detail
    assert "Страница 1/2" in page


@pytest.mark.unit
def test_format_draft_status_label() -> None:
    post = SimpleNamespace(
        post_type="single",
        status="draft",
        title="Title",
        body="Body",
    )
    text = format_draft(post, "Cluster B")
    assert "черновик" in text
    assert "Cluster B" in text


@pytest.mark.unit
def test_keyboards_have_expected_buttons() -> None:
    main = get_pains_menu_keyboard()
    assert "📊 Топ болей" in _texts(main)
    assert "🏠 Главное меню" in _texts(main)

    top = get_top_pains_keyboard(
        [SimpleNamespace(id=1, name="Name", pain_count=2)], page=0, total_pages=2
    )
    assert any("Name" in t for t in _texts(top))

    cluster = get_cluster_keyboard(3)
    assert "✍️ Создать пост" in _texts(cluster)

    quotes = get_quotes_keyboard(cluster_id=3, page=1, total_pages=3)
    assert "◀️ К кластеру" in _texts(quotes)
