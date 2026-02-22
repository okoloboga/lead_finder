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
from bot.ui.lead_card import format_lead_card, get_lead_card_keyboard
from modules.telegram_client import AuthorizationRequiredError
from modules import members_parser, qualifier
from modules.enrichment import telegram as telegram_enricher
from modules.enrichment import web_search as web_enricher
from modules.pain_collector import collect_pains
from modules.pain_clusterer import cluster_new_pains

logger = logging.getLogger(__name__)

LeadCallback = Callable[[Lead], Awaitable[None]]


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


async def run_program_pipeline(
    program: Program, 
    session: AsyncSession, 
    on_lead_found: LeadCallback = None
) -> Dict[str, Any]:
    """
    Runs the full lead-finding pipeline, sending leads in real-time via a callback.
    """
    logger.info(f"Starting REAL pipeline for program '{program.name}' (ID: {program.id})")
    
    sources = [chat.chat_username for chat in program.chats]
    if not sources:
        return {"error": "No sources found."}

    all_candidates = []
    all_chat_messages: list[dict] = []  # Collected for pain analysis (Task #7)
    try:
        for source in sources:
            logger.info(f"--- Parsing source: {source} ---")
            candidates, chat_messages = await members_parser.parse_users_from_messages(
                chat_identifier=source,
                messages_limit=config.MESSAGES_LIMIT,
                only_with_channels=False,
                use_batch_analysis=True  # Use batch analysis for efficiency
            )
            all_candidates.extend(candidates)
            all_chat_messages.extend(chat_messages)
    except AuthorizationRequiredError:
        logger.warning("Authorization is required to proceed. Aborting pipeline.")
        return {"status": "auth_required"}
    
    total_candidates = len(all_candidates)
    qualified_leads_count = 0
    logger.info(f"--- Found a total of {total_candidates} unique candidates. ---")

    ai_ideas = web_enricher.search_ai_ideas_for_niche(program.niche_description)
    if ai_ideas:
        logger.info("AI ideas for niche fetched from web search.")

    for i, candidate in enumerate(all_candidates):
        if not candidate.get('username'):
            continue

        logger.info(f"--- Processing candidate {i+1}/{total_candidates}: @{candidate['username']} ---")
        
        enrichment_data = await _enrich_candidate(candidate, program.enrich)
        
        qualification_result_data = qualifier.qualify_lead(candidate, enrichment_data, program.niche_description, ai_ideas)

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
            Lead.program_id == program.id,
            Lead.telegram_username == username,
        )
        lead = (await session.execute(existing_lead_query)).scalars().first()

        # Extract data according to the prompt schema
        identification = qualification_result.get("identification") or {}
        outreach_details = qualification_result.get("outreach") or {}
        pains_raw = qualification_result.get("identified_pains") or []
        product_idea = qualification_result.get("product_idea") or {}

        # Handle pains - can be list of strings or list of dicts
        pains = []
        for pain in pains_raw:
            if isinstance(pain, str):
                pains.append(pain)
            elif isinstance(pain, dict):
                # Extract pain text from dict (try common keys)
                pain_text = pain.get("pain") or pain.get("text") or pain.get("description") or str(pain)
                pains.append(pain_text)

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
            logger.info(f"Creating new lead for @{username} with program_id={program.id}")
            lead = Lead(program_id=program.id, telegram_username=username, **lead_data)
            session.add(lead)

        await session.flush()
        await session.refresh(lead, attribute_names=['program'])

        logger.info(f"Lead saved: id={lead.id}, program_id={lead.program_id}, username=@{lead.telegram_username}")

        # Commit immediately so the lead is available in the database
        # for the user to click on
        await session.commit()

        # DEBUG: Verify the lead is actually in the database
        verification_query = select(func.count(Lead.id)).where(Lead.program_id == program.id)
        verified_count = (await session.execute(verification_query)).scalar_one()
        logger.info(f"After commit: Total leads for program_id={program.id}: {verified_count}")

        if on_lead_found:
            await on_lead_found(lead)

        if qualified_leads_count >= program.max_leads_per_run:
            logger.info(f"Reached max leads limit of {program.max_leads_per_run}. Stopping.")
            break
    
    await session.commit()

    # Final verification
    final_count_query = select(func.count(Lead.id)).where(Lead.program_id == program.id)
    final_count = (await session.execute(final_count_query)).scalar_one()
    logger.info(f"Pipeline complete for program '{program.name}'. Final lead count in DB: {final_count}")

    return {
        "program_name": program.name, "candidates_found": total_candidates,
        "leads_qualified": qualified_leads_count,
        "all_chat_messages": all_chat_messages,  # Passed to caller for pain analysis
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
        program_query = select(Program).options(selectinload(Program.chats)).where(Program.id == program_id)
        program = (await session.execute(program_query)).scalars().first()

        if not program:
            logger.error(f"[JOB] Program {program_id} not found. Aborting job.")
            await bot.send_message(chat_id, f"❌ Ошибка: не удалось запустить программу, так как она была удалена.")
            return

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

        # --- Pain collection (runs after lead pipeline) ---
        all_chat_messages = run_results.get("all_chat_messages", [])
        if all_chat_messages:
            logger.info(
                f"[JOB] Starting pain collection: {len(all_chat_messages)} messages "
                f"for program_id={program_id}."
            )
            chat_name = program.chats[0].chat_username if program.chats else "unknown"
            try:
                pains_count = await collect_pains(
                    all_messages=all_chat_messages,
                    program_id=program_id,
                    chat_name=chat_name,
                    session=session,
                )
                logger.info(f"[JOB] Pain collection done: {pains_count} new pains saved.")
            except Exception as e:
                logger.error(f"[JOB] Pain collection failed: {e}")
                await session.rollback()

        # --- Pain clustering (runs after all pain collection) ---
        if config.PAIN_COLLECTION_ENABLED:
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
