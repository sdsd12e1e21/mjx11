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

"""Persistent evidence DAGs with atomic native recall eligibility transitions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE,
    SOURCE_LIFECYCLE_GRAPHS_TABLE,
)
from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime

_Policy = Literal["all", "any"]
_Reference = SourceRef | MemoryCitation | ArtifactRef


class SourceLifecycleError(ValueError):
    """Invalid lifecycle identity, dependency, event or generation request."""

    def __init__(self, issue: str) -> None:
        self.issue = issue
        super().__init__(f"source lifecycle: {issue}")


class SourceLifecycleEvent(BaseModel):
    """One exact, monotonically ordered availability event for a Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise SourceLifecycleError("blank-identity-or-reason")
        return value


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["source", "memory", "topic"]
    reference: _Reference
    revision: int | None = None
    parents: tuple[str, ...] = ()
    policy: _Policy = "all"
    available: bool = True
    event: SourceLifecycleEvent | None = None


class _Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, _Node] = Field(default_factory=dict)

    def propagate(self) -> list[str]:
        # Parents must precede registration. Resolve explicitly rather than relying on
        # JSON object order, which a database or a future serializer may normalize.
        resolved: dict[str, bool] = {}

        def available(node_id: str) -> bool:
            if node_id not in resolved:
                node = self.nodes[node_id]
                supported = [available(parent) for parent in node.parents]
                resolved[node_id] = (
                    node.available
                    if node.kind == "source"
                    else (all(supported) if node.policy == "all" else any(supported))
                )
            return resolved[node_id]

        for node_id in self.nodes:
            self.nodes[node_id] = self.nodes[node_id].model_copy(update={"available": available(node_id)})
        return sorted(node_id for node_id, state in resolved.items() if state)


@dataclass(frozen=True)
class SourceLifecycleStore:
    """Storage dependencies sharing the caller's single transaction."""

    database: AsyncDatabase
    sources: SourceRepository
    topics: TopicMemoryRepository
    memory: Callable[[str, AsyncConnection], MemoryService]


class SourceLifecycleApplication:
    """Select a scope without creating or implicitly registering it."""

    def __init__(self, runtime: BuiltinRuntime, store: SourceLifecycleStore | None) -> None:
        self._runtime = runtime
        self._store = store

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._store, scope_id)


