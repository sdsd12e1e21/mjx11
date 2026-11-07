"""Construct context only from retrieved engineering documents and saved progress."""

from datetime import UTC, datetime
from pathlib import Path

from minimax_sdd.database import EngineeringIndex
from minimax_sdd.documents import collect, manifest_digest
from minimax_sdd.state import TaskState


class ContextModule:
    def __init__(self, state_dir: Path, project_id: str):
        self.index = EngineeringIndex(state_dir, project_id)
        self.progress = TaskState(state_dir, project_id)

    async def ingest(self, project: Path):
        return await self.index.ingest(collect(project))

    async def build(self, project: Path, task: dict):
        documents = collect(project)
        by_path = {document.path: document for document in documents}
        sources = await self.index.retrieve(task["query"])
        for source in sources:
            current = by_path.get(source["path"])
            if current is None or current.sha256 != source["sha256"]:
                raise ValueError("engineering index is stale; import the project again before building context")
        missing_kinds = {"spec", "code", "test"} - {source["kind"] for source in sources}
        if missing_kinds:
            raise ValueError(f"query did not retrieve required engineering categories: {sorted(missing_kinds)}")
        saved = await self.progress.load(task["task_id"])
        fingerprint = manifest_digest(documents)
        stale_state = bool(saved and saved["state"].get("source_manifest") != fingerprint)
        state = None if saved is None else saved["state"]
        pending = (
            ["资料已变化，需要重新执行验证"]
            if stale_state
            else (
                ["MiniMax 实际代码修改", "目标测试与回归测试", "保存并复用任务状态"]
                if state is None
                else state.get("pending", [])
            )
        )
        return {
            "schema": "minimax-sdd-context-v1",
            "built_at": datetime.now(UTC).isoformat(),
            "project_id": self.index.project_id,
            "task": task,
            "source_manifest": fingerprint,
            "sources": sources,
            "resumed": saved is not None,
            "needs_revalidation": stale_state,
            "progress": {"saved": state, "pending": pending, "powercontext_reference": saved},
        }
