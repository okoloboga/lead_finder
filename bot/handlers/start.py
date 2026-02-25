import logging
import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.ui.main_menu import get_main_menu_keyboard, MAIN_MENU_TEXT
from bot.models.user import User

router = Router()


async def _touch_user(user, session: AsyncSession) -> None:
    existing = (
        await session.execute(select(User).where(User.telegram_id == user.id))
    ).scalars().first()
    now = datetime.datetime.utcnow()
    if existing:
        existing.username = user.username
        existing.last_active_at = now
    else:
        session.add(
            User(
                telegram_id=user.id,
                username=user.username,
                last_active_at=now,
            )
        )
    await session.commit()


@router.message(Command("start"))
async def start_handler(message: Message, session: AsyncSession):
    """Handler for the /start command."""
    logging.info("Handling /start command")
    await _touch_user(message.from_user, session)
    await message.answer(
        MAIN_MENU_TEXT,
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "main_menu")
async def main_menu_callback_handler(
    callback: CallbackQuery, session: AsyncSession
):
    """Handler for the 'Back to Main Menu' button."""
    logging.info("Handling 'main_menu' callback")
    await _touch_user(callback.from_user, session)
    await callback.message.edit_text(
        MAIN_MENU_TEXT,
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

# --- Stub handlers for main menu buttons ---

@router.callback_query(F.data == "statistics")
async def statistics_stub(callback: CallbackQuery):
    logging.warning("Handler 'statistics' is a stub.")
    await callback.answer("Вы выбрали 'Статистика'. Этот раздел в разработке.")

@router.callback_query(F.data == "settings")
async def settings_stub(callback: CallbackQuery):
    logging.warning("Handler 'settings' is a stub.")
    await callback.answer("Вы выбрали 'Настройки'. Этот раздел в разработке.")
