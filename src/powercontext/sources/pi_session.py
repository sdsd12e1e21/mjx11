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

"""Capture raw Pi v3 branch history and resume through durable checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PiSessionInput(BaseModel):
    """A complete offline Pi v3 JSONL archive and optional branch endpoint."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One original visible event, including its complete unmodified record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source, PiEventInput):
    """Captured event evidence independent of later model-context compaction."""


@dataclass(frozen=True)
class _Archive:
    session_id: str
    records: dict[str, dict[str, JsonValue]]
    branch: tuple[str, ...]


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Pi {field} must be a non-empty string")  # noqa: TRY003
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"Pi JSON must not contain {value}")  # noqa: TRY003


def _jsonl_records(content: bytes) -> Iterator[dict[str, JsonValue]]:
    for line in io.StringIO(content.decode("utf-8-sig"), newline=None):
        if not line.strip():
            continue
        record = json.loads(line, parse_constant=_reject_constant)
        if not isinstance(record, dict):
            raise ValueError("Pi JSONL records must be objects")  # noqa: TRY003, TRY004
        yield record


def _parse_archive(value: PiSessionInput) -> _Archive:
    entries = _jsonl_records(value.content)
    header = next(entries, None)
    if (
        header is None
        or header.get("type") != "session"
        or type(header.get("version")) is not int
        or header["version"] != 3
    ):
        raise ValueError("Pi archives must begin with a version 3 session header")  # noqa: TRY003
    session_id = _nonempty_string(header.get("id"), "session id")
    records: dict[str, dict[str, JsonValue]] = {}
    for record in entries:
        event_id = _nonempty_string(record.get("id"), "event id")
        event_type = _nonempty_string(record.get("type"), "event type")
        if event_type == "session":
            raise ValueError("Pi session headers may only appear at the start")  # noqa: TRY003
        if event_id in records:
            raise ValueError(f"Duplicate Pi event id: {event_id}")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError(f"Pi event {event_id} is missing parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in records):
            raise ValueError(f"Pi event {event_id} must reference an earlier parent")  # noqa: TRY003
        records[event_id] = record
    leaf = value.leaf_id
    if leaf is None:
        leaf = next(reversed(records), None)
    elif leaf not in records:
        raise ValueError(f"Pi leaf does not exist: {leaf}")  # noqa: TRY003
    branch: list[str] = []
    while leaf is not None:
        branch.append(leaf)
        # Parent validation above guarantees a finite chain of earlier nodes.
        parent = records[leaf]["parentId"]
        leaf = parent if isinstance(parent, str) else None
    return _Archive(session_id, records, tuple(reversed(branch)))


def _visible_blocks(value: JsonValue | None, *, tool_calls: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError("Pi message content must be a string or content blocks")  # noqa: TRY003, TRY004
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ValueError("Pi text blocks must contain string text")  # noqa: TRY003
            parts.append(text)
        elif tool_calls and block.get("type") == "toolCall":
            name = _nonempty_string(block.get("name"), "tool name")
            call_id = _nonempty_string(block.get("id"), "tool call id")
            arguments = json.dumps(
                block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return "\n".join(parts)


def _event(archive: _Archive, event_id: str) -> PiEventInput | None:
    record = archive.records[event_id]
    event_type = _nonempty_string(record.get("type"), "event type")
    if event_type in {"compaction", "branch_summary"}:
        role = event_type
        body = record.get("summary", "")
        if not isinstance(body, str):
            raise ValueError("Pi summaries must be strings")  # noqa: TRY003
    elif event_type == "custom_message":
        role = "custom"
        body = _visible_blocks(record.get("content"))
    elif event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("Pi message entries must contain a message object")  # noqa: TRY003
        role = _nonempty_string(message.get("role"), "message role")
        if role == "bashExecution":
            command, output = message.get("command", ""), message.get("output", "")
            if not isinstance(command, str) or not isinstance(output, str):
                raise ValueError("Pi bash commands and outputs must be strings")  # noqa: TRY003
            body = f"$ {command}\n{output}" if command or output else ""
        else:
            body = _visible_blocks(message.get("content"), tool_calls=True)
            if body and role == "toolResult":
                name = _nonempty_string(message.get("toolName"), "tool result name")
                call_id = _nonempty_string(message.get("toolCallId"), "tool result call id")
                body = f"[tool_result {name} {call_id}] {body}"
    else:
        return None
    if not body:
        return None
    parent = record["parentId"]
    return PiEventInput(
        session_id=archive.session_id,
        event_id=event_id,
        parent_id=parent if isinstance(parent, str) else None,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _branch_events(archive: _Archive) -> tuple[PiEventInput, ...]:
    return tuple(event for event_id in archive.branch if (event := _event(archive, event_id)) is not None)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return the selected branch's raw evidence, without applying context edits."""
    return _branch_events(_parse_archive(value))


def _event_source_id(session_id: str, event_id: str) -> str:
    # A structured pair avoids separator collisions and bounds even very long IDs.
    identity = json.dumps([session_id, event_id], ensure_ascii=False, separators=(",", ":"))
    return f"pi:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


class _PiEventAdapter:
    input_class = PiEventInput
    source_class = PiEventSource
    name = "pi-event"

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_event_source_id(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(**{field: getattr(source, field) for field in PiEventInput.model_fields})


class _PiTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    _PiEventAdapter(), projections=(_PiTextEvidenceProjection(),)
)


class _Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    session_id: str
    imported: dict[str, str]


def _record_digest(record: dict[str, JsonValue]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Import unseen branch events and let ConnectorLifecycle commit progress."""

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = await asyncio.to_thread(self.path.read_bytes)
        archive = _parse_archive(PiSessionInput(content=raw, leaf_id=self.leaf_id))
        events = _branch_events(archive)
        previous = (
            _Checkpoint(session_id=archive.session_id, imported={})
            if session.checkpoint is None
            else _Checkpoint.model_validate(session.checkpoint)
        )
        if previous.session_id != archive.session_id:
            raise ValueError("Pi session identity changed since the committed checkpoint")  # noqa: TRY003

        # Check every imported branch, not only the branch selected for this run.
        for event_id, digest in previous.imported.items():
            record = archive.records.get(event_id)
            if record is None or _record_digest(record) != digest:
                raise ValueError(f"Previously imported Pi event changed or disappeared: {event_id}")  # noqa: TRY003

        # Prepare all records before the first write, including their fingerprints.
        pending = tuple(
            (event, _record_digest(event.record)) for event in events if event.event_id not in previous.imported
        )
        imported = dict(previous.imported)
        for event, digest in pending:
            outcome = await session.submit(_event_source_id(event.session_id, event.event_id), "pi-event", event)
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE, checkpoint=session.checkpoint)
            imported[event.event_id] = digest
        checkpoint = _Checkpoint(session_id=archive.session_id, imported=imported)
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint.model_dump(mode="json"))


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
