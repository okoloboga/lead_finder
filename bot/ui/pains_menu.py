"""Keyboards and text formatters for the Pains & Content UI."""
from datetime import datetime, timezone, timedelta

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.pain import Pain, PainCluster, GeneratedPost

_INTENSITY_LABEL = {"low": "низкая", "medium": "средняя", "high": "высокая"}
_TREND_LABEL = {"growing": "📈 Растёт", "stable": "➡️ Стабильно", "declining": "📉 Снижается"}
_INTENSITY_MAP = {"low": 1, "medium": 2, "high": 3}


def cluster_score(cluster: PainCluster) -> float:
    """Compute ranking score for a cluster per the spec formula."""
    now = datetime.now(timezone.utc)

    def _days_since(dt: datetime | None) -> int:
        if not dt:
            return 999
        aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        return (now - aware).days

    days = _days_since(cluster.last_seen)
    freshness_bonus = 3 if days < 3 else (1 if days < 7 else 0)
    intensity_bonus = (cluster.avg_intensity or 1) * 2
    already_posted_penalty = 10 if cluster.post_generated else 0

    return cluster.pain_count * 2 + freshness_bonus + intensity_bonus - already_posted_penalty


# --- Keyboards ---

def get_pains_menu_keyboard() -> InlineKeyboardMarkup:
    """Main keyboard for the Pains & Content screen."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Топ болей", callback_data="top_pains")
    builder.button(text="✍️ Сгенерировать пост", callback_data="generate_post_menu")
    builder.button(text="📝 Мои черновики", callback_data="my_drafts")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_top_pains_keyboard(clusters: list[PainCluster]) -> InlineKeyboardMarkup:
    """Keyboard for the top-pains list: one button per cluster + back."""
    builder = InlineKeyboardBuilder()
    for c in clusters:
        builder.button(
            text=f"#{c.id} {c.name[:40]} (×{c.pain_count})",
            callback_data=f"cluster_detail_{c.id}",
        )
    builder.button(text="◀️ Назад", callback_data="pains_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_cluster_keyboard(cluster_id: int) -> InlineKeyboardMarkup:
    """Keyboard for a single cluster detail view."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Создать пост", callback_data=f"generate_post_{cluster_id}")
    builder.button(text="💬 Все цитаты", callback_data=f"cluster_quotes_{cluster_id}_0")
    builder.button(text="◀️ К топу болей", callback_data="top_pains")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1, 1, 2)
    return builder.as_markup()


def get_post_type_keyboard(cluster_id: int) -> InlineKeyboardMarkup:
    """Keyboard for choosing post type."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎭 Сценарий", callback_data=f"gen_scenario_{cluster_id}")
    builder.button(text="💡 Инсайт", callback_data=f"gen_insight_{cluster_id}")
    builder.button(text="📈 Разбор тренда", callback_data=f"gen_breakdown_{cluster_id}")
    builder.button(text="◀️ Назад", callback_data=f"cluster_detail_{cluster_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_draft_keyboard(post_id: int, cluster_id: int) -> InlineKeyboardMarkup:
    """Keyboard for a generated draft post."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовано", callback_data=f"mark_published_{post_id}")
    builder.button(text="🔄 Перегенерировать", callback_data=f"regen_post_{cluster_id}")
    builder.button(text="❌ Удалить", callback_data=f"delete_draft_{post_id}")
    builder.button(text="◀️ К черновикам", callback_data="my_drafts")
    builder.adjust(1)
    return builder.as_markup()


