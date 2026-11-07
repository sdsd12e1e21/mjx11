"""Task progress is persisted and reread using the real PowerContext Memory SDK."""

from __future__ import annotations

import json
import os
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    ReviseMemoryEntryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

from minimax_sdd.database import append_record


class TaskState:
    def __init__(self, state_dir: Path, project_id: str):
        self.root = state_dir.resolve()
        self.project_id = project_id
        self.log = self.root / "technology/powercontext.jsonl"

    def _config(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return BuiltinConfig(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{(self.root / 'powercontext.sqlite').as_posix()}")
        )

    async def _scope(self, runtime):
        return await runtime.scopes.create(
            ScopeDraft(
                title="MiniMax SDD task progress",
                summary="Persistent task verification state",
                idempotency_key=f"minimax-sdd-{self.project_id}",
            )
        )

    @staticmethod
    async def _find(memory, task_id):
        page = await memory.list()
        for record in page.entries:
            try:
                value = json.loads(record.entry.text)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and value.get("record_type") == "sdd_task_state"
                and value.get("task_id") == task_id
            ):
                return record, value
        return None, None

    async def load(self, task_id: str):
        # A new Runtime per operation makes reopening storage an actual SDK path.
        async with open_builtin_runtime(self._config()) as runtime:
            scope = await self._scope(runtime)
            record, value = await self._find(runtime.memory.for_scope(scope.scope_id), task_id)
            citation = None if record is None else record.citation.model_dump(mode="json")
        append_record(
            self.log,
            {
                "technology": "PowerContext",
                "operation": "read",
                "task_id": task_id,
                "found": record is not None,
                "scope_id": scope.scope_id,
                "citation": citation,
                "pid": os.getpid(),
            },
        )
        return None if value is None else {"state": value, "scope_id": scope.scope_id, "citation": citation}

    async def save(self, task_id: str, state: dict):
        value = {**state, "record_type": "sdd_task_state", "task_id": task_id}
        body = json.dumps(value, ensure_ascii=False, sort_keys=True)
        async with open_builtin_runtime(self._config()) as runtime:
            scope = await self._scope(runtime)
            memory = runtime.memory.for_scope(scope.scope_id)
            previous, _ = await self._find(memory, task_id)
            if previous is None:
                result = await memory.remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=body),))
                )
            else:
                result = await memory.revise(
                    ReviseMemoryEntryRequest(citation=previous.citation, kind="fact", text=body)
                )
            citation = result.entry.citation.model_dump(mode="json")
        append_record(
            self.log,
            {
                "technology": "PowerContext",
                "operation": "write",
                "task_id": task_id,
                "scope_id": scope.scope_id,
                "citation": citation,
                "state": value,
                "pid": os.getpid(),
            },
        )
        return {"state": value, "scope_id": scope.scope_id, "citation": citation}
