"""Unit tests for bot.services.program_runner."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bot.models.lead import Lead
from bot.models.pain import Pain
from bot.services import program_runner as pr
from bot.models.user import User
from modules.telegram_client import AuthorizationRequiredError


class _ScalarsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows: list[object] | None = None, scalar: int | None = None):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._rows)

    def scalar_one(self) -> int:
        if self._scalar is None:
            raise AssertionError("scalar_one() requested without scalar payload")
        return self._scalar


class _FakeSession:
    def __init__(self, user: User, program_name: str = "Program") -> None:
        self.user = user
        self.program_name = program_name
        self.leads: list[Lead] = []
        self.pains: list[Pain] = []
        self.no_autoflush = nullcontext()
        self._lead_id_seq = 1
        self._pain_id_seq = 1
        self.commit_calls = 0
        self.rollback_calls = 0

    async def get(self, model, key):
        if model is User and key == self.user.telegram_id:
            return self.user
        return None

    def add(self, obj):
        if isinstance(obj, Lead):
            if getattr(obj, "id", None) is None:
                obj.id = self._lead_id_seq
                self._lead_id_seq += 1
            self.leads.append(obj)
            return
        if isinstance(obj, Pain):
            if getattr(obj, "id", None) is None:
                obj.id = self._pain_id_seq
                self._pain_id_seq += 1
            self.pains.append(obj)
            return
        raise AssertionError(f"Unsupported add type: {type(obj)}")

    async def flush(self):
        return None

    async def refresh(self, lead: Lead, attribute_names=None):  # noqa: ANN001
        lead.program = SimpleNamespace(name=self.program_name)
        return None

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1

    async def execute(self, query):
        # Count leads queries
        if "count(leads.id)" in str(query):
            return _ExecuteResult(scalar=len(self.leads))

        # Lead lookup by username/program/user
        if self._query_entity_name(query) == "Lead":
            username = self._extract_equal_value(query, "telegram_username")
            program_id = self._extract_equal_value(query, "program_id")
            user_id = self._extract_equal_value(query, "user_id")
            for lead in self.leads:
                if (
                    lead.telegram_username == username
                    and lead.program_id == program_id
                    and lead.user_id == user_id
                ):
                    return _ExecuteResult(rows=[lead])
            return _ExecuteResult(rows=[])

        # Pain dedup lookup
        if self._query_entity_name(query) == "Pain":
            source_message_id = self._extract_equal_value(query, "source_message_id")
            source_chat = self._extract_equal_value(query, "source_chat")
            original_quote = self._extract_equal_value(query, "original_quote")
            user_id = self._extract_equal_value(query, "user_id")
            for pain in self.pains:
                if (
                    pain.user_id == user_id
                    and pain.source_message_id == source_message_id
                    and pain.source_chat == source_chat
                    and pain.original_quote == original_quote
                ):
                    return _ExecuteResult(rows=[pain])
            return _ExecuteResult(rows=[])

        return _ExecuteResult(rows=[])

    @staticmethod
    def _query_entity_name(query) -> str | None:
        column_descriptions = getattr(query, "column_descriptions", None) or []
        if not column_descriptions:
            return None
        entity = column_descriptions[0].get("entity")
        return entity.__name__ if entity else None

    @staticmethod
    def _extract_equal_value(query, column_name: str):
        for criterion in getattr(query, "_where_criteria", []):
            left = getattr(criterion, "left", None)
            right = getattr(criterion, "right", None)
            if getattr(left, "name", None) != column_name:
                continue
            return getattr(right, "value", None)
        return None


@dataclass
class _ProgramChat:
    chat_username: str


@dataclass
class _ProgramStub:
    id: int
    user_id: int
    name: str
    max_leads_per_run: int
    chats: list[_ProgramChat]
    niche_description: str = "niche"
    enrich: bool = False
    min_score: int = 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_pipeline_no_sources_returns_error(user_factory) -> None:
    user = user_factory(telegram_id=10)
    session = _FakeSession(user=user, program_name="NoSources")
    program = _ProgramStub(
        id=1, user_id=10, name="NoSources", max_leads_per_run=5, chats=[]
    )

    result = await pr.run_program_pipeline(program, session)

    assert result == {"error": "No sources found."}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_pipeline_auth_required(user_factory, monkeypatch) -> None:
    user = user_factory(telegram_id=11)
    session = _FakeSession(user=user, program_name="Auth")
    program = _ProgramStub(
        id=2,
        user_id=11,
        name="Auth",
        max_leads_per_run=5,
        chats=[_ProgramChat(chat_username="chat_a")],
    )

    async def _raise_auth(**kwargs):  # noqa: ANN003
        raise AuthorizationRequiredError("auth required")

    monkeypatch.setattr(
        pr.members_parser, "parse_users_from_messages", _raise_auth
    )

    result = await pr.run_program_pipeline(program, session)

    assert result == {"status": "auth_required"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_pipeline_creates_and_filters_leads(
    user_factory, monkeypatch
) -> None:
    user = user_factory(telegram_id=12, services_description="AI bots")
    session = _FakeSession(user=user, program_name="Pipeline")
    program = _ProgramStub(
        id=3,
        user_id=12,
        name="Pipeline",
        max_leads_per_run=10,
        chats=[_ProgramChat(chat_username="chat_main")],
        min_score=5,
    )

    candidates = [
        {"username": None},
        {
            "username": "alice",
            "source_chat_username": "chat_main",
            "messages_with_metadata": [
                {"message_id": 1, "text": "pain one", "link": "t.me/x/1"}
            ],
        },
        {
            "username": "bob",
            "source_chat_username": "chat_main",
            "messages_with_metadata": [
                {"message_id": 2, "text": "pain two", "link": "t.me/x/2"}
            ],
        },
    ]

    async def _parse_users_from_messages(**kwargs):  # noqa: ANN003
        return candidates, []

    monkeypatch.setattr(
        pr.members_parser, "parse_users_from_messages", _parse_users_from_messages
    )
    monkeypatch.setattr(pr.web_enricher, "search_ai_ideas_for_niche", lambda _: "")

    captured_services: list[str] = []

    def _qualify(candidate, enrichment, niche, ai_ideas, user_services_description):  # noqa: ANN001
        captured_services.append(user_services_description)
        if candidate["username"] == "alice":
            return {
                "llm_response": {
                    "qualification": {"score": 7},
                    "identification": {"business_type": "Seller"},
                    "identified_pains": ["manual ops"],
                    "product_idea": {"idea": "Bot"},
                    "outreach": {"message": "hello"},
                },
                "raw_input_prompt": "prompt-a",
            }
        if candidate["username"] == "bob":
            return {"error": "llm failure"}
        raise AssertionError("unexpected candidate")

    monkeypatch.setattr(pr.qualifier, "qualify_lead", _qualify)

    async def _fake_enrich(candidate, enrich_web):  # noqa: ANN001
        return {}

    monkeypatch.setattr(pr, "_enrich_candidate", _fake_enrich)

    async def _save_pains(**kwargs):  # noqa: ANN003
        return 2

    monkeypatch.setattr(pr, "_save_pains_from_lead", _save_pains)

    delivered: list[str] = []

    async def _on_lead_found(lead: Lead) -> None:
        delivered.append(lead.telegram_username)

    result = await pr.run_program_pipeline(program, session, _on_lead_found)

    assert result["candidates_found"] == 3
    assert result["leads_qualified"] == 1
    assert result["pains_saved"] == 2
    assert len(session.leads) == 1
    assert session.leads[0].telegram_username == "alice"
    assert delivered == ["alice"]
    assert captured_services == ["AI bots", "AI bots"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_program_pipeline_stops_at_max_leads(user_factory, monkeypatch) -> None:
    user = user_factory(telegram_id=13, services_description="svc")
    session = _FakeSession(user=user, program_name="Limit")
    program = _ProgramStub(
        id=4,
        user_id=13,
        name="Limit",
        max_leads_per_run=1,
        chats=[_ProgramChat(chat_username="chat_limit")],
        min_score=5,
    )

    candidates = [
        {
            "username": "u1",
            "messages_with_metadata": [{"message_id": 10, "text": "a"}],
        },
        {
            "username": "u2",
            "messages_with_metadata": [{"message_id": 11, "text": "b"}],
        },
    ]

    async def _parse_users_from_messages(**kwargs):  # noqa: ANN003
        return candidates, []

    monkeypatch.setattr(
        pr.members_parser, "parse_users_from_messages", _parse_users_from_messages
    )
    monkeypatch.setattr(pr.web_enricher, "search_ai_ideas_for_niche", lambda _: "")

    qual_calls = 0

    def _qualify(candidate, enrichment, niche, ai_ideas, user_services_description):  # noqa: ANN001
        nonlocal qual_calls
        qual_calls += 1
        return {
            "llm_response": {
                "qualification": {"score": 8},
                "identification": {"business_type": "Biz"},
                "identified_pains": ["pain"],
                "product_idea": {"idea": "Bot"},
                "outreach": {"message": "msg"},
            },
            "raw_input_prompt": "prompt",
        }

    monkeypatch.setattr(pr.qualifier, "qualify_lead", _qualify)

    async def _enrich(candidate, enrich_web):  # noqa: ANN001
        return {}

    monkeypatch.setattr(pr, "_enrich_candidate", _enrich)

    async def _save_pains(**kwargs):  # noqa: ANN003
        return 0

    monkeypatch.setattr(pr, "_save_pains_from_lead", _save_pains)

    result = await pr.run_program_pipeline(program, session)

    assert result["leads_qualified"] == 1
    assert len(session.leads) == 1
    assert qual_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_pains_from_lead_deduplicates_and_sanitizes(user_factory) -> None:
    user = user_factory(telegram_id=14)
    session = _FakeSession(user=user, program_name="Pain")

    candidate = {
        "username": "candidate_user",
        "user_id": 2**40,  # out of int32 range -> should be dropped
        "source_chat_username": "@chat_a",
        "messages_with_metadata": [
            {"message_id": 101, "text": "same quote", "link": "t.me/c/1/101"}
        ],
    }
    qualification = {
        "identified_pains": ["pain1", "pain2"],  # same msg cycles -> dedup key hit
        "identification": {"business_type": "Retail"},
    }

    inserted = await pr._save_pains_from_lead(
        user_id=14,
        program_id=99,
        candidate=candidate,
        qualification_result=qualification,
        session=session,
    )

    assert inserted == 1
    assert len(session.pains) == 1
    pain = session.pains[0]
    assert pain.source_chat == "chat_a"
    assert pain.source_user_id is None
    assert pain.business_type == "Retail"


@pytest.mark.unit
def test_extract_pain_texts_and_trim_helpers() -> None:
    result = pr._extract_pain_texts(
        {
            "identified_pains": [
                "  text pain  ",
                {"pain": "dict pain"},
                {"description": "desc pain"},
                {"text": "txt pain"},
                {"unknown": "x"},
                123,
                "",
            ]
        }
    )
    assert result == ["text pain", "dict pain", "desc pain", "txt pain"]

    assert pr._trim("  abc  ", 2) == "ab"
    assert pr._trim("   ", 10) is None
    assert pr._trim(None, 10) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enrich_candidate_paths(monkeypatch) -> None:
    async def _tg(username):  # noqa: ANN001
        return {"entity_data": {"username": username}}

    monkeypatch.setattr(pr.telegram_enricher, "enrich_with_telegram_data", _tg)
    monkeypatch.setattr(
        pr.web_enricher,
        "enrich_with_web_search",
        lambda candidate: {"q": candidate["username"]},
    )

    enriched = await pr._enrich_candidate(
        {
            "username": "alice",
            "has_channel": True,
            "channel_username": "alice_channel",
        },
        enrich_web=True,
    )
    assert enriched["channel_data"]["entity_data"]["username"] == "alice_channel"
    assert enriched["web_search_data"]["q"] == "alice"

    not_enriched = await pr._enrich_candidate(
        {"username": "bob", "has_channel": False}, enrich_web=False
    )
    assert not_enriched == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_pains_from_lead_empty_inputs(user_factory) -> None:
    user = user_factory(telegram_id=20)
    session = _FakeSession(user=user)

    no_pains = await pr._save_pains_from_lead(
        user_id=20,
        program_id=1,
        candidate={"messages_with_metadata": [{"message_id": 1, "text": "x"}]},
        qualification_result={"identified_pains": []},
        session=session,
    )
    assert no_pains == 0

    no_messages = await pr._save_pains_from_lead(
        user_id=20,
        program_id=1,
        candidate={"messages_with_metadata": []},
        qualification_result={"identified_pains": ["pain"]},
        session=session,
    )
    assert no_messages == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_pains_from_lead_skips_existing(user_factory) -> None:
    user = user_factory(telegram_id=21)
    session = _FakeSession(user=user)
    session.pains.append(
        Pain(
            user_id=21,
            program_id=2,
            text="existing",
            original_quote="quote",
            category="other",
            intensity="medium",
            source_chat="chat",
            source_message_id=5,
        )
    )

    inserted = await pr._save_pains_from_lead(
        user_id=21,
        program_id=2,
        candidate={
            "username": "u",
            "source_chat_username": "chat",
            "messages_with_metadata": [{"message_id": 5, "text": "quote", "link": None}],
        },
        qualification_result={"identified_pains": ["new pain"]},
        session=session,
    )

    assert inserted == 0