class ScopedSourceLifecycle:
    """Manage one immutable dependency graph and its event identities."""

    def __init__(self, runtime: BuiltinRuntime, store: SourceLifecycleStore | None, scope_id: str) -> None:
        self._runtime = runtime
        self._store = store
        self.scope_id = validate_scope_id(scope_id)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[tuple[SourceLifecycleStore, AsyncConnection, _Graph]]:
        if self._store is None:
            raise SourceLifecycleError("storage-unavailable")
        async with (
            self._runtime._scope_operation(self.scope_id),
            self._runtime._locked(self.scope_id),
            self._store.database.transaction() as connection,
        ):
            payload = await connection.scalar(
                select(SOURCE_LIFECYCLE_GRAPHS_TABLE.c.content).where(
                    SOURCE_LIFECYCLE_GRAPHS_TABLE.c.scope_id == self.scope_id
                )
            )
            graph = _Graph() if payload is None else _Graph.model_validate_json(payload)
            yield self._store, connection, graph

    async def register_source(self, node_id: str, reference: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision < 1 or not isinstance(reference, SourceRef):
            raise SourceLifecycleError("invalid-source-registration")
        await self._register(node_id, _Node(kind="source", reference=reference, revision=revision))

    async def register_memory(
        self, node_id: str, reference: MemoryCitation, *, parents: tuple[str, ...], policy: _Policy
    ) -> None:
        if not isinstance(reference, MemoryCitation):
            raise SourceLifecycleError("invalid-memory-registration")
        await self._register(node_id, self._derived("memory", reference, parents, policy))

    async def register_topic(
        self, node_id: str, reference: ArtifactRef, *, parents: tuple[str, ...], policy: _Policy
    ) -> None:
        if not isinstance(reference, ArtifactRef) or reference.family != "topic-memory":
            raise SourceLifecycleError("invalid-topic-registration")
        await self._register(node_id, self._derived("topic", reference, parents, policy))

    @staticmethod
    def _derived(
        kind: Literal["memory", "topic"], reference: _Reference, parents: tuple[str, ...], policy: _Policy
    ) -> _Node:
        if (
            not isinstance(parents, tuple)
            or not parents
            or any(not isinstance(parent, str) or not parent.strip() for parent in parents)
            or len(set(parents)) != len(parents)
            or policy not in {"all", "any"}
        ):
            raise SourceLifecycleError("invalid-parents-or-policy")
        return _Node(kind=kind, reference=reference, parents=tuple(sorted(parents)), policy=policy)

    async def _register(self, node_id: str, node: _Node) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("blank-node-id")
        async with self._transaction() as (store, connection, graph):
            existing = graph.nodes.get(node_id)
            if existing is not None:
                if existing.model_copy(update={"available": True, "event": None}) != node:
                    raise SourceLifecycleError("registration-conflict")
                return
            if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                raise SourceLifecycleError("missing-or-cyclic-parent")
            # Append-only registration of existing parents prevents every possible cycle.
            try:
                if isinstance(node.reference, SourceRef):
                    await store.sources.get(connection, self.scope_id, node.reference)
                elif isinstance(node.reference, MemoryCitation):
                    await store.memory(self.scope_id, connection).validate_citation(node.reference)
                else:
                    await store.topics.get_exact(connection, self.scope_id, node.reference)
            except (ValueError, LookupError) as error:
                raise SourceLifecycleError("reference-not-readable-in-scope") from error
            graph.nodes[node_id] = node
            graph.propagate()
            await self._commit(store, connection, graph)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("invalid-event")
        async with self._transaction() as (store, connection, graph):
            node = graph.nodes.get(event.node_id)
            if node is None or node.kind != "source" or event.revision != node.revision:
                raise SourceLifecycleError("unknown-source-or-revision")
            if node.event is not None and event.sequence <= node.event.sequence:
                if event != node.event:
                    raise SourceLifecycleError("stale-or-conflicting-event")
                return graph.propagate()
            graph.nodes[event.node_id] = node.model_copy(update={"available": event.available, "event": event})
            active = graph.propagate()
            # The graph, event acknowledgement, Memory revisions, and Topic eligibility
            # commit together. A failed native write leaves the event retryable in full.
            await self._commit(store, connection, graph)
            return active

    async def resolve(self, node_id: str, *, purpose: Literal["generation", "audit"]) -> _Reference:
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("invalid-purpose")
        async with self._transaction() as (_, _, graph):
            node = graph.nodes.get(node_id)
            if node is None or (purpose == "generation" and not node.available):
                raise SourceLifecycleError("unknown-or-unavailable-node")
            return node.reference.model_copy(deep=True)

    async def _commit(self, store: SourceLifecycleStore, connection: AsyncConnection, graph: _Graph) -> None:
        by_memory: dict[str, dict[str, bool]] = {}
        blocked: set[tuple[str, int]] = set()
        for node in graph.nodes.values():
            if isinstance(node.reference, MemoryCitation):
                states = by_memory.setdefault(node.reference.memory_ref.artifact_id, {})
                states[node.reference.entry_id] = states.get(node.reference.entry_id, True) and node.available
            elif node.kind == "topic" and isinstance(node.reference, ArtifactRef) and not node.available:
                blocked.add((node.reference.artifact_id, node.reference.revision))
        service = store.memory(self.scope_id, connection)
        for artifact_id, states in by_memory.items():
            head = await service.head(artifact_id)
            entries = await service.entries(head)
            manifest = {item.entry_id: item.state for item in head.content.manifest.entries}
            inactive = tuple(
                item for item in entries if states.get(item.entry_id) is False and manifest[item.entry_id] == "active"
            )
            active = tuple(
                item for item in entries if states.get(item.entry_id) is True and manifest[item.entry_id] == "inactive"
            )
            if inactive:
                head = await service.forget(head, entries=inactive, reason="source lifecycle withdrawal")
            if active:
                await service.reactivate(head, entries=active, reason="source lifecycle restoration")
        await connection.execute(
            delete(SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE).where(
                SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE.c.scope_id == self.scope_id
            )
        )
        if blocked:
            await connection.execute(
                insert(SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE),
                [
                    {"scope_id": self.scope_id, "artifact_id": artifact_id, "revision": revision}
                    for artifact_id, revision in sorted(blocked)
                ],
            )
        payload = graph.model_dump_json().encode("utf-8")
        exists = await connection.scalar(
            select(SOURCE_LIFECYCLE_GRAPHS_TABLE.c.scope_id).where(
                SOURCE_LIFECYCLE_GRAPHS_TABLE.c.scope_id == self.scope_id
            )
        )
        if exists is None:
            await connection.execute(
                insert(SOURCE_LIFECYCLE_GRAPHS_TABLE).values(scope_id=self.scope_id, content=payload)
            )
        else:
            await connection.execute(
                update(SOURCE_LIFECYCLE_GRAPHS_TABLE)
                .where(SOURCE_LIFECYCLE_GRAPHS_TABLE.c.scope_id == self.scope_id)
                .values(content=payload)
            )
