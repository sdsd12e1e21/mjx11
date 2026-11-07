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

"""Same-database native comparison with the unchanged two-statement strategy."""

import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import EmbeddingProfile, Memory, MemoryEntryInput, MemoryService
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.artifacts import ArtifactRepository
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires the native Linux seekdb binding")
PROFILE = EmbeddingProfile(
    profile_id="native-comparison", model="deterministic", dimension=384, distance="l2", normalization="unit"
)


class _Embedding:
    profile = PROFILE

    async def embed(self, texts, /):
        vectors = []
        for content in texts:
            match = re.search(r"topic(\d+)", content)
            topic = int(match[1]) % 20 if match else 20
            raw = hashlib.shake_256(content.encode()).digest(384)
            vector = [((value / 255) - 0.5) * 0.001 for value in raw]
            vector[topic] = 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append(tuple(value / norm for value in vector))
        return EmbeddingResult(vectors=tuple(vectors))


def _identities(result):
    return tuple((hit.memory_ref, hit.entry_id, hit.entry_version_id, hit.text, hit.matched_by) for hit in result.hits)


def _candidate_recorder(statements):
    def record(_connection, _cursor, statement, parameters, _context, _many):
        if "AGAINST" in statement.upper() and "l2_distance" in statement.lower():
            statements.append((statement, parameters))

    return record


async def test_native_384_dimensional_hybrid_matches_two_statement_retrieval(tmp_path):
    statements = []
    tag_statements = []
    record = _candidate_recorder(statements)
    record_tag = _candidate_recorder(tag_statements)

    model = _Embedding()
    latencies = []
    matches = 0
    recalls = []
    async with open_builtin_contexts(
        BuiltinConfig(database=SeekDBConfig(path=tmp_path / "native")), embedding_model=model
    ) as contexts:
        for scope_number in range(3):
            scope = f"comparison-{scope_number}"
            memory = (await contexts.get(scope)).artifacts.memory
            head = await memory.remember(
                memory=None,
                entries=tuple(
                    MemoryEntryInput(
                        kind="document",
                        text=f"topic{index % 20} evidence document {index} records controlled measurements.",
                    )
                    for index in range(173)
                ),
                mode="append",
            )
            head = await memory.remember(
                memory=head,
                entries=(MemoryEntryInput(kind="document", text="unrelated appended observation"),),
                mode="append",
            )
            assert head is not None
            baseline = MemoryService(
                backend=RelationalMemoryBackend(
                    database=contexts.database,
                    scope_id=scope,
                    artifacts=ArtifactRepository((Memory,)),
                    index=CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(PROFILE)),
                ),
                embedding_model=model,
            )
            originals = {entry.entry_id: entry for entry in await memory.entries(head)}
            for number in range(20):
                query = f"topic{number}"
                await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                await baseline.search(query, memories=(head,), mode="hybrid", limit=10)

                async def candidate(memory=memory, query=query, head=head):
                    event.listen(Engine, "before_cursor_execute", record)
                    before = len(statements)
                    started = time.perf_counter()
                    try:
                        result = await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                    finally:
                        event.remove(Engine, "before_cursor_execute", record)
                    latencies.append((time.perf_counter() - started) * 1000)
                    assert len(statements) - before == 1
                    return result

                if number % 2:
                    expected = await baseline.search(query, memories=(head,), mode="hybrid", limit=10)
                    actual = await candidate()
                else:
                    actual = await candidate()
                    expected = await baseline.search(query, memories=(head,), mode="hybrid", limit=10)
                assert _identities(actual) == _identities(expected)
                assert _identities(
                    await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                ) == _identities(actual)
                matches += 1
                relevant = {entry_id for entry_id, entry in originals.items() if entry.text.startswith(query + " ")}
                returned = {hit.entry_id for hit in actual.hits}
                recalls.append(len(returned & relevant) / len(relevant))
                assert len(returned) == len(actual.hits)
                for hit in actual.hits:
                    assert hit.memory_ref == head.as_ref()
                    assert hit.text == originals[hit.entry_id].text
                    assert hit.entry_version_id == originals[hit.entry_id].entry_version_id
                    assert hit.matched_by
            target = next(entry for entry in originals.values() if entry.text.startswith("topic0 "))
            tagged_target = MemoryEntryTagTarget(artifact_id=head.artifact_id, entry_id=target.entry_id)
            tags = await contexts.records.get_tags(scope, tagged_target)
            await contexts.records.replace_tags(scope, tagged_target, ("selected", "reviewed"), expected_etag=tags.etag)
            for tag_filter in (
                TagFilter(tags=("selected", "reviewed"), match="all"),
                TagFilter(tags=("selected", "missing"), match="any"),
            ):
                event.listen(Engine, "before_cursor_execute", record_tag)
                before = len(tag_statements)
                try:
                    tagged = await memory.search(
                        "topic0", memories=(head,), mode="hybrid", limit=10, tag_filter=tag_filter
                    )
                finally:
                    event.remove(Engine, "before_cursor_execute", record_tag)
                assert len(tag_statements) - before == 1
                assert [hit.entry_id for hit in tagged.hits] == [target.entry_id]
        statement, parameters = statements[0]
        async with contexts.database.transaction() as connection:
            plan = "\n".join(
                str(row[0]) for row in (await connection.exec_driver_sql("EXPLAIN " + statement, parameters)).all()
            )
        assert "TEXT RETRIEVAL SCAN" in plan
        assert "VECTOR INDEX" in plan
        tag_statement, tag_parameters = tag_statements[0]
        async with contexts.database.transaction() as connection:
            tag_plan = "\n".join(
                str(row[0])
                for row in (await connection.exec_driver_sql("EXPLAIN " + tag_statement, tag_parameters)).all()
            )
        assert "TEXT RETRIEVAL SCAN" in tag_plan
        assert "VECTOR INDEX" in tag_plan
    summary = {
        "queries": matches,
        "candidate_statements": len(statements),
        "exact_baseline_matches": matches,
        "mean_recall_at_10": statistics.mean(recalls),
        "p50_latency_ms": statistics.median(latencies),
        "tagged_candidate_statements": len(tag_statements),
    }
    assert summary["mean_recall_at_10"] >= 0.95
    assert summary["p50_latency_ms"] <= 500
    report = Path(os.environ.get("POWERCONTEXT_NATIVE_REPORT_DIR", tmp_path))
    (report / "native-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (report / "native-explain.txt").write_text(plan, encoding="utf-8")
    (report / "native-tagged-explain.txt").write_text(tag_plan, encoding="utf-8")
