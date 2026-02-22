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
        ch_data = (enrichment_data["channel_data"] or {}).get("entity_data") or {}
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
    niche: str,
    ai_ideas: str = "",
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
    if ai_ideas:
        input_data += ai_ideas

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

        # Get freshness summary for metadata (display only)
        freshness_summary = get_freshness_summary(candidate_data)

        # Get score from LLM
        qualification = parsed_response.get("qualification") or {}
        if isinstance(qualification, dict):
            llm_score = qualification.get("score", 0)
        else:
            llm_score = 0

        # Apply penalty: force score = 0 if LLM indicates we can't solve the problem
        reasoning = qualification.get("reasoning", "").lower()

        # Indicators that we CAN'T solve the problem with our bot
        cant_solve_indicators = [
            "не можем решить", "не можем сделать", "не можем закрыть",
            "не решается ботом", "не решается нашим", "не решается telegram",
            "не подходит для бота", "бот не может", "бот не решает",
            "нет api", "недоступен api", "api отсутствует", "нет доступа к api",
            "нет интеграции", "недоступна интеграция",
            "методологическая проблема", "бухгалтерская проблема",
            "не процесс", "не решается через", "недоступных api",
            "нужна интеграция с", "требует интеграции с",
            "нет конкретной боли", "не выявлено конкретной боли",
            "боли не выявлено", "боли отсутствуют"
        ]

        # Indicators that pain is vague/assumed (should also be score 0)
        vague_indicators = [
            "нет болей", "нет прямых болей", "не видно болей",
            "боли предполагаемые", "боли не очевидны",
            "типичные боли", "вероятные боли", "косвенные боли",
            "боли типичные для", "предположительно", "вероятно владелец"
        ]

        has_cant_solve = any(indicator in reasoning for indicator in cant_solve_indicators)
        has_vague_reasoning = any(indicator in reasoning for indicator in vague_indicators)

        final_score = llm_score

        if has_cant_solve or has_vague_reasoning:
            # Force score to 0 if we can't solve or pain is vague
            final_score = 0
            logger.info(
                f"Forcing score to 0 for @{candidate_data.get('username')} "
                f"due to: {'cant_solve' if has_cant_solve else 'vague_reasoning'}. "
                f"Reasoning: {reasoning[:150]}"
            )

        # Update the qualification result with final score
        if isinstance(qualification, dict):
            qualification["llm_score"] = llm_score
            qualification["score"] = final_score
            qualification["penalty_applied"] = has_cant_solve or has_vague_reasoning
            qualification["penalty_reason"] = "cant_solve" if has_cant_solve else ("vague" if has_vague_reasoning else None)
            parsed_response["qualification"] = qualification

        # Add freshness metadata (for display, not scoring)
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


def load_batch_analysis_prompt() -> str:
    """Loads the batch chat analysis prompt from the file."""
    try:
        with open('prompts/chat_batch_analysis.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(
            "Batch analysis prompt file not found at 'prompts/chat_batch_analysis.txt'"
        )
        return ""


def batch_analyze_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyzes an entire chat's messages in one LLM call to identify potential leads.

    This is the first stage of two-stage qualification:
    1. Batch screening (this function) - identifies candidates with pain/problems
    2. Detailed analysis (qualify_lead) - full qualification of selected candidates

    Args:
        messages: List of message dictionaries with keys:
            - username: str (e.g., "@username")
            - text: str (message text)
            - date: str (ISO format date)
            - messages_count: int (total messages from this user)

    Returns:
        Dictionary with:
        - potential_leads: List[Dict] with username, priority, pain_summary, etc.
        - filtering_stats: Dict with analysis statistics
        - error: str (if error occurred)
    """
    if not llm:
        return {"error": "LLM client is not initialized.", "potential_leads": []}

    prompt_template = load_batch_analysis_prompt()
    if not prompt_template:
        return {
            "error": "Could not load batch analysis prompt.",
            "potential_leads": []
        }

    # Format messages for the prompt
    messages_json = json.dumps(messages, ensure_ascii=False, indent=2)

    system_message = SystemMessage(
        content=(
            "You are a business analyst expert in B2B lead identification. "
            "Analyze the provided chat messages and identify potential leads "
            "for Telegram bot development services. "
            "Return ONLY valid JSON as specified in the prompt."
        )
    )
    human_message = HumanMessage(
        content=f"{prompt_template}\n\nСообщения для анализа:\n{messages_json}"
    )

    try:
        logger.info(
            f"Starting batch analysis of {len(messages)} messages. Waiting for LLM..."
        )

        start_time = time.time()
        response = llm.invoke([system_message, human_message])
        end_time = time.time()
        duration = end_time - start_time

        logger.info(
            f"Batch analysis LLM response received. "
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
        logger.info(
            f"Successfully parsed batch analysis. "
            f"Found {len(parsed_response.get('potential_leads', []))} potential leads."
        )

        return parsed_response

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from batch analysis LLM response: {e}")
        logger.error(f"Raw response content: {response.content[:500]}")
        return {
            "error": "JSONDecodeError",
            "raw_response": response.content,
            "potential_leads": []
        }
    except Exception as e:
        logger.error(f"An error occurred during batch chat analysis: {e}")
        return {"error": str(e), "potential_leads": []}


if __name__ == '__main__':
    print("Qualifier module v2. To be tested as part of the main pipeline.")
