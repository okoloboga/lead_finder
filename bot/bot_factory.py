"""Creation of aiogram Bot instances with optional proxy support."""

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

import config


def create_bot(token: str) -> Bot:
    """Creates a Bot routed through config.TELEGRAM_PROXY when it is set."""
    if not config.TELEGRAM_PROXY:
        return Bot(token=token, parse_mode="HTML")

    return Bot(
        token=token,
        parse_mode="HTML",
        session=AiohttpSession(proxy=config.TELEGRAM_PROXY),
    )
