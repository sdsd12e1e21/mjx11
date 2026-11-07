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

"""Query-specific literal spans, complete budgets, identity, and native prepare."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    ContextAssembly,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY
from powercontext.builtin.scope import ScopeDraft

MEMORY = ArtifactRef(family="memory", artifact_id="memory", revision=3)


def _hit(text, entry_id="fact"):
    return MemoryHit(
        memory_ref=MEMORY, entry_id=entry_id, entry_version_id=f"{entry_id}-v1", text=text, score=1, matched_by=("fts",)
    )


def _build(text, query, budget=1400, **settings):
    return PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True, **settings),
        current_scope_id="scope",
        memory_candidates=(PreparedMemoryCandidates(scope_id="scope", memory_ref=MEMORY, hits=(_hit(text),)),),
    )


def _assert_literal(build, originals, budget):
    content = build.context.content or ""
    assert build.context.content_bytes == len(content.encode("utf-8")) <= budget
    if not content:
        assert build.context.status == "empty" and not build.fragments and not build.origins
        return
    assert content.startswith(TRUST_POLICY)
    assert "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n" in content
    assert content.endswith("\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1")
    envelope = json.loads(content.splitlines()[-2])
    assert envelope["trust"] == "untrusted_history"
    assert len(envelope["items"]) == len(build.fragments) == len(build.origins)
    for item, fragment, origin in zip(envelope["items"], build.fragments, build.origins, strict=True):
        address = fragment.address
        text = originals[(address.memory.scope_id, address.entry_id)]
        assert type(fragment.start) is int and type(fragment.end) is int
        assert 0 <= fragment.start < fragment.end <= len(text)
        assert fragment.text == text[fragment.start : fragment.end]
        assert origin == address
        assert item == {
            "citation": {
                "scope_id": address.memory.scope_id,
                "memory_ref": address.memory.artifact.model_dump(mode="json"),
                "entry_id": address.entry_id,
                "entry_version_id": address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }


def test_query_switch_and_disjoint_evidence_preserve_whole_sentences():
    first = "The cobalt sensor is calibrated at 37 degrees."
    last = "The amber valve opens at 19 degrees."
    text = first + " " + "Unrelated administrative scheduling information. " * 80 + last
    cobalt = _build(text, "cobalt sensor calibrated", 1200)
    amber = _build(text, "amber valve opens", 1200)
    assert any(first in fragment.text for fragment in cobalt.fragments)
    assert any(last in fragment.text for fragment in amber.fragments)
    assert cobalt.fragments != amber.fragments
    both = _build(text, "cobalt sensor calibrated amber valve opens", 1800)
    assert len(both.fragments) >= 2
    assert any(first in fragment.text for fragment in both.fragments)
    assert any(last in fragment.text for fragment in both.fragments)
    assert both.fragments[0].end < both.fragments[-1].start
    _assert_literal(both, {("scope", "fact"): text}, 1800)


@pytest.mark.parametrize("budget", (512, 650, 800, 1200, 1400, 1800, 32768))
def test_unicode_json_escaping_and_exact_wire_budget(budget):
    text = (
        '前言，海洋数据记录。 station "测温" \\ 🧪\n' * 12  # noqa: RUF001 -- exercise fullwidth punctuation
        + "海洋观测 station 记录了 37 度。\x85第二次 station 观测\u2028仍有证据\u2029结束。"
    )
    build = _build(text, "海洋观测 station", budget)
    _assert_literal(build, {("scope", "fact"): text}, budget)
    if budget >= 1200:
        assert build.fragments


def test_late_matches_in_unpunctuated_text_and_inflected_terms():
    text = "irrelevant preliminary wording " * 120 + "Activated cells increased receptor binding and signaling"
    build = _build(text, "cell activation receptor binds", 1200)
    assert any("Activated cells" in fragment.text for fragment in build.fragments)
    assert all(fragment.start > 2000 for fragment in build.fragments)
    _assert_literal(build, {("scope", "fact"): text}, 1200)


def test_identical_text_across_scopes_retains_distinct_addresses_and_deduplicates_exact_candidates():
    text = "The cobalt sensor was calibrated."
    groups = tuple(
        PreparedMemoryCandidates(scope_id=scope, memory_ref=MEMORY, hits=(_hit(text),))
        for scope in ("left", "right", "left")
    )
    build = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensor", max_bytes=4096, evidence_selection=True),
        current_scope_id="left",
        memory_candidates=groups,
    )
    assert len(build.fragments) == 2
    assert {fragment.address.memory.scope_id for fragment in build.fragments} == {"left", "right"}
    _assert_literal(build, {("left", "fact"): text, ("right", "fact"): text}, 4096)


def test_tiny_budget_and_irrelevant_candidates_are_empty_without_invented_evidence():
    assert not _build("cobalt evidence", "cobalt", 512).fragments
    assert not _build("administrative scheduling information", "cobalt sensor", 1400).fragments
    assert not _build("cobalt evidence", "the and of", 1400).fragments


def test_exact_final_byte_boundary_can_still_deliver_the_full_fragment():
    full = _build("enzyme", "enzyme", 1200)
    exact = _build("enzyme", "enzyme", full.context.content_bytes)
    assert exact == full
    _assert_literal(exact, {("scope", "fact"): "enzyme"}, full.context.content_bytes)


def test_default_off_uses_unchanged_normal_assembly_and_budget_probe_agrees():
    builder = PreparedContextBuilder()
    group = PreparedMemoryCandidates(
        scope_id="scope", memory_ref=MEMORY, hits=(_hit("A station records temperature."),)
    )
    options = {"current_scope_id": "scope", "memory_candidates": (group,)}
    ordinary = builder.build_scopes_result(
        request=PrepareContextRequest(query="temperature", max_bytes=1200), **options
    )
    disabled = builder.build_scopes_result(
        request=PrepareContextRequest(query="temperature", max_bytes=1200, evidence_selection=False), **options
    )
    assert ordinary == disabled
    assert not ordinary.fragments
    request = PrepareContextRequest(
        query="temperature",
        max_bytes=1200,
        evidence_selection=True,
        assembly=ContextAssembly(sections=()),
        include_code=True,
    )
    selected = builder.build_scopes_result(request=request, **options)
    budget = builder.probe_budget(request=request, **options)
    assert selected.fragments
    assert budget.delivered_items == len(selected.fragments)
    assert budget.unused_bytes == request.max_bytes - selected.context.content_bytes


@pytest.mark.parametrize("value", (None, "true", 1))
def test_selection_flag_is_a_strict_boolean(value):
    with pytest.raises(ValidationError):
        PrepareContextRequest(query="station", evidence_selection=value)


def test_reference_invariant_is_enforced_before_selection():
    with pytest.raises(PreparedContextInvariantError):
        PreparedContextBuilder().build_scopes_result(
            request=PrepareContextRequest(query="station", evidence_selection=True),
            current_scope_id="scope",
            memory_candidates=(PreparedMemoryCandidates(scope_id="scope", hits=(_hit("station"),)),),
        )


async def test_fragments_resolve_through_real_memory_in_each_scope_and_native_prepare():
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        groups = []
        originals = {}
        for label in ("left", "right"):
            scope = await runtime.scopes.create(ScopeDraft(title=label, summary=label, idempotency_key=label))
            memory = runtime.memory.for_scope(scope.scope_id)
            text = "Background administrative notes. " * 50 + f"The cobalt station in {label} recorded 37 degrees."
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=text),)))
            page = await memory.search(SearchMemoryRequest(query="cobalt station", mode="fts", limit=16))
            groups.append(PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits))
            originals[(scope.scope_id, page.hits[0].entry_id)] = text
        build = PreparedContextBuilder().build_scopes_result(
            request=PrepareContextRequest(query="cobalt station", max_bytes=1800, evidence_selection=True),
            current_scope_id=groups[0].scope_id,
            memory_candidates=tuple(groups),
        )
        _assert_literal(build, originals, 1800)
        assert {fragment.address.memory.scope_id for fragment in build.fragments} == {
            group.scope_id for group in groups
        }
        for fragment in build.fragments:
            address = fragment.address
            citation = MemoryCitation(
                memory_ref=address.memory.artifact, entry_id=address.entry_id, entry_version_id=address.entry_version_id
            )
            original = await runtime.memory.for_scope(address.memory.scope_id).get(
                GetMemoryEntryRequest(citation=citation)
            )
            assert fragment.text == original.entry.text[fragment.start : fragment.end]
        native = await runtime.context.for_scope(groups[0].scope_id).prepare(
            PrepareContextRequest(
                query="cobalt station",
                max_bytes=1200,
                evidence_selection=True,
                include_code=True,
                assembly=ContextAssembly(sections=()),
            )
        )
        assert native.status == "ready" and native.content_bytes <= 1200
        assert "37 degrees" in native.content
