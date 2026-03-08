"""Unit tests for modules.qualifier."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules import qualifier as q


@pytest.mark.unit
def test_extract_json_payload_and_parse_helpers() -> None:
    raw = "```json\nnoise\n{\"a\":1,\"b\":2}\n```"
    payload = q._extract_json_payload(raw)
    assert payload.startswith("{")
    parsed = q._parse_llm_json(raw)
    assert parsed["a"] == 1


@pytest.mark.unit
def test_recover_partial_batch_response() -> None:
    truncated = (
        '{"total_messages_analyzed":3,"potential_leads":['
        '{"username":"@u1","priority":"high"},'
        '{"username":"@u2","priority":"medium"}'
    )
    recovered = q._recover_partial_batch_response(truncated, analyzed_count=3)
    assert recovered is not None
    assert recovered["total_messages_analyzed"] == 3
    assert len(recovered["potential_leads"]) == 2
    assert recovered["recovered_from_truncated_json"] is True


@pytest.mark.unit
def test_formatters_and_freshness_summary() -> None:
    assert q.get_freshness_emoji("hot") == "🔥"
    assert q.get_freshness_emoji("unknown") == ""

    messages = [
        {
            "freshness": "hot",
            "age_display": "today",
            "text": "Need automation",
            "link": "t.me/chat/1",
            "chat_username": "chat",
        },
        {
            "freshness": "cold",
            "age_display": "10 days",
            "text": "Old one",
        },
    ]
    formatted = q.format_messages_with_metadata(messages)
    assert "Сообщения пользователя в чате" in formatted
    assert "🔗 t.me/chat/1" in formatted

    prompt_data = q.format_enrichment_data_for_prompt(
        {
            "channel_data": {"entity_data": {"title": "C", "participants_count": 10}},
            "web_search_data": {
                "website": "https://example.com",
                "mentions": [{"title": "Mention", "source": "Web"}],
            },
        },
        {"messages_with_metadata": messages},
    )
    assert "Данные с личного Telegram-канала" in prompt_data
    assert "Данные из веб-поиска" in prompt_data

    summary = q.get_freshness_summary({"messages_with_metadata": messages})
    assert summary["total_messages"] == 2
    assert summary["has_hot"] is True
    assert summary["can_reply_in_chat"] is True


@pytest.mark.unit
def test_qualify_lead_success_and_penalty(monkeypatch) -> None:
    monkeypatch.setattr(q, "load_qualification_prompt", lambda: "X {services_description}")

    class _LLM:
        def invoke(self, _messages):  # noqa: ANN001
            return SimpleNamespace(
                content=(
                    '{"qualification":{"score":7,"reasoning":"не можем решить через API"},'
                    '"identification":{"business_type":"Seller"},'
                    '"identified_pains":["manual"],'
                    '"product_idea":{"idea":"Bot"},'
                    '"outreach":{"message":"hi"}}'
                )
            )

    monkeypatch.setattr(q, "llm", _LLM())
    result = q.qualify_lead(
        candidate_data={"username": "alice", "messages_with_metadata": []},
        enrichment_data={},
        niche="ecom",
        ai_ideas="",
        user_services_description="AI bots",
    )

    assert "error" not in result
    qual = result["llm_response"]["qualification"]
    assert qual["llm_score"] == 7
    assert qual["score"] == 0
    assert qual["penalty_applied"] is True
    assert "Ниша, в которой он найден" in result["raw_input_prompt"]


@pytest.mark.unit
def test_qualify_lead_error_paths(monkeypatch) -> None:
    monkeypatch.setattr(q, "llm", None)
    no_llm = q.qualify_lead({}, {}, "niche")
    assert no_llm["error"] == "LLM client is not initialized."

    class _BadLLM:
        def invoke(self, _messages):  # noqa: ANN001
            return SimpleNamespace(content="not json")

    monkeypatch.setattr(q, "llm", _BadLLM())
    monkeypatch.setattr(q, "load_qualification_prompt", lambda: "prompt")
    bad_json = q.qualify_lead({"username": "u"}, {}, "n")
    assert bad_json["error"] == "JSONDecodeError"


@pytest.mark.unit
def test_batch_analyze_chat_paths(monkeypatch) -> None:
    monkeypatch.setattr(q, "llm", None)
    none_llm = q.batch_analyze_chat([{"username": "@u", "text": "x"}])
    assert none_llm["error"] == "LLM client is not initialized."

    class _LLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, _messages):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content=(
                        '{"potential_leads":['
                        '{"username":"@u1","priority":"high"}'
                    )
                )
            return SimpleNamespace(
                content='{"potential_leads":[{"username":"@u1","priority":"high"}]}'
            )

    monkeypatch.setattr(q, "llm", _LLM())
    monkeypatch.setattr(q, "load_batch_analysis_prompt", lambda: "prompt")
    recovered = q.batch_analyze_chat([{"username": "@u1", "text": "pain"}])
    assert "potential_leads" in recovered
    assert recovered["potential_leads"][0]["username"] == "@u1"
