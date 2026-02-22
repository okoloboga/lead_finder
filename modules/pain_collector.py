"""Pain Collector: extracts entrepreneur pains from chat messages using LLM."""
import asyncio
import json
import logging
import random
from datetime import datetime
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
    prompt = prompt_template.format(chat_name=chat_name, messages=messages_json)

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
            original_quote = raw.get("original_quote", "")
            source_chat = source_msg.get("chat_username") or ""

            # Deduplication check
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

            raw_date = source_msg.get("date")
            msg_date: datetime | None = None
            if raw_date:
                try:
                    msg_date = datetime.fromisoformat(raw_date)
                except ValueError:
                    pass

            pain = Pain(
                program_id=program_id,
                text=raw.get("text", ""),
                original_quote=original_quote,
                category=raw.get("category", "other"),
                intensity=raw.get("intensity", "low"),
                business_type=raw.get("business_type"),
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
