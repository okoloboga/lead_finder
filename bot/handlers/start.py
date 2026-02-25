import logging
import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.ui.main_menu import get_main_menu_keyboard, MAIN_MENU_TEXT
from bot.models.user import User
from bot.states import UserProfile

router = Router()


def _get_settings_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить описание услуг",
        callback_data="edit_services_description",
    )
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def _render_settings_text(services_description: str | None) -> str:
    current = services_description or "Не заполнено"
    return (
        "⚙️ Настройки\n"
        "━━━━━━━━━━━\n\n"
        "Мои услуги:\n"
        f"\"{current}\"\n\n"
        "Нажмите кнопку ниже, чтобы обновить описание."
    )


async def _touch_user(user, session: AsyncSession) -> User:
    existing = (
        await session.execute(select(User).where(User.telegram_id == user.id))
    ).scalars().first()
    now = datetime.datetime.utcnow()
    if existing:
        existing.username = user.username
        existing.last_active_at = now
    else:
        existing = User(
            telegram_id=user.id,
            username=user.username,
            last_active_at=now,
        )
        session.add(existing)
    await session.commit()
    return existing


@router.message(Command("start"))
async def start_handler(
    message: Message, session: AsyncSession, state: FSMContext
):
    """Handler for the /start command."""
    logging.info("Handling /start command")
    user = await _touch_user(message.from_user, session)

    if not (user.services_description or "").strip():
        await state.set_state(UserProfile.enter_services_description)
        await state.update_data(profile_flow="onboarding")
        await message.answer(
            "Привет! Я помогаю находить клиентов в Telegram-чатах.\n\n"
            "Чтобы настроить поиск под тебя, напиши одним сообщением:\n"
            "• Какие услуги ты продаешь?\n"
            "• Кто твои клиенты?\n\n"
            "Пример: «Делаю сайты и лендинги для малого бизнеса».",
        )
        return

    await message.answer(
        MAIN_MENU_TEXT,
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "main_menu")
async def main_menu_callback_handler(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
):
    """Handler for the 'Back to Main Menu' button."""
    logging.info("Handling 'main_menu' callback")
    await _touch_user(callback.from_user, session)
    await state.clear()
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
async def settings_handler(callback: CallbackQuery, session: AsyncSession):
    user = await _touch_user(callback.from_user, session)
    await callback.message.edit_text(
        _render_settings_text(user.services_description),
        reply_markup=_get_settings_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "edit_services_description")
async def edit_services_description_handler(
    callback: CallbackQuery, state: FSMContext
):
    await state.set_state(UserProfile.enter_services_description)
    await state.update_data(profile_flow="settings")
    await callback.message.edit_text(
        "✏️ Введите новое описание услуг одним сообщением.\n\n"
        "Пример: «Настраиваю AI-автоматизацию для e-commerce».",
        reply_markup=_get_settings_keyboard(),
    )
    await callback.answer()


@router.message(UserProfile.enter_services_description)
async def save_services_description_handler(
    message: Message, state: FSMContext, session: AsyncSession
):
    description = (message.text or "").strip()
    if len(description) < 10:
        await message.answer("Описание слишком короткое. Напишите подробнее (10+ символов).")
        return

    user = await _touch_user(message.from_user, session)
    user.services_description = description
    user.last_active_at = datetime.datetime.utcnow()
    await session.commit()

    data = await state.get_data()
    flow = data.get("profile_flow")
    await state.clear()

    if flow == "onboarding":
        await message.answer(
            "Отлично! Сохранил описание услуг.\n"
            "Теперь я буду использовать его в квалификации лидов."
        )
        await message.answer(MAIN_MENU_TEXT, reply_markup=get_main_menu_keyboard())
        return

    await message.answer(
        "✅ Описание услуг обновлено.",
    )
    await message.answer(
        _render_settings_text(description),
        reply_markup=_get_settings_keyboard(),
    )
