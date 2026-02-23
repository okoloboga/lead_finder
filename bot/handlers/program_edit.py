import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.models.program import Program, ProgramChat
from bot.scheduler import schedule_program_job, remove_program_job
from bot.states import ProgramEdit

logger = logging.getLogger(__name__)
router = Router()


def get_edit_menu_keyboard(program_id: int) -> InlineKeyboardMarkup:
    """Creates the edit menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data=f"edit_name_{program_id}")
    builder.button(text="🎯 Ниша", callback_data=f"edit_niche_{program_id}")
    builder.button(text="💬 Чаты", callback_data=f"edit_chats_{program_id}")
    builder.button(text="⚙️ Настройки", callback_data=f"edit_settings_{program_id}")
    builder.button(text="◀️ Назад", callback_data=f"show_program_{program_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_back_keyboard(program_id: int) -> InlineKeyboardMarkup:
    """Generic back button keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=f"edit_program_{program_id}")
    builder.adjust(1)
    return builder.as_markup()


def get_settings_keyboard(
    program_id: int,
    min_score: int,
    max_leads: int,
    enrich: bool,
    auto_collect: bool,
) -> InlineKeyboardMarkup:
    """Creates settings edit keyboard."""
    builder = InlineKeyboardBuilder()

    # Min score buttons
    for score in [1, 2, 3, 4, 5]:
        marker = "✅" if score == min_score else ""
        builder.button(text=f"{score}{marker}", callback_data=f"set_score_{program_id}_{score}")

    builder.adjust(5)  # All scores in one row

    # Max leads buttons
    for count in [10, 20, 50]:
        marker = "✅" if count == max_leads else ""
        builder.button(text=f"{count}{marker}", callback_data=f"set_max_{program_id}_{count}")

    builder.adjust(6, 3)  # Scores, then max leads

    # Web enrichment toggle
    enrich_text = "Web-обогащение: Вкл ✅" if enrich else "Web-обогащение: Выкл"
    builder.button(text=enrich_text, callback_data=f"toggle_enrich_{program_id}")
    auto_collect_text = (
        "Автосбор по расписанию: Вкл ✅"
        if auto_collect else
        "Автосбор по расписанию: Выкл"
    )
    builder.button(
        text=auto_collect_text,
        callback_data=f"toggle_autocollect_{program_id}",
    )

    # Save button
    builder.button(text="✅ Сохранить", callback_data=f"save_settings_{program_id}")
    builder.button(text="◀️ Назад", callback_data=f"edit_program_{program_id}")

    builder.adjust(5, 3, 1, 1, 1, 1)

    return builder.as_markup()


# --- Edit Menu ---

