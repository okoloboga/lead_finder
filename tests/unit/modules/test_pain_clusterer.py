"""Unit tests for modules.pain_clusterer helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from modules.pain_clusterer import _parse_llm_json, _render_prompt, _update_cluster_stats


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeSession:
    def __init__(self, pains, cluster):
        self._pains = pains
        self._cluster = cluster

    async def execute(self, _query):  # noqa: ANN001
        return _Result(self._pains)

    async def get(self, _model, _cluster_id):  # noqa: ANN001
        return self._cluster


@pytest.mark.unit
def test_parse_llm_json_plain_and_fenced() -> None:
    plain = '{"assignments":[{"pain_id":1,"cluster_id":2}]}'
    fenced = "```json\n{\"assignments\":[{\"pain_id\":1,\"cluster_id\":2}]}\n```"
    assert _parse_llm_json(plain)["assignments"][0]["pain_id"] == 1
    assert _parse_llm_json(fenced)["assignments"][0]["cluster_id"] == 2


@pytest.mark.unit
def test_render_prompt_replaces_known_placeholders() -> None:
    template = "old={existing_clusters};new={new_pains};json={\"k\":\"v\"}"
    rendered = _render_prompt(
        template,
        existing_clusters="A",
        new_pains="B",
    )
    assert "old=A" in rendered
    assert "new=B" in rendered
    assert "json={\"k\":\"v\"}" in rendered


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_cluster_stats_sets_counts_intensity_and_trend() -> None:
    now = datetime.now(timezone.utc)
    pains = [
        SimpleNamespace(intensity="high", message_date=now - timedelta(days=1)),
        SimpleNamespace(intensity="medium", message_date=now - timedelta(days=2)),
        SimpleNamespace(intensity="low", message_date=now - timedelta(days=10)),
    ]
    cluster = SimpleNamespace(
        pain_count=0,
        avg_intensity=0.0,
        first_seen=None,
        last_seen=None,
        trend="stable",
    )
    session = _FakeSession(pains, cluster)

    await _update_cluster_stats(cluster_id=1, session=session)

    assert cluster.pain_count == 3
    assert cluster.avg_intensity == 2.0
    assert cluster.first_seen is not None
    assert cluster.last_seen is not None
    assert cluster.trend == "growing"
