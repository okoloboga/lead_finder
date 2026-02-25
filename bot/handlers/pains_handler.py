"""Handlers for the Pains & Content UI section."""
import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.pain import Pain, PainCluster, GeneratedPost
from bot.ui.main_menu import get_main_menu_keyboard, MAIN_MENU_TEXT
from bot.ui.pains_menu import (
    cluster_score,
    format_pains_summary,
    format_top_pains,
    format_cluster_detail,
    format_quotes_page,
    format_draft,
    get_pains_menu_keyboard,
    get_top_pains_keyboard,
    get_cluster_keyboard,
    get_draft_keyboard,
    get_drafts_list_keyboard,
    get_quotes_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

_QUOTES_PAGE_SIZE = 5
_DRAFTS_PAGE_SIZE = 5
_CLUSTERS_PAGE_SIZE = 10
_UNIFIED_POST_TYPE = "single"


# --- Helper ---

async def _safe_edit_text(
    callback: CallbackQuery, text: str, **kwargs
) -> None:
    """Edit callback message and ignore duplicate-content edit errors."""
    if not callback.message:
        return

    try:
        await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug("Skip edit_text: message is not modified")
            return
        raise


async def _get_program_ids_for_user(
    user_id: int, session: AsyncSession
) -> list[int]:
    """Return all visible program IDs for the Pains & Content section.

    `owner_chat_id` is currently used as the auto-collection toggle marker.
    Disabled schedules set it to NULL, but programs still exist and must remain
    available in this section.
    """
    from bot.models.program import Program

    result = await session.execute(
        select(Program.id)
        .where(Program.user_id == user_id)
        .order_by(Program.id)
    )
    return [row[0] for row in result.all()]


# --- Main Pains Menu ---

@router.callback_query(F.data == "pains_menu")
async def pains_menu_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Display the Pains & Content main screen with aggregate stats."""
    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)

    if not program_ids:
        await _safe_edit_text(callback, 
            "У вас нет программ. Создайте программу, чтобы начать сбор болей.",
            reply_markup=get_main_menu_keyboard(),
        )
        await callback.answer()
        return

    total_pains = (
        await session.execute(
            select(func.count(Pain.id)).where(Pain.program_id.in_(program_ids))
        )
    ).scalar_one()

    total_clusters = (
        await session.execute(
            select(func.count(PainCluster.id)).where(
                PainCluster.program_id.in_(program_ids)
            )
        )
    ).scalar_one()

    total_posts = (
        await session.execute(
            select(func.count(GeneratedPost.id))
            .join(PainCluster, GeneratedPost.cluster_id == PainCluster.id)
            .where(PainCluster.program_id.in_(program_ids))
        )
    ).scalar_one()

    text = format_pains_summary(total_pains, total_clusters, total_posts)
    await _safe_edit_text(callback, text, reply_markup=get_pains_menu_keyboard())
    await callback.answer()


# --- Top Pains ---

@router.callback_query(F.data == "top_pains")
@router.callback_query(F.data.startswith("top_pains_"))
async def top_pains_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show all clusters ranked by score formula with pagination."""
    parts = callback.data.split("_")
    page = int(parts[2]) if len(parts) > 2 else 0

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)

    if not program_ids:
        await _safe_edit_text(callback, 
            "У вас нет программ. Создайте программу, чтобы начать сбор болей.",
            reply_markup=get_main_menu_keyboard(),
        )
        await callback.answer()
        return

    clusters_result = await session.execute(
        select(PainCluster).where(PainCluster.program_id.in_(program_ids))
    )
    clusters = clusters_result.scalars().all()
    ranked = sorted(clusters, key=cluster_score, reverse=True)

    if not ranked:
        text = format_top_pains([])
        await _safe_edit_text(callback, 
            text,
            reply_markup=get_top_pains_keyboard([], 0, 1),
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    total = len(ranked)
    total_pages = (total + _CLUSTERS_PAGE_SIZE - 1) // _CLUSTERS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start = page * _CLUSTERS_PAGE_SIZE
    page_clusters = ranked[start : start + _CLUSTERS_PAGE_SIZE]

    text = format_top_pains(
        page_clusters,
        page=page,
        total_pages=total_pages,
        total_clusters=total,
    )
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_top_pains_keyboard(
            page_clusters, page, total_pages, mode="top"
        ),
        disable_web_page_preview=True,
    )
    await callback.answer()


# --- Cluster Detail ---

