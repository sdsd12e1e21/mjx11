# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Lifecycle transaction recovery, strict bindings, scope isolation and native recall."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    GetTopicMemoryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


async def _fixture(runtime, suffix):
    scope = await runtime.scopes.create(ScopeDraft(title=suffix, summary=suffix, idempotency_key=suffix))
    scope_id = scope.scope_id
    source = await runtime.sources.for_scope(scope_id).capture(
        CaptureSource(source_id=f"{suffix}-origin", content="origin", metadata={})
    )
    lifecycle = runtime.lifecycle.for_scope(scope_id)
    await lifecycle.register_source("origin", source.source_ref, revision=3)
    memory = runtime.memory.for_scope(scope_id)
    created = await memory.remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{suffix} evidence"),))
    )
    citation = created.entry.citation
    await lifecycle.register_memory("fact", citation, parents=("origin",), policy="all")
    topic = await runtime.records.for_scope(scope_id).create_artifact(
        "topic-memory", ArtifactWrite(content={"title": suffix, "summary": f"{suffix} evidence", "detail": suffix})
    )
    ref = ArtifactRef(family="topic-memory", artifact_id=topic.artifact_id, revision=topic.revision)
    await lifecycle.register_topic("topic", ref, parents=("fact",), policy="all")
    return scope_id, source.source_ref, citation, ref


def _event(sequence, available):
    return SourceLifecycleEvent(node_id="origin", revision=3, sequence=sequence, available=available, reason="test")


@pytest.mark.parametrize("restoring", (False, True))
async def test_native_write_failure_rolls_back_event_and_retries_after_restart(tmp_path, monkeypatch, restoring):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}"))
    async with open_builtin_runtime(config) as runtime:
        scope, _, citation, topic = await _fixture(runtime, "recovery")
        lifecycle = runtime.lifecycle.for_scope(scope)
        if restoring:
            await lifecycle.apply(_event(1, False))
        before = await runtime.memory.for_scope(scope).list(include_inactive=True)
        operation = "reactivate" if restoring else "forget"
        original = getattr(MemoryService, operation)

        async def failing(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("injected-after-native-commit")

        with monkeypatch.context() as patch:
            patch.setattr(MemoryService, operation, failing)
            with pytest.raises(RuntimeError, match="injected-after-native-commit"):
                await lifecycle.apply(_event(2, restoring))
        assert await runtime.memory.for_scope(scope).list(include_inactive=True) == before
        assert await lifecycle.resolve("fact", purpose="audit") == citation
        assert (
            bool((await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="recovery"))).hits)
            != restoring
        )
    async with open_builtin_runtime(config) as runtime:
        lifecycle = runtime.lifecycle.for_scope(scope)
        actual = await lifecycle.apply(_event(2, restoring))
        assert actual == (["fact", "origin", "topic"] if restoring else [])
        memory = runtime.memory.for_scope(scope)
        after = await memory.list(include_inactive=True)
        assert after.entries[0].state == ("active" if restoring else "inactive")
        assert after.entries[0].entry.entry_version_id == citation.entry_version_id
        assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == "recovery evidence"
        assert await lifecycle.resolve("topic", purpose="audit") == topic
        await lifecycle.apply(_event(2, restoring))
        assert await memory.list(include_inactive=True) == after


async def test_scope_isolation_registration_identity_and_invalid_references(tmp_path):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'scopes.db'}"))
    async with open_builtin_runtime(config) as runtime:
        left, source, citation, topic = await _fixture(runtime, "left")
        right, _, _, _ = await _fixture(runtime, "right")
        lifecycle = runtime.lifecycle.for_scope(left)
        await lifecycle.apply(_event(7, False))
        # Identical registrations stay idempotent even after their current state changes.
        before = await runtime.memory.for_scope(left).list(include_inactive=True)
        await lifecycle.register_source("origin", source, revision=3)
        await lifecycle.register_memory("fact", citation, parents=("origin",), policy="all")
        await lifecycle.register_topic("topic", topic, parents=("fact",), policy="all")
        assert await runtime.memory.for_scope(left).list(include_inactive=True) == before
        other = runtime.lifecycle.for_scope(right)
        for ref, method, kwargs in (
            (source, other.register_source, {"revision": 3}),
            (citation, other.register_memory, {"parents": ("origin",), "policy": "all"}),
            (topic, other.register_topic, {"parents": ("origin",), "policy": "all"}),
        ):
            with pytest.raises(SourceLifecycleError):
                await method("foreign", ref, **kwargs)
        with pytest.raises(SourceLifecycleError):
            await lifecycle.register_source("absent", SourceRef(source_type="content", source_id="absent"), revision=3)
        for parents, policy in ((("origin", "origin"), "all"), (("absent",), "all"), (("origin",), "bogus")):
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_memory("bad", citation, parents=parents, policy=policy)
        with pytest.raises(SourceLifecycleError):
            await lifecycle.resolve("origin", purpose="unknown")
        with pytest.raises(SourceLifecycleError):
            await lifecycle.resolve("unknown", purpose="audit")
        assert (await runtime.memory.for_scope(right).list()).entries[0].state == "active"
        assert await other.apply(_event(1, True)) == ["fact", "origin", "topic"]
    async with open_builtin_runtime(config) as runtime:
        assert not (await runtime.memory.for_scope(left).list()).entries
        assert (await runtime.memory.for_scope(right).list()).entries
        await runtime.lifecycle.for_scope(left).apply(_event(8, True))
        assert await runtime.lifecycle.for_scope(left).resolve("fact", purpose="generation") == citation


async def test_withdrawn_topics_do_not_consume_native_fts_or_browse_limit():
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        scope, _, _, withdrawn = await _fixture(runtime, "shared")
        # Inactive matches outnumber a single query's requested candidate page.
        lifecycle = runtime.lifecycle.for_scope(scope)
        for index in range(8):
            topic = await runtime.records.for_scope(scope).create_artifact(
                "topic-memory",
                ArtifactWrite(content={"title": "shared shared shared", "summary": "shared", "detail": "shared"}),
            )
            await lifecycle.register_topic(
                f"withdrawn{index}",
                ArtifactRef(family="topic-memory", artifact_id=topic.artifact_id, revision=topic.revision),
                parents=("origin",),
                policy="all",
            )
        survivor = await runtime.records.for_scope(scope).create_artifact(
            "topic-memory", ArtifactWrite(content={"title": "shared", "summary": "shared", "detail": "shared"})
        )
        independent = await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="shared independent evidence"),))
        )
        await lifecycle.apply(_event(1, False))
        page = await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="shared", limit=1))
        assert [hit.artifact_ref.artifact_id for hit in page.hits] == [survivor.artifact_id]
        browse = await runtime.topic_memory.for_scope(scope).browse(limit=1)
        assert [item.artifact_ref.artifact_id for item in browse] == [survivor.artifact_id]
        memory = await runtime.memory.for_scope(scope).search(SearchMemoryRequest(query="shared", mode="fts", limit=1))
        assert [hit.entry_version_id for hit in memory.hits] == [independent.entry.citation.entry_version_id]
        exact = await runtime.topic_memory.for_scope(scope).get(GetTopicMemoryRequest(artifact=withdrawn))
        assert exact.topic.as_ref() == withdrawn


@pytest.mark.parametrize(
    "field,value", (("revision", True), ("sequence", "1"), ("available", 0), ("reason", " \t"), ("node_id", ""))
)
def test_events_reject_coerced_or_blank_fields(field, value):
    data = _event(1, True).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent(**data)
