import argparse
import asyncio
import logging
import datetime
import os
import random
import time
from typing import List, Dict, Any, Optional

from modules import input_handler, members_parser, qualifier, output, telegram_client
from modules.enrichment import telegram as telegram_enricher
from modules.enrichment import web_search as web_enricher
from modules.members_parser import ParsingPausedError

import config
from config import MIN_QUALIFICATION_SCORE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def estimate_run_time(num_chats: int, messages_per_chat: int) -> str:
    """Estimate total run time based on safety mode and parameters."""
    mode = config.SAFETY_MODE
    delays = config.SAFETY_DELAYS.get(mode, config.SAFETY_DELAYS["normal"])

    # Average delay between chats
    avg_chat_delay = sum(delays["between_chats"]) / 2

    # Estimate time per chat (message parsing + profile fetches)
    # Rough estimate: 1 message per 0.1 second + delays
    avg_request_delay = sum(delays["between_requests"]) / 2
    num_delay_points = messages_per_chat // 50  # Delay every 50 messages
    parsing_time_per_chat = (
        messages_per_chat * 0.05  # Base parsing time
        + num_delay_points * avg_request_delay  # Delays during parsing
        + 10  # Profile fetch buffer
    )

    total_seconds = (
        num_chats * parsing_time_per_chat
        + (num_chats - 1) * avg_chat_delay  # Delays between chats
    )

    minutes = int(total_seconds / 60)
    if minutes < 1:
        return "меньше минуты"
    elif minutes < 5:
        return f"~{minutes} мин"
    elif minutes < 60:
        low = max(1, minutes - 2)
        high = minutes + 3
        return f"~{low}-{high} мин"
    else:
        hours = minutes / 60
        return f"~{hours:.1f} ч"


async def random_delay(delay_type: str) -> None:
    """Apply randomized delay based on safety mode."""
    min_delay, max_delay = config.get_delay(delay_type)
    delay = random.uniform(min_delay, max_delay)
    await asyncio.sleep(delay)


async def enrich_candidate(
    candidate: Dict[str, Any],
    enrich_web: bool
) -> Dict[str, Any]:
    """Enrich candidate with channel data and optionally web search."""
    enrichment_data = {}

    if candidate.get("has_channel") and candidate.get("channel_username"):
        channel_username = candidate["channel_username"]
        logger.info(f"  → Enriching with personal channel: {channel_username}")

        # Apply delay before channel parsing
        await random_delay("between_channel_parse")

        parsed_channel_data = await telegram_enricher.enrich_with_telegram_data(
            channel_username
        )
        if parsed_channel_data:
            enrichment_data["channel_data"] = parsed_channel_data

    if enrich_web:
        logger.info("  → Enriching with web search...")
        enrichment_data["web_search_data"] = web_enricher.enrich_with_web_search(
            candidate
        )

    return enrichment_data


def check_session_limits(
    num_chats: int,
    qualified_count: int,
    start_time: float
) -> Optional[str]:
    """Check if session limits have been exceeded."""
    # Check chat limit
    if num_chats > config.MAX_CHATS_PER_RUN:
        return (
            f"Превышен лимит чатов за запуск ({num_chats} > "
            f"{config.MAX_CHATS_PER_RUN}). Обработаем первые "
            f"{config.MAX_CHATS_PER_RUN}."
        )

    # Check channel limit
    if qualified_count >= config.MAX_CHANNELS_PER_RUN:
        return (
            f"Достигнут лимит каналов за сессию: {config.MAX_CHANNELS_PER_RUN}"
        )

    # Check session duration
    elapsed_minutes = (time.time() - start_time) / 60
    if elapsed_minutes >= config.MAX_SESSION_DURATION_MINUTES:
        return (
            f"Достигнут лимит времени сессии: "
            f"{config.MAX_SESSION_DURATION_MINUTES} мин"
        )

    return None


def print_progress_header(
    num_chats: int,
    messages_limit: int,
    safety_mode: str
) -> None:
    """Print pipeline start information."""
    estimated_time = estimate_run_time(num_chats, messages_limit)
    print("\n" + "=" * 50)
    print("🔍 Lead Finder v2 — Запуск парсинга")
    print("=" * 50)
    print(f"📊 Чатов для парсинга: {num_chats}")
    print(f"📝 Сообщений на чат: {messages_limit}")
    print(f"🛡️  Режим безопасности: {safety_mode}")
    print(f"⏱️  Примерное время: {estimated_time}")
    print("=" * 50 + "\n")


def print_chat_progress(
    chat_idx: int,
    total_chats: int,
    chat_name: str,
    candidates_found: int = 0,
    status: str = "parsing"
) -> None:
    """Print progress for current chat."""
    progress_bar = "█" * (chat_idx + 1) + "░" * (total_chats - chat_idx - 1)
    if status == "parsing":
        print(f"\n⏳ Парсинг чата {chat_idx + 1}/{total_chats}: {chat_name}")
        print(f"   [{progress_bar}]")
    elif status == "done":
        print(f"   ✅ Найдено участников: {candidates_found}")


