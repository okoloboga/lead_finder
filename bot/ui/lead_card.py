from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape

from bot.models.lead import Lead

_STATUS_LABEL = {
    "new": "",
    "contacted": "✅ Написал",
    "skipped": "❌ Пропущен",
}


def get_lead_card_keyboard(lead_id: int, status: str = "new") -> InlineKeyboardMarkup:
    """Returns outreach action buttons based on current lead status."""
    builder = InlineKeyboardBuilder()
    if status == "new":
        builder.button(text="✅ Написал", callback_data=f"lead_contacted_{lead_id}")
        builder.button(text="❌ Пропустить", callback_data=f"lead_skipped_{lead_id}")
        builder.adjust(2)
    elif status == "skipped":
        builder.button(text="↩️ Вернуть", callback_data=f"lead_restore_{lead_id}")
        builder.adjust(1)
    # contacted — no action buttons needed
    return builder.as_markup()


def get_lead_navigation_keyboard(
    program_id: int,
    current_page: int,
    total_pages: int,
    lead_id: int,
    lead_status: str = "new",
) -> InlineKeyboardMarkup:
    """Pagination + outreach action buttons for the lead viewer."""
    builder = InlineKeyboardBuilder()

    # Outreach actions
    if lead_status == "new":
        builder.button(text="✅ Написал", callback_data=f"lead_contacted_{lead_id}")
        builder.button(text="❌ Пропустить", callback_data=f"lead_skipped_{lead_id}")
        builder.adjust(2)
    elif lead_status == "skipped":
        builder.button(text="↩️ Вернуть", callback_data=f"lead_restore_{lead_id}")
        builder.adjust(1)

    # Navigation
    nav_buttons = []
    if current_page > 0:
        builder.button(
            text="◀️ Назад",
            callback_data=f"lead_page_{program_id}_{current_page - 1}",
        )
        nav_buttons.append(1)
    builder.button(
        text=f"{current_page + 1}/{total_pages}", callback_data="noop"
    )
    nav_buttons.append(1)
    if current_page < total_pages - 1:
        builder.button(
            text="Вперёд ▶️",
            callback_data=f"lead_page_{program_id}_{current_page + 1}",
        )
        nav_buttons.append(1)

    builder.button(
        text="◀️ К программе", callback_data=f"show_program_{program_id}"
    )

    # Layout: action row(s), then nav row, then back
    action_count = 2 if lead_status == "new" else (1 if lead_status == "skipped" else 0)
    nav_count = len(nav_buttons)

    if action_count > 0:
        builder.adjust(action_count, nav_count, 1)
    else:
        builder.adjust(nav_count, 1)

    return builder.as_markup()


def format_lead_card(lead: Lead, index: int, total: int) -> str:
    """Formats a Lead object into a message string for the bot."""
    program_name = lead.program.name if lead.program else "N/A"

    raw_data = lead.raw_qualification_data or {}
    profile_data = lead.raw_user_profile_data or {}
    identification = raw_data.get("identification") or {}
    qualification = raw_data.get("qualification") or {}
    product_idea = raw_data.get("product_idea") or {}

    status_label = _STATUS_LABEL.get(lead.status, "")
    status_line = f"{status_label}\n" if status_label else ""

    card = (
        f"🎯 Лид #{index} из {total}\n"
        f"Программа: {program_name}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"👤 @{lead.telegram_username}\n"
        f"⭐ Оценка: {lead.qualification_score}/5\n"
        f"{status_line}"
    )

    reasoning = qualification.get("reasoning")
    if reasoning:
        card += f"💭 {reasoning}\n"

    card += "\n"

    business_scale = identification.get("business_scale")
    card += f"💼 Бизнес:\n{lead.business_summary or 'Нет данных'}"
    if business_scale:
        card += f" ({business_scale})"
    card += "\n\n"

    card += f"😤 Боли:\n{lead.pains_summary or 'Нет данных'}\n\n"

    source_chat_username = profile_data.get("source_chat_username")
    source_chat = profile_data.get("source_chat")
    source_chat_id = profile_data.get("source_chat_id")
    messages_in_chat = profile_data.get("messages_in_chat")
    messages_meta = profile_data.get("messages_with_metadata") or []

    chat_label = "не указан"
    if source_chat_username:
        chat_label = f"@{str(source_chat_username).lstrip('@')}"
    elif source_chat:
        chat_label = str(source_chat)
    elif source_chat_id:
        chat_label = f"id:{source_chat_id}"

    card += "📍 Источник:\n"
    card += f"• Чат: {chat_label}\n"
    if messages_in_chat:
        card += f"• Сообщений кандидата: {messages_in_chat}\n"
    card += "\n"

    if messages_meta:
        card += "💬 Сообщения из чата:\n"
        for msg in messages_meta[:3]:
            text = str(msg.get("text") or "").strip()
            text_short = text[:180] + ("..." if len(text) > 180 else "")
            age = msg.get("age_display")
            freshness = msg.get("freshness")
            link = msg.get("link")

            prefix = ""
            if freshness == "hot":
                prefix = "🔥 "

            age_label = f"[{age}] " if age else ""
            if text_short:
                card += f"• {prefix}{age_label}\"{escape(text_short)}\"\n"
            if link:
                link_value = str(link)
                if not link_value.startswith(("http://", "https://")):
                    link_value = f"https://{link_value}"
                card += f"  🔗 {link_value}\n"
        card += "\n"

    card += f"💡 Что предложить:\n{lead.solution_idea or 'Нет данных'}\n"

    pain_addressed = product_idea.get("pain_addressed")
    estimated_value = product_idea.get("estimated_value")
    if pain_addressed:
        card += f"✅ Решает: {pain_addressed}\n"
    if estimated_value:
        card += f"💰 Ценность: {estimated_value}\n"

    if lead.recommended_message:
        card += f"\n📝 Сообщение для @{lead.telegram_username}:\n"
        card += "━━━━━━━━━━━━━\n\n"
        card += f"{lead.recommended_message}\n"

    return card
