"""Unit tests for modules.content_generator helper functions."""

from __future__ import annotations

import pytest

from modules.content_generator import anonymize_quotes, _parse_llm_json, _render_prompt


@pytest.mark.unit
def test_anonymize_quotes_masks_usernames_links_and_phones() -> None:
    quotes = [
        "Пиши @john_doe и смотри t.me/abc +7 999 111-22-33 https://site.com",
    ]

    cleaned = anonymize_quotes(quotes)

    assert "[автор]" in cleaned[0]
    assert "[ссылка]" in cleaned[0]
    assert "[телефон]" in cleaned[0]
    assert "@john_doe" not in cleaned[0]


@pytest.mark.unit
def test_parse_llm_json_plain() -> None:
    payload = '{"title":"T","body":"B","hashtags":["#x"]}'

    data = _parse_llm_json(payload)

    assert data["title"] == "T"
    assert data["body"] == "B"
    assert data["hashtags"] == ["#x"]


@pytest.mark.unit
def test_parse_llm_json_markdown_fenced() -> None:
    payload = """```json\n{\"title\":\"T\",\"body\":\"B\",\"hashtags\":[]}\n```"""

    data = _parse_llm_json(payload)

    assert data["title"] == "T"
    assert data["body"] == "B"


@pytest.mark.unit
def test_render_prompt_replaces_known_placeholders_only() -> None:
    template = (
        "type={post_type};name={cluster_name};desc={cluster_description};"
        "count={pain_count};quotes={sample_quotes};ai={ai_best_practices};"
        "raw_json={\"k\":\"v\"}"
    )

    rendered = _render_prompt(
        template,
        post_type="Scenario",
        cluster_name="Cluster 1",
        cluster_description="Desc",
        pain_count=3,
        sample_quotes="Q1",
        ai_best_practices="Best",
    )

    assert "type=Scenario" in rendered
    assert "name=Cluster 1" in rendered
    assert "count=3" in rendered
    assert "raw_json={\"k\":\"v\"}" in rendered
