import logging
from typing import Dict, Any, Callable, Awaitable
from aiogram import Bot

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

import config
from bot.db_config import async_session
from bot.models.program import Program
from bot.models.lead import Lead
from bot.models.pain import Pain
from bot.models.user import User
from bot.ui.lead_card import format_lead_card, get_lead_card_keyboard
from bot.services.subscription import check_weekly_analysis_limit, mark_analysis_started
from modules.telegram_client import AuthorizationRequiredError
from modules import members_parser, qualifier
from modules.enrichment import telegram as telegram_enricher
from modules.enrichment import web_search as web_enricher
from modules.pain_clusterer import cluster_new_pains

logger = logging.getLogger(__name__)

LeadCallback = Callable[[Lead], Awaitable[None]]
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


async def _enrich_candidate(candidate: Dict[str, Any], enrich_web: bool) -> Dict[str, Any]:
    """Enriches candidate data with Telegram channel info and web search results."""
    enrichment_data = {}
    if candidate.get("has_channel") and candidate.get("channel_username"):
        channel_username = candidate["channel_username"]
        logger.info(f"Enriching with personal channel: {channel_username}")
        parsed_channel_data = await telegram_enricher.enrich_with_telegram_data(channel_username)
        if parsed_channel_data:
            enrichment_data["channel_data"] = parsed_channel_data
    
    if enrich_web:
        logger.info(f"Enriching @{candidate.get('username')} with web search.")
        enrichment_data["web_search_data"] = web_enricher.enrich_with_web_search(candidate)

    return enrichment_data


def _extract_pain_texts(qualification_result: Dict[str, Any]) -> list[str]:
    """Extract normalized pain texts from LLM qualification output."""
    pains_raw = qualification_result.get("identified_pains") or []
    pains: list[str] = []
    for pain in pains_raw:
        if isinstance(pain, str):
            text = pain.strip()
        elif isinstance(pain, dict):
            text = (
                pain.get("pain")
                or pain.get("text")
                or pain.get("description")
                or ""
            )
            text = str(text).strip()
        else:
            text = ""
        if text:
            pains.append(text)
    return pains