@router.callback_query(F.data.startswith("edit_program_"))
async def show_edit_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Shows the edit menu for a program."""
    program_id = int(callback.data.split("_")[-1])

    # Clear any existing state
    await state.clear()

    query = select(Program).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if not program:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    text = (
        f"✏️ Редактирование: {program.name}\n\n"
        "Что изменить?"
    )

    await callback.message.edit_text(text, reply_markup=get_edit_menu_keyboard(program_id))
    await callback.answer()


# --- Edit Name ---

@router.callback_query(F.data.startswith("edit_name_"))
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    """Starts name editing."""
    program_id = int(callback.data.split("_")[-1])

    await state.set_state(ProgramEdit.edit_name)
    await state.update_data(program_id=program_id)

    text = "📝 Введи новое название программы:"

    await callback.message.edit_text(text, reply_markup=get_back_keyboard(program_id))
    await callback.answer()


@router.message(ProgramEdit.edit_name)
async def edit_name_save(message: Message, state: FSMContext, session: AsyncSession):
    """Saves the new name."""
    data = await state.get_data()
    program_id = data.get("program_id")
    new_name = message.text.strip()

    if not new_name:
        await message.answer("Название не может быть пустым. Попробуй снова:")
        return

    query = select(Program).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if program:
        program.name = new_name
        await session.commit()
        await message.answer(f"✅ Название изменено на: {new_name}")

    await state.clear()

    # Show edit menu again
    text = f"✏️ Редактирование: {new_name}\n\nЧто ещё изменить?"
    await message.answer(text, reply_markup=get_edit_menu_keyboard(program_id))


# --- Edit Niche ---

@router.callback_query(F.data.startswith("edit_niche_"))
async def edit_niche_start(callback: CallbackQuery, state: FSMContext):
    """Starts niche editing."""
    program_id = int(callback.data.split("_")[-1])

    await state.set_state(ProgramEdit.edit_niche)
    await state.update_data(program_id=program_id)

    text = "🎯 Введи новое описание ниши:"

    await callback.message.edit_text(text, reply_markup=get_back_keyboard(program_id))
    await callback.answer()


@router.message(ProgramEdit.edit_niche)
async def edit_niche_save(message: Message, state: FSMContext, session: AsyncSession):
    """Saves the new niche description."""
    data = await state.get_data()
    program_id = data.get("program_id")
    new_niche = message.text.strip()

    if not new_niche:
        await message.answer("Описание не может быть пустым. Попробуй снова:")
        return

    query = select(Program).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if program:
        program.niche_description = new_niche
        await session.commit()
        await message.answer(f"✅ Описание ниши изменено")

    await state.clear()

    # Show edit menu again
    text = f"✏️ Редактирование: {program.name}\n\nЧто ещё изменить?"
    await message.answer(text, reply_markup=get_edit_menu_keyboard(program_id))


# --- Edit Chats ---

@router.callback_query(F.data.startswith("edit_chats_"))
async def edit_chats_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Shows current chats and allows adding/removing."""
    program_id = int(callback.data.split("_")[-1])

    query = select(Program).options(selectinload(Program.chats)).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if not program:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await state.set_state(ProgramEdit.edit_chats)
    await state.update_data(program_id=program_id)

    chats_list = "\n".join([f"• @{chat.chat_username}" for chat in program.chats]) if program.chats else "Чатов нет"

    text = (
        f"💬 Чаты программы: {program.name}\n\n"
        f"Текущие чаты:\n{chats_list}\n\n"
        "Отправь новые чаты для добавления (каждый с новой строки).\n"
        "Формат: @username или t.me/username\n\n"
        "Для удаления чата отправь: удалить @username"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data=f"done_chats_{program_id}")
    builder.button(text="◀️ Назад", callback_data=f"edit_program_{program_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.message(ProgramEdit.edit_chats)
async def edit_chats_process(message: Message, state: FSMContext, session: AsyncSession):
    """Processes chat add/remove commands."""
    data = await state.get_data()
    program_id = data.get("program_id")

    text = message.text.strip()

    query = select(Program).options(selectinload(Program.chats)).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if not program:
        await message.answer("Программа не найдена.")
        return

    # Check if it's a delete command
    if text.lower().startswith("удалить"):
        chat_username = text.replace("удалить", "").strip().lstrip("@")

        chat_to_delete = next((c for c in program.chats if c.chat_username == chat_username), None)
        if chat_to_delete:
            await session.delete(chat_to_delete)
            await session.commit()
            await message.answer(f"✅ Чат @{chat_username} удалён")
        else:
            await message.answer(f"❌ Чат @{chat_username} не найден")
    else:
        # Add new chats
        lines = text.split("\n")
        added = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Extract username
            chat_username = line.replace("t.me/", "").replace("@", "").strip()

            # Check if already exists
            exists = any(c.chat_username == chat_username for c in program.chats)
            if not exists:
                new_chat = ProgramChat(program_id=program_id, chat_username=chat_username)
                session.add(new_chat)
                added.append(f"@{chat_username}")

        if added:
            await session.commit()
            await message.answer(f"✅ Добавлено чатов: {', '.join(added)}")
        else:
            await message.answer("Чаты уже существуют или некорректный формат")


@router.callback_query(F.data.startswith("done_chats_"))
async def edit_chats_done(callback: CallbackQuery, state: FSMContext):
    """Finishes chat editing."""
    program_id = int(callback.data.split("_")[-1])
    await state.clear()

    text = "✏️ Редактирование\n\nЧто ещё изменить?"
    await callback.message.edit_text(text, reply_markup=get_edit_menu_keyboard(program_id))
    await callback.answer()


# --- Edit Settings ---

@router.callback_query(F.data.startswith("edit_settings_"))
async def edit_settings_show(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Shows settings editor."""
    program_id = int(callback.data.split("_")[-1])

    query = select(Program).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if not program:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await state.set_state(ProgramEdit.edit_settings)
    await state.update_data(
        program_id=program_id,
        min_score=program.min_score,
        max_leads=program.max_leads_per_run,
        enrich=program.enrich,
        auto_collect=program.owner_chat_id is not None,
    )

    text = (
        f"⚙️ Настройки программы: {program.name}\n\n"
        f"Минимальный скор: {program.min_score}\n"
        f"Лидов за запуск: {program.max_leads_per_run}\n"
        f"Web-обогащение: {'Вкл' if program.enrich else 'Выкл'}\n"
        f"Автосбор по расписанию: "
        f"{'Вкл' if program.owner_chat_id is not None else 'Выкл'}"
    )

    keyboard = get_settings_keyboard(
        program_id,
        program.min_score,
        program.max_leads_per_run,
        program.enrich,
        program.owner_chat_id is not None,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("set_score_"))
async def set_min_score(callback: CallbackQuery, state: FSMContext):
    """Updates min score in state."""
    parts = callback.data.split("_")
    program_id = int(parts[2])
    new_score = int(parts[3])

    data = await state.get_data()
    await state.update_data(min_score=new_score)

    text = (
        f"⚙️ Настройки программы\n\n"
        f"Минимальный скор: {new_score}\n"
        f"Лидов за запуск: {data.get('max_leads', 20)}\n"
        f"Web-обогащение: {'Вкл' if data.get('enrich', False) else 'Выкл'}\n"
        f"Автосбор по расписанию: "
        f"{'Вкл' if data.get('auto_collect', True) else 'Выкл'}"
    )

    keyboard = get_settings_keyboard(
        program_id,
        new_score,
        data.get('max_leads', 20),
        data.get('enrich', False),
        data.get('auto_collect', True),
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("set_max_"))
async def set_max_leads(callback: CallbackQuery, state: FSMContext):
    """Updates max leads in state."""
    parts = callback.data.split("_")
    program_id = int(parts[2])
    new_max = int(parts[3])

    data = await state.get_data()
    await state.update_data(max_leads=new_max)

    text = (
        f"⚙️ Настройки программы\n\n"
        f"Минимальный скор: {data.get('min_score', 5)}\n"
        f"Лидов за запуск: {new_max}\n"
        f"Web-обогащение: {'Вкл' if data.get('enrich', False) else 'Выкл'}\n"
        f"Автосбор по расписанию: "
        f"{'Вкл' if data.get('auto_collect', True) else 'Выкл'}"
    )

    keyboard = get_settings_keyboard(
        program_id,
        data.get('min_score', 5),
        new_max,
        data.get('enrich', False),
        data.get('auto_collect', True),
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_enrich_"))
async def toggle_enrichment(callback: CallbackQuery, state: FSMContext):
    """Toggles web enrichment setting."""
    program_id = int(callback.data.split("_")[-1])

    data = await state.get_data()
    new_enrich = not data.get('enrich', False)
    await state.update_data(enrich=new_enrich)

    text = (
        f"⚙️ Настройки программы\n\n"
        f"Минимальный скор: {data.get('min_score', 5)}\n"
        f"Лидов за запуск: {data.get('max_leads', 20)}\n"
        f"Web-обогащение: {'Вкл' if new_enrich else 'Выкл'}\n"
        f"Автосбор по расписанию: "
        f"{'Вкл' if data.get('auto_collect', True) else 'Выкл'}"
    )

    keyboard = get_settings_keyboard(
        program_id,
        data.get('min_score', 5),
        data.get('max_leads', 20),
        new_enrich,
        data.get('auto_collect', True),
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_autocollect_"))
async def toggle_auto_collect(callback: CallbackQuery, state: FSMContext):
    """Toggles scheduled auto-collection setting."""
    program_id = int(callback.data.split("_")[-1])

    data = await state.get_data()
    new_auto_collect = not data.get('auto_collect', True)
    await state.update_data(auto_collect=new_auto_collect)

    text = (
        f"⚙️ Настройки программы\n\n"
        f"Минимальный скор: {data.get('min_score', 5)}\n"
        f"Лидов за запуск: {data.get('max_leads', 20)}\n"
        f"Web-обогащение: {'Вкл' if data.get('enrich', False) else 'Выкл'}\n"
        f"Автосбор по расписанию: {'Вкл' if new_auto_collect else 'Выкл'}"
    )

    keyboard = get_settings_keyboard(
        program_id,
        data.get('min_score', 5),
        data.get('max_leads', 20),
        data.get('enrich', False),
        new_auto_collect,
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("save_settings_"))
async def save_settings(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Saves the settings to database."""
    program_id = int(callback.data.split("_")[-1])
    data = await state.get_data()

    query = select(Program).where(Program.id == program_id)
    program = (await session.execute(query)).scalars().first()

    if program:
        program.min_score = data.get('min_score', 5)
        program.max_leads_per_run = data.get('max_leads', 20)
        program.enrich = data.get('enrich', False)
        auto_collect = data.get('auto_collect', program.owner_chat_id is not None)
        if auto_collect:
            owner_chat_id = program.owner_chat_id or callback.from_user.id
            program.owner_chat_id = owner_chat_id
            schedule_program_job(program.id, owner_chat_id, program.schedule_time)
        else:
            program.owner_chat_id = None
            remove_program_job(program.id)
        await session.commit()

    await state.clear()
    await callback.answer("✅ Настройки сохранены", show_alert=True)

    text = "✏️ Редактирование\n\nЧто ещё изменить?"
    await callback.message.edit_text(text, reply_markup=get_edit_menu_keyboard(program_id))
