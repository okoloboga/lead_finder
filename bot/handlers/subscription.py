import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.subscription import (
    STARS_PRICES,
    activate_paid_subscription,
    check_weekly_analysis_limit,
    is_paid_user,
    normalize_subscription,
)
from bot.i18n import get_locale, pick
from bot.ui.main_menu import get_main_menu_keyboard

router = Router()
logger = logging.getLogger(__name__)


_PERIOD_LABELS = {"1m": "1 мес", "3m": "3 мес", "6m": "6 мес", "12m": "12 мес"}
_PERIOD_DISCOUNTS = {"1m": None, "3m": 20, "6m": 33, "12m": 42}


def _period_label(period_key: str) -> str:
    return _PERIOD_LABELS.get(period_key, period_key)


def _subscription_menu_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    for period_key in ("1m", "3m", "6m", "12m"):
        stars = STARS_PRICES[period_key]
        discount = _PERIOD_DISCOUNTS[period_key]
        discount_str = f" (-{discount}%)" if discount else ""
        builder.button(
            text=f"{_period_label(period_key)} — ⭐ {stars}{discount_str}",
            callback_data=f"buy_sub_{period_key}",
        )
    builder.button(
        text="🆘 Поддержка оплаты",
        callback_data="subscription_support",
    )
    builder.button(
        text="◀️ Главное меню",
        callback_data="main_menu",
    )
    builder.adjust(1)
    return builder.as_markup()


def _render_subscription_text(user: User) -> str:
    normalize_subscription(user)
    paid = is_paid_user(user)
    if paid and user.subscription_expires_at:
        status = f"💚 Paid до {user.subscription_expires_at.strftime('%d.%m.%Y')}"
        programs_limit = "♾ Безлимит"
        analyses_limit = "♾ Безлимит"
    else:
        status = "🆓 Free"
        programs_limit = "1"
        can_run, _ = check_weekly_analysis_limit(user)
        analyses_limit = "0/1 ⏳" if not can_run else "1/1 ✅"

    return (
        "💎 Подписка\n"
        "━━━━━━━━━━━\n\n"
        f"Статус: {status}\n\n"
        "📊 Лимиты:\n"
        f"• 📁 Программы: {programs_limit}\n"
        f"• 🔄 Запусков в неделю: {analyses_limit}\n\n"
        "⭐ Выберите период для оплаты Telegram Stars:"
    )


@router.callback_query(F.data == "subscription_menu")
async def subscription_menu_handler(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    locale = get_locale(callback.from_user.language_code)
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
    await callback.message.edit_text(
        _render_subscription_text(user),
        reply_markup=_subscription_menu_keyboard(),
    )
    await session.commit()
    await callback.answer()


@router.callback_query(F.data.startswith("buy_sub_"))
async def buy_subscription_handler(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    locale = get_locale(callback.from_user.language_code)
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

    period_key = callback.data.split("_")[-1]
    if period_key not in STARS_PRICES:
        await callback.answer(
            pick(
                locale,
                "Неверный период подписки.",
                "Invalid subscription period.",
            ),
            show_alert=True,
        )
        return

    price = STARS_PRICES[period_key]
    title = pick(
        locale,
        f"LeadCore — подписка {_period_label(period_key)}",
        f"LeadCore — subscription {_period_label(period_key)}",
    )
    payload = f"subscription:{user.telegram_id}:{period_key}"

    await callback.message.answer_invoice(
        title=title,
        description=pick(
            locale,
            "Безлимитные программы и запуски анализа.",
            "Unlimited programs and analysis runs.",
        ),
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=price)],
    )
    await callback.answer(pick(locale, "Инвойс отправлен.", "Invoice sent."))


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message, session: AsyncSession
) -> None:
    locale = get_locale(message.from_user.language_code)
    payment = message.successful_payment
    if not payment:
        return

    payload = payment.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "subscription":
        await message.answer("Платёж получен, но payload не распознан.")
        return

    _, user_id_raw, period_key = parts
    if period_key not in STARS_PRICES:
        await message.answer("Платёж получен, но период не распознан.")
        return

    try:
        user_id = int(user_id_raw)
    except ValueError:
        await message.answer("Платёж получен, но user_id не распознан.")
        return

    user = await session.get(User, user_id)
    if not user:
        await message.answer("Платёж получен, но профиль не найден.")
        return

    expires_at = activate_paid_subscription(user, period_key)
    await session.commit()

    await message.answer(
        pick(
            locale,
            "🎉 Подписка активирована!\n"
            f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n\n"
            "🚀 Теперь доступны безлимитные программы и запуски анализа.",
            "🎉 Subscription activated!\n"
            f"📅 Valid until: {expires_at.strftime('%d.%m.%Y')}\n\n"
            "🚀 Unlimited programs and analysis runs are now available.",
        ),
        reply_markup=get_main_menu_keyboard(message.from_user.language_code),
    )


@router.callback_query(F.data == "subscription_support")
async def subscription_support_handler(callback: CallbackQuery) -> None:
    await callback.answer("Поддержка оплаты: @devcore_dev", show_alert=True)
