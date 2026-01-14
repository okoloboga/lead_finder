import json
import logging
import time
from typing import Dict, Any, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

import config

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize LLM once at the module level to save memory
try:
    llm = ChatOpenAI(
        openai_api_key=config.COMET_API_KEY,
        openai_api_base=config.COMET_API_BASE_URL,
        model=config.COMET_API_MODEL,
        temperature=0.5,
        request_timeout=60
    )
    logger.info("LLM client initialized successfully.")
except Exception as e:
    llm = None
    logger.error(f"Failed to initialize LLM client: {e}")


def load_qualification_prompt() -> str:
    """Loads the v2 qualification prompt from the file."""
    try:
        with open('prompts/qualification_v2.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(
            "Qualification prompt file not found at 'prompts/qualification_v2.txt'"
        )
        return ""


def get_freshness_emoji(freshness: str) -> str:
    """Get emoji indicator for message freshness."""
    return {
        "hot": "🔥",
        "warm": "",
        "cold": "⚠️",
        "stale": "🥶"
    }.get(freshness, "")


def format_messages_with_metadata(messages: List[Dict[str, Any]]) -> str:
    """Format messages with their links and freshness for the prompt."""
    if not messages:
        return ""

    lines = ["--- Сообщения пользователя в чате (с датами и ссылками) ---"]

    for msg in messages:
        freshness = msg.get("freshness", "unknown")
        emoji = get_freshness_emoji(freshness)
        age = msg.get("age_display", "дата неизвестна")
        text = msg.get("text", "")[:200]  # Limit text length
        link = msg.get("link", "")
        chat = msg.get("chat_username", "private chat")

        if emoji:
            line = f'- {emoji} [{age}] "{text}"'
        else:
            line = f'- [{age}] "{text}"'

        if link:
            line += f"\n  📍 {chat} | 🔗 {link}"

        lines.append(line)

    return "\n".join(lines) + "\n\n"


def format_enrichment_data_for_prompt(
    enrichment_data: Dict[str, Any],
    candidate_data: dict
) -> str:
    """Formats the enrichment data into a string for the LLM prompt."""
    prompt_text = ""

    # Use messages_with_metadata if available (new format)
    messages_with_metadata = candidate_data.get("messages_with_metadata", [])
    if messages_with_metadata:
        prompt_text += format_messages_with_metadata(messages_with_metadata)
    else:
        # Fallback to old format (sample_messages)
        sample_messages = candidate_data.get("sample_messages", [])
        if sample_messages:
            prompt_text += "--- Примеры сообщений пользователя в чате ---\n"
            for msg in sample_messages:
                prompt_text += f'- "{msg}"\n'
            prompt_text += "\n"

    if enrichment_data.get("channel_data"):
        ch_data = enrichment_data["channel_data"].get("entity_data", {})
        prompt_text += "--- Данные с личного Telegram-канала ---\n"
        prompt_text += f"Название: {ch_data.get('title', 'N/A')}\n"
        prompt_text += f"Подписчиков: {ch_data.get('participants_count', 'N/A')}\n"
        prompt_text += f"Описание: {ch_data.get('about', 'N/A')}\n\n"

    if enrichment_data.get("web_search_data"):
        web_data = enrichment_data["web_search_data"]
        prompt_text += "--- Данные из веб-поиска ---\n"
        if web_data.get('website'):
            prompt_text += f"Найденный сайт: {web_data['website']}\n"
        mentions_str = "\n".join([
            f'- {m.get("title", "")} ({m.get("source", "")})'
            for m in web_data.get("mentions", [])
        ])
        if mentions_str:
            prompt_text += f"Упоминания в сети:\n{mentions_str}\n"
        prompt_text += "\n"

    return prompt_text


def calculate_freshness_bonus(candidate_data: dict) -> int:
    """
    Calculate scoring bonus based on message freshness.

    Returns bonus points to add to the base LLM score.
    """
    bonus = 0
    messages = candidate_data.get("messages_with_metadata", [])

    if not messages:
        return 0

    # Bonus for having any messages (indicates activity)
    has_messages = len(messages) > 0
    if has_messages:
        bonus += config.FRESHNESS_SCORE_BONUS.get("has_pain_message", 0)

    # Bonus for fresh messages (< 3 days)
    has_fresh = any(m.get("freshness") == "hot" for m in messages)
    if has_fresh:
        bonus += config.FRESHNESS_SCORE_BONUS.get("fresh_message", 0)

    # Bonus for multiple messages (indicates engaged user)
    if len(messages) >= 3:
        bonus += config.FRESHNESS_SCORE_BONUS.get("multiple_pain_messages", 0)

    return bonus


