import logging
import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import get_locale, pick, t
from bot.ui.main_menu import get_main_menu_keyboard, get_main_menu_text
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


def _channel_check_keyboard(language_code: str | None) -> object:
    locale = get_locale(language_code)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=pick(locale, "📢 Подписаться на канал", "📢 Subscribe to Channel"),
        url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}",
    )
    builder.button(
        text=pick(locale, "✅ Я подписался", "✅ I Subscribed"),
        callback_data="check_channel_subscription",
    )
    builder.adjust(1)
    return builder.as_markup()


def _get_settings_keyboard(language_code: str | None) -> object:
    locale = get_locale(language_code)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=pick(
            locale,
            "✏️ Изменить описание услуг",
            "✏️ Edit Services Description",
        ),
        callback_data="edit_services_description",
    )
    builder.button(text=t("btn_back", language_code), callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def _render_settings_text(
    services_description: str | None, language_code: str | None
) -> str:
    locale = get_locale(language_code)
    current = services_description or pick(locale, "Не заполнено", "Not set")
    return pick(
        locale,
        (
            "⚙️ Настройки\n"
            "━━━━━━━━━━━\n\n"
            "💼 Мои услуги:\n"
            f"\"{current}\"\n\n"
            "✏️ Нажмите кнопку ниже, чтобы обновить описание."
        ),
        (
            "⚙️ Settings\n"
            "━━━━━━━━━━━\n\n"
            "💼 My Services:\n"
            f"\"{current}\"\n\n"
            "✏️ Tap the button below to update your services description."
        ),
    )


async def _touch_user(user, session: AsyncSession) -> User:
    existing = (
        await session.execute(select(User).where(User.telegram_id == user.id))
    ).scalars().first()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
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
    locale = get_locale(getattr(tg_user, "language_code", None))
    user = await _touch_user(tg_user, session)
    if not (user.services_description or "").strip():
        await state.set_state(UserProfile.enter_services_description)
        await state.update_data(profile_flow="onboarding")
        await send_fn(
            pick(
                locale,
                (
                    "👋 Привет! Я LeadCore — нахожу клиентов в Telegram-чатах.\n\n"
                    "🎯 Чтобы настроить поиск под тебя, напиши одним сообщением:\n"
                    "• 💼 Какие услуги ты продаёшь?\n"
                    "• 👥 Кто твои клиенты?\n\n"
                    "💡 Пример: «Делаю сайты и лендинги для малого бизнеса»."
                ),
                (
                    "👋 Hi! I’m LeadCore — I find clients in Telegram chats.\n\n"
                    "🎯 To personalize lead search for you, send one message:\n"
                    "• 💼 What services do you sell?\n"
                    "• 👥 Who are your clients?\n\n"
                    "💡 Example: “I build websites and landing pages for SMBs.”"
                ),
            ),
        )
        return
    await send_fn(
        get_main_menu_text(getattr(tg_user, "language_code", None)),
        reply_markup=get_main_menu_keyboard(getattr(tg_user, "language_code", None)),
    )


@router.message(Command("start"))
async def start_handler(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    """Handler for the /start command."""
    logging.info("Handling /start command")
    locale = get_locale(message.from_user.language_code)

    if not await _is_channel_member(bot, message.from_user.id):
        await message.answer(
            pick(
                locale,
                (
                    f"🔒 Доступ закрыт\n\n"
                    f"Чтобы пользоваться ботом, подпишись на канал "
                    f"{REQUIRED_CHANNEL} — там делюсь инсайтами по "
                    "лидогенерации в Telegram.\n\n"
                    "После подписки нажми кнопку ниже 👇"
                ),
                (
                    f"🔒 Access Restricted\n\n"
                    f"To use this bot, subscribe to {REQUIRED_CHANNEL} — "
                    "I share Telegram lead generation insights there.\n\n"
                    "After subscribing, tap the button below 👇"
                ),
            ),
            reply_markup=_channel_check_keyboard(message.from_user.language_code),
        )
        return

    await _continue_onboarding(message.from_user, message.answer, session, state)


@router.callback_query(F.data == "check_channel_subscription")
async def check_channel_subscription_handler(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    """Re-checks channel membership and continues onboarding if passed."""
    locale = get_locale(callback.from_user.language_code)
    if not await _is_channel_member(bot, callback.from_user.id):
        await callback.answer(
            pick(
                locale,
                f"❌ Вы ещё не подписаны на {REQUIRED_CHANNEL}.\n"
                "Подпишитесь и попробуйте снова.",
                f"❌ You are not subscribed to {REQUIRED_CHANNEL} yet.\n"
                "Subscribe and try again.",
            ),
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
        get_main_menu_text(callback.from_user.language_code),
        reply_markup=get_main_menu_keyboard(callback.from_user.language_code),
    )
    await callback.answer()

# --- Stub handlers for main menu buttons ---

@router.callback_query(F.data == "statistics")
async def statistics_stub(callback: CallbackQuery):
    logging.warning("Handler 'statistics' is a stub.")
    locale = get_locale(callback.from_user.language_code)
    await callback.answer(
        pick(
            locale,
            "Вы выбрали 'Статистика'. Этот раздел в разработке.",
            "You selected 'Statistics'. This section is under development.",
        )
    )

@router.callback_query(F.data == "settings")
async def settings_handler(callback: CallbackQuery, session: AsyncSession):
    user = await _touch_user(callback.from_user, session)
    await callback.message.edit_text(
        _render_settings_text(
            user.services_description,
            callback.from_user.language_code,
        ),
        reply_markup=_get_settings_keyboard(callback.from_user.language_code),
    )
    await callback.answer()


@router.callback_query(F.data == "edit_services_description")
async def edit_services_description_handler(
    callback: CallbackQuery, state: FSMContext
):
    locale = get_locale(callback.from_user.language_code)
    await state.set_state(UserProfile.enter_services_description)
    await state.update_data(profile_flow="settings")
    await callback.message.edit_text(
        pick(
            locale,
            "✏️ Введите новое описание услуг одним сообщением.\n\n"
            "💡 Пример: «Настраиваю AI-автоматизацию для e-commerce».",
            "✏️ Enter your new services description in one message.\n\n"
            "💡 Example: “I implement AI automation for e-commerce.”",
        ),
        reply_markup=_get_settings_keyboard(callback.from_user.language_code),
    )
    await callback.answer()


@router.message(UserProfile.enter_services_description)
async def save_services_description_handler(
    message: Message, state: FSMContext, session: AsyncSession
):
    locale = get_locale(message.from_user.language_code)
    description = (message.text or "").strip()
    if len(description) < 10:
        await message.answer(
            pick(
                locale,
                "⚠️ Описание слишком короткое. Напишите подробнее "
                "(10+ символов).",
                "⚠️ Description is too short. Please provide at least "
                "10 characters.",
            )
        )
        return

    user = await _touch_user(message.from_user, session)
    user.services_description = description
    user.last_active_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await session.commit()

    data = await state.get_data()
    flow = data.get("profile_flow")
    await state.clear()

    if flow == "onboarding":
        await message.answer(
            pick(
                locale,
                "🎉 Отлично! Сохранил описание услуг.\n"
                "🤖 Теперь буду использовать его при квалификации лидов.",
                "🎉 Great! Services description saved.\n"
                "🤖 I will now use it while qualifying leads.",
            )
        )
        await message.answer(
            get_main_menu_text(message.from_user.language_code),
            reply_markup=get_main_menu_keyboard(message.from_user.language_code),
        )
        return

    await message.answer(
        pick(
            locale,
            "✅ Описание услуг обновлено.",
            "✅ Services description updated.",
        ),
    )
    await message.answer(
        _render_settings_text(description, message.from_user.language_code),
        reply_markup=_get_settings_keyboard(message.from_user.language_code),
    )
