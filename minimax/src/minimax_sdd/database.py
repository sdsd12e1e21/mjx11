"""Real embedded seekdb storage and bounded, role-balanced full-text retrieval."""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from powercontext.builtin.persistence.seekdb import SeekDBConfig, SeekDBProfile
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, delete, insert, select, text, update
from sqlalchemy.dialects.mysql import LONGTEXT

from minimax_sdd.documents import Document

MATERIALS = Table(
    "minimax_sdd_materials",
    MetaData(),
    Column("project_id", String(64), primary_key=True),
    Column("path", String(512), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("source_text", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
    Column("search_text", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
    Column("line_count", Integer, nullable=False),
    Column("symbols_json", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
)
_SEARCH = text("""
SELECT path, kind, sha256, revision, source_text, line_count, symbols_json,
       MATCH(search_text) AGAINST(:query) AS relevance
FROM minimax_sdd_materials
WHERE project_id = :project_id AND kind = :kind
  AND MATCH(search_text) AGAINST(:query)
ORDER BY relevance DESC, path
LIMIT :limit
""")


def append_record(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"at": datetime.now(UTC).isoformat(), **record}, ensure_ascii=False) + "\n")


class EngineeringIndex:
    def __init__(self, state_dir: Path, project_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
            raise ValueError("project_id must contain 1-64 ASCII letters, digits, hyphens or underscores")
        self.root = state_dir.resolve()
        self.project_id = project_id
        self.log = self.root / "technology/seekdb.jsonl"

    @asynccontextmanager
    async def opened(self):
        self.root.mkdir(parents=True, exist_ok=True)
        async with SeekDBProfile.open(
            SeekDBConfig(path=self.root / "engineering.seekdb"), tables=(MATERIALS,)
        ) as profile:
            async with profile.database.transaction() as connection:
                present = await connection.scalar(
                    text("""
SELECT COUNT(*) FROM information_schema.statistics
WHERE table_schema = DATABASE() AND table_name = 'minimax_sdd_materials'
  AND index_name = 'idx_minimax_sdd_materials_fts'
""")
                )
                if not present:
                    await connection.exec_driver_sql(
                        "CREATE FULLTEXT INDEX idx_minimax_sdd_materials_fts "
                        "ON minimax_sdd_materials(search_text) WITH PARSER SPACE"
                    )
            yield profile.database

    async def ingest(self, documents: tuple[Document, ...]):
        if not documents:
            raise ValueError("refusing to replace an engineering index with an empty import")
        changed = []
        async with self.opened() as database, database.transaction() as connection:
            previous = {
                row["path"]: row
                for row in (
                    await connection.execute(
                        select(MATERIALS.c.path, MATERIALS.c.sha256, MATERIALS.c.revision).where(
                            MATERIALS.c.project_id == self.project_id
                        )
                    )
                ).mappings()
            }
            for document in documents:
                old = previous.get(document.path)
                if old is not None and old["sha256"] == document.sha256:
                    continue
                revision = 1 if old is None else old["revision"] + 1
                values = {
                    "kind": document.kind,
                    "sha256": document.sha256,
                    "revision": revision,
                    "source_text": document.content,
                    "search_text": document.searchable,
                    "line_count": document.line_count,
                    "symbols_json": json.dumps(document.symbols, ensure_ascii=False),
                }
                if old is None:
                    await connection.execute(
                        insert(MATERIALS).values(project_id=self.project_id, path=document.path, **values)
                    )
                else:
                    await connection.execute(
                        update(MATERIALS)
                        .where(
                            MATERIALS.c.project_id == self.project_id,
                            MATERIALS.c.path == document.path,
                        )
                        .values(**values)
                    )
                changed.append({"path": document.path, "sha256": document.sha256, "revision": revision})
            paths = tuple(document.path for document in documents)
            removed = sorted(set(previous) - set(paths))
            if removed:
                await connection.execute(
                    delete(MATERIALS).where(
                        MATERIALS.c.project_id == self.project_id,
                        MATERIALS.c.path.in_(removed),
                    )
                )
        result = {"project_id": self.project_id, "documents": len(documents), "changed": changed, "removed": removed}
        append_record(self.log, {"engine": "seekdb", "operation": "import", **result})
        return result

    async def retrieve(self, query: str, limit_per_kind: int = 3):
        analyzed = " ".join(re.findall(r"[a-z]+|\d+|[\u3400-\u9fff]", query.casefold()))
        if not analyzed or not 1 <= limit_per_kind <= 10:
            raise ValueError("retrieval requires a nonblank query and limit between 1 and 10")
        sources = []
        async with self.opened() as database, database.transaction() as connection:
            for kind in ("spec", "code", "test"):
                parameters = {"project_id": self.project_id, "kind": kind, "query": analyzed, "limit": limit_per_kind}
                rows = tuple((await connection.execute(_SEARCH, parameters)).mappings())
                for row in rows:
                    sources.append(
                        {
                            "path": row["path"],
                            "kind": row["kind"],
                            "sha256": row["sha256"],
                            "revision": row["revision"],
                            "content": row["source_text"],
                            "start_line": 1,
                            "end_line": row["line_count"],
                            "symbols": json.loads(row["symbols_json"]),
                            "score": float(row["relevance"]),
                        }
                    )
                append_record(
                    self.log,
                    {
                        "engine": "seekdb",
                        "operation": "query",
                        "sql": str(_SEARCH),
                        "parameters": parameters,
                        "results": [
                            {"path": row["path"], "sha256": row["sha256"], "revision": row["revision"]} for row in rows
                        ],
                    },
                )
        return sources
