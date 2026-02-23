import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.models.program import Program
from bot.ui.main_menu import MAIN_MENU_TEXT, get_main_menu_keyboard

router = Router()

def get_my_programs_keyboard(programs: list[Program]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if programs:
        for program in programs:
            builder.button(text=f"📁 {program.name}", callback_data=f"show_program_{program.id}")
        builder.adjust(1) # Adjust later for 2-column layout if many programs
        builder.button(text="➕ Создать ещё", callback_data="create_program") # Add as a regular button
    else:
        builder.button(text="➕ Создать программу", callback_data="create_program")
    
    # These buttons will appear on their own rows due to adjust or explicitly being added after others
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1) # Ensure these last two buttons are on separate rows, or a different adjust if more buttons are added

    return builder.as_markup()

@router.callback_query(F.data == "my_programs")
async def my_programs_handler(callback: CallbackQuery, session: AsyncSession):
    logging.info("Handling 'my_programs' callback.")
    
    # Use selectinload to eagerly load the 'chats' relationship
    query = select(Program).options(selectinload(Program.chats)).order_by(Program.id)
    result = await session.execute(query)
    programs = result.scalars().all()

    if not programs:
        text = (
            "📋 Мои программы\n\n"
            "У тебя пока нет программ поиска.\n"
            "Создай первую — это займёт пару минут."
        )
    else:
        text = "📋 Мои программы\n\n"
        for i, program in enumerate(programs):
            schedule_status = (
                f"⏰ {program.schedule_time}"
                if program.owner_chat_id is not None else
                "⏸ выключено"
            )
            text += (
                f"{i+1}️⃣ {program.name}\n"
                f"   {len(program.chats)} чата(ов) • скор ≥{program.min_score} • {schedule_status}\n"
                "\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=get_my_programs_keyboard(programs)
    )
    await callback.answer()
