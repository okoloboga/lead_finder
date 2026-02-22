import os
from dotenv import load_dotenv

load_dotenv()

#
# API Keys
#
COMET_API_KEY = os.getenv("COMET_API_KEY")
COMET_API_BASE_URL = os.getenv("COMET_API_BASE_URL", "https://api.cometapi.com/v1")
COMET_API_MODEL = os.getenv("COMET_API_MODEL", "gpt-4o")

# Google Custom Search API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

#
# Telegram API
#
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

#
# Application Settings
#
POSTS_TO_FETCH = int(os.getenv("POSTS_TO_FETCH", 50))
MAX_CHANNELS_PER_SEARCH = int(os.getenv("MAX_CHANNELS_PER_SEARCH", 20))
SEARCH_QUERIES_COUNT = int(os.getenv("SEARCH_QUERIES_COUNT", 5))


#
# Rate Limiting & Safety Settings
#
# Safety modes: "fast", "normal", "careful"
SAFETY_MODE = os.getenv("SAFETY_MODE", "normal")

# Delays between operations (in seconds) - base values, will be randomized
SAFETY_DELAYS = {
    "fast": {
        "between_chats": (15, 30),           # seconds between parsing different chats
        "between_requests": (1, 2),          # seconds between API requests
        "between_channel_parse": (1, 2),     # seconds between parsing lead channels
        "between_posts_fetch": (0.5, 1),     # seconds between fetching posts
    },
    "normal": {
        "between_chats": (30, 60),
        "between_requests": (2, 3),
        "between_channel_parse": (2, 3),
        "between_posts_fetch": (1, 2),
    },
    "careful": {
        "between_chats": (60, 120),
        "between_requests": (3, 5),
        "between_channel_parse": (3, 5),
        "between_posts_fetch": (2, 3),
    }
}

# Session limits
MAX_CHATS_PER_RUN = int(os.getenv("MAX_CHATS_PER_RUN", 5))
MAX_PARTICIPANTS_PER_CHAT = int(os.getenv("MAX_PARTICIPANTS_PER_CHAT", 500))
MAX_CHANNELS_PER_RUN = int(os.getenv("MAX_CHANNELS_PER_RUN", 50))
MAX_SESSION_DURATION_MINUTES = int(os.getenv("MAX_SESSION_DURATION_MINUTES", 40))

# FloodWait handling
FLOODWAIT_EXTRA_SECONDS = 10  # Extra seconds to wait after FloodWaitError
MAX_FLOODWAIT_RETRIES = 2     # Max retries after FloodWait before stopping

# Message age filtering - only consider recent messages
MESSAGE_MAX_AGE_DAYS = int(os.getenv("MESSAGE_MAX_AGE_DAYS", 10))  # Only messages from last 10 days

# Message parsing limits
MESSAGES_LIMIT = int(os.getenv("MESSAGES_LIMIT", 500))  # Number of recent messages to parse per chat

# Message freshness categories (for display/metadata only, not scoring)
MESSAGE_FRESHNESS_DAYS = {
    "hot": 3,       # Messages < 3 days old
    "warm": 7,      # Messages < 7 days
    "cold": 30,     # Messages > 30 days
}


#
# Pain Collection Settings
#
PAIN_COLLECTION_ENABLED = os.getenv("PAIN_COLLECTION_ENABLED", "true").lower() == "true"
PAIN_BATCH_SIZE = int(os.getenv("PAIN_BATCH_SIZE", 25))


DEFAULT_CONFIG = {
    "search": {
        "queries_per_niche": 5,
        "max_results_per_query": 10,
        "deduplicate": True
    },
    "parser": {
        "posts_limit": 50,
        "include_comments": False,
        "timeout_seconds": 30
    },
    "qualifier": {
        "include_reasoning": True
    },
    "output": {
        "formats": ["json", "markdown"],
        "include_raw_data": False
    }
}


def get_delay(delay_type: str) -> tuple[float, float]:
    """Get delay range for current safety mode."""
    mode = SAFETY_MODE if SAFETY_MODE in SAFETY_DELAYS else "normal"
    return SAFETY_DELAYS[mode].get(delay_type, (2, 3))
