"""Pain Collector: extracts entrepreneur pains from chat messages using LLM."""
import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models.pain import Pain

logger = logging.getLogger(__name__)

_PROMPT_CACHE: str | None = None

try:
    _llm = ChatOpenAI(
        openai_api_key=config.COMET_API_KEY,
        openai_api_base=config.COMET_API_BASE_URL,
        model=config.COMET_API_MODEL,
        temperature=0.2,
        request_timeout=60,
    )
    logger.info("pain_collector: LLM client initialized.")
except Exception as _e:
    _llm = None
    logger.error(f"pain_collector: Failed to initialize LLM client: {_e}")


def _load_prompt() -> str:
    """Load and cache the pain extraction prompt template."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        with open("prompts/pain_extraction.txt", "r", encoding="utf-8") as f:
            _PROMPT_CACHE = f.read()
    return _PROMPT_CACHE


def _parse_llm_json(raw: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = (
            "\n".join(lines[1:-1])
            if lines[-1].strip() == "```"
            else "\n".join(lines[1:])
        )
        text = inner.strip()
    return json.loads(text)


def _normalize_text(
    value: Any, default: str | None = ""
) -> str | None:
    """Normalize potentially-null/non-string LLM field to a safe text value."""
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    return default


def _normalize_category(value: Any) -> str:
    """Return a valid pain category or fallback to 'other'."""
    allowed = {
        "operations",
        "sales",
        "communication",
        "analytics",
        "automation",
        "marketplace",
        "hiring",
        "finance",
        "legal",
        "other",
    }
    category = _normalize_text(value, "other").lower()
    return category if category in allowed else "other"


def _normalize_intensity(value: Any) -> str:
    """Return a valid intensity or fallback to 'low'."""
    allowed = {"low", "medium", "high"}
    intensity = _normalize_text(value, "low").lower()
    return intensity if intensity in allowed else "low"


def _parse_message_date(raw_date: Any) -> datetime | None:
    """Parse ISO date and normalize to UTC naive datetime for DB storage.

    DB columns use timestamp without timezone, so aware datetimes from Telegram
    must be converted to naive UTC to avoid asyncpg DataError.
    """
    if not raw_date or not isinstance(raw_date, str):
        return None

    try:
        msg_date = datetime.fromisoformat(raw_date)
    except ValueError:
        return None

    if msg_date.tzinfo is not None:
        msg_date = msg_date.astimezone(timezone.utc).replace(tzinfo=None)

    return msg_date


def _render_prompt(
    template: str,
    *,
    chat_name: str,
    messages: str,
) -> str:
    """Render prompt by replacing only known placeholders.

    We intentionally avoid str.format() because prompt templates contain JSON
    examples with many curly braces.
    """
    return (
        template
        .replace("{chat_name}", chat_name)
        .replace("{messages}", messages)
    )


async def _extract_pains_batch(
    messages_batch: list[dict],
    chat_name: str,
    prompt_template: str,
) -> list[dict[str, Any]]:
    """Call LLM asynchronously on one batch; return list of raw pain dicts."""
    if not _llm:
        logger.error("pain_collector: LLM not initialized, skipping batch.")
        return []

    formatted = [
        {"index": i, "text": msg["text"]}
        for i, msg in enumerate(messages_batch)
    ]
    messages_json = json.dumps(formatted, ensure_ascii=False, indent=2)
    prompt = _render_prompt(
        prompt_template,
        chat_name=chat_name,
        messages=messages_json,
    )

    try:
        response = await _llm.ainvoke([HumanMessage(content=prompt)])
        result = _parse_llm_json(response.content)
        pains = result.get("pains", [])
        logger.info(f"pain_collector: Batch returned {len(pains)} pains.")
        return pains
    except json.JSONDecodeError as e:
        logger.warning(f"pain_collector: JSON parse error in batch: {e}")
        return []
    except Exception as e:
        logger.error(f"pain_collector: LLM call failed: {e}")
        return []


async def collect_pains(
    all_messages: list[dict],
    program_id: int,
    chat_name: str,
    session: AsyncSession,
) -> int:
    """Extract pains from chat messages and persist new ones to the DB.

    Args:
        all_messages: All text messages collected from a chat (from members_parser).
        program_id: The program this collection run belongs to.
        chat_name: Display name of the chat (used in the prompt).
        session: Active async SQLAlchemy session.

    Returns:
        Number of new Pain records inserted.
    """
    if not config.PAIN_COLLECTION_ENABLED:
        logger.info("pain_collector: Disabled via config, skipping.")
        return 0

    if not all_messages:
        logger.info("pain_collector: No messages to process.")
        return 0

    prompt_template = _load_prompt()
    batch_size = config.PAIN_BATCH_SIZE
    new_pains_count = 0
    total_batches = (len(all_messages) + batch_size - 1) // batch_size

    for batch_num, batch_start in enumerate(range(0, len(all_messages), batch_size)):
        batch = all_messages[batch_start : batch_start + batch_size]
        logger.info(
            f"pain_collector: Batch {batch_num + 1}/{total_batches} "
            f"({len(batch)} messages) from '{chat_name}'."
        )

        raw_pains = await _extract_pains_batch(batch, chat_name, prompt_template)

        for raw in raw_pains:
            idx = raw.get("source_message_index", 0)
            if not isinstance(idx, int) or idx < 0 or idx >= len(batch):
                logger.warning(
                    f"pain_collector: Invalid source_message_index={idx}, skipping."
                )
                continue

            source_msg = batch[idx]
            text = _normalize_text(raw.get("text"))
            original_quote = _normalize_text(raw.get("original_quote"))
            category = _normalize_category(raw.get("category"))
            intensity = _normalize_intensity(raw.get("intensity"))
            business_type = _normalize_text(raw.get("business_type"), None)
            source_chat = source_msg.get("chat_username") or ""

            # Skip malformed LLM rows that would violate NOT NULL constraints
            # or create unusable pain records.
            if not text or not original_quote:
                logger.debug(
                    "pain_collector: Skipping malformed pain row "
                    "(empty text/original_quote)."
                )
                continue

            # Deduplication check
            with session.no_autoflush:
                existing = (
                    await session.execute(
                        select(Pain).where(
                            Pain.source_message_id == source_msg["message_id"],
                            Pain.source_chat == source_chat,
                            Pain.original_quote == original_quote,
                        )
                    )
                ).scalars().first()

            if existing:
                continue

            msg_date = _parse_message_date(source_msg.get("date"))

            pain = Pain(
                program_id=program_id,
                text=text,
                original_quote=original_quote,
                category=category,
                intensity=intensity,
                business_type=business_type,
                source_chat=source_chat,
                source_message_id=source_msg["message_id"],
                source_message_link=source_msg.get("link"),
                message_date=msg_date,
            )
            session.add(pain)
            new_pains_count += 1

        await session.flush()

        # Delay between batches to respect rate limits
        if batch_num < total_batches - 1:
            min_d, max_d = config.get_delay("between_requests")
            await asyncio.sleep(random.uniform(min_d, max_d))

    if new_pains_count:
        await session.commit()
        logger.info(
            f"pain_collector: Saved {new_pains_count} new pains "
            f"from '{chat_name}' for program_id={program_id}."
        )

    return new_pains_count