def print_candidate_progress(
    idx: int,
    total: int,
    username: str,
    score: Optional[int] = None,
    status: str = "processing"
) -> None:
    """Print progress for current candidate."""
    if status == "processing":
        pct = (idx + 1) / total * 100
        print(f"\r   Обработка {idx + 1}/{total} ({pct:.0f}%): @{username}", end="")
    elif status == "qualified":
        print(f"\r   ✅ @{username} — оценка: {score}/10" + " " * 20)
    elif status == "skipped":
        print(f"\r   ⏭️  @{username} — оценка: {score}/10 (ниже порога)" + " " * 10)


async def parse_pipeline(args) -> None:
    """Main v2 parsing pipeline with progress indication."""
    start_time = time.time()

    # Process sources
    sources = input_handler.process_sources(args.sources, args.file)
    if not sources:
        logger.error("No valid sources found. Exiting.")
        return

    # Apply chat limit
    if len(sources) > config.MAX_CHATS_PER_RUN:
        logger.warning(
            f"Limiting chats from {len(sources)} to {config.MAX_CHATS_PER_RUN}"
        )
        sources = sources[:config.MAX_CHATS_PER_RUN]

    # Print header
    print_progress_header(len(sources), args.messages_limit, config.SAFETY_MODE)

    # Parse all chats
    all_candidates = []
    parsing_paused = False

    for idx, source in enumerate(sources):
        # Check session limits
        limit_warning = check_session_limits(
            idx + 1, len(all_candidates), start_time
        )
        if limit_warning and "времени" in limit_warning:
            print(f"\n⚠️  {limit_warning}")
            print("Продолжу с собранными данными...")
            break

        print_chat_progress(idx, len(sources), source)

        try:
            # Progress callback for message parsing
            def progress_cb(current, total, status):
                pct = current / total * 100
                print(f"\r   Сообщений: {current}/{total} ({pct:.0f}%)", end="")

            candidates = await members_parser.parse_users_from_messages(
                chat_identifier=source,
                only_with_channels=args.only_with_channels,
                messages_limit=args.messages_limit,
                progress_callback=progress_cb
            )
            all_candidates.extend(candidates)
            print_chat_progress(
                idx, len(sources), source,
                candidates_found=len(candidates), status="done"
            )

        except ParsingPausedError as e:
            print(f"\n⚠️  Парсинг приостановлен: {e}")
            print("Продолжу с собранными данными...")
            parsing_paused = True
            break
        except Exception as e:
            logger.error(f"Failed to parse {source}: {e}")
            print(f"\n❌ Ошибка парсинга {source}: {e}")

        # Delay between chats (except after last one)
        if idx < len(sources) - 1:
            delay_range = config.get_delay("between_chats")
            delay = random.uniform(*delay_range)
            print(f"\n   ⏳ Пауза {delay:.0f} сек перед следующим чатом...")
            await asyncio.sleep(delay)

    print(f"\n{'=' * 50}")
    print(f"📊 Всего кандидатов найдено: {len(all_candidates)}")
    print(f"{'=' * 50}\n")

    if not all_candidates:
        print("❌ Кандидаты не найдены. Завершение.")
        return

    # Sort candidates by freshness (hot messages first)
    all_candidates.sort(
        key=lambda x: (not x.get("has_fresh_message", False), -x.get("messages_in_chat", 0))
    )

    # Setup output files
    qualified_leads_count = 0
    run_name = sources[0].replace('@', '').replace('t.me/', '').replace('+', '')
    output_formats = [f.strip() for f in args.format.split(',')]

    jsonl_filepath = None
    if "json" in output_formats:
        jsonl_filename = output.get_timestamped_filename(run_name, "jsonl")
        jsonl_filepath = os.path.join(args.output_dir, jsonl_filename)

    md_filepath = None
    if "md" in output_formats:
        md_filename = output.get_timestamped_filename(run_name, "md")
        md_filepath = os.path.join(args.output_dir, md_filename)
        output.initialize_markdown_file(md_filepath, run_name)

    print("🔬 Квалификация кандидатов...")
    print("-" * 50)

    channels_processed = 0

    for i, candidate in enumerate(all_candidates):
        # Check session limits
        limit_warning = check_session_limits(
            len(sources), channels_processed, start_time
        )
        if limit_warning:
            print(f"\n⚠️  {limit_warning}")
            break

        username = candidate.get('username', 'unknown')
        print_candidate_progress(i, len(all_candidates), username)

        # Enrich candidate
        enrichment_data = await enrich_candidate(candidate, args.enrich)
        if candidate.get("has_channel"):
            channels_processed += 1

        # Qualify
        niche_context = candidate.get("source_chat", "general")
        qualification_result = qualifier.qualify_lead(
            candidate, enrichment_data, niche_context
        )

        if "error" in qualification_result:
            logger.error(
                f"Qualification error for @{username}: "
                f"{qualification_result['error']}"
            )
            continue

        # Extract score
        qualification_details = qualification_result.get("qualification", {})
        score = (
            qualification_details.get("score", 0)
            if isinstance(qualification_details, dict) else 0
        )

        if score < args.min_score:
            print_candidate_progress(
                i, len(all_candidates), username, score, "skipped"
            )
            continue

        qualified_leads_count += 1
        print_candidate_progress(
            i, len(all_candidates), username, score, "qualified"
        )

        # Build lead card with message metadata
        messages_with_links = candidate.get("messages_with_metadata", [])

        lead_card = {
            "id": candidate["user_id"],
            "timestamp": datetime.datetime.now().isoformat(),
            "source_chat": candidate["source_chat"],
            "source_chat_username": candidate.get("source_chat_username"),
            "source_chat_id": candidate.get("source_chat_id"),
            "source_chat_is_public": candidate.get("source_chat_is_public"),
            "niche_context": niche_context,
            "contact": {
                "telegram_username": f"@{candidate['username']}",
                "telegram_channel": candidate.get("channel_username"),
                "website": enrichment_data.get("web_search_data", {}).get("website"),
            },
            "user_profile": candidate,
            "enrichment_data": enrichment_data,
            "qualification_result": qualification_result,
            "messages_with_links": messages_with_links,
            "has_fresh_message": candidate.get("has_fresh_message", False),
        }

        if jsonl_filepath:
            output.append_to_jsonl(lead_card, jsonl_filepath)
        if md_filepath:
            output.append_to_markdown(lead_card, qualified_leads_count, md_filepath)

        if qualified_leads_count >= args.max_leads:
            print(f"\n✅ Достигнут лимит лидов: {args.max_leads}")
            break

        # Small delay between candidates
        if i < len(all_candidates) - 1:
            await random_delay("between_requests")

    # Final summary
    elapsed = time.time() - start_time
    elapsed_str = f"{elapsed / 60:.1f} мин" if elapsed > 60 else f"{elapsed:.0f} сек"

    print("\n" + "=" * 50)
    print("✅ Парсинг завершён!")
    print("=" * 50)
    print(f"⏱️  Время выполнения: {elapsed_str}")
    print(f"📊 Обработано кандидатов: {len(all_candidates)}")
    print(f"🎯 Квалифицировано лидов: {qualified_leads_count}")

    if parsing_paused:
        print("\n⚠️  Парсинг был приостановлен из-за FloodWait.")
        print("   Попробуйте запустить снова позже.")

    if qualified_leads_count > 0:
        print("\n📁 Файлы сохранены:")
        if jsonl_filepath:
            print(f"   • {jsonl_filepath}")
        if md_filepath:
            print(f"   • {md_filepath}")
    else:
        print("\n❌ Квалифицированных лидов не найдено.")

    print("=" * 50 + "\n")


