import logging
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from bot.models.program import Program
from bot.models.lead import Lead
from bot.models.user import User
from bot.ui.main_menu import get_main_menu_keyboard
from bot.i18n import get_locale, pick
from bot.tasks import enqueue_program_job
from bot.services.subscription import (
    TRIAL_OVER_MESSAGE,
    TRIAL_OVER_MESSAGE_EN,
    has_full_access,
)
from bot.ui.lead_card import format_lead_card, get_lead_card_keyboard
from bot.scheduler import remove_program_job
from sqlalchemy import delete

logger = logging.getLogger(__name__)
router = Router()

# --- Keyboards ---

def get_program_card_keyboard(program_id: int, leads_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if leads_count > 0:
        builder.button(text=f"👀 Посмотреть лидов ({leads_count})", callback_data=f"view_program_leads_{program_id}")
        builder.button(text="🗑 Очистить лидов", callback_data=f"clear_leads_{program_id}")
    builder.button(text="▶️ Запустить", callback_data=f"run_program_{program_id}")
    builder.button(text="✏️ Изменить", callback_data=f"edit_program_{program_id}")
    builder.button(text="🗑 Удалить", callback_data=f"delete_program_{program_id}")
    builder.button(text="◀️ Назад", callback_data="my_programs")
    builder.adjust(2 if leads_count > 0 else 1, 2, 1, 1)
    return builder.as_markup()

def get_delete_confirmation_keyboard(program_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить", callback_data=f"confirm_delete_{program_id}")
    builder.button(text="◀️ Нет, вернуться", callback_data=f"show_program_{program_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_clear_leads_confirmation_keyboard(program_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, очистить", callback_data=f"confirm_clear_leads_{program_id}")
    builder.button(text="◀️ Нет, вернуться", callback_data=f"show_program_{program_id}")
    builder.adjust(1)
    return builder.as_markup()

# --- View / Main Card Handler ---

@router.callback_query(F.data.startswith("show_program_"))
async def show_program_handler(callback: CallbackQuery, session: AsyncSession):
    logging.info(f"Handling 'show_program' callback: {callback.data}")
    locale = get_locale(callback.from_user.language_code)
    program_id = int(callback.data.split("_")[-1])

    program_query = (
        select(Program)
        .options(selectinload(Program.chats))
        .where(
            Program.id == program_id,
            Program.user_id == callback.from_user.id,
        )
    )
    program = (await session.execute(program_query)).scalars().first()

    if not program:
        text = pick(locale, "Программа не найдена.", "Program not found.")
        await callback.message.edit_text(
            text,
            reply_markup=get_main_menu_keyboard(callback.from_user.language_code),
        )
        await callback.answer(text, show_alert=True)
        return

    leads_count_query = select(func.count(Lead.id)).where(Lead.program_id == program.id)
    leads_count = (await session.execute(leads_count_query)).scalar_one()
    logger.info(f"Querying lead count for program_id={program.id}. Found: {leads_count} leads.")

    # DEBUG: Let's also check all leads in the database
    all_leads_query = select(Lead.id, Lead.program_id, Lead.telegram_username)
    all_leads_result = await session.execute(all_leads_query)
    all_leads = all_leads_result.all()
    logger.info(f"All leads in database: {all_leads}")

    chats_list_str = "\n".join([f"• @{chat.chat_username}" for chat in program.chats]) if program.chats else "Нет чатов."
    schedule_status = "✅" if program.auto_collect_enabled else "❌"
    schedule_label = (
        f"ежедневно в {program.schedule_time}"
        if program.auto_collect_enabled else
        "выключено"
    )
    text = (
        f"📁 {program.name}\n\n"
        f"🎯 Ниша: {program.niche_description}\n\n"
        f"💬 Чаты:\n{chats_list_str}\n\n"
        f"⚙️ Настройки:\n"
        f"• 🏆 Минимальный скор: {program.min_score}\n"
        f"• 👥 Лидов за запуск: макс {program.max_leads_per_run}\n"
        f"• 🌐 Web-обогащение: {'вкл ✅' if program.enrich else 'выкл ❌'}\n"
        f"• ⏰ Расписание: {schedule_label} {schedule_status}\n\n"
        f"📊 Статистика:\n"
        f"• 🧑 Всего найдено: {leads_count} лидов\n"
    )

    await callback.message.edit_text(text, reply_markup=get_program_card_keyboard(program.id, leads_count))
    await callback.answer()

# --- 'Run Now' Handler (Non-blocking) ---

@router.callback_query(F.data.startswith("run_program_"))
async def run_program_handler(callback: CallbackQuery, session: AsyncSession):
    program_id = int(callback.data.split("_")[-1])
    locale = get_locale(callback.from_user.language_code)
    logging.info(f"Starting immediate job for program_id={program_id}")

    owned_program = (
        await session.execute(
            select(Program.id).where(
                Program.id == program_id,
                Program.user_id == callback.from_user.id,
            )
        )
    ).scalar_one_or_none()
    if not owned_program:
        await callback.answer(
            pick(locale, "Программа не найдена.", "Program not found."),
            show_alert=True,
        )
        return

    user = await session.get(User, callback.from_user.id)
    if not user:
        await callback.answer(
            pick(
                locale,
                "Профиль не найден. Откройте главное меню и попробуйте снова.",
                "Profile not found. Open the main menu and try again.",
            ),
            show_alert=True,
        )
        return

    if not has_full_access(user):
        await callback.answer(
            pick(locale, TRIAL_OVER_MESSAGE, TRIAL_OVER_MESSAGE_EN),
            show_alert=True,
        )
        return

    async def _enqueue_background() -> None:
        task_id = enqueue_program_job(program_id, callback.from_user.id)
        logger.info(
            f"Program run enqueued: program_id={program_id}, "
            f"user_id={callback.from_user.id}, task_id={task_id}"
        )

    try:
        asyncio.create_task(_enqueue_background())
    except Exception as e:
        logger.error(f"Failed to enqueue program run: {e}")
        await callback.answer(
            pick(
                locale,
                "Не удалось поставить запуск в очередь. Попробуйте позже.",
                "Failed to queue the run. Please try again later.",
            ),
            show_alert=True,
        )
        return

    await callback.answer(
        pick(
            locale,
            "🕓 Программа запущена и поставлена в очередь.\n"
            "Результаты будут приходить в чат по мере обработки.",
            "🕓 Program started and queued.\n"
            "Results will be sent as processing continues.",
        ),
        show_alert=True,
    )

# --- Delete Flow Handlers ---

@router.callback_query(F.data.startswith("delete_program_"))
async def delete_program_confirmation(callback: CallbackQuery, session: AsyncSession):
    program_id = int(callback.data.split("_")[-1])
    query = select(Program).where(
        Program.id == program_id,
        Program.user_id == callback.from_user.id,
    )
    program = (await session.execute(query)).scalars().first()
    if not program:
        await callback.answer("Программа уже удалена.", show_alert=True)
        return
    
    text = f"🗑 Удаление программы\n\n⚠️ Точно удалить «{program.name}»?\n\nЭто действие нельзя отменить."
    await callback.message.edit_text(text, reply_markup=get_delete_confirmation_keyboard(program_id))
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_"))
async def delete_program_confirmed(callback: CallbackQuery, session: AsyncSession):
    program_id = int(callback.data.split("_")[-1])
    locale = get_locale(callback.from_user.language_code)
    query = select(Program).where(
        Program.id == program_id,
        Program.user_id == callback.from_user.id,
    )
    program = (await session.execute(query)).scalars().first()

    if program:
        program_name = program.name
        await session.delete(program)
        await session.commit()
        remove_program_job(program_id)
        await callback.message.edit_text(
            pick(
                locale,
                f"✅ Программа «{program_name}» удалена.",
                f"✅ Program “{program_name}” deleted.",
            ),
            reply_markup=get_main_menu_keyboard(callback.from_user.language_code),
        )
    else:
        await callback.message.edit_text(
            pick(
                locale,
                "✅ Программа уже была удалена ранее.",
                "✅ Program had already been deleted earlier.",
            ),
            reply_markup=get_main_menu_keyboard(callback.from_user.language_code),
        )
    await callback.answer()

# --- Clear Leads Flow Handlers ---

@router.callback_query(F.data.startswith("clear_leads_"))
async def clear_leads_confirmation(callback: CallbackQuery, session: AsyncSession):
    program_id = int(callback.data.split("_")[-1])

    # Get program and count leads
    program_query = select(Program).where(
        Program.id == program_id,
        Program.user_id == callback.from_user.id,
    )
    program = (await session.execute(program_query)).scalars().first()

    if not program:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    leads_count_query = select(func.count(Lead.id)).where(Lead.program_id == program.id)
    leads_count = (await session.execute(leads_count_query)).scalar_one()

    if leads_count == 0:
        await callback.answer("Нет лидов для удаления.", show_alert=True)
        return

    text = (
        f"🗑 Очистка лидов\n\n"
        f"Программа: \"{program.name}\"\n"
        f"Найдено лидов: {leads_count}\n\n"
        f"Точно удалить всех лидов этой программы?\n\n"
        f"⚠️ Это действие нельзя отменить."
    )
    await callback.message.edit_text(text, reply_markup=get_clear_leads_confirmation_keyboard(program_id))
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_clear_leads_"))
async def clear_leads_confirmed(callback: CallbackQuery, session: AsyncSession):
    program_id = int(callback.data.split("_")[-1])

    # Get program
    program_query = select(Program).where(
        Program.id == program_id,
        Program.user_id == callback.from_user.id,
    )
    program = (await session.execute(program_query)).scalars().first()

    if not program:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    # Count leads before deletion
    leads_count_query = select(func.count(Lead.id)).where(Lead.program_id == program.id)
    leads_count = (await session.execute(leads_count_query)).scalar_one()

    # Delete all leads for this program
    delete_query = delete(Lead).where(
        Lead.program_id == program_id,
        Lead.user_id == callback.from_user.id,
    )
    result = await session.execute(delete_query)
    await session.commit()

    logger.info(f"Deleted {leads_count} leads for program_id={program_id} ({program.name})")

    # Show updated program card
    await callback.answer(f"✅ Удалено лидов: {leads_count}", show_alert=True)
    await show_program_handler(callback, session)

# --- Edit Stub ---

# Edit handler moved to program_edit.py
