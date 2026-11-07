"""Read bounded engineering inputs with exact local provenance."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Document:
    path: str
    kind: str
    sha256: str
    content: str
    line_count: int
    symbols: tuple[dict, ...]

    def as_dict(self):
        return asdict(self)

    @property
    def searchable(self):
        return " ".join(re.findall(r"[a-z]+|\d+|[\u3400-\u9fff]", (self.path + " " + self.content).casefold()))


def collect(project: Path) -> tuple[Document, ...]:
    root = project.resolve(strict=True)
    documents = []
    for folder, pattern, kind in (("specs", "*.md", "spec"), ("src", "*.py", "code"), ("tests", "*.py", "test")):
        for path in sorted((root / folder).rglob(pattern)):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("engineering input must remain inside the project")
            raw = path.read_bytes()
            if len(raw) > 100_000:
                raise ValueError("engineering input exceeds the 100 KB per-file limit")
            content = raw.decode("utf-8")
            symbols = []
            if path.suffix == ".py":
                tree = ast.parse(content, filename=str(path))
                symbols = [
                    {"name": node.name, "start_line": node.lineno, "end_line": node.end_lineno}
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ]
            else:
                symbols = [
                    {"name": line.lstrip("# "), "start_line": index, "end_line": index}
                    for index, line in enumerate(content.splitlines(), 1)
                    if line.startswith("#")
                ]
            documents.append(
                Document(
                    path.relative_to(root).as_posix(),
                    kind,
                    digest(raw),
                    content,
                    len(content.splitlines()),
                    tuple(symbols),
                )
            )
    if not documents:
        raise ValueError("no engineering specifications, source or tests were found")
    return tuple(documents)


def manifest_digest(documents):
    payload = sorted((document.path, document.sha256) for document in documents)
    return digest(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def read_task(path: Path):
    task = json.loads(path.read_text(encoding="utf-8"))
    required = ("task_id", "description", "query", "preserve", "editable_files", "target_tests", "regression_tests")
    if any(key not in task for key in required):
        raise ValueError("task manifest is missing required fields")
    for relative in task["editable_files"]:
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not relative.startswith("src/"):
            raise ValueError("editable files must be relative source paths")
    return task
