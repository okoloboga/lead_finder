import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.models.lead import Lead
from bot.ui.lead_card import format_lead_card, get_lead_navigation_keyboard, get_lead_card_keyboard

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("view_program_leads_"))
async def view_program_leads_handler(callback: CallbackQuery, session: AsyncSession):
    """Shows the first lead in paginated view."""
    program_id = int(callback.data.split("_")[-1])
    await show_lead_page(callback, session, program_id, page=0, edit=False)


@router.callback_query(F.data.startswith("lead_page_"))
async def lead_page_navigation_handler(callback: CallbackQuery, session: AsyncSession):
    """Handles pagination navigation between leads."""
    parts = callback.data.split("_")
    program_id = int(parts[2])
    page = int(parts[3])
    await show_lead_page(callback, session, program_id, page, edit=True)


async def show_lead_page(
    callback: CallbackQuery,
    session: AsyncSession,
    program_id: int,
    page: int,
    edit: bool,
) -> None:
    """Shows a specific lead page."""
    logger.info(f"Showing lead page {page} for program_id={program_id}")

    query = (
        select(Lead)
        .where(
            Lead.program_id == program_id,
            Lead.user_id == callback.from_user.id,
        )
        .options(selectinload(Lead.program))
        .order_by(Lead.created_at.desc())
    )
    leads = (await session.execute(query)).scalars().all()

    if not leads:
        await callback.answer("Для этой программы лиды еще не найдены.", show_alert=True)
        return

    total_leads = len(leads)

    if page < 0 or page >= total_leads:
        await callback.answer("Неверная страница.", show_alert=True)
        return

    lead = leads[page]
    card_text = format_lead_card(lead, page + 1, total_leads)
    keyboard = get_lead_navigation_keyboard(
        program_id, page, total_leads, lead.id, lead.status
    )

    if edit:
        await callback.message.edit_text(
            card_text, reply_markup=keyboard, disable_web_page_preview=True
        )
    else:
        await callback.message.answer(
            card_text, reply_markup=keyboard, disable_web_page_preview=True
        )
    await callback.answer()


# --- Outreach status handlers ---

@router.callback_query(F.data.startswith("lead_contacted_"))
async def mark_lead_contacted(callback: CallbackQuery, session: AsyncSession):
    """Marks a lead as contacted."""
    lead_id = int(callback.data.split("_")[-1])
    lead = await _get_lead(session, lead_id, callback.from_user.id)
    if lead:
        lead.status = "contacted"
        await session.commit()
        await callback.message.edit_reply_markup(
            reply_markup=get_lead_card_keyboard(lead_id, "contacted")
        )
    await callback.answer("✅ Отмечено: написал!", show_alert=False)


@router.callback_query(F.data.startswith("lead_skipped_"))
async def mark_lead_skipped(callback: CallbackQuery, session: AsyncSession):
    """Marks a lead as skipped."""
    lead_id = int(callback.data.split("_")[-1])
    lead = await _get_lead(session, lead_id, callback.from_user.id)
    if lead:
        lead.status = "skipped"
        await session.commit()
        await callback.message.edit_reply_markup(
            reply_markup=get_lead_card_keyboard(lead_id, "skipped")
        )
    await callback.answer("❌ Пропущен", show_alert=False)


@router.callback_query(F.data.startswith("lead_restore_"))
async def restore_lead(callback: CallbackQuery, session: AsyncSession):
    """Restores a skipped lead back to new."""
    lead_id = int(callback.data.split("_")[-1])
    lead = await _get_lead(session, lead_id, callback.from_user.id)
    if lead:
        lead.status = "new"
        await session.commit()
        await callback.message.edit_reply_markup(
            reply_markup=get_lead_card_keyboard(lead_id, "new")
        )
    await callback.answer("↩️ Возвращён в очередь", show_alert=False)


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    """Handles the page counter button (does nothing)."""
    await callback.answer()


async def _get_lead(
    session: AsyncSession, lead_id: int, user_id: int
) -> Lead | None:
    """Helper to fetch a lead by id."""
    result = await session.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.user_id == user_id,
        )
    )
    return result.scalars().first()
