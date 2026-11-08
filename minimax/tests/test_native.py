import json
import sys
from pathlib import Path

import pytest

from minimax_sdd.context import ContextModule
from minimax_sdd.documents import collect, read_task
from minimax_sdd.workflow import prepare, verify

DEMO = Path(__file__).parents[1] / "demo"


@pytest.mark.skipif(sys.platform != "linux", reason="native seekdb validation uses the delivered Linux container")
async def test_native_seekdb_context_refresh_and_empty_state(tmp_path):
    run = tmp_path / "run"
    result = await prepare(DEMO, run, "native-project")
    assert result["status"] == "awaiting_minimax_change"
    original = json.loads((run / "context.json").read_text(encoding="utf-8"))
    assert set(original["task"]["expected_sources"]) <= {item["path"] for item in original["sources"]}
    assert original["progress"]["saved"]["validation"]["before_target_exit"] != 0
    module = ContextModule(run / "state", "native-project")
    project = run / "project"
    specification = project / "specs/orders.md"
    specification.write_bytes(specification.read_bytes() + b"\norders amount UPDATED_SPEC_NATIVE\n")
    with pytest.raises(ValueError, match="stale"):
        await module.build(project, read_task(project / "task.json"))
    imported = await module.ingest(project)
    assert [item["path"] for item in imported["changed"]] == ["specs/orders.md"]
    context = await module.build(project, read_task(project / "task.json"))
    assert any("UPDATED_SPEC_NATIVE" in source["content"] for source in context["sources"])
    assert context["needs_revalidation"]
    assert not (await module.ingest(project))["changed"]
    assert len(collect(project)) >= 4


@pytest.mark.skipif(sys.platform != "linux", reason="native seekdb validation uses the delivered Linux container")
async def test_full_recorded_development_replay(tmp_path):
    record_path = Path(__file__).parents[1] / "evidence/minimax-development.json"
    assert record_path.exists(), "a real MiniMax development record is required for full acceptance"
    run = tmp_path / "verified"
    await prepare(DEMO, run, "recorded-project")
    result = await verify(run, json.loads(record_path.read_text(encoding="utf-8")))
    assert result["all_required_checks_passed"]