def _trim(value: Any, limit: int) -> str | None:
    """Trim string values to DB column limits."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


async def _save_pains_from_lead(
    *,
    user_id: int,
    program_id: int,
    candidate: Dict[str, Any],
    qualification_result: Dict[str, Any],
    session: AsyncSession,
) -> int:
    """Persist pains from an already-qualified lead.

    Uses the lead's parsed chat messages as sources to avoid additional
    full-chat LLM passes.
    """
    pains = _extract_pain_texts(qualification_result)
    if not pains:
        return 0

    messages = candidate.get("messages_with_metadata") or []
    if not messages:
        return 0

    source_chat = (
        candidate.get("source_chat_username")
        or candidate.get("source_chat")
        or ""
    )
    if source_chat:
        source_chat = str(source_chat).lstrip("@")
    source_chat = _trim(source_chat, 100) or ""

    business_type_raw = (
        (qualification_result.get("identification") or {}).get("business_type")
    )
    business_type = _trim(business_type_raw, 100)

    inserted = 0
    seen_keys: set[tuple[int, str, str]] = set()
    raw_user_id = candidate.get("user_id")
    safe_user_id: int | None = None
    if isinstance(raw_user_id, int) and _INT32_MIN <= raw_user_id <= _INT32_MAX:
        safe_user_id = raw_user_id
    elif raw_user_id is not None:
        logger.debug(
            f"Skip source_user_id={raw_user_id} for pains: out of int32 range."
        )

    for idx, pain_text in enumerate(pains):
        msg = messages[idx % len(messages)]
        source_message_id = msg.get("message_id")
        if not source_message_id:
            continue

        original_quote = (msg.get("text") or pain_text or "").strip()
        if not original_quote:
            continue

        dedup_key = (source_message_id, source_chat, original_quote)
        if dedup_key in seen_keys:
            continue

        with session.no_autoflush:
            existing_query = select(Pain).where(
                Pain.user_id == user_id,
                Pain.source_message_id == source_message_id,
                Pain.source_chat == source_chat,
                Pain.original_quote == original_quote,
            )
            existing = (await session.execute(existing_query)).scalars().first()
        if existing:
            seen_keys.add(dedup_key)
            continue

        pain = Pain(
            user_id=user_id,
            program_id=program_id,
            text=pain_text,
            original_quote=original_quote,
            category="other",
            intensity="medium",
            business_type=business_type,
            source_chat=source_chat,
            source_message_id=source_message_id,
            source_message_link=_trim(msg.get("link"), 255),
            source_user_id=safe_user_id,
            source_username=_trim(candidate.get("username"), 100),
            message_date=None,
        )
        session.add(pain)
        seen_keys.add(dedup_key)
        inserted += 1

    if inserted:
        await session.flush()

    return inserted


async def run_program_pipeline(
    program: Program, 
    session: AsyncSession, 
    on_lead_found: LeadCallback = None
) -> Dict[str, Any]:
    """
    Runs the full lead-finding pipeline, sending leads in real-time via a callback.
    """
    program_id = program.id
    user_id = program.user_id
    program_name = program.name
    program_max_leads = program.max_leads_per_run
    logger.info(
        f"Starting REAL pipeline for program '{program_name}' (ID: {program_id})"
    )
    
    sources = [chat.chat_username for chat in program.chats]
    if not sources:
        return {"error": "No sources found."}

    all_candidates = []
    try:
        for source in sources:
            logger.info(f"--- Parsing source: {source} ---")
            candidates, _chat_messages = await members_parser.parse_users_from_messages(
                chat_identifier=source,
                messages_limit=config.MESSAGES_LIMIT,
                only_with_channels=False,
                use_batch_analysis=True  # Use batch analysis for efficiency
            )
            all_candidates.extend(candidates)
    except AuthorizationRequiredError:
        logger.warning("Authorization is required to proceed. Aborting pipeline.")
        return {"status": "auth_required"}
    
    total_candidates = len(all_candidates)
    qualified_leads_count = 0
    pains_saved_count = 0
    logger.info(f"--- Found a total of {total_candidates} unique candidates. ---")

    ai_ideas = web_enricher.search_ai_ideas_for_niche(program.niche_description)
    if ai_ideas:
        logger.info("AI ideas for niche fetched from web search.")
    user_profile = await session.get(User, user_id)
    user_services_description = (
        user_profile.services_description if user_profile else ""
    )

    for i, candidate in enumerate(all_candidates):
        if not candidate.get('username'):
            continue

        logger.info(f"--- Processing candidate {i+1}/{total_candidates}: @{candidate['username']} ---")
        
        enrichment_data = await _enrich_candidate(candidate, program.enrich)
        
        qualification_result_data = qualifier.qualify_lead(
            candidate,
            enrichment_data,
            program.niche_description,
            ai_ideas,
            user_services_description=user_services_description,
        )

        if "error" in qualification_result_data:
            logger.error(f"Qualification error for @{candidate['username']}: {qualification_result_data['error']}")
            continue
        
        qualification_result = qualification_result_data.get("llm_response") or {}
        raw_llm_input = qualification_result_data.get("raw_input_prompt")

        # DEBUG: Log the full LLM response to see its structure
        logger.info(f"LLM Response for @{candidate['username']}: {qualification_result}")

        qual_details = qualification_result.get("qualification") or {}
        score = qual_details.get("score", 0) if isinstance(qual_details, dict) else 0
            
        if score < program.min_score:
            continue

        logger.info(f"SUCCESS: Qualified @{candidate['username']} with score {score}.")
        qualified_leads_count += 1

        username = candidate['username']
        existing_lead_query = select(Lead).where(
            Lead.user_id == user_id,
            Lead.program_id == program_id,
            Lead.telegram_username == username,
        )
        lead = (await session.execute(existing_lead_query)).scalars().first()

        # Extract data according to the prompt schema
        identification = qualification_result.get("identification") or {}
        outreach_details = qualification_result.get("outreach") or {}
        product_idea = qualification_result.get("product_idea") or {}

        pains = _extract_pain_texts(qualification_result)

        pains_summary = "\n• ".join(pains) if pains else None
        if pains_summary:
            pains_summary = "• " + pains_summary

        solution_idea = product_idea.get("idea") if isinstance(product_idea, dict) else None

        lead_data = {
            "qualification_score": score,
            "business_summary": identification.get("business_type"),
            "pains_summary": pains_summary,
            "solution_idea": solution_idea,
            "recommended_message": outreach_details.get("message"),
            "raw_qualification_data": qualification_result,
            "raw_user_profile_data": candidate,
            "raw_llm_input": raw_llm_input,
        }

        # DEBUG: Log what we're saving
        logger.info(f"Saving lead data for @{username}:")
        logger.info(f"  - business_summary: {lead_data['business_summary']}")
        logger.info(f"  - pains_summary: {lead_data['pains_summary'][:100] if lead_data['pains_summary'] else None}...")
        logger.info(f"  - solution_idea: {lead_data['solution_idea'][:100] if lead_data['solution_idea'] else None}...")
        logger.info(f"  - recommended_message: {lead_data['recommended_message'][:100] if lead_data['recommended_message'] else None}...")

        if lead:
            logger.info(f"Updating existing lead {lead.id} for @{username}")
            for key, value in lead_data.items():
                setattr(lead, key, value)
        else:
            logger.info(
                f"Creating new lead for @{username} with program_id={program_id}"
            )
            lead = Lead(
                user_id=user_id,
                program_id=program_id,
                telegram_username=username,
                **lead_data,
            )
            session.add(lead)

        await session.flush()
        await session.refresh(lead, attribute_names=['program'])

        logger.info(f"Lead saved: id={lead.id}, program_id={lead.program_id}, username=@{lead.telegram_username}")

        # Commit immediately so the lead is available in the database
        # for the user to click on
        await session.commit()

        # DEBUG: Verify the lead is actually in the database
        verification_query = select(func.count(Lead.id)).where(
            Lead.program_id == program_id
        )
        verified_count = (await session.execute(verification_query)).scalar_one()
        logger.info(
            f"After commit: Total leads for program_id={program_id}: {verified_count}"
        )

        if on_lead_found:
            await on_lead_found(lead)

        # Save pains directly from qualified/saved leads (no heavy full-chat pass)
        try:
            new_pains = await _save_pains_from_lead(
                program_id=program_id,
                user_id=user_id,
                candidate=candidate,
                qualification_result=qualification_result,
                session=session,
            )
            if new_pains:
                pains_saved_count += new_pains
                await session.commit()
        except Exception as e:
            logger.error(
                f"Failed to save pains from lead @{username}: {e}"
            )
            await session.rollback()

        if qualified_leads_count >= program_max_leads:
            logger.info(
                f"Reached max leads limit of {program_max_leads}. Stopping."
            )
            break
    
    await session.commit()

    # Final verification
    final_count_query = select(func.count(Lead.id)).where(
        Lead.program_id == program_id
    )
    final_count = (await session.execute(final_count_query)).scalar_one()
    logger.info(
        f"Pipeline complete for program '{program_name}'. "
        f"Final lead count in DB: {final_count}"
    )

    return {
        "program_name": program_name, "candidates_found": total_candidates,
        "leads_qualified": qualified_leads_count,
        "pains_saved": pains_saved_count,
    }


# --- APScheduler Job Worker ---

async def run_program_job(program_id: int, chat_id: int) -> None:
    """
    Executed by APScheduler (or asyncio.create_task for manual runs).
    Creates its own Bot instance so it can be safely serialized by APScheduler.
    """
    logger.info(f"[JOB] Starting job for program_id={program_id}, user_chat_id={chat_id}")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN, parse_mode="HTML")
    try:
        await _run_program_job_inner(bot, program_id, chat_id)
    finally:
        await bot.session.close()


async def _run_program_job_inner(bot: Bot, program_id: int, chat_id: int) -> None:
    """Inner logic for run_program_job, separated to allow proper Bot cleanup."""
    # Each job needs its own database session
    async with async_session() as session:
        program_query = (
            select(Program)
            .options(selectinload(Program.chats))
            .where(
                Program.id == program_id,
                Program.user_id == chat_id,
            )
        )
        program = (await session.execute(program_query)).scalars().first()

        if not program:
            logger.error(f"[JOB] Program {program_id} not found. Aborting job.")
            await bot.send_message(chat_id, f"❌ Ошибка: не удалось запустить программу, так как она была удалена.")
            return

        user = await session.get(User, chat_id)
        if not user:
            await bot.send_message(chat_id, "❌ Профиль пользователя не найден. Нажмите /start.")
            return

        can_run, days_left = check_weekly_analysis_limit(user)
        if not can_run:
            await bot.send_message(
                chat_id,
                "⏸ Запуск пропущен: на бесплатном тарифе доступен 1 анализ в неделю. "
                f"Следующий запуск через {days_left} дн.",
            )
            return

        mark_analysis_started(user)
        await session.commit()

        # --- Define the real-time callback for this job ---
        qualified_leads_count = 0
        async def send_lead_card_callback(lead: Lead) -> None:
            nonlocal qualified_leads_count
            qualified_leads_count += 1
            card_text = format_lead_card(lead, qualified_leads_count, "??")
            await bot.send_message(
                chat_id, card_text,
                reply_markup=get_lead_card_keyboard(lead.id, lead.status),
                disable_web_page_preview=True
            )

        await bot.send_message(chat_id, f"⏳ Запускаю программу \"{program.name}\" в фоновом режиме...")
        run_results = await run_program_pipeline(program, session, on_lead_found=send_lead_card_callback)

        if run_results.get("status") == "auth_required":
            await bot.send_message(chat_id, "Требуется авторизация в Telegram. Пожалуйста, запустите программу еще раз, чтобы войти.")
            return

        if "error" in run_results:
            await bot.send_message(chat_id, f"❌ Ошибка при выполнении программы \"{run_results['program_name']}\":\n{run_results['error']}")
            return

        pains_saved = run_results.get("pains_saved", 0)
        logger.info(
            f"[JOB] Lead-based pain sync done: {pains_saved} pains saved."
        )

        # --- Pain clustering (runs after all pain collection) ---
        if pains_saved > 0:
            try:
                clustered = await cluster_new_pains(program_id, session)
                logger.info(f"[JOB] Pain clustering done: {clustered} pains clustered.")
            except Exception as e:
                logger.error(f"[JOB] Pain clustering failed: {e}")
                await session.rollback()

        final_summary_text = (
            f"✅ Готово! Поиск по программе \"{run_results['program_name']}\" завершен.\n"
            f"• Найдено новых лидов: {qualified_leads_count}.\n\n"
            "Теперь Вы можете вернуться к карточке программы, чтобы их просмотреть."
        )
        await bot.send_message(chat_id, final_summary_text)