async def search_pipeline(args) -> None:
    """Legacy v1 pipeline - web search for channels."""
    print("⚠️  Команда 'search' устарела. Используйте 'parse' для v2 пайплайна.")
    pass


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Lead Finder v2")
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Available commands"
    )

    # Parse command (v2 pipeline)
    parser_parse = subparsers.add_parser(
        "parse", help="Parse members from seed chats/channels (v2 pipeline)."
    )
    parser_parse.add_argument(
        "sources", nargs='*', help="List of seed sources (e.g., @chat1 @chat2)."
    )
    parser_parse.add_argument(
        "--file", type=str, help="File with a list of seed sources."
    )
    parser_parse.add_argument(
        "--enrich", action="store_true",
        help="Enrich candidate data via web search."
    )
    parser_parse.add_argument(
        "--messages-limit", type=int, default=500,
        help="Number of recent messages to parse from each source."
    )
    parser_parse.add_argument(
        "--only-with-channels", action="store_true",
        help="Process only users who have a personal channel in their bio."
    )
    parser_parse.add_argument(
        "--min-score", type=int, default=MIN_QUALIFICATION_SCORE,
        help="Minimum qualification score."
    )
    parser_parse.add_argument(
        "--max-leads", type=int, default=50,
        help="Maximum number of leads to generate."
    )
    parser_parse.add_argument(
        "--output-dir", type=str, default="./output",
        help="Directory for results."
    )
    parser_parse.add_argument(
        "--format", type=str, default="json,md",
        help="Output formats (json,md). json is now jsonl."
    )
    parser_parse.add_argument(
        "--safety-mode", type=str, choices=["fast", "normal", "careful"],
        help="Override safety mode for this run."
    )

    # Search command (legacy v1)
    parser_search = subparsers.add_parser(
        "search", help="Legacy web search for channels (v1 pipeline)."
    )
    parser_search.add_argument(
        "niche", type=str, help="Niche description to search for."
    )
    parser_search.add_argument(
        "--max-channels", type=int, default=20,
        help="Maximum channels to find."
    )

    args = parser.parse_args()

    # Override safety mode if specified
    if hasattr(args, 'safety_mode') and args.safety_mode:
        config.SAFETY_MODE = args.safety_mode

    loop = asyncio.get_event_loop()
    try:
        if args.command == "parse":
            loop.run_until_complete(parse_pipeline(args))
        elif args.command == "search":
            loop.run_until_complete(search_pipeline(args))
    finally:
        loop.run_until_complete(
            telegram_client.TelegramClientSingleton.disconnect_client()
        )


if __name__ == '__main__':
    main()
