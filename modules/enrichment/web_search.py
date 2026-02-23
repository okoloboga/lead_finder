import re
from googleapiclient.discovery import build
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import logging
from typing import Dict, Any, List

import config

logger = logging.getLogger(__name__)


def _perform_google_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Performs a Google Custom Search and returns raw search items."""
    try:
        service = build("customsearch", "v1", developerKey=config.GOOGLE_API_KEY)
        res = service.cse().list(q=query, cx=config.GOOGLE_CSE_ID, num=num_results).execute()
        return res.get('items', [])
    except Exception as e:
        logger.error(f"Error during Google search for query '{query}': {e}")
        return []

def enrich_with_web_search(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Enriches a candidate's profile with data from web search."""
    logger.info(f"Enriching @{candidate.get('username', 'N/A')} with web search...")
    
    queries = []
    if candidate.get('first_name'):
        queries.append(f"{candidate['first_name']} {candidate.get('last_name', '')} {candidate.get('bio', '')}")
    queries.append(f"telegram @{candidate['username']}")
    if candidate.get('channel_username'):
        queries.append(f"telegram channel {candidate['channel_username']}")
    
    web_search_results = {"website": None, "mentions": []}
    seen_links = set()

    for query in queries[:3]: # Limit to 3 queries per candidate
        search_items = _perform_google_search(query)
        for item in search_items:
            link = item.get('link')
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            
            if web_search_results["website"] is None and 'instagram.com' not in link and 't.me' not in link and 'youtube.com' not in link and 'vk.com' not in link:
                web_search_results["website"] = link

            web_search_results["mentions"].append({
                "source": item.get('displayLink'), "title": item.get('title'),
                "snippet": item.get('snippet'), "link": link
            })
            
    return web_search_results

def search_ai_ideas_for_niche(niche: str) -> str:
    """Searches for fresh AI integration ideas relevant to the given niche.

    Runs a single Google search query and returns a formatted string
    suitable for injection into the qualification prompt.
    """
    query = f"AI автоматизация интеграция для бизнеса {niche} 2025"
    items = _perform_google_search(query, num_results=5)
    if not items:
        return ""

    lines = ["--- Актуальные AI-решения для ниши (из сети) ---"]
    for item in items:
        title = item.get("title", "").strip()
        snippet = item.get("snippet", "").strip()
        if title:
            lines.append(f"- {title}: {snippet}" if snippet else f"- {title}")

    return "\n".join(lines) + "\n\n"


def search_ai_best_practices_for_cluster(
    cluster_name: str,
    cluster_description: str,
    post_type: str,
) -> str:
    """Search fresh AI/automation integration practices for a pain cluster.

    Returns a formatted text block for prompt injection.
    """
    queries = [
        (
            "AI business automation integration best practices "
            f"{cluster_name} {post_type} 2026"
        ),
        (
            "case study AI agents workflow automation CRM integration "
            f"{cluster_name} {cluster_description[:120]} 2026"
        ),
    ]

    seen_links: set[str] = set()
    picked_items: list[dict[str, str]] = []

    for query in queries:
        items = _perform_google_search(query, num_results=5)
        for item in items:
            link = (item.get("link") or "").strip()
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            picked_items.append(item)
            if len(picked_items) >= 6:
                break
        if len(picked_items) >= 6:
            break

    if not picked_items:
        return (
            "--- Актуальные best practices AI-интеграций (из сети) ---\n"
            "- Нет данных из поиска (проверь GOOGLE_API_KEY/GOOGLE_CSE_ID).\n\n"
        )

    lines = ["--- Актуальные best practices AI-интеграций (из сети) ---"]
    for item in picked_items:
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        link = (item.get("link") or "").strip()
        if title and snippet:
            lines.append(f"- {title}: {snippet}")
        elif title:
            lines.append(f"- {title}")
        if link:
            lines.append(f"  Источник: {link}")

    return "\n".join(lines) + "\n\n"


# --- Legacy v1 functions ---

def _generate_v1_search_queries(niche: str) -> list[str]:
    """Generates v1-style search queries for finding channels."""
    llm = ChatOpenAI(openai_api_key=config.COMET_API_KEY, openai_api_base=config.COMET_API_BASE_URL, model=config.COMET_API_MODEL, temperature=0.7)
    system_message = SystemMessage(content="Вы опытный SEO-специалист, который генерирует разнообразные поисковые запросы для поиска Telegram-каналов.")
    human_message = HumanMessage(content=f"Сгенерируй {config.SEARCH_QUERIES_COUNT} уникальных поисковых запросов для поиска Telegram-каналов, связанных с нишей '{niche}'. Верни запросы в виде нумерованного списка.")
    response = llm.invoke([system_message, human_message])
    queries = [line.strip().replace('"', '') for line in response.content.split('\n') if line.strip() and re.match(r'^\d+\.', line.strip())]
    return [re.sub(r'^\d+\.\s*', '', query) for query in queries]

def legacy_search_for_channels(niche: str, max_channels: int) -> list[str]:
    """Legacy v1 function to search for Telegram channels via web search."""
    all_telegram_links = set()
    logger.info("Генерация поисковых запросов (v1 legacy)...")
    generated_queries = _generate_v1_search_queries(niche)
    logger.info(f"Сгенерированные запросы: {generated_queries}")

    pattern = re.compile(r'(?<!\w)(?:t\.me\/|telegram\.me\/)([a-zA-Z0-9_]{5,32})\b|(?<!\w)@([a-zA-Z0-9_]{5,32})\b')

    for query in generated_queries:
        logger.info(f"Выполнение поиска по запросу (v1 legacy): '{query}'")
        search_items = _perform_google_search(query, num_results=10)
        for item in search_items:
            text_to_search = f"{item.get('title', '')} {item.get('link', '')} {item.get('htmlSnippet', '')}"
            matches = pattern.finditer(text_to_search)
            for match in matches:
                if match.group(1):
                    all_telegram_links.add("t.me/" + match.group(1))
                elif match.group(2):
                    all_telegram_links.add("@" + match.group(2))
            if len(all_telegram_links) >= max_channels:
                break
        if len(all_telegram_links) >= max_channels:
            break
            
    return list(all_telegram_links)[:max_channels]
