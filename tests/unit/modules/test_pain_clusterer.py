"""Unit tests for modules.pain_clusterer helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bot.models.pain import Pain, PainCluster
from bot.models.program import Program  # noqa: F401
from modules import pain_clusterer as clusterer
from modules.pain_clusterer import (
    _parse_llm_json,
    _render_prompt,
    _update_cluster_stats,
)


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


class _ClusterResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _ClusterSession:
    def __init__(self, unclustered, existing_clusters):
        self.unclustered = unclustered
        self.existing_clusters = existing_clusters
        self.added: list[PainCluster] = []
        self.exec_calls = 0
        self.flush_calls = 0
        self.commit_calls = 0
        self._next_cluster_id = 100

    async def execute(self, query):  # noqa: ANN001
        if self.exec_calls == 0:
            self.exec_calls += 1
            return _ClusterResult(self.unclustered)
        self.exec_calls += 1
        return _ClusterResult(self.existing_clusters)

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1
        for cluster in self.added:
            if getattr(cluster, "id", None) is None:
                cluster.id = self._next_cluster_id
                self._next_cluster_id += 1

    async def commit(self) -> None:
        self.commit_calls += 1


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_new_pains_disabled_or_no_unclustered(monkeypatch) -> None:
    monkeypatch.setattr(clusterer.config, "PAIN_COLLECTION_ENABLED", False)
    disabled = await clusterer.cluster_new_pains(
        1, _ClusterSession(unclustered=[], existing_clusters=[])
    )
    assert disabled == 0

    monkeypatch.setattr(clusterer.config, "PAIN_COLLECTION_ENABLED", True)
    no_rows = await clusterer.cluster_new_pains(
        1, _ClusterSession(unclustered=[], existing_clusters=[])
    )
    assert no_rows == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cluster_new_pains_assigns_existing_and_new(monkeypatch) -> None:
    pains = [
        Pain(
            id=1,
            user_id=10,
            program_id=7,
            text="p1",
            original_quote="q1",
            category="sales",
            intensity="high",
            source_chat="chat",
            source_message_id=1,
        ),
        Pain(
            id=2,
            user_id=10,
            program_id=7,
            text="p2",
            original_quote="q2",
            category="other",
            intensity="low",
            source_chat="chat",
            source_message_id=2,
        ),
        Pain(
            id=3,
            user_id=10,
            program_id=7,
            text="p3",
            original_quote="q3",
            category="other",
            intensity="low",
            source_chat="chat",
            source_message_id=3,
        ),
    ]
    existing_cluster = PainCluster(
        id=10,
        user_id=10,
        program_id=7,
        name="Existing",
        category="sales",
        description="desc",
    )
    session = _ClusterSession(unclustered=pains, existing_clusters=[existing_cluster])
    monkeypatch.setattr(clusterer.config, "PAIN_COLLECTION_ENABLED", True)
    monkeypatch.setattr(clusterer, "_load_prompt", lambda: "tpl")

    class _LLM:
        async def ainvoke(self, _messages):  # noqa: ANN001
            content = (
                '{"assignments":['
                '{"pain_id":1,"cluster_id":10},'
                '{"pain_id":2,"cluster_id":"new","new_cluster_name":"Ops","new_cluster_category":"operations","new_cluster_description":"d"},'
                '{"pain_id":3,"cluster_id":"new","new_cluster_name":"Ops","new_cluster_category":"operations","new_cluster_description":"d"},'
                '{"pain_id":999,"cluster_id":10},'
                '{"pain_id":2,"cluster_id":"bad"}'
                ']}'
            )
            return SimpleNamespace(content=content)

    monkeypatch.setattr(clusterer, "_llm", _LLM())
    updated: list[int] = []

    async def _update_stats(cluster_id: int, sess):  # noqa: ANN001
        updated.append(cluster_id)

    monkeypatch.setattr(clusterer, "_update_cluster_stats", _update_stats)

    clustered = await clusterer.cluster_new_pains(7, session)

    assert clustered == 3
    assert session.commit_calls == 1
    assert pains[0].cluster_id == 10
    assert pains[1].cluster_id is not None
    assert pains[2].cluster_id == pains[1].cluster_id
    assert sorted(updated) == sorted({10, pains[1].cluster_id})
