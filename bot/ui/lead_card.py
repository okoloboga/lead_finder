from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.lead import Lead # Import Lead for type hinting

def get_lead_card_keyboard(lead_id: int) -> InlineKeyboardMarkup:
    """Returns an empty keyboard since all info is in the card now."""
    builder = InlineKeyboardBuilder()
    # No buttons needed - message is already in the card
    return builder.as_markup()

def format_lead_card(lead: Lead, index: int, total: int) -> str:
    """Formats a Lead object into a message string for the bot."""
    # Use lead.program.name if the program relationship is eagerly loaded
    program_name = lead.program.name if lead.program else "N/A"

    # Extract additional details from raw_qualification_data
    raw_data = lead.raw_qualification_data or {}
    identification = raw_data.get("identification") or {}
    qualification = raw_data.get("qualification") or {}
    product_idea = raw_data.get("product_idea") or {}

    # Build the card
    card = (
        f"🎯 Лид #{index} из {total}\n"
        f"Программа: {program_name}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"👤 @{lead.telegram_username}\n"
        f"⭐ Оценка: {lead.qualification_score}/5\n"
    )

    # Add reasoning if available
    reasoning = qualification.get("reasoning")
    if reasoning:
        card += f"💭 {reasoning}\n"

    card += "\n"

    # Business info with scale
    business_scale = identification.get("business_scale")
    card += f"💼 Бизнес:\n{lead.business_summary or 'Нет данных'}"
    if business_scale:
        card += f" ({business_scale})"
    card += "\n\n"

    # Pains
    card += f"😤 Боли:\n{lead.pains_summary or 'Нет данных'}\n\n"

    # Solution idea with value
    card += f"💡 Что предложить:\n{lead.solution_idea or 'Нет данных'}\n"

    pain_addressed = product_idea.get("pain_addressed")
    estimated_value = product_idea.get("estimated_value")

    if pain_addressed:
        card += f"✅ Решает: {pain_addressed}\n"
    if estimated_value:
        card += f"💰 Ценность: {estimated_value}\n"

    # Add outreach message
    if lead.recommended_message:
        card += f"\n📝 Сообщение для @{lead.telegram_username}:\n"
        card += "━━━━━━━━━━━━━\n\n"
        card += f"{lead.recommended_message}\n"

    return card