def get_drafts_list_keyboard(
    posts: list[GeneratedPost], page: int = 0, page_size: int = 5
) -> InlineKeyboardMarkup:
    """Paginated keyboard for the drafts list."""
    builder = InlineKeyboardBuilder()
    start = page * page_size
    page_posts = posts[start : start + page_size]

    for p in page_posts:
        label = f"#{p.id} {p.title[:35]}…" if len(p.title) > 35 else f"#{p.id} {p.title}"
        builder.button(text=label, callback_data=f"view_draft_{p.id}")

    nav_row = []
    if page > 0:
        nav_row.append(("◀️", f"my_drafts_{page - 1}"))
    if start + page_size < len(posts):
        nav_row.append(("▶️", f"my_drafts_{page + 1}"))

    for text, cb in nav_row:
        builder.button(text=text, callback_data=cb)

    builder.button(text="◀️ Назад", callback_data="pains_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_quotes_keyboard(
    cluster_id: int, page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """Pagination keyboard for cluster quotes view."""
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(("◀️", f"cluster_quotes_{cluster_id}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(("▶️", f"cluster_quotes_{cluster_id}_{page + 1}"))
    for text, cb in nav:
        builder.button(text=text, callback_data=cb)
    builder.button(text="◀️ К кластеру", callback_data=f"cluster_detail_{cluster_id}")
    builder.adjust(len(nav) if nav else 1, 1)
    return builder.as_markup()


# --- Text formatters ---

def format_pains_summary(
    total_pains: int, total_clusters: int, total_posts: int
) -> str:
    """Format the main Pains & Content screen text."""
    return (
        "🔥 Боли и контент\n\n"
        f"Собрано болей: {total_pains}\n"
        f"Кластеров: {total_clusters}\n"
        f"Постов сгенерировано: {total_posts}\n"
    )


def format_top_pains(clusters: list[PainCluster]) -> str:
    """Format top-5 clusters list."""
    if not clusters:
        return "📊 Топ болей\n\nПока нет данных. Запустите программу, чтобы собрать боли."

    lines = ["📊 Топ болей\n"]
    for i, c in enumerate(clusters, 1):
        trend = _TREND_LABEL.get(c.trend, "➡️ Стабильно")
        intensity = _INTENSITY_LABEL.get(
            _intensity_label_from_avg(c.avg_intensity), "medium"
        )
        freshness = "🔥 " if _is_fresh(c.last_seen, days=3) else ""
        lines.append(
            f"{i}. {freshness}{c.name} (×{c.pain_count})\n"
            f"   {trend} · {c.category} · {intensity}"
        )
    return "\n\n".join(lines)


def format_cluster_detail(cluster: PainCluster, sample_pains: list[Pain]) -> str:
    """Format cluster detail view with sample quotes."""
    trend = _TREND_LABEL.get(cluster.trend, "➡️ Стабильно")
    intensity_avg = _intensity_label_from_avg(cluster.avg_intensity)
    intensity_label = _INTENSITY_LABEL.get(intensity_avg, "medium")

    lines = [
        f"📌 {cluster.name}\n",
        f"Категория: {cluster.category}",
        f"Упоминаний: {cluster.pain_count}",
        f"Интенсивность: {intensity_label}",
        f"Тренд: {trend}",
        f"\n{cluster.description}",
    ]

    if sample_pains:
        lines.append("\n💬 Примеры цитат:")
        for p in sample_pains[:3]:
            quote = p.original_quote[:150]
            link = f" [→]({p.source_message_link})" if p.source_message_link else ""
            lines.append(f"• «{quote}»{link}")

    return "\n".join(lines)


def format_quotes_page(
    cluster: PainCluster, pains: list[Pain], page: int, page_size: int = 5
) -> str:
    """Format a page of quotes for a cluster."""
    start = page * page_size
    page_pains = pains[start : start + page_size]
    total_pages = (len(pains) + page_size - 1) // page_size

    lines = [f"💬 Цитаты: {cluster.name}\nСтраница {page + 1}/{total_pages}\n"]
    for i, p in enumerate(page_pains, start + 1):
        link = f" [→]({p.source_message_link})" if p.source_message_link else ""
        lines.append(f"{i}. «{p.original_quote[:200]}»{link}")

    return "\n\n".join(lines)


def format_draft(post: GeneratedPost, cluster_name: str) -> str:
    """Format a generated draft post for display."""
    status_label = {
        "draft": "черновик",
        "edited": "отредактирован",
        "published": "опубликован",
        "rejected": "отклонён",
    }.get(post.status, post.status)

    return (
        f"✍️ Черновик поста\n\n"
        f"Кластер: {cluster_name}\n"
        f"Тип: {post.post_type} · Статус: {status_label}\n\n"
        f"<b>{post.title}</b>\n\n"
        f"{post.body}"
    )


# --- Helpers ---

def _intensity_label_from_avg(avg: float) -> str:
    if avg >= 2.5:
        return "high"
    if avg >= 1.5:
        return "medium"
    return "low"


def _is_fresh(dt: datetime | None, days: int = 3) -> bool:
    if not dt:
        return False
    now = datetime.now(timezone.utc)
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return (now - aware).days < days
