import asyncio
import random
import re
import logging
from datetime import datetime, timezone
from typing import Optional

import telethon.tl.types
from telethon.errors import FloodWaitError

from modules.telegram_client import TelegramAuthManager, AuthorizationRequiredError
import config

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ParsingPausedError(Exception):
    """Raised when parsing is paused due to repeated FloodWait errors."""

    pass


def find_channel_in_bio(bio_text: str) -> str | None:
    """Finds a potential personal channel link in a user's bio."""
    if not bio_text:
        return None
    match = re.search(r'(?<!\w)@([a-zA-Z0-9_]{5,32})', bio_text)
    if match:
        return match.group(0)
    match = re.search(r't\.me\/([a-zA-Z0-9_]{5,32})', bio_text)
    if match:
        return "t.me/" + match.group(1)
    return None


def generate_message_link(
    chat_username: Optional[str],
    chat_id: int,
    message_id: int,
    is_public: bool
) -> Optional[str]:
    """
    Generate a link to a specific message in a chat.

    For public chats: t.me/{chat_username}/{message_id}
    For private chats: t.me/c/{chat_id_without_100}/{message_id}
    """
    if is_public and chat_username:
        # Remove @ if present
        username = chat_username.lstrip('@')
        return f"t.me/{username}/{message_id}"
    elif chat_id:
        # For private chats, remove -100 prefix from channel ID
        chat_id_str = str(abs(chat_id))
        if chat_id_str.startswith("100"):
            chat_id_str = chat_id_str[3:]
        return f"t.me/c/{chat_id_str}/{message_id}"
    return None


def get_message_freshness(message_date: datetime) -> str:
    """
    Determine freshness category for a message.

    Returns: 'hot', 'warm', 'cold', or 'stale'
    """
    if not message_date:
        return "stale"

    now = datetime.now(timezone.utc)
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    days_old = (now - message_date).days

    if days_old < config.MESSAGE_FRESHNESS_DAYS["hot"]:
        return "hot"
    elif days_old < config.MESSAGE_FRESHNESS_DAYS["warm"]:
        return "warm"
    elif days_old < config.MESSAGE_FRESHNESS_DAYS["cold"]:
        return "cold"
    return "stale"


def format_message_age(message_date: datetime) -> str:
    """Format message age for display."""
    if not message_date:
        return "дата неизвестна"

    now = datetime.now(timezone.utc)
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    days_old = (now - message_date).days

    if days_old == 0:
        return "сегодня"
    elif days_old == 1:
        return "вчера"
    elif days_old < 7:
        return f"{days_old} дн. назад"
    elif days_old < 14:
        return "неделю назад"
    elif days_old < 30:
        return f"{days_old // 7} нед. назад"
    else:
        return "больше месяца назад"


async def _random_delay(delay_type: str) -> None:
    """Apply randomized delay based on safety mode."""
    min_delay, max_delay = config.get_delay(delay_type)
    delay = random.uniform(min_delay, max_delay)
    await asyncio.sleep(delay)


async def _handle_flood_wait(
    e: FloodWaitError,
    operation: str,
    retry_count: int
) -> bool:
    """
    Handle FloodWaitError with appropriate waiting.

    Returns True if should retry, False if should stop.
    """
    wait_time = e.seconds + config.FLOODWAIT_EXTRA_SECONDS
    logger.warning(
        f"FloodWaitError during {operation}: waiting {wait_time} seconds "
        f"(retry {retry_count + 1}/{config.MAX_FLOODWAIT_RETRIES})"
    )

    if retry_count >= config.MAX_FLOODWAIT_RETRIES:
        logger.error(
            f"Max FloodWait retries exceeded for {operation}. Stopping."
        )
        return False

    await asyncio.sleep(wait_time)
    return True


