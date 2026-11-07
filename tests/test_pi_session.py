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

"""Raw branch evidence, immutable events, and real-runtime recovery."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from powercontext import ConnectorSubmissionRejectedError
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CommitConnectorCheckpoint,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    ConnectorBinding,
    ConnectorRunStatus,
    SourceDefinitionRegistry,
    SourceMaterialization,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.connectors import ConnectorLifecycle
from powercontext.sources.pi_session import (
    PI_EVENT_SOURCE_DEFINITION,
    PiEventSource,
    PiSessionConnector,
    PiSessionInput,
    parse_pi_session,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def _archive(records, *, session_id="session", sort_keys=False):
    header = {"type": "session", "version": 3, "id": session_id}
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=sort_keys) for row in [header, *records]).encode()


def _message(event_id, parent=None, text="evidence", role="user"):
    return {"type": "message", "id": event_id, "parentId": parent, "message": {"role": role, "content": text}}


def test_raw_branch_ignores_context_edits_and_preserves_text_block_boundaries():
    records = [
        _message("root", text="  第一行\u2028第二行\r\n  "),
        _message("hidden", "root", [{"type": "thinking", "thinking": "private"}, {"type": "image"}]),
        _message(
            "call",
            "hidden",
            [
                {"type": "text", "text": ""},
                {"type": "toolCall", "name": "read", "id": "call:1", "arguments": {"z": "中文", "a": [1, False]}},
                {"type": "text", "text": " end "},
            ],
            role="assistant",
        ),
        {"type": "context_edit", "id": "edit", "parentId": "call", "targetId": "root", "replacement": None},
        {"type": "compaction", "id": "compact", "parentId": "edit", "summary": "摘要", "firstKeptEntryId": "call"},
        {"type": "branch_summary", "id": "summary", "parentId": "compact", "fromId": "call", "summary": "另一摘要"},
        {"type": "custom_message", "id": "custom", "parentId": "summary", "content": " \n "},
        {
            "type": "message",
            "id": "bash",
            "parentId": "custom",
            "message": {"role": "bashExecution", "command": "printf untouched", "output": "raw\r\noutput"},
        },
    ]
    events = parse_pi_session(PiSessionInput(content=b"\xef\xbb\xbf" + _archive(records)))
    assert [event.event_id for event in events] == ["root", "call", "compact", "summary", "custom", "bash"]
    assert [event.content for event in events] == [
        "user:   第一行\u2028第二行\r\n  ",
        'assistant: \n[tool_call read call:1] {"a":[1,false],"z":"中文"}\n end ',
        "compaction: 摘要",
        "branch_summary: 另一摘要",
        "custom:  \n ",
        "bashExecution: $ printf untouched\nraw\r\noutput",
    ]
    assert events[1].parent_id == "hidden"
    assert [event.record for event in events] == [records[index] for index in (0, 2, 4, 5, 6, 7)]
    assert parse_pi_session(PiSessionInput(content=_archive(records), leaf_id="edit")) == events[:2]


@pytest.mark.parametrize(
    "raw",
    [
        _archive([], session_id=""),
        b'{"type":"session","version":"3","id":"s"}',
        b'{"type":"session","version":3.0,"id":"s"}',
        _archive([{"type": "message", "id": "a"}]),
        _archive([{"type": "model_change", "id": "a", "parentId": 1}]),
        _archive([
            {"type": "model_change", "id": "a", "parentId": "b"},
            {"type": "label", "id": "b", "parentId": None},
        ]),
        _archive([{"type": "session", "id": "again", "version": 3, "parentId": None}]),
        _archive([_message("ok")]) + b'\n{"type":"label","id":"bad","parentId":null,"data":NaN}',
        _archive([_message("ok")]) + b"\nnull",
        _archive([_message("ok")]) + b"\n\xff",
        _archive([_message("ok")]) + b'\n{"unfinished":',
    ],
)
def test_invalid_archives_fail_before_returning_events(raw):
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=raw, leaf_id="ok"))


def test_header_only_and_control_only_archives_are_valid_but_missing_leaves_are_not():
    assert parse_pi_session(PiSessionInput(content=_archive([]))) == ()
    controls = [{"type": "model_change", "id": "model", "parentId": None}]
    assert parse_pi_session(PiSessionInput(content=_archive(controls))) == ()
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=_archive([]), leaf_id="absent"))
    bad_unselected_branch = _archive([_message("root"), {"type": "label", "id": "bad", "parentId": "missing"}])
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=bad_unselected_branch, leaf_id="root"))


async def test_source_identity_is_bounded_and_independent_of_payload_or_path():
    registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
    pairs = [("s:a", "b"), ("s", "a:b"), ("会话" * 300, "事件" * 300), ("s", "a/b"), ("s", "a%2Fb")]
    names = []
    for session_id, event_id in pairs:
        event = parse_pi_session(PiSessionInput(content=_archive([_message(event_id)], session_id=session_id)))[0]
        source = await registry.resolve(event)
        assert source.materialization is SourceMaterialization.CAPTURED
        assert len(source.name) <= 256
        restored = PiEventSource.model_validate_json(source.model_dump_json())
        assert await registry.read(restored) == event
        evidence = registry.project(restored, TEXT_EVIDENCE_PROJECTION_KEY)
        assert evidence["source_id"] == source.name
        assert evidence["content"] == event.content
        assert evidence["metadata"]["session_id"] == session_id
        changed = event.model_copy(update={"content": "different text"})
        assert (await registry.resolve(changed)).name == source.name
        names.append(source.name)
    assert len(set(names)) == len(pairs)


class _RuntimeSink:
    def __init__(self, runtime, failure=None):
        self.runtime = runtime
        self.registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
        self.failure = failure

    async def submit(self, binding, item_id, definition_name, value):
        if value.event_id == "tail" and self.failure:
            if self.failure == "reject":
                raise ConnectorSubmissionRejectedError("test rejection")  # noqa: TRY003
            raise OSError("test write failure")  # noqa: TRY003
        source = await self.registry.resolve(value)
        receipt = await self.runtime.ingestion.submit(
            SubmitSourceObservation(
                scope_id=binding.scope_id, observation=project_source_for_transport(self.registry, source)
            )
        )
        return receipt.source_ref


class _RuntimeCheckpoints:
    def __init__(self, runtime):
        self.runtime = runtime

    async def load(self, binding):
        return (await self.runtime.ingestion.checkpoint(binding)).checkpoint

    async def save(self, binding, checkpoint, *, expected):
        await self.runtime.ingestion.commit(
            CommitConnectorCheckpoint(binding=binding, checkpoint=checkpoint, expected=expected)
        )


async def _prepare(tmp_path):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pi.db'}"))
    async with open_builtin_runtime(config) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Pi", summary="Raw evidence", idempotency_key="pi"))
        await runtime.ingestion.register(manifest_for_definition(PI_EVENT_SOURCE_DEFINITION))
    binding = ConnectorBinding(
        scope_id=scope.scope_id, binding_id="pi", connector_name="pi-session-history", connector_version="1"
    )
    return config, binding


async def _run(config, binding, path, leaf=None, failure=None):
    async with open_builtin_runtime(config) as runtime:
        return await ConnectorLifecycle(
            sink=_RuntimeSink(runtime, failure), checkpoints=_RuntimeCheckpoints(runtime)
        ).run(PiSessionConnector(path, leaf), binding)


async def _stored(config, binding):
    async with open_builtin_contexts(config) as contexts:
        entries = await (await contexts.get(binding.scope_id)).sources.journal.entries()
        return {entry.source.payload["event_id"]: entry.source for entry in entries}


async def test_changed_abandoned_branch_fails_before_new_sources_or_checkpoint_are_written(tmp_path):
    config, binding = await _prepare(tmp_path)
    path = tmp_path / "branches.jsonl"
    records = [_message("root"), _message("left", "root"), _message("right", "root")]
    path.write_bytes(_archive(records))
    await _run(config, binding, path, "left")
    right = await _run(config, binding, path, "right")
    records.append(_message("new", "right"))
    original_left = deepcopy(records[1])
    records[1]["extra"] = {"changed": True}
    path.write_bytes(_archive(records))
    with pytest.raises(ValueError, match="left"):
        await _run(config, binding, path, "new")
    assert set(await _stored(config, binding)) == {"root", "left", "right"}
    records[1] = original_left
    path.write_bytes(_archive(records, sort_keys=True))
    repaired = await _run(config, binding, path, "new")
    assert repaired.previous_checkpoint == right.committed_checkpoint
    assert len(repaired.items) == 1
    assert set(await _stored(config, binding)) == {"root", "left", "right", "new"}


class _EvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(kind=f"pi-part-{index}", text=content[index : index + 1500], sources=(source,))
            for source in request.sources
            for content in (source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],)
            for index in range(0, len(content), 1500)
        )


@pytest.mark.parametrize("failure", ["raise", "reject"])
async def test_partial_failure_restarts_idempotently_and_large_tool_result_remains_complete(tmp_path, failure):
    config, binding = await _prepare(tmp_path)
    path = tmp_path / "failure.jsonl"
    records = [_message("root")]
    path.write_bytes(_archive(records))
    first = await _run(config, binding, path)
    output = "完整结果\n" * 10000 + "final evidence"
    records.extend([_message("accepted", "root", "new evidence"), _message("tail", "accepted", output, "toolResult")])
    records[-1]["message"].update(toolName="read", toolCallId="tool-1", details={"retained": [1, 2, 3]})
    path.write_bytes(_archive(records))
    if failure == "raise":
        with pytest.raises(OSError, match="test write failure"):
            await _run(config, binding, path, failure=failure)
    else:
        rejected = await _run(config, binding, path, failure=failure)
        assert rejected.status is ConnectorRunStatus.INCOMPLETE
        assert rejected.committed_checkpoint == first.committed_checkpoint
    assert set(await _stored(config, binding)) == {"root", "accepted"}
    recovered = await _run(config, binding, path)
    assert recovered.previous_checkpoint == first.committed_checkpoint
    assert len(recovered.items) == 2
    assert (await _run(config, binding, path)).items == ()
    stored = await _stored(config, binding)
    assert len(stored) == 3
    full = f"toolResult: [tool_result read tool-1] {output}"
    assert stored["tail"].payload["record"] == records[-1]
    assert stored["tail"].projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"] == full
    async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
        memory = runtime.memory.for_scope(binding.scope_id)
        for _ in range(5):
            if not (await memory.flush()).processed:
                break
        page = await memory.search(SearchMemoryRequest(query="toolResult", mode="fts", limit=100))
        assert page.hits
        for hit in page.hits:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )
            entry = await memory.get(GetMemoryEntryRequest(citation=citation))
            assert any(source.source_id == stored["tail"].name for source in entry.entry.sources)
            assert entry.entry.text in full


async def test_late_invalid_graph_does_not_import_an_earlier_new_event(tmp_path):
    config, binding = await _prepare(tmp_path)
    path = tmp_path / "late-error.jsonl"
    records = [_message("root")]
    path.write_bytes(_archive(records))
    first = await _run(config, binding, path)
    records.append(_message("new", "root"))
    path.write_bytes(_archive([*records, {"type": "label", "id": "bad", "parentId": "absent"}]))
    with pytest.raises(ValueError):
        await _run(config, binding, path, "new")
    assert set(await _stored(config, binding)) == {"root"}
    path.write_bytes(_archive(records))
    repaired = await _run(config, binding, path)
    assert repaired.previous_checkpoint == first.committed_checkpoint
    assert len(repaired.items) == 1
