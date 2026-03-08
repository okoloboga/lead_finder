"""Unit tests for modules.members_parser."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from modules import members_parser as mp
from modules.telegram_client import AuthorizationRequiredError


class _FakeTgUser:
    def __init__(
        self,
        user_id: int,
        username: str | None,
        *,
        first_name: str = "F",
        last_name: str = "L",
        bot: bool = False,
        deleted: bool = False,
        about: str | None = None,
    ) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.bot = bot
        self.deleted = deleted
        self.about = about


class _FakeMessage:
    def __init__(self, msg_id: int, text: str | None, date: datetime, sender) -> None:  # noqa: ANN001
        self.id = msg_id
        self.text = text
        self.date = date
        self._sender = sender

    async def get_sender(self):
        return self._sender


class _FakeClient:
    def __init__(self, chat_entity, messages, full_users):  # noqa: ANN001
        self.chat_entity = chat_entity
        self.messages = messages
        self.full_users = full_users

    async def get_entity(self, identifier):  # noqa: ANN001
        if isinstance(identifier, str):
            return self.chat_entity
        return self.full_users[identifier]

    async def iter_messages(self, _entity, limit: int):  # noqa: ANN001
        for msg in self.messages[:limit]:
            yield msg


@pytest.mark.unit
def test_members_parser_small_helpers() -> None:
    assert mp.find_channel_in_bio("contact @mychan12345") == "@mychan12345"
    assert mp.find_channel_in_bio("https://t.me/mychan12345") == "t.me/mychan12345"
    assert mp.find_channel_in_bio("none") is None

    assert mp.generate_message_link("@chat", -100123456, 77, True) == "t.me/chat/77"
    assert mp.generate_message_link(None, -100123456, 77, False) == "t.me/c/123456/77"

    now = datetime.now(timezone.utc)
    assert mp.get_message_freshness(now - timedelta(days=1)) == "hot"
    assert mp.format_message_age(now - timedelta(days=1)) == "вчера"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_users_from_messages_requires_auth(monkeypatch) -> None:
    async def _not_auth() -> bool:
        return False

    monkeypatch.setattr(mp.TelegramAuthManager, "is_authorized", staticmethod(_not_auth))
    with pytest.raises(AuthorizationRequiredError):
        await mp.parse_users_from_messages("@chat")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_users_from_messages_happy_path_without_batch(monkeypatch) -> None:
    monkeypatch.setattr(mp.telethon.tl.types, "User", _FakeTgUser)

    now = datetime.now(timezone.utc)
    sender = _FakeTgUser(1, "alice")
    sender_full = _FakeTgUser(1, "alice", about="I do stuff @alicechan")
    bot_sender = _FakeTgUser(2, "botuser", bot=True)
    old_sender = _FakeTgUser(3, "old")
    messages = [
        _FakeMessage(11, "need automation", now - timedelta(days=1), sender),
        _FakeMessage(12, "bot text", now - timedelta(days=1), bot_sender),
        _FakeMessage(
            13,
            "too old",
            now - timedelta(days=mp.config.MESSAGE_MAX_AGE_DAYS + 1),
            old_sender,
        ),
    ]
    entity = SimpleNamespace(username="chat_public", id=-100555000)
    client = _FakeClient(entity, messages, {1: sender_full})

    async def _auth() -> bool:
        return True

    async def _get_client():
        return client

    async def _no_delay(_kind: str) -> None:
        return None

    monkeypatch.setattr(mp.TelegramAuthManager, "is_authorized", staticmethod(_auth))
    monkeypatch.setattr(mp.TelegramAuthManager, "get_client", staticmethod(_get_client))
    monkeypatch.setattr(mp, "_random_delay", _no_delay)

    candidates, all_messages = await mp.parse_users_from_messages(
        "@chat_public",
        use_batch_analysis=False,
        messages_limit=100,
        max_messages_per_user=5,
    )

    assert len(all_messages) == 2
    assert len(candidates) == 1
    c = candidates[0]
    assert c["username"] == "alice"
    assert c["has_channel"] is True
    assert c["channel_username"] == "@alicechan"
    assert c["has_fresh_message"] is True
    assert c["messages_with_metadata"][0]["link"] == "t.me/chat_public/11"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_users_from_messages_with_batch_filter(monkeypatch) -> None:
    monkeypatch.setattr(mp.telethon.tl.types, "User", _FakeTgUser)
    now = datetime.now(timezone.utc)
    alice = _FakeTgUser(1, "alice")
    bob = _FakeTgUser(2, "bob")
    messages = [
        _FakeMessage(21, "alice pain", now - timedelta(days=1), alice),
        _FakeMessage(22, "bob pain", now - timedelta(days=1), bob),
    ]
    entity = SimpleNamespace(username="chat_public", id=-100777000)
    full_users = {
        1: _FakeTgUser(1, "alice", about="about alice"),
        2: _FakeTgUser(2, "bob", about="about bob"),
    }
    client = _FakeClient(entity, messages, full_users)

    async def _auth() -> bool:
        return True

    async def _get_client():
        return client

    monkeypatch.setattr(mp.TelegramAuthManager, "is_authorized", staticmethod(_auth))
    monkeypatch.setattr(mp.TelegramAuthManager, "get_client", staticmethod(_get_client))
    monkeypatch.setattr(
        mp,
        "batch_analyze_chat",
        lambda payload: {"potential_leads": [{"username": "@alice"}], "filtering_stats": {}},  # noqa: ARG005
    )

    candidates, _messages = await mp.parse_users_from_messages(
        "@chat_public", use_batch_analysis=True, messages_limit=10
    )
    assert len(candidates) == 1
    assert candidates[0]["username"] == "alice"
