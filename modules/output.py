import json
import os
import datetime
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def get_timestamped_filename(niche_slug: str, extension: str) -> str:
    """Generates a filename with a timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"leads_{niche_slug}_{timestamp}.{extension}"


def append_to_jsonl(lead: dict, filepath: str) -> None:
    """Appends a single lead object to a .jsonl file."""
    try:
        # Serialize datetime objects
        serializable_lead = _make_json_serializable(lead)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(serializable_lead, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.error(f"Error appending to JSONL report {filepath}: {e}")


def _make_json_serializable(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO format strings."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_json_serializable(item) for item in obj]
    return obj


def _get_freshness_emoji(freshness: str) -> str:
    """Get emoji indicator for message freshness."""
    return {
        "hot": "🔥",
        "warm": "",
        "cold": "⚠️",
        "stale": "🥶"
    }.get(freshness, "")


def _format_messages_with_links(messages: List[Dict[str, Any]]) -> str:
    """Format messages with their links and freshness for markdown."""
    if not messages:
        return ""

    lines = []
    for msg in messages:
        freshness = msg.get("freshness", "unknown")
        emoji = _get_freshness_emoji(freshness)
        age = msg.get("age_display", "дата неизвестна")
        text = msg.get("text", "")[:150]  # Limit text for readability
        if len(msg.get("text", "")) > 150:
            text += "..."
        link = msg.get("link", "")
        chat = msg.get("chat_username", "приватный чат")

        # Format message block
        if emoji:
            lines.append(f"💬 {emoji} **[{age}]** \"{text}\"")
        else:
            lines.append(f"💬 **[{age}]** \"{text}\"")

        # Add link if available
        if link:
            lines.append(f"   📍 @{chat} • [Открыть →](https://{link})")
        else:
            lines.append(f"   📍 @{chat}")

        lines.append("")  # Empty line between messages

    return "\n".join(lines)


def format_lead_as_markdown(lead: dict, lead_index: int) -> str:
    """Formats a single lead into a markdown string with message links."""
    qual_result = lead.get("qualification_result", {})
    qual = qual_result.get("qualification", {})
    identification = qual_result.get("identification", {})
    pains = qual_result.get("identified_pains", [])
    idea = qual_result.get("product_idea", {})
    outreach = qual_result.get("outreach", {})
    contact = lead.get("contact", {})
    enrichment = lead.get("enrichment_data", {})
    channel_entity_data = enrichment.get("channel_data", {}).get("entity_data", {})

    # Get message metadata
    messages = lead.get("messages_with_links", [])
    has_fresh = lead.get("has_fresh_message", False)
    freshness_summary = qual_result.get("freshness_summary", {})

    # Score info
    score = qual.get('score', 'N/A')
    base_score = qual.get('base_score')
    freshness_bonus = qual.get('freshness_bonus', 0)

    # Header with score
    md_block = f"## Лид #{lead_index}"
    if has_fresh:
        md_block += " 🔥"  # Hot lead indicator
    md_block += f" — Оценка: {score}/10"
    if base_score is not None and freshness_bonus > 0:
        md_block += f" (базовая: {base_score} + бонус за свежесть: {freshness_bonus})"
    md_block += "\n\n"

    # Contact info
    md_block += f"**Контакт:** {contact.get('telegram_username', 'N/A')}\n"
    if contact.get('telegram_channel'):
        subscribers = channel_entity_data.get('participants_count', 'N/A')
        md_block += f"**Канал:** {contact.get('telegram_channel')}"
        if subscribers != 'N/A':
            md_block += f" ({subscribers} подписчиков)"
        md_block += "\n"
    md_block += "\n"

    # Business info
    md_block += "### 💼 Бизнес\n"
    md_block += f"{identification.get('business_type', 'N/A')}. "
    md_block += f"Масштаб: {identification.get('business_scale', 'N/A')}.\n\n"

    # Messages with links (new section)
    if messages:
        md_block += "### 💬 Сообщения из чатов\n"
        can_reply = freshness_summary.get("can_reply_in_chat", False)
        if can_reply:
            md_block += (
                "*💡 Совет: Ответьте на сообщение в чате — "
                "это безопаснее и эффективнее, чем писать в личку.*\n\n"
            )
        md_block += _format_messages_with_links(messages)
        md_block += "\n"

    # Identified pains
    md_block += "### 😤 Выявленные боли\n"
    if pains:
        for pain in pains:
            md_block += f"- {pain}\n"
    else:
        md_block += "Боли не выявлены.\n"
    md_block += "\n"

    # Solution idea
    md_block += "### 💡 Идея решения\n"
    if idea and idea.get('idea'):
        md_block += f"**{idea.get('idea', 'N/A')}**\n"
        if idea.get('pain_addressed'):
            md_block += f"- Закрываемая боль: {idea.get('pain_addressed')}\n"
        if idea.get('estimated_value'):
            md_block += f"- Ценность: {idea.get('estimated_value')}\n"
    else:
        md_block += "Идеи не сгенерированы.\n"
    md_block += "\n"

    # Outreach message
    md_block += "### 📝 Рекомендованное сообщение\n"
    message = outreach.get('message', 'N/A')
    if message and message != 'N/A':
        formatted_message = message.replace('\n', '\n> ')
        md_block += f"> {formatted_message}\n"
    else:
        md_block += "Сообщение не сгенерировано.\n"
    md_block += "\n"

    # Outreach options
    md_block += "### 🎯 Варианты связи\n"
    username = contact.get('telegram_username', '').replace('@', '')
    if username:
        md_block += f"- [📱 Написать в личку](https://t.me/{username})\n"

    if messages:
        # Find best message to reply to
        hot_msgs = [m for m in messages if m.get("freshness") == "hot"]
        if hot_msgs and hot_msgs[0].get("link"):
            best_link = hot_msgs[0]["link"]
            md_block += f"- [💬 Ответить в чате](https://{best_link}) *(рекомендуется)*\n"
        elif messages[0].get("link"):
            best_link = messages[0]["link"]
            md_block += f"- [💬 Ответить в чате](https://{best_link})\n"

    md_block += "\n---\n\n"

    return md_block


def initialize_markdown_file(filepath: str, niche: str) -> None:
    """Writes the header to the markdown file."""
    if os.path.exists(filepath):
        return  # Header already exists

    report_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# 🎯 Lead Finder Report\n\n"
    header += f"**Дата:** {report_date}\n"
    header += f"**Источник:** {niche}\n\n"
    header += "### Легенда\n"
    header += "- 🔥 Свежее сообщение (< 3 дней) — горячий лид\n"
    header += "- ⚠️ Остывающее сообщение (> 14 дней)\n"
    header += "- 🥶 Холодное сообщение (> 30 дней)\n\n"
    header += "---\n\n"

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(header)
    except Exception as e:
        logger.error(f"Error initializing Markdown report {filepath}: {e}")


def append_to_markdown(lead: dict, lead_index: int, filepath: str) -> None:
    """Appends a single formatted lead to a .md file."""
    try:
        md_block = format_lead_as_markdown(lead, lead_index)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(md_block)
    except Exception as e:
        logger.error(f"Error appending to Markdown report {filepath}: {e}")


def format_lead_summary(lead: dict) -> str:
    """Format a short summary of the lead for console output."""
    contact = lead.get("contact", {})
    qual = lead.get("qualification_result", {}).get("qualification", {})
    score = qual.get("score", "?")
    has_fresh = lead.get("has_fresh_message", False)

    username = contact.get("telegram_username", "unknown")
    indicators = ""
    if has_fresh:
        indicators += "🔥"

    messages = lead.get("messages_with_links", [])
    if messages:
        indicators += "💬"

    return f"{username} ⭐{score} {indicators}".strip()
