import logging
import datetime
from aiogram import Router, F, Bot
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

REQUIRED_CHANNEL = "@leather_tensor"


async def _is_channel_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception:
        return False


def _channel_check_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Подписаться на канал", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")
    builder.button(text="✅ Я подписался", callback_data="check_channel_subscription")
    builder.adjust(1)
    return builder.as_markup()


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
        "💼 Мои услуги:\n"
        f"\"{current}\"\n\n"
        "✏️ Нажмите кнопку ниже, чтобы обновить описание."
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


async def _continue_onboarding(
    tg_user: object,
    send_fn,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    user = await _touch_user(tg_user, session)
    if not (user.services_description or "").strip():
        await state.set_state(UserProfile.enter_services_description)
        await state.update_data(profile_flow="onboarding")
        await send_fn(
            "👋 Привет! Я LeadSense — нахожу клиентов в Telegram-чатах.\n\n"
            "🎯 Чтобы настроить поиск под тебя, напиши одним сообщением:\n"
            "• 💼 Какие услуги ты продаёшь?\n"
            "• 👥 Кто твои клиенты?\n\n"
            "💡 Пример: «Делаю сайты и лендинги для малого бизнеса».",
        )
        return
    await send_fn(MAIN_MENU_TEXT, reply_markup=get_main_menu_keyboard())


@router.message(Command("start"))
async def start_handler(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    """Handler for the /start command."""
    logging.info("Handling /start command")

    if not await _is_channel_member(bot, message.from_user.id):
        await message.answer(
            f"🔒 Доступ закрыт\n\n"
            f"Чтобы пользоваться ботом, подпишись на канал {REQUIRED_CHANNEL} — "
            "там делюсь инсайтами по лидогенерации в Telegram.\n\n"
            "После подписки нажми кнопку ниже 👇",
            reply_markup=_channel_check_keyboard(),
        )
        return

    await _continue_onboarding(message.from_user, message.answer, session, state)


@router.callback_query(F.data == "check_channel_subscription")
async def check_channel_subscription_handler(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    """Re-checks channel membership and continues onboarding if passed."""
    if not await _is_channel_member(bot, callback.from_user.id):
        await callback.answer(
            f"❌ Вы ещё не подписаны на {REQUIRED_CHANNEL}.\nПодпишитесь и попробуйте снова.",
            show_alert=True,
        )
        return

    await callback.message.delete()
    await _continue_onboarding(callback.from_user, callback.message.answer, session, state)
    await callback.answer()

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
        "💡 Пример: «Настраиваю AI-автоматизацию для e-commerce».",
        reply_markup=_get_settings_keyboard(),
    )
    await callback.answer()


@router.message(UserProfile.enter_services_description)
async def save_services_description_handler(
    message: Message, state: FSMContext, session: AsyncSession
):
    description = (message.text or "").strip()
    if len(description) < 10:
        await message.answer("⚠️ Описание слишком короткое. Напишите подробнее (10+ символов).")
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
            "🎉 Отлично! Сохранил описание услуг.\n"
            "🤖 Теперь буду использовать его при квалификации лидов."
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
