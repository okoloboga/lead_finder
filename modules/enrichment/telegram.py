import asyncio
import random
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, User
from telethon.errors import FloodWaitError
import re
import logging
import config
from modules.telegram_client import TelegramAuthManager

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def _random_delay(delay_type: str) -> None:
    """Apply randomized delay based on safety mode."""
    min_delay, max_delay = config.get_delay(delay_type)
    delay = random.uniform(min_delay, max_delay)
    await asyncio.sleep(delay)

async def _get_entity_details(client, entity):
    """Gathers details for a given Telegram entity (Channel or User)."""
    if isinstance(entity, Channel):
        full_channel = await client(GetFullChannelRequest(entity))
        return {
            "type": "channel", "id": entity.id, "title": entity.title,
            "username": entity.username, "participants_count": full_channel.full_chat.participants_count,
            "about": full_channel.full_chat.about
        }
    elif isinstance(entity, User):
        full_user = await client.get_entity(entity)
        return {
            "type": "user", "id": full_user.id,
            "title": f"{full_user.first_name or ''} {full_user.last_name or ''}".strip(),
            "username": full_user.username, "participants_count": None,
            "about": full_user.about if hasattr(full_user, 'about') else None
        }
    return None

async def _get_entity_posts(client, entity, limit):
    """Fetches recent posts only if the entity is a channel."""
    if not isinstance(entity, Channel):
        return []
    posts = []
    try:
        async for message in client.iter_messages(entity, limit=limit):
            posts.append({"id": message.id, "date": message.date.isoformat(), "text": message.text, "views": message.views})
    except Exception as e:
        logger.error(f"Error fetching posts for {entity.username}: {e}")
    return posts

def _extract_contact_info(details: dict):
    """Extracts contact information from the entity's 'about' (bio/description)."""
    contacts = {"telegram_username": None, "website": None, "other_links": []}
    about_text = details.get("about", "")
    if not about_text:
        return contacts
    
    telegram_matches = re.findall(r'(?<!\w)@([a-zA-Z0-9_]{5,32})', about_text)
    if telegram_matches:
        contacts["telegram_username"] = "@" + telegram_matches[0]

    website_matches = re.findall(r'https?://[^\s/$.?#].[^\s]*', about_text)
    for link in website_matches:
        if 't.me' not in link and 'telegram.me' not in link:
            if contacts["website"] is None:
                contacts["website"] = link
            else:
                contacts["other_links"].append(link)
        elif contacts["telegram_username"] is None:
            contacts["telegram_username"] = link
    return contacts

async def enrich_with_telegram_data(entity_identifier: str) -> dict | None:
    """
    Enrichment function. Parses a Telegram entity (user or channel).

    Uses configured safety delays and proper FloodWaitError handling.
    """
    client = await TelegramAuthManager.get_client()
    max_retries = config.MAX_FLOODWAIT_RETRIES + 1

    for attempt in range(max_retries):
        try:
            logger.debug(
                f"Enriching '{entity_identifier}' with Telegram data "
                f"(Attempt {attempt + 1})..."
            )
            entity = await client.get_entity(entity_identifier)

            # Apply delay before getting details
            await _random_delay("between_channel_parse")
            details = await _get_entity_details(client, entity)
            if not details:
                logger.warning(f"Could not get details for '{entity_identifier}'.")
                return None

            # Apply delay before getting posts
            await _random_delay("between_posts_fetch")
            posts = await _get_entity_posts(client, entity, config.POSTS_TO_FETCH)
            contact_info = _extract_contact_info(details)

            return {
                "entity_data": details,
                "recent_posts": posts,
                "contact_info": contact_info
            }
        except (ValueError, TypeError) as e:
            logger.error(
                f"Cannot find entity for enrichment '{entity_identifier}'. "
                f"Error: {e}"
            )
            return None
        except FloodWaitError as e:
            if attempt < max_retries - 1:
                wait_time = e.seconds + config.FLOODWAIT_EXTRA_SECONDS
                logger.warning(
                    f"FloodWait for '{entity_identifier}'. "
                    f"Waiting {wait_time}s (attempt {attempt + 1}/{max_retries})."
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"Max retries exceeded for '{entity_identifier}' "
                    f"due to FloodWait."
                )
                return None
        except Exception as e:
            logger.error(f"Failed to enrich '{entity_identifier}': {e}")
            return None
    return None