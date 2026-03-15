import logging
import re
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import StateFilter
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states import ProgramCreate
from bot.i18n import get_locale, pick
from bot.ui.main_menu import get_main_menu_keyboard, get_main_menu_text
from bot.models.program import Program, ProgramChat
from bot.models.user import User
from bot.scheduler import schedule_program_job
from bot.services.subscription import check_program_limit

router = Router()


# --- Keyboards ---
def get_step_keyboard(back_callback: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if back_callback:
        builder.button(text="◀️ Back", callback_data=f"back_to_{back_callback}")
    builder.button(text="❌ Cancel", callback_data="cancel_create_program")
    builder.adjust(2)
    return builder.as_markup()

def get_chats_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить ещё", callback_data="add_more_chats")
    builder.button(text="✅ Готово, дальше", callback_data="chats_done")
    builder.button(text="◀️ Назад", callback_data="back_to_niche_description")
    builder.button(text="❌ Отмена", callback_data="cancel_create_program")
    builder.adjust(2, 2)
    return builder.as_markup()

def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # builder.button(text="🎚 Изменить настройки", callback_data="edit_settings") # TODO
    builder.button(text="✅ Всё ок, создать", callback_data="save_program")
    builder.button(text="◀️ Назад", callback_data="back_to_chats")
    builder.button(text="❌ Отмена", callback_data="cancel_create_program")
    builder.adjust(1, 2)
    return builder.as_markup()


# --- FSM Steps ---

# Step 1: Start and Enter Name
@router.callback_query(F.data == "create_program")
async def create_program_start(callback: CallbackQuery, state: FSMContext):
    logging.info("Starting new program creation FSM.")
    locale = get_locale(callback.from_user.language_code)
    await state.set_state(ProgramCreate.enter_name)
    await callback.message.edit_text(
        pick(
            locale,
            "➕ Новая программа\n\n"
            "📝 Шаг 1 из 4: Название\n\n"
            "Как назовём программу?\n"
            "💡 Например: «Селлеры WB», «Инфобизнес», «Логистика»",
            "➕ New Program\n\n"
            "📝 Step 1 of 4: Name\n\n"
            "How would you like to name this program?\n"
            "💡 Example: “WB Sellers”, “Infobiz”, “Logistics”",
        ),
        reply_markup=get_step_keyboard()
    )
    await callback.answer()

# Step 2: Enter Niche Description
@router.message(StateFilter(ProgramCreate.enter_name))
async def enter_name(message: Message, state: FSMContext):
    logging.info(f"FSM 'create_program': entered name '{message.text}'")
    program_name = message.text.strip()
    if len(program_name) > 100:
        await message.answer("⚠️ Название слишком длинное. Попробуйте что-то до 100 символов.",
                             reply_markup=get_step_keyboard())
        return
    await state.update_data(name=program_name)
    await state.set_state(ProgramCreate.enter_niche_description)
    await message.answer(
        f"➕ Новая программа: \"{program_name}\"\n\n"
        "🎯 Шаг 2 из 4: Описание ниши\n\n"
        "Опиши, кого ищем — это поможет точнее квалифицировать лидов.\n\n"
        "💡 Например: «селлеры wildberries и ozon, малый бизнес, ищут автоматизацию»",
        reply_markup=get_step_keyboard(back_callback="name")
    )

# Step 3: Enter Chats
@router.message(StateFilter(ProgramCreate.enter_niche_description))
async def enter_niche_description(message: Message, state: FSMContext):
    logging.info(f"FSM 'create_program': entered niche description '{message.text}'")
    await state.update_data(niche_description=message.text)
    await state.set_state(ProgramCreate.enter_chats)
    data = await state.get_data()
    await message.answer(
        f"➕ Новая программа: \"{data['name']}\"\n\n"
        "💬 Шаг 3 из 4: Чаты для парсинга\n\n"
        "Отправь список чатов, из которых собирать лидов.\n"
        "Можно несколько в одном сообщении, каждый с новой строки.\n\n"
        "📌 Формат: `@username` или `t.me/username`",
        reply_markup=get_step_keyboard(back_callback="niche_description")
    )

# Step 4: Confirm Settings
@router.message(StateFilter(ProgramCreate.enter_chats))
async def enter_chats(message: Message, state: FSMContext):
    chat_usernames = re.findall(r'@(\w+)|t\.me/(\w+)', message.text)
    chats = [item for tpl in chat_usernames for item in tpl if item]
    
    if not chats:
        logging.warning("User provided message with no valid chat usernames.")
        await message.answer("❌ Не нашёл валидных юзернеймов чатов. Попробуй ещё раз.\n"
                             "📌 Формат: `@username` или `t.me/username`",
                             reply_markup=get_step_keyboard(back_callback="niche_description"))
        return

    logging.info(f"FSM 'create_program': entered chats {chats}")
    await state.update_data(chats=chats)
    await state.set_state(ProgramCreate.confirm_settings)
    data = await state.get_data()

    chats_list_str = "\n".join([f"• @{chat}" for chat in data.get('chats', [])])
    text = (
        f"➕ Новая программа: \"{data['name']}\"\n\n"
        f"⚙️ Шаг 4 из 4: Подтверждение\n\n"
        "Текущие настройки:\n"
        "• 🏆 Минимальный скор: 5\n"
        "• 👥 Лидов за запуск: макс 20\n"
        "• 🌐 Web-обогащение: выкл\n"
        "• ⏰ Расписание: ежедневно в 09:00\n\n"
        "💬 Чаты для парсинга:\n"
        f"{chats_list_str}"
    )
    await message.answer(text, reply_markup=get_confirmation_keyboard())


# --- Back Button Handlers ---
@router.callback_query(F.data == "back_to_name")
async def back_to_name(callback: CallbackQuery, state: FSMContext):
    logging.info("FSM 'create_program': going back to 'enter_name' step.")
    await create_program_start(callback, state)

@router.callback_query(F.data == "back_to_niche_description")
async def back_to_niche_description(callback: CallbackQuery, state: FSMContext):
    logging.info("FSM 'create_program': going back to 'enter_niche_description' step.")
    await state.set_state(ProgramCreate.enter_niche_description)
    data = await state.get_data()
    await callback.message.edit_text(
        f"➕ Новая программа: \"{data['name']}\"\n\n"
        "🎯 Шаг 2 из 4: Описание ниши\n\n"
        "Опиши, кого ищем — это поможет точнее квалифицировать лидов.\n\n"
        "💡 Например: «селлеры wildberries и ozon, малый бизнес, ищут автоматизацию»",
        reply_markup=get_step_keyboard(back_callback="name")
    )

@router.callback_query(F.data == "back_to_chats")
async def back_to_chats(callback: CallbackQuery, state: FSMContext):
    logging.info("FSM 'create_program': going back to 'enter_chats' step.")
    await state.set_state(ProgramCreate.enter_chats)
    data = await state.get_data()
    await callback.message.edit_text(
        f"➕ Новая программа: \"{data['name']}\"\n\n"
        "💬 Шаг 3 из 4: Чаты для парсинга\n\n"
        "Отправь список чатов, из которых собирать лидов.\n"
        "Можно несколько в одном сообщении, каждый с новой строки.\n\n"
        "📌 Формат: `@username` или `t.me/username`",
        reply_markup=get_step_keyboard(back_callback="niche_description")
    )


# --- Finalization and Cancellation ---
@router.callback_query(F.data == "save_program", StateFilter(ProgramCreate.confirm_settings))
async def save_program(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    logging.info(f"Saving new program with data: {data}")

    user = await session.get(User, callback.from_user.id)
    if not user:
        await callback.answer(
            "Профиль не найден. Откройте главное меню и попробуйте снова.",
            show_alert=True,
        )
        return

    allowed, reason = await check_program_limit(session, user)
    if not allowed:
        await callback.answer(reason, show_alert=True)
        return

    owner_chat_id = callback.from_user.id
    new_program = Program(
        user_id=callback.from_user.id,
        name=data['name'],
        niche_description=data['niche_description'],
        auto_collect_enabled=False,
        owner_chat_id=owner_chat_id,
    )

    for chat_username in data.get('chats', []):
        new_program.chats.append(ProgramChat(chat_username=chat_username))

    session.add(new_program)
    await session.commit()
    await session.refresh(new_program)

    schedule_program_job(new_program.id, owner_chat_id, new_program.schedule_time)

    await state.clear()
    logging.info(f"Successfully saved new program with id={new_program.id}")
    
    chats_count = len(data.get('chats', []))
    await callback.message.edit_text(
        "🎉 Программа создана!\n\n"
        f"📁 {new_program.name}\n"
        f"• 💬 {chats_count} чата(ов)\n"
        f"• 🏆 Скор ≥{new_program.min_score}\n"
        f"• ⏰ Запуск: ежедневно в {new_program.schedule_time}\n\n"
        "🔜 Первый автозапуск: завтра в 09:00",
        reply_markup=get_main_menu_keyboard(callback.from_user.language_code)
    )
    await callback.answer("Программа успешно создана!")

@router.callback_query(F.data == "cancel_create_program")
async def cancel_creation(callback: CallbackQuery, state: FSMContext):
    """Cancels the program creation process."""
    logging.info("User cancelled program creation.")
    locale = get_locale(callback.from_user.language_code)
    await state.clear()
    await callback.message.edit_text(
        get_main_menu_text(callback.from_user.language_code),
        reply_markup=get_main_menu_keyboard(callback.from_user.language_code),
    )
    await callback.answer(
        pick(
            locale,
            "❌ Создание программы отменено.",
            "❌ Program creation cancelled.",
        )
    )