@router.callback_query(F.data.startswith("cluster_detail_"))
async def cluster_detail_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show detail view of a single pain cluster with sample quotes."""
    cluster_id = int(callback.data.split("_")[-1])

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    cluster = (
        await session.execute(
            select(PainCluster).where(
                PainCluster.id == cluster_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not cluster:
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    sample_pains_result = await session.execute(
        select(Pain).where(Pain.cluster_id == cluster_id).limit(3)
    )
    sample_pains = sample_pains_result.scalars().all()

    text = format_cluster_detail(cluster, sample_pains)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_cluster_keyboard(cluster_id),
        disable_web_page_preview=True,
    )
    await callback.answer()


# --- All Quotes (paginated) ---

@router.callback_query(F.data.startswith("cluster_quotes_"))
async def cluster_quotes_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Paginated view of all quotes in a cluster."""
    parts = callback.data.split("_")
    cluster_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    cluster = (
        await session.execute(
            select(PainCluster).where(
                PainCluster.id == cluster_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not cluster:
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    pains_result = await session.execute(
        select(Pain).where(Pain.cluster_id == cluster_id)
    )
    pains = pains_result.scalars().all()

    if not pains:
        await callback.answer("Нет цитат для этого кластера.", show_alert=True)
        return

    total_pages = (len(pains) + _QUOTES_PAGE_SIZE - 1) // _QUOTES_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    text = format_quotes_page(cluster, pains, page, _QUOTES_PAGE_SIZE)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_quotes_keyboard(cluster_id, page, total_pages),
        disable_web_page_preview=True,
    )
    await callback.answer()


# --- Generate Post — Select Type ---

@router.callback_query(F.data == "generate_post_menu")
@router.callback_query(F.data.startswith("generate_pains_"))
async def generate_post_menu_handler(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show all clusters for post generation selection with pagination."""
    page = 0
    if callback.data.startswith("generate_pains_"):
        parts = callback.data.split("_")
        page = int(parts[2]) if len(parts) > 2 else 0

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)

    if not program_ids:
        await _safe_edit_text(callback, 
            "У вас нет программ. Создайте программу, чтобы начать сбор болей.",
            reply_markup=get_main_menu_keyboard(),
        )
        await callback.answer()
        return

    clusters_result = await session.execute(
        select(PainCluster).where(PainCluster.program_id.in_(program_ids))
    )
    clusters = clusters_result.scalars().all()
    ranked = sorted(clusters, key=cluster_score, reverse=True)

    if not ranked:
        await _safe_edit_text(callback, 
            "Нет кластеров для генерации поста. Запустите программу сначала.",
            reply_markup=get_pains_menu_keyboard(),
        )
        await callback.answer()
        return

    total = len(ranked)
    total_pages = (total + _CLUSTERS_PAGE_SIZE - 1) // _CLUSTERS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start = page * _CLUSTERS_PAGE_SIZE
    page_clusters = ranked[start : start + _CLUSTERS_PAGE_SIZE]

    text = (
        "✍️ Выберите кластер для генерации поста:\n\n"
        + format_top_pains(
            page_clusters,
            page=page,
            total_pages=total_pages,
            total_clusters=total,
        )
    )
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_top_pains_keyboard(
            page_clusters, page, total_pages, mode="generate"
        ),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("generate_post_"))
async def generate_post_choose_type(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Generate post for a specific cluster using unified single post type."""
    await callback.answer()
    cluster_id = int(callback.data.split("_")[-1])
    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    cluster = (
        await session.execute(
            select(PainCluster).where(
                PainCluster.id == cluster_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not cluster:
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    await _safe_edit_text(callback, "⏳ Генерирую черновик поста...")

    from modules.content_generator import generate_post

    try:
        post = await generate_post(
            cluster_id, session, post_type=_UNIFIED_POST_TYPE
        )
    except Exception as e:
        logger.error(f"Content generation failed for cluster_id={cluster_id}: {e}")
        await _safe_edit_text(callback, 
            "❌ Ошибка при генерации поста. Попробуйте позже.",
            reply_markup=get_cluster_keyboard(cluster_id),
        )
        return

    text = format_draft(post, cluster.name)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_draft_keyboard(post.id, cluster_id),
        parse_mode="HTML",
    )


# --- Generate Post — Execute ---

@router.callback_query(F.data.regexp(r"^gen_(scenario|insight|breakdown)_\d+$"))
async def generate_post_execute(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Backward-compatible handler: generate post in unified mode."""
    # Acknowledge callback immediately to avoid Telegram 30s timeout while
    # web search + LLM generation is running.
    await callback.answer()

    parts = callback.data.split("_")
    cluster_id = int(parts[2])

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    cluster = (
        await session.execute(
            select(PainCluster).where(
                PainCluster.id == cluster_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not cluster:
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    await _safe_edit_text(callback, "⏳ Генерирую черновик поста...")

    from modules.content_generator import generate_post

    try:
        post = await generate_post(
            cluster_id, session, post_type=_UNIFIED_POST_TYPE
        )
    except Exception as e:
        logger.error(f"Content generation failed for cluster_id={cluster_id}: {e}")
        await _safe_edit_text(callback, 
            "❌ Ошибка при генерации поста. Попробуйте позже.",
            reply_markup=get_cluster_keyboard(cluster_id),
        )
        return

    text = format_draft(post, cluster.name)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_draft_keyboard(post.id, cluster_id),
        parse_mode="HTML",
    )


# --- My Drafts ---

@router.callback_query(F.data.startswith("my_drafts"))
async def my_drafts_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """List all draft posts with pagination."""
    parts = callback.data.split("_")
    page = int(parts[2]) if len(parts) > 2 else 0

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    if not program_ids:
        await _safe_edit_text(callback, 
            "У вас нет программ. Создайте программу, чтобы начать сбор болей.",
            reply_markup=get_main_menu_keyboard(),
        )
        await callback.answer()
        return

    posts_result = await session.execute(
        select(GeneratedPost)
        .join(PainCluster, GeneratedPost.cluster_id == PainCluster.id)
        .where(PainCluster.program_id.in_(program_ids))
        .order_by(GeneratedPost.generated_at.desc())
    )
    posts = posts_result.scalars().all()

    if not posts:
        await _safe_edit_text(callback, 
            "📝 Черновики\n\nПока нет черновиков. Сгенерируйте первый пост!",
            reply_markup=get_pains_menu_keyboard(),
        )
        await callback.answer()
        return

    total = len(posts)
    total_pages = (total + _DRAFTS_PAGE_SIZE - 1) // _DRAFTS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    text = f"📝 Черновики ({total} шт.)\n\nВыберите черновик для просмотра:"
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_drafts_list_keyboard(posts, page, _DRAFTS_PAGE_SIZE),
    )
    await callback.answer()


# --- View Single Draft ---

@router.callback_query(F.data.startswith("view_draft_"))
async def view_draft_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show full text of a draft post."""
    post_id = int(callback.data.split("_")[-1])

    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    post = (
        await session.execute(
            select(GeneratedPost)
            .join(PainCluster, GeneratedPost.cluster_id == PainCluster.id)
            .where(
                GeneratedPost.id == post_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not post:
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    cluster = (
        await session.execute(
            select(PainCluster).where(PainCluster.id == post.cluster_id)
        )
    ).scalars().first()
    cluster_name = cluster.name if cluster else "Неизвестный кластер"

    text = format_draft(post, cluster_name)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_draft_keyboard(post.id, post.cluster_id),
        parse_mode="HTML",
    )
    await callback.answer()


# --- Draft Actions ---
@router.callback_query(F.data.startswith("regen_post_"))
async def regen_post_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Regenerate a draft post for cluster in unified mode."""
    await callback.answer()
    cluster_id = int(callback.data.split("_")[-1])
    program_ids = await _get_program_ids_for_user(callback.from_user.id, session)
    cluster = (
        await session.execute(
            select(PainCluster).where(
                PainCluster.id == cluster_id,
                PainCluster.program_id.in_(program_ids),
            )
        )
    ).scalars().first()
    if not cluster:
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    await _safe_edit_text(callback, "⏳ Перегенерирую черновик поста...")
    from modules.content_generator import generate_post

    try:
        post = await generate_post(
            cluster_id, session, post_type=_UNIFIED_POST_TYPE
        )
    except Exception as e:
        logger.error(
            f"Content regeneration failed for cluster_id={cluster_id}: {e}"
        )
        await _safe_edit_text(callback, 
            "❌ Ошибка при перегенерации поста. Попробуйте позже.",
            reply_markup=get_cluster_keyboard(cluster_id),
        )
        return

    text = format_draft(post, cluster.name)
    await _safe_edit_text(callback, 
        text,
        reply_markup=get_draft_keyboard(post.id, cluster_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("delete_draft_"))
async def delete_draft_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    """Delete a draft post."""
    post_id = int(callback.data.split("_")[-1])
    await session.execute(delete(GeneratedPost).where(GeneratedPost.id == post_id))
    await session.commit()
    await callback.answer("🗑 Черновик удалён.")
    await my_drafts_handler(callback, session)


# --- Main Menu shortcut ---

@router.callback_query(F.data == "main_menu")
async def main_menu_shortcut(callback: CallbackQuery) -> None:
    """Return to main menu."""
    await _safe_edit_text(callback, 
        MAIN_MENU_TEXT, reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()