async def parse_users_from_messages(
    chat_identifier: str,
    only_with_channels: bool = False,
    messages_limit: int = 1000,
    max_messages_per_user: int = 5,
    progress_callback: Optional[callable] = None
) -> list[dict]:
    """
    Parses active users by reading the message history of a chat.

    Stores full message metadata including message_id, chat info, and date
    for generating message links.

    Args:
        chat_identifier: Chat username or ID to parse
        only_with_channels: Only return users who have channels in bio
        messages_limit: Maximum messages to fetch
        max_messages_per_user: Maximum sample messages to store per user
        progress_callback: Optional callback(current, total, status) for progress

    Returns:
        List of candidate dictionaries with message metadata
    """
    if not await TelegramAuthManager.is_authorized():
        logger.warning(
            "Telegram client not authorized. Raising error to trigger auth flow."
        )
        raise AuthorizationRequiredError("Client is not authorized.")

    client = await TelegramAuthManager.get_client()
    logger.info(
        f"Starting to parse active users from messages in: {chat_identifier} "
        f"(limit: {messages_limit} messages, mode: {config.SAFETY_MODE})"
    )

    flood_wait_retries = 0

    try:
        # Get chat entity with retry logic
        entity = None
        for attempt in range(config.MAX_FLOODWAIT_RETRIES + 1):
            try:
                entity = await client.get_entity(chat_identifier)
                break
            except FloodWaitError as e:
                if not await _handle_flood_wait(e, "get_entity", attempt):
                    raise ParsingPausedError(
                        f"FloodWait limit exceeded getting entity: {chat_identifier}"
                    )

        if entity is None:
            logger.error(f"Could not get entity for {chat_identifier}")
            return []

        logger.info(
            f"Successfully got entity for '{chat_identifier}'. "
            f"Type: {type(entity).__name__}"
        )

        # Determine if chat is public (has username)
        chat_username = getattr(entity, 'username', None)
        chat_id = entity.id
        is_public = bool(chat_username)

        logger.info(
            f"Chat info: username={chat_username}, id={chat_id}, "
            f"is_public={is_public}"
        )

        # Store user objects, message count, and detailed message data
        unique_users: dict[int, dict] = {}
        messages_processed = 0

        logger.info(f"Fetching last {messages_limit} messages...")

        # Iterate messages with delays and flood protection
        try:
            async for message in client.iter_messages(entity, limit=messages_limit):
                messages_processed += 1

                # Progress callback
                if progress_callback and messages_processed % 100 == 0:
                    progress_callback(
                        messages_processed,
                        messages_limit,
                        f"Обработано {messages_processed} сообщений..."
                    )

                # Apply delay every N messages to avoid rate limits
                if messages_processed % 50 == 0:
                    await _random_delay("between_requests")

                # Get sender
                try:
                    sender = await message.get_sender()
                except FloodWaitError as e:
                    if not await _handle_flood_wait(
                        e, "get_sender", flood_wait_retries
                    ):
                        raise ParsingPausedError(
                            "FloodWait limit exceeded during message parsing"
                        )
                    flood_wait_retries += 1
                    continue

                if not sender:
                    continue
                if not isinstance(sender, telethon.tl.types.User):
                    continue
                if not message.text:
                    continue

                # Filter bots, deleted users, users without username
                if sender.bot or sender.deleted or not sender.username:
                    continue

                if sender.id not in unique_users:
                    unique_users[sender.id] = {
                        "user_obj": sender,
                        "message_count": 0,
                        "messages": []  # Store full message metadata
                    }

                # Increment message count
                unique_users[sender.id]["message_count"] += 1

                # Store message with full metadata (up to max_messages_per_user)
                if len(unique_users[sender.id]["messages"]) < max_messages_per_user:
                    # Note: We store date as ISO string, not datetime object,
                    # to ensure JSON serialization works for database storage
                    message_data = {
                        "message_id": message.id,
                        "text": message.text,
                        "date": message.date.isoformat() if message.date else None,
                        "chat_username": chat_username,
                        "chat_id": chat_id,
                        "is_public": is_public,
                        "link": generate_message_link(
                            chat_username, chat_id, message.id, is_public
                        ),
                        "freshness": get_message_freshness(message.date),
                        "age_display": format_message_age(message.date)
                    }
                    unique_users[sender.id]["messages"].append(message_data)

        except FloodWaitError as e:
            if not await _handle_flood_wait(e, "iter_messages", flood_wait_retries):
                raise ParsingPausedError(
                    "FloodWait limit exceeded during message iteration"
                )

        logger.info(
            f"Total messages processed: {messages_processed}. "
            f"Found {len(unique_users)} unique active users."
        )

        # Fetch full user entities to get bio and other profile details
        logger.info(f"Fetching full user profiles for {len(unique_users)} users...")
        full_users: dict[int, telethon.tl.types.User] = {}

        for idx, user_id in enumerate(unique_users.keys()):
            # Apply delay between profile fetches
            if idx > 0 and idx % 10 == 0:
                await _random_delay("between_requests")

            try:
                full_user = await client.get_entity(user_id)
                full_users[user_id] = full_user
            except FloodWaitError as e:
                if not await _handle_flood_wait(e, "get_entity_profile", 0):
                    logger.warning(
                        f"Stopping profile fetch due to FloodWait at user {idx}"
                    )
                    break
                # After waiting, try again
                try:
                    full_user = await client.get_entity(user_id)
                    full_users[user_id] = full_user
                except Exception as retry_e:
                    logger.warning(
                        f"Failed to fetch profile for user_id={user_id} "
                        f"after FloodWait retry: {retry_e}"
                    )
                    full_users[user_id] = unique_users[user_id]["user_obj"]
            except Exception as e:
                logger.warning(
                    f"Failed to fetch full profile for user_id={user_id}: {e}"
                )
                full_users[user_id] = unique_users[user_id]["user_obj"]

        # Build candidate list
        candidate_list = []
        for user_id, user_data in unique_users.items():
            user = full_users.get(user_id, user_data["user_obj"])

            bio = getattr(user, 'about', None)
            channel_in_bio = find_channel_in_bio(bio)

            if only_with_channels and not channel_in_bio:
                continue

            # Extract sample messages text for backward compatibility
            sample_messages_text = [m["text"] for m in user_data["messages"]]

            # Determine if any message is fresh
            has_fresh_message = any(
                m["freshness"] == "hot" for m in user_data["messages"]
            )

            candidate = {
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "bio": bio,
                "has_channel": bool(channel_in_bio),
                "channel_username": channel_in_bio,
                "source_chat": chat_identifier,
                "source_chat_username": chat_username,
                "source_chat_id": chat_id,
                "source_chat_is_public": is_public,
                "messages_in_chat": user_data["message_count"],
                "sample_messages": sample_messages_text,  # Backward compatible
                "messages_with_metadata": user_data["messages"],  # Full metadata
                "has_fresh_message": has_fresh_message,
            }
            candidate_list.append(candidate)

        logger.info(
            f"Found {len(candidate_list)} potential leads from message history."
        )
        return candidate_list

    except ParsingPausedError:
        raise  # Re-raise to be handled by caller
    except Exception as e:
        logger.error(f"Failed to parse messages from {chat_identifier}: {e}")
        return []


async def main():
    """Test function for local development."""
    test_chat = "@tondev_eng"
    logger.info(f"--- Testing Message Parser on chat: {test_chat} ---")

    try:
        candidates = await parse_users_from_messages(
            test_chat, only_with_channels=False, messages_limit=100
        )

        if candidates:
            print(f"\n--- Found {len(candidates)} active users ---")
            candidates.sort(key=lambda x: x['messages_in_chat'], reverse=True)

            for i, candidate in enumerate(candidates[:10]):
                print(
                    f"#{i+1}: @{candidate['username']} "
                    f"(Messages: {candidate['messages_in_chat']})"
                )
                print(f"  Bio: {candidate['bio']}")
                print(f"  Has fresh message: {candidate['has_fresh_message']}")

                if candidate['messages_with_metadata']:
                    print("  Messages with links:")
                    for msg in candidate['messages_with_metadata'][:2]:
                        print(
                            f"    - [{msg['freshness']}] {msg['age_display']}: "
                            f"{msg['text'][:50]}..."
                        )
                        print(f"      Link: {msg['link']}")
        else:
            print("\n--- No candidates found ---")
    finally:
        await TelegramAuthManager.disconnect()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
