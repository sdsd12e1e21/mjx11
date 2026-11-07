"""Reproduce baseline failures, MiniMax changes, verification, and process restart."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from minimax_sdd.context import ContextModule
from minimax_sdd.documents import collect, digest, manifest_digest, read_task
from minimax_sdd.minimax_client import apply_record, write_json


def versions():
    result = {"python": sys.version.split()[0]}
    for name in ("minimax-sdd-context", "powercontext", "pylibseekdb", "sqlalchemy", "pyobvector", "httpx"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not installed"
    return result


def _child_environment(project: Path | None = None):
    # Model-generated business code is tested without any provider credentials.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in ("API_KEY", "AUTH_TOKEN", "GITHUB_TOKEN"))
    }
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if project is not None:
        environment["PYTHONPATH"] = str(project / "src")
    return environment


def run_tests(project: Path, arguments: list[str], report_path: Path):
    if arguments[:3] != ["-m", "unittest", "discover"]:
        raise ValueError("this reproducible runner accepts unittest discovery commands only")
    before = collect(project)
    process = subprocess.run(  # noqa: S603 - explicit Python argv, no shell
        [sys.executable, *arguments],
        cwd=project,
        env=_child_environment(project),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    output = (process.stdout + process.stderr).replace(str(project.resolve()), "<project>")
    result = {
        "at": datetime.now(UTC).isoformat(),
        "command": ["python", *arguments],
        "cwd": "project",
        "exit_code": process.returncode,
        "source_manifest": manifest_digest(before),
        "source_versions": [{"path": item.path, "sha256": item.sha256} for item in before],
        "output": output,
        "python": sys.version.split()[0],
    }
    write_json(report_path, result)
    return result


def _assert_original_behavior(target, regression):
    if (
        target["exit_code"] == 0
        or "FAILED (failures=" not in target["output"]
        or "ERROR:" in target["output"]
        or "ModuleNotFoundError" in target["output"]
    ):
        raise ValueError("baseline must fail actual target assertions, not environment setup")
    if regression["exit_code"] != 0:
        raise ValueError("baseline regression tests must pass before MiniMax is called")


async def prepare(source: Path, run_dir: Path, project_id: str):
    source = source.resolve(strict=True)
    run_dir = run_dir.resolve()
    if run_dir.exists():
        raise ValueError("use a fresh run directory, or archive the existing run with the reset command")
    run_dir.mkdir(parents=True)
    project = run_dir / "project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".run"))
    task = read_task(project / "task.json")
    write_json(
        run_dir / "run.json",
        {
            "schema": "minimax-sdd-run-v1",
            "project_id": project_id,
            "task_sha256": digest((project / "task.json").read_bytes()),
        },
    )
    for relative, baseline in task.get("baseline_files", {}).items():
        original = (source / baseline).resolve(strict=True)
        target = (project / relative).resolve(strict=True)
        if (
            relative not in task["editable_files"]
            or not original.is_relative_to(source)
            or not target.is_relative_to(project)
        ):
            raise ValueError("baseline snapshots must refer to declared project source files")
        target.write_bytes(original.read_bytes())
    module = ContextModule(run_dir / "state", project_id)
    if await module.progress.load(task["task_id"]) is not None:
        raise ValueError("the preparation must start without saved task state")
    imported = await module.ingest(project)
    reports = run_dir / "reports"
    target = run_tests(project, task["target_tests"], reports / "before-target.json")
    regression = run_tests(project, task["regression_tests"], reports / "before-regression.json")
    _assert_original_behavior(target, regression)
    await module.progress.save(
        task["task_id"],
        {
            "source_manifest": manifest_digest(collect(project)),
            "completed": ["工程资料已导入 seekdb", "目标测试的基线功能失败已确认", "基线回归通过"],
            "pending": ["MiniMax 实际代码修改", "目标测试与回归测试", "重启后的任务状态复用"],
            "validation": {
                "before_target_exit": target["exit_code"],
                "before_regression_exit": regression["exit_code"],
            },
        },
    )
    context = await module.build(project, task)
    required = set(task.get("expected_sources", []))
    if not required <= {item["path"] for item in context["sources"]}:
        raise ValueError("retrieved context is missing a declared required source")
    write_json(run_dir / "context.json", context)
    write_json(
        run_dir / "preparation.json",
        {
            "versions": versions(),
            "import": imported,
            "status": "awaiting_minimax_change",
            "source_manifest": context["source_manifest"],
        },
    )
    return {"status": "awaiting_minimax_change", "run_dir": str(run_dir), "sources": len(context["sources"])}


async def context_for_run(run_dir: Path):
    config = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    project = run_dir / "project"
    return await ContextModule(run_dir / "state", config["project_id"]).build(project, read_task(project / "task.json"))


async def verify(run_dir: Path, record: dict):
    run_dir = run_dir.resolve(strict=True)
    config = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    project = run_dir / "project"
    task = read_task(project / "task.json")
    if digest((project / "task.json").read_bytes()) != config["task_sha256"]:
        raise ValueError("the task manifest changed after baseline tests")
    before_tests = {item.path: item.sha256 for item in collect(project) if item.kind == "test"}
    baseline_report = json.loads((run_dir / "reports/before-target.json").read_text(encoding="utf-8"))
    original_tests = {
        item["path"]: item["sha256"] for item in baseline_report["source_versions"] if item["path"].startswith("tests/")
    }
    if before_tests != original_tests:
        raise ValueError("target and regression test files must remain identical to the baseline")
    changes = apply_record(project, task, record, run_dir / "changes")
    target = run_tests(project, task["target_tests"], run_dir / "reports/after-target.json")
    regression = run_tests(project, task["regression_tests"], run_dir / "reports/after-regression.json")
    if target["exit_code"] or regression["exit_code"]:
        raise ValueError("MiniMax change did not pass the unchanged target and regression tests")
    if before_tests != {item.path: item.sha256 for item in collect(project) if item.kind == "test"}:
        raise ValueError("test files changed during verification")
    module = ContextModule(run_dir / "state", config["project_id"])
    await module.ingest(project)
    saved = await module.progress.save(
        task["task_id"],
        {
            "source_manifest": manifest_digest(collect(project)),
            "completed": ["MiniMax 实际代码修改", "目标测试通过", "原有回归测试通过"],
            "pending": [],
            "validation": {"target_exit": 0, "regression_exit": 0},
            "model_response_id": record["response_id"],
            "changes": changes,
        },
    )
    # A separate Python process reopens seekdb and PowerContext. Its output is then
    # used by the next step, rather than merely checking that a state file exists.
    resumed_path = run_dir / "resumed-context.json"
    process = subprocess.run(  # noqa: S603 - explicit Python argv, no shell
        [sys.executable, "-m", "minimax_sdd", "context", "--run-dir", str(run_dir), "--output", str(resumed_path)],
        env=_child_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    if process.returncode:
        raise ValueError("restarting the context module failed: " + process.stderr[-1000:])
    resumed = json.loads(resumed_path.read_text(encoding="utf-8"))
    if not resumed["resumed"] or resumed["progress"]["saved"]["model_response_id"] != record["response_id"]:
        raise ValueError("saved PowerContext task progress was not used after restart")
    if resumed["progress"]["saved"]["validation"] != {"target_exit": 0, "regression_exit": 0}:
        raise ValueError("the resumed context did not reuse the actual validation result")
    update = task["spec_update"]
    specification = (project / update["path"]).resolve(strict=True)
    if not specification.is_relative_to(project.resolve()) or not update["path"].startswith("specs/"):
        raise ValueError("specification update must stay inside the project's specification directory")
    original = specification.read_bytes()
    specification.write_bytes(original + update["append"].encode("utf-8"))
    imported = await module.ingest(project)
    updated = await module.build(project, task)
    if not any(update["marker"] in item["content"] for item in updated["sources"] if item["kind"] == "spec"):
        raise ValueError("reimported specification was not used in the new context")
    if not updated["needs_revalidation"]:
        raise ValueError("saved validation must be marked stale after specifications change")
    write_json(run_dir / "updated-spec-context.json", updated)
    summary = {
        "schema": "minimax-sdd-verification-v1",
        "all_required_checks_passed": True,
        "versions": versions(),
        "minimax_response_id": record["response_id"],
        "model": record["response_model"],
        "changes": changes,
        "unchanged_test_sha256": before_tests,
        "before_target_exit": json.loads((run_dir / "reports/before-target.json").read_text(encoding="utf-8"))[
            "exit_code"
        ],
        "before_regression_exit": 0,
        "after_target_exit": 0,
        "after_regression_exit": 0,
        "restarted_process_exit": process.returncode,
        "state_reused": True,
        "powercontext_citation": saved["citation"],
        "specification_reimport": imported,
    }
    write_json(run_dir / "verification.json", summary)
    return summary


def reset(run_dir: Path):
    root = run_dir.resolve(strict=True)
    config = json.loads((root / "run.json").read_text(encoding="utf-8"))
    if config.get("schema") != "minimax-sdd-run-v1" or not (root / "project").is_dir():
        raise ValueError("reset only archives a marked SDD run directory")
    archived = root.with_name(root.name + ".archive-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f"))
    root.rename(archived)
    return {"archived": str(archived), "fresh_run_dir": str(root)}
