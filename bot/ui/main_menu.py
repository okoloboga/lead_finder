from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN_MENU_TEXT = """
🎯 Lead Finder

Нахожу потенциальных клиентов в Telegram-чатах
и присылаю тебе готовые карточки для аутрича.
"""

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns inline keyboard for the main menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои программы", callback_data="my_programs")
    builder.button(text="🔥 Боли и контент", callback_data="pains_menu")
    builder.button(text="💎 Подписка", callback_data="subscription_menu")
    builder.adjust(1)  # Adjust to 1 button per row
    return builder.as_markup()
