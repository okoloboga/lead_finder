"""Content Generator: generates Telegram post drafts from pain clusters."""
import asyncio
import json
import logging
import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models.pain import Pain, PainCluster, GeneratedPost
from modules.enrichment.web_search import search_ai_best_practices_for_cluster

logger = logging.getLogger(__name__)

_PROMPT_CACHE: str | None = None
DEFAULT_POST_TYPE = "single"
_POST_TYPE_LABELS = {
    "single": "Пост по кластеру боли",
    "scenario": "Сценарий",
    "insight": "Инсайт",
    "breakdown": "Разбор тренда",
}

try:
    _llm = ChatOpenAI(
        openai_api_key=config.COMET_API_KEY,
        openai_api_base=config.COMET_API_BASE_URL,
        model=config.COMET_API_POST_MODEL,
        temperature=0.7,
        request_timeout=90,
    )
    logger.info("content_generator: LLM client initialized.")
except Exception as _e:
    _llm = None
    logger.error(f"content_generator: Failed to initialize LLM client: {_e}")


def _load_prompt() -> str:
    """Load and cache the content generation prompt template."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        with open("prompts/content_generation.txt", "r", encoding="utf-8") as f:
            _PROMPT_CACHE = f.read()
    return _PROMPT_CACHE


def anonymize_quotes(quotes: list[str]) -> list[str]:
    """Remove usernames, profile links, and phone numbers from quotes.

    Args:
        quotes: Raw quote strings from the database.

    Returns:
        Sanitized quotes safe for inclusion in LLM prompts.
    """
    result = []
    for q in quotes:
        # Remove @username mentions
        q = re.sub(r"@\w+", "[автор]", q)
        # Remove t.me/... links
        q = re.sub(r"t\.me/\w+", "[ссылка]", q)
        # Remove https:// links
        q = re.sub(r"https?://\S+", "[ссылка]", q)
        # Remove phone numbers (loose pattern)
        q = re.sub(r"\+?[\d][\d\s\-\(\)]{8,}", "[телефон]", q)
        result.append(q.strip())
    return result


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


def _render_prompt(
    template: str,
    *,
    post_type: str,
    cluster_name: str,
    cluster_description: str,
    pain_count: int,
    sample_quotes: str,
    ai_best_practices: str,
) -> str:
    """Render prompt by replacing only known placeholders.

    We intentionally avoid str.format() because prompt templates contain JSON
    examples with many curly braces.
    """
    return (
        template
        .replace("{post_type}", post_type)
        .replace("{cluster_name}", cluster_name)
        .replace("{cluster_description}", cluster_description)
        .replace("{pain_count}", str(pain_count))
        .replace("{sample_quotes}", sample_quotes)
        .replace("{ai_best_practices}", ai_best_practices)
    )


async def generate_post(
    cluster_id: int,
    session: AsyncSession,
    post_type: str = DEFAULT_POST_TYPE,
) -> GeneratedPost:
    """Generate a draft Telegram post for a pain cluster.

    Args:
        cluster_id: ID of the PainCluster to generate a post for.
        post_type: Post type label key. Defaults to a single unified mode.
        session: Active async SQLAlchemy session.

    Returns:
        The saved GeneratedPost record (status="draft").

    Raises:
        ValueError: If cluster not found or LLM is unavailable.
        RuntimeError: If LLM call or JSON parsing fails.
    """
    if not _llm:
        raise ValueError("content_generator: LLM not initialized.")

    cluster = await session.get(PainCluster, cluster_id)
    if not cluster:
        raise ValueError(f"PainCluster {cluster_id} not found.")

    # Load sample quotes (up to 7)
    pains_result = await session.execute(
        select(Pain)
        .where(Pain.cluster_id == cluster_id)
        .order_by(Pain.intensity.desc())
        .limit(7)
    )
    pains = pains_result.scalars().all()

    raw_quotes = [p.original_quote for p in pains if p.original_quote]
    clean_quotes = anonymize_quotes(raw_quotes)
    sample_quotes = "\n".join(f"• «{q}»" for q in clean_quotes) if clean_quotes else "Нет цитат."

    post_type_label = _POST_TYPE_LABELS.get(post_type, post_type)
    ai_best_practices = await asyncio.to_thread(
        search_ai_best_practices_for_cluster,
        cluster.name,
        cluster.description,
        post_type_label,
    )

    prompt_template = _load_prompt()
    prompt = _render_prompt(
        prompt_template,
        post_type=post_type_label,
        cluster_name=cluster.name,
        cluster_description=cluster.description,
        pain_count=cluster.pain_count,
        sample_quotes=sample_quotes,
        ai_best_practices=ai_best_practices,
    )

    try:
        response = await _llm.ainvoke([HumanMessage(content=prompt)])
        result = _parse_llm_json(response.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"content_generator: JSON parse error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"content_generator: LLM call failed: {e}") from e

    title = result.get("title", "Без заголовка")[:500]
    body = result.get("body", "")
    hashtags = result.get("hashtags", [])
    if hashtags:
        body = body.rstrip() + "\n\n" + " ".join(hashtags)

    post = GeneratedPost(
        user_id=cluster.user_id,
        cluster_id=cluster_id,
        post_type=post_type,
        title=title,
        body=body,
        status="draft",
    )
    session.add(post)

    # Mark cluster as having a generated post
    cluster.post_generated = True

    await session.commit()
    await session.refresh(post)

    logger.info(
        f"content_generator: Generated {post_type} post (id={post.id}) "
        f"for cluster_id={cluster_id}."
    )
    return post
