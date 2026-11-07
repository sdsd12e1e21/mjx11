import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from minimax_sdd.documents import collect, digest, read_task
from minimax_sdd.minimax_client import apply_record, develop, validate_edits
from minimax_sdd.state import TaskState

DEMO = Path(__file__).parents[1] / "demo"


def project(tmp_path):
    target = tmp_path / "project"
    shutil.copytree(DEMO, target)
    return target


def test_documents_have_real_symbols_and_change_fingerprints(tmp_path):
    root = project(tmp_path)
    first = collect(root)
    assert {item.kind for item in first} == {"spec", "code", "test"}
    source = next(item for item in first if item.path == "src/order_service.py")
    assert any(symbol["name"] == "select_orders" for symbol in source.symbols)
    specification = root / "specs/orders.md"
    specification.write_bytes(specification.read_bytes() + b"\nUpdated amount range requirements.\n")
    after = collect(root)
    assert next(item.sha256 for item in after if item.path == "specs/orders.md") != next(
        item.sha256 for item in first if item.path == "specs/orders.md"
    )


@pytest.mark.parametrize("path", ("../outside.py", "/tmp/outside.py", "tests/test_target.py", "src/../../outside.py"))
def test_model_edits_cannot_escape_declared_source_files(path):
    with pytest.raises(ValueError):
        validate_edits({"files": [{"path": path, "content": "pass\n"}]}, ["src/order_service.py"])


async def test_minimax_records_retain_final_code_but_not_key_or_private_reasoning(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-secret-never-saved")
    answer = {"summary": "Test fixture only", "files": [{"path": "src/example.py", "content": "VALUE = 1\n"}]}

    def respond(request):
        assert request.headers["Authorization"] == "Bearer test-secret-never-saved"
        return httpx.Response(
            200,
            json={
                "id": "unit-response",
                "model": "MiniMax-M3.1-Flash",
                "choices": [
                    {"message": {"content": json.dumps(answer), "reasoning_content": "PRIVATE_REASONING_SENTINEL"}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    output = tmp_path / "record.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await develop(
            {"task": {"editable_files": ["src/example.py"]}, "source_manifest": "fixture", "sources": []},
            output,
            client=client,
        )
    raw = output.read_text(encoding="utf-8")
    assert "test-secret-never-saved" not in raw
    assert "PRIVATE_REASONING_SENTINEL" not in raw
    assert result["kind"] == "test-transport"
    with pytest.raises(ValueError, match="actual MiniMax"):
        apply_record(tmp_path, {"editable_files": ["src/example.py"]}, result, tmp_path / "edits")


async def test_powercontext_state_is_reused_in_another_python_process(tmp_path):
    state = TaskState(tmp_path / "state", "test-project")
    assert await state.load("task") is None
    saved = await state.save(
        "task", {"completed": ["baseline tested"], "pending": ["MiniMax change"], "source_manifest": "v1"}
    )
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "minimax_sdd",
            "state-show",
            "--state-dir",
            str(tmp_path / "state"),
            "--project-id",
            "test-project",
            "--task-id",
            "task",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    reopened = json.loads(process.stdout)
    assert reopened["state"] == saved["state"]
    assert reopened["scope_id"] == saved["scope_id"]
    await state.save(
        "task", {"completed": ["baseline tested", "MiniMax change"], "pending": [], "source_manifest": "v2"}
    )
    assert (await TaskState(tmp_path / "state", "test-project").load("task"))["state"]["source_manifest"] == "v2"


def test_baseline_business_failure_and_regression_are_real(tmp_path):
    root = project(tmp_path)
    baseline = root / "baseline/src/order_service.py"
    (root / "src/order_service.py").write_bytes(baseline.read_bytes())
    task = read_task(root / "task.json")
    results = [
        subprocess.run([sys.executable, *task[name]], cwd=root, capture_output=True, text=True, check=False)
        for name in ("target_tests", "regression_tests")
    ]
    assert results[0].returncode != 0 and "FAILED (failures=3)" in results[0].stderr
    assert results[1].returncode == 0
    assert "ERROR:" not in results[0].stderr


def test_replay_rejects_changed_source_before_writing(tmp_path):
    root = project(tmp_path)
    source = root / "src/order_service.py"
    record = {
        "answer": {"files": [{"path": "src/order_service.py", "content": "VALUE = 1\n"}]},
        "input_sources": [{"path": "src/order_service.py", "sha256": digest(source.read_bytes())}],
    }
    source.write_bytes(b"# changed concurrently\n")
    with pytest.raises(ValueError, match="source changed"):
        apply_record(root, read_task(root / "task.json"), record, tmp_path / "edits", require_live=False)
    assert source.read_bytes() == b"# changed concurrently\n"