def get_freshness_summary(candidate_data: dict) -> Dict[str, Any]:
    """Get summary of message freshness for the lead card."""
    messages = candidate_data.get("messages_with_metadata", [])

    if not messages:
        return {
            "total_messages": 0,
            "has_hot": False,
            "has_warm": False,
            "freshest_age": None,
            "can_reply_in_chat": False
        }

    freshness_counts = {"hot": 0, "warm": 0, "cold": 0, "stale": 0}
    for msg in messages:
        freshness = msg.get("freshness", "stale")
        if freshness in freshness_counts:
            freshness_counts[freshness] += 1

    # Can reply in chat if any message has a link
    can_reply = any(msg.get("link") for msg in messages)

    return {
        "total_messages": len(messages),
        "has_hot": freshness_counts["hot"] > 0,
        "has_warm": freshness_counts["warm"] > 0,
        "freshest_age": messages[0].get("age_display") if messages else None,
        "can_reply_in_chat": can_reply,
        "freshness_breakdown": freshness_counts
    }


def qualify_lead(
    candidate_data: dict,
    enrichment_data: dict,
    niche: str
) -> dict:
    """
    Qualifies a lead using the pre-initialized LLM.

    Applies freshness bonuses to the score and returns comprehensive results.
    """
    if not llm:
        return {"error": "LLM client is not initialized."}

    prompt_template = load_qualification_prompt()
    if not prompt_template:
        return {"error": "Could not load qualification prompt."}

    # Build input data
    input_data = (
        "--- Профиль пользователя в Telegram ---\n"
        f"Ниша, в которой он найден: {niche}\n"
        f"Имя: {candidate_data.get('first_name', '')} "
        f"{candidate_data.get('last_name', '')}\n"
        f"Username: @{candidate_data.get('username', 'N/A')}\n"
        f"Био: {candidate_data.get('bio', 'N/A')}\n"
        f"Сообщений в чате-источнике: "
        f"{candidate_data.get('messages_in_chat', 'N/A')}\n\n"
    )
    input_data += format_enrichment_data_for_prompt(enrichment_data, candidate_data)

    system_message = SystemMessage(
        content=(
            "You are a business analyst expert in B2B lead qualification. "
            "Analyze the profile and provide a structured JSON output based "
            "on the provided schema. Do not add any text before or after "
            "the JSON object."
        )
    )
    human_message = HumanMessage(
        content=f"{prompt_template}\n\nВот полные данные для анализа:\n{input_data}"
    )

    try:
        username = candidate_data.get('username', 'N/A')
        logger.info(f"Qualifying lead: @{username}. Waiting for LLM...")

        start_time = time.time()
        response = llm.invoke([system_message, human_message])
        end_time = time.time()
        duration = end_time - start_time

        logger.info(
            f"LLM response received for @{username}. "
            f"Call duration: {duration:.2f} seconds."
        )

        # Parse JSON response
        json_response_str = (
            response.content.strip()
            .lstrip("```json")
            .rstrip("```")
            .strip()
        )

        parsed_response = json.loads(json_response_str)
        logger.info(f"Successfully parsed LLM response for @{username}")

        # Calculate freshness bonus
        freshness_bonus = calculate_freshness_bonus(candidate_data)
        freshness_summary = get_freshness_summary(candidate_data)

        # Get base score from LLM
        base_score = 0
        qualification = parsed_response.get("qualification", {})
        if isinstance(qualification, dict):
            base_score = qualification.get("score", 0)

        # Apply bonus (cap at 10)
        final_score = min(10, base_score + freshness_bonus)

        # Update the qualification result with adjusted score
        if isinstance(qualification, dict):
            qualification["base_score"] = base_score
            qualification["freshness_bonus"] = freshness_bonus
            qualification["score"] = final_score
            parsed_response["qualification"] = qualification

        # Add freshness metadata
        parsed_response["freshness_summary"] = freshness_summary

        return {
            "llm_response": parsed_response,
            "raw_input_prompt": input_data,
            # Flatten for backward compatibility
            **parsed_response
        }

    except json.JSONDecodeError as e:
        username = candidate_data.get('username', 'N/A')
        logger.error(
            f"Failed to decode JSON from LLM response for @{username}: {e}"
        )
        logger.error(f"Raw response content: {response.content[:500]}")
        return {"error": "JSONDecodeError", "raw_response": response.content}
    except Exception as e:
        username = candidate_data.get('username', 'N/A')
        logger.error(
            f"An error occurred during lead qualification for @{username}: {e}"
        )
        return {"error": str(e)}


if __name__ == '__main__':
    print("Qualifier module v2. To be tested as part of the main pipeline.")
