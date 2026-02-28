import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models.lead import Lead
from bot.models.pain import PainCluster
from bot.models.program import Program
from bot.models.user import User
from bot.services.subscription import activate_paid_subscription, normalize_subscription
from bot.states import AdminPanel
from bot.ui.main_menu import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in config.ADMIN_TELEGRAM_IDS


def _admin_menu_keyboard() -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="admin_panel")
    builder.button(text="🔎 Найти пользователя", callback_data="admin_find_user")
    builder.button(text="◀️ Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def _admin_user_card_keyboard(user_id: int) -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ 1 мес", callback_data=f"admin_grant_1m_{user_id}")
    builder.button(text="➕ 3 мес", callback_data=f"admin_grant_3m_{user_id}")
    builder.button(text="➕ 6 мес", callback_data=f"admin_grant_6m_{user_id}")
    builder.button(text="➕ 12 мес", callback_data=f"admin_grant_12m_{user_id}")
    builder.button(text="📋 Программы пользователя", callback_data=f"admin_user_programs_{user_id}")
    builder.button(text="◀️ К админке", callback_data="admin_panel")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


async def _render_admin_dashboard(session: AsyncSession) -> str:
    total_users = (await session.execute(select(func.count(User.telegram_id)))).scalar_one()
    paid_users = (
        await session.execute(select(func.count(User.telegram_id)).where(User.subscription_type == "paid"))
    ).scalar_one()
    free_users = total_users - paid_users
    total_programs = (await session.execute(select(func.count(Program.id)))).scalar_one()
    total_leads = (await session.execute(select(func.count(Lead.id)))).scalar_one()
    total_clusters = (await session.execute(select(func.count(PainCluster.id)))).scalar_one()

    return (
        "📊 Админка LeadCore\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователи: {total_users}\n"
        f"├ С подпиской: {paid_users}\n"
        f"└ Без подписки: {free_users}\n\n"
        f"📋 Программы: {total_programs}\n"
        f"🎯 Лиды: {total_leads}\n"
        f"📁 Кластеры: {total_clusters}"
    )


@router.message(Command("admin_panel"))
async def admin_panel_command(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    text = await _render_admin_dashboard(session)
    await message.answer(text, reply_markup=_admin_menu_keyboard())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    text = await _render_admin_dashboard(session)
    await callback.message.edit_text(text, reply_markup=_admin_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_find_user")
async def admin_find_user(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminPanel.waiting_user_query)
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ К админке", callback_data="admin_panel")
    builder.adjust(1)
    await callback.message.edit_text(
        "🔎 Введите @username или telegram_id пользователя.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(AdminPanel.waiting_user_query)
async def admin_find_user_input(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    query_raw = (message.text or "").strip()
    if not query_raw:
        await message.answer("Пустой запрос. Введите @username или telegram_id.")
        return

    user = None
    if query_raw.isdigit():
        user = await session.get(User, int(query_raw))
    else:
        username = query_raw.lstrip("@")
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalars().first()

    if not user:
        await message.answer("Пользователь не найден.")
        return

    normalize_subscription(user)
    await session.commit()

    program_count = (
        await session.execute(select(func.count(Program.id)).where(Program.user_id == user.telegram_id))
    ).scalar_one()
    lead_count = (
        await session.execute(select(func.count(Lead.id)).where(Lead.user_id == user.telegram_id))
    ).scalar_one()

    sub_status = user.subscription_type
    if user.subscription_type == "paid" and user.subscription_expires_at:
        sub_status = f"paid до {user.subscription_expires_at.strftime('%d.%m.%Y')}"

    text = (
        f"👤 @{user.username or 'unknown'} (id: {user.telegram_id})\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Регистрация: {user.created_at.strftime('%d.%m.%Y')}\n"
        f"💎 Подписка: {sub_status}\n"
        f"📋 Программ: {program_count}\n"
        f"🎯 Лидов: {lead_count}"
    )
    await message.answer(text, reply_markup=_admin_user_card_keyboard(user.telegram_id))


@router.callback_query(F.data.startswith("admin_grant_"))
async def admin_grant_subscription(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer("Некорректная команда.", show_alert=True)
        return
    period_key = parts[2]
    try:
        target_user_id = int(parts[3])
    except ValueError:
        await callback.answer("Некорректный user_id.", show_alert=True)
        return

    user = await session.get(User, target_user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    expires_at = activate_paid_subscription(user, period_key)
    await session.commit()
    await callback.answer(
        f"✅ Подписка продлена до {expires_at.strftime('%d.%m.%Y')}",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("admin_user_programs_"))
async def admin_user_programs(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        user_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Некорректный user_id.", show_alert=True)
        return

    programs = (
        await session.execute(
            select(Program)
            .where(Program.user_id == user_id)
            .order_by(Program.id)
        )
    ).scalars().all()
    if not programs:
        await callback.answer("У пользователя нет программ.", show_alert=True)
        return

    lines = [f"📋 Программы пользователя {user_id}\n"]
    for p in programs[:30]:
        status = "вкл" if p.auto_collect_enabled else "выкл"
        lines.append(
            f"• #{p.id} {p.name} | скор≥{p.min_score} | автосбор: {status}"
        )
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_admin_menu_keyboard(),
    )
    await callback.answer()
