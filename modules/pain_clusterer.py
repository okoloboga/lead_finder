"""Pain Clusterer: groups extracted pains into named clusters via LLM."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import config
from bot.models.pain import Pain, PainCluster

logger = logging.getLogger(__name__)

_PROMPT_CACHE: str | None = None
_INTENSITY_MAP = {"low": 1, "medium": 2, "high": 3}

try:
    _llm = ChatOpenAI(
        openai_api_key=config.COMET_API_KEY,
        openai_api_base=config.COMET_API_BASE_URL,
        model=config.COMET_API_MODEL,
        temperature=0.3,
        request_timeout=90,
    )
    logger.info("pain_clusterer: LLM client initialized.")
except Exception as _e:
    _llm = None
    logger.error(f"pain_clusterer: Failed to initialize LLM client: {_e}")


def _load_prompt() -> str:
    """Load and cache the pain clustering prompt template."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        with open("prompts/pain_clustering.txt", "r", encoding="utf-8") as f:
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


async def _update_cluster_stats(cluster_id: int, session: AsyncSession) -> None:
    """Recalculate pain_count, avg_intensity, first_seen, last_seen, and trend."""
    pains_result = await session.execute(
        select(Pain).where(Pain.cluster_id == cluster_id)
    )
    pains = pains_result.scalars().all()

    if not pains:
        return

    pain_count = len(pains)
    intensity_scores = [_INTENSITY_MAP.get(p.intensity, 1) for p in pains]
    avg_intensity = sum(intensity_scores) / len(intensity_scores)

    dates = [p.message_date for p in pains if p.message_date]
    first_seen = min(dates) if dates else None
    last_seen = max(dates) if dates else None

    # Trend: compare last 7 days vs previous 7 days
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=7)
    cutoff_prev = now - timedelta(days=14)

    def _aware(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt

    count_recent = sum(
        1 for p in pains
        if p.message_date and _aware(p.message_date) >= cutoff_recent
    )
    count_prev = sum(
        1 for p in pains
        if p.message_date
        and cutoff_prev <= _aware(p.message_date) < cutoff_recent
    )

    if count_prev == 0:
        trend = "stable"
    elif count_recent > count_prev * 1.2:
        trend = "growing"
    elif count_recent < count_prev * 0.8:
        trend = "declining"
    else:
        trend = "stable"

    cluster = await session.get(PainCluster, cluster_id)
    if cluster:
        cluster.pain_count = pain_count
        cluster.avg_intensity = round(avg_intensity, 2)
        cluster.first_seen = first_seen
        cluster.last_seen = last_seen
        cluster.trend = trend


async def cluster_new_pains(program_id: int, session: AsyncSession) -> int:
    """Assign unclustered pains to existing clusters or create new ones via LLM.

    Args:
        program_id: Only process pains belonging to this program.
        session: Active async SQLAlchemy session.

    Returns:
        Number of pains that were clustered.
    """
    if not config.PAIN_COLLECTION_ENABLED:
        return 0

    # Fetch unclustered pains
    unclustered_result = await session.execute(
        select(Pain).where(
            Pain.program_id == program_id,
            Pain.cluster_id.is_(None),
        )
    )
    unclustered = unclustered_result.scalars().all()

    if not unclustered:
        logger.info(f"pain_clusterer: No unclustered pains for program_id={program_id}.")
        return 0

    # Fetch existing clusters
    clusters_result = await session.execute(
        select(PainCluster).where(PainCluster.program_id == program_id)
    )
    existing_clusters = clusters_result.scalars().all()

    # Format existing clusters for the prompt
    if existing_clusters:
        clusters_text = "\n".join(
            f"- ID {c.id}: [{c.category}] \"{c.name}\" — {c.description}"
            for c in existing_clusters
        )
    else:
        clusters_text = "Кластеров пока нет. Создай новые."

    # Format new pains for the prompt
    new_pains_text = "\n".join(
        f"- ID {p.id}: [{p.category}] [{p.intensity}] \"{p.text}\" | Цитата: \"{p.original_quote[:100]}\""
        for p in unclustered
    )

    prompt_template = _load_prompt()
    prompt = prompt_template.format(
        existing_clusters=clusters_text,
        new_pains=new_pains_text,
    )

    if not _llm:
        logger.error("pain_clusterer: LLM not initialized.")
        return 0

    try:
        response = await _llm.ainvoke([HumanMessage(content=prompt)])
        result = _parse_llm_json(response.content)
    except json.JSONDecodeError as e:
        logger.warning(f"pain_clusterer: JSON parse error: {e}")
        return 0
    except Exception as e:
        logger.error(f"pain_clusterer: LLM call failed: {e}")
        return 0

    assignments: list[dict[str, Any]] = result.get("assignments", [])
    if not assignments:
        logger.info("pain_clusterer: LLM returned no assignments.")
        return 0

    # Map pain_id → Pain for fast lookup
    pain_by_id = {p.id: p for p in unclustered}
    # Track newly created clusters by their temp "new" key within this run
    new_clusters_cache: dict[str, PainCluster] = {}
    affected_cluster_ids: set[int] = set()
    clustered_count = 0

    for assignment in assignments:
        pain_id = assignment.get("pain_id")
        cluster_ref = assignment.get("cluster_id")

        pain = pain_by_id.get(pain_id)
        if not pain:
            logger.warning(f"pain_clusterer: Unknown pain_id={pain_id}, skipping.")
            continue

        if cluster_ref == "new":
            # Create a new cluster (or reuse if same name was already created this run)
            new_name = assignment.get("new_cluster_name", "Без названия")
            cache_key = new_name.lower().strip()

            if cache_key not in new_clusters_cache:
                new_cluster = PainCluster(
                    program_id=program_id,
                    name=new_name,
                    category=assignment.get("new_cluster_category", "other"),
                    description=assignment.get("new_cluster_description", ""),
                    pain_count=0,
                    avg_intensity=0.0,
                )
                session.add(new_cluster)
                await session.flush()  # Get the auto-generated id
                new_clusters_cache[cache_key] = new_cluster
                logger.info(
                    f"pain_clusterer: Created new cluster '{new_name}' "
                    f"(id={new_cluster.id})."
                )
            cluster = new_clusters_cache[cache_key]
            pain.cluster_id = cluster.id
            affected_cluster_ids.add(cluster.id)
            clustered_count += 1

        elif isinstance(cluster_ref, int):
            pain.cluster_id = cluster_ref
            affected_cluster_ids.add(cluster_ref)
            clustered_count += 1
        else:
            logger.warning(
                f"pain_clusterer: Invalid cluster_id={cluster_ref!r} for pain {pain_id}."
            )

    await session.flush()

    # Update stats for all affected clusters
    for cluster_id in affected_cluster_ids:
        await _update_cluster_stats(cluster_id, session)

    await session.commit()
    logger.info(
        f"pain_clusterer: Clustered {clustered_count} pains into "
        f"{len(affected_cluster_ids)} clusters for program_id={program_id}."
    )
    return clustered_count
