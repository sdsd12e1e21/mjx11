"""StudyRelay FastAPI application.

Serves the static frontend and provides API endpoints that proxy to PowerContext.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.cards import BUILTIN_CARDS
from app.models import (
    LearningSpace,
    SaveSessionRequest,
    SetupPreferencesRequest,
    StudyRecord,
    StudyPlan,
)
from app.powercontext_client import (
    PowerContextClient,
    PowerContextError,
    PowerContextHealth,
)
from app.scheduler import compute_next_review_date, compute_schedule

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
SHOWCASE_DIR = BASE_DIR / "showcase"

POWERCONTEXT_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:18000")
POWERCONTEXT_TOKEN = os.environ.get("POWERCONTEXT_TOKEN")
POWERCONTEXT_HOME = os.environ.get(
    "POWERCONTEXT_HOME",
    str(BASE_DIR / ".data" / "powercontext"),
)
APP_PORT = int(os.environ.get("APP_PORT", "18080"))

SYNTHETIC_SPACES = [
    LearningSpace(
        space_id="synthetic-xiaoming",
        name="小明（合成演示）",
        is_synthetic=True,
    ),
    LearningSpace(
        space_id="synthetic-xiaohong",
        name="小红（合成演示）",
        is_synthetic=True,
    ),
]

SPACE_IDEMPOTENCY_PREFIX = "studyrelay-space"
NOTES_MAX_LENGTH = 500

app = FastAPI(title="StudyRelay", version="1.0.0")

_pc_client: Optional[PowerContextClient] = None
_scope_cache: dict[str, str] = {}


def get_pc_client() -> PowerContextClient:
    global _pc_client
    if _pc_client is None:
        _pc_client = PowerContextClient(
            base_url=POWERCONTEXT_URL,
            token=POWERCONTEXT_TOKEN,
        )
    return _pc_client


def _space_idempotency_key(space_id: str) -> str:
    return f"{SPACE_IDEMPOTENCY_PREFIX}-{space_id}"


def get_scope_id(space_id: str) -> str:
    if space_id in _scope_cache:
        return _scope_cache[space_id]

    client = get_pc_client()
    idem_key = _space_idempotency_key(space_id)

    space_name = space_id
    for s in SYNTHETIC_SPACES:
        if s.space_id == space_id:
            space_name = s.name
            break

    scope_id = client.create_scope(
        title=f"StudyRelay: {space_name}",
        summary=f"Learning space for {space_name}",
        idempotency_key=idem_key,
    )
    _scope_cache[space_id] = scope_id
    return scope_id


@app.on_event("startup")
async def startup_event() -> None:
    data_dir = Path(POWERCONTEXT_HOME)
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("StudyRelay starting. PowerContext URL: %s", POWERCONTEXT_URL)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _pc_client
    if _pc_client is not None:
        _pc_client.close()
        _pc_client = None
    logger.info("StudyRelay shutdown complete.")


@app.get("/health")
async def health() -> dict[str, Any]:
    client = get_pc_client()
    pc_health = client.check_health()
    return {
        "status": "ok" if pc_health.available else "degraded",
        "powercontext": {
            "available": pc_health.available,
            "detail": pc_health.detail,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/spaces")
async def list_spaces() -> dict[str, Any]:
    spaces: list[dict[str, Any]] = []

    for s in SYNTHETIC_SPACES:
        space_data = s.model_dump()
        try:
            scope_id = get_scope_id(s.space_id)
            space_data["scope_id"] = scope_id
        except PowerContextError as exc:
            space_data["scope_error"] = str(exc)
        spaces.append(space_data)

    client = get_pc_client()
    try:
        custom_metas = client.list_all_space_metas()
    except PowerContextError:
        custom_metas = []

    for meta in custom_metas:
        sid = meta.get("space_id", "")
        if not sid or sid.startswith("synthetic-"):
            continue
        if any(s["space_id"] == sid for s in spaces):
            continue
        space_data = {
            "space_id": sid,
            "name": meta.get("name", sid),
            "is_synthetic": False,
        }
        try:
            scope_id = get_scope_id(sid)
            space_data["scope_id"] = scope_id
        except PowerContextError as exc:
            space_data["scope_error"] = str(exc)
        spaces.append(space_data)

    return {"spaces": spaces}


@app.post("/api/spaces")
async def create_space(request: Request) -> dict[str, Any]:
    body = await request.json()
    name = body.get("name", "").strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=422, detail="Name must be 1-100 characters")

    space_id = f"custom-{uuid.uuid4().hex[:12]}"

    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc

    client = get_pc_client()
    now = datetime.utcnow().isoformat() + "Z"
    space_meta = {
        "space_id": space_id,
        "name": name,
        "is_synthetic": False,
        "created_at": now,
        "updated_at": now,
    }
    try:
        client.save_space_meta(scope_id, space_meta)
    except PowerContextError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to persist space metadata: {exc}",
        ) from exc

    return {
        "space_id": space_id,
        "name": name,
        "scope_id": scope_id,
        "is_synthetic": False,
    }


@app.get("/api/cards")
async def list_cards() -> dict[str, Any]:
    return {"cards": [c.model_dump() for c in BUILTIN_CARDS]}


@app.get("/api/spaces/{space_id}/preferences")
async def get_preferences(space_id: str) -> dict[str, Any]:
    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    client = get_pc_client()
    try:
        prefs = client.get_preferences(scope_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc

    return {
        "space_id": space_id,
        "scope_id": scope_id,
        "preferences": prefs,
        "powercontext_available": True,
    }


@app.put("/api/spaces/{space_id}/preferences")
async def save_preferences(space_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        prefs_req = SetupPreferencesRequest(**body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid preferences: {exc}") from exc

    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    now = datetime.utcnow().isoformat() + "Z"
    preferences_data = {
        "daily_minutes": prefs_req.daily_minutes,
        "learning_goal": prefs_req.learning_goal,
        "created_at": now,
        "updated_at": now,
    }

    client = get_pc_client()
    start = time.monotonic()
    try:
        citations = client.save_preferences(scope_id, preferences_data)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc
    elapsed_ms = (time.monotonic() - start) * 1000

    citation_dicts = [c.as_dict() for c in citations]

    return {
        "space_id": space_id,
        "scope_id": scope_id,
        "preferences": preferences_data,
        "elapsed_ms": round(elapsed_ms, 2),
        "memory_citations": citation_dicts,
    }


@app.get("/api/spaces/{space_id}/plan")
async def get_study_plan(space_id: str) -> dict[str, Any]:
    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    client = get_pc_client()
    start = time.monotonic()

    daily_minutes: Optional[int] = None
    try:
        prefs = client.get_preferences(scope_id)
        if prefs and isinstance(prefs.get("daily_minutes"), int):
            daily_minutes = prefs["daily_minutes"]
    except PowerContextError:
        pass

    try:
        records = client.get_study_records(scope_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc
    elapsed_ms = (time.monotonic() - start) * 1000

    plan = compute_schedule(records, daily_minutes=daily_minutes)
    plan.space_id = space_id

    budget_note = ""
    if daily_minutes is not None and plan.total_estimated_minutes > daily_minutes:
        budget_note = (
            f"每日预算 {daily_minutes} 分钟，当前计划 {plan.total_estimated_minutes} 分钟；"
            f"单卡超时仍保留以便完成当前复习，后续卡片已截断。"
        )

    return {
        "plan": plan.model_dump(),
        "total_records": len(records),
        "elapsed_ms": round(elapsed_ms, 2),
        "scope_id": scope_id,
        "daily_minutes": daily_minutes,
        "budget_note": budget_note,
        "continuation_reason": _build_continuation_reason(records, plan),
    }


def _build_continuation_reason(records: list[dict], plan: StudyPlan) -> str:
    if not records:
        return "尚无学习记录，从全新卡片开始，薄弱内容优先安排。"

    needs_work_count = sum(1 for r in records if r.get("assessment") == "needs_work")
    mastered_count = sum(1 for r in records if r.get("assessment") == "mastered")
    unique_cards = len(set(r.get("card_id") for r in records if r.get("card_id")))

    parts = [
        f"共 {len(records)} 条学习记录，覆盖 {unique_cards} 张卡片",
        f"其中 {needs_work_count} 次「需加强」",
        f"{mastered_count} 次「已掌握」",
    ]

    if plan.items:
        priority_counts: dict[str, int] = {}
        for item in plan.items:
            priority_counts[item.priority] = priority_counts.get(item.priority, 0) + 1
        if priority_counts.get("needs_work", 0) > 0:
            parts.append(f"本次计划 {priority_counts['needs_work']} 张需加强卡片优先")
        if priority_counts.get("mastered_due", 0) > 0:
            parts.append(f"{priority_counts['mastered_due']} 张已掌握到期复习")
        if priority_counts.get("new", 0) > 0:
            parts.append(f"{priority_counts['new']} 张新卡片")

    return "；".join(parts) + "。"


@app.post("/api/spaces/{space_id}/session")
async def save_session(space_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()

    try:
        session_req = SaveSessionRequest(**body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid session data: {exc}") from exc

    if session_req.notes and len(session_req.notes) > NOTES_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Notes must be at most {NOTES_MAX_LENGTH} characters",
        )

    card = None
    for c in BUILTIN_CARDS:
        if c.id == session_req.card_id:
            card = c
            break
    if card is None:
        raise HTTPException(status_code=404, detail=f"Card not found: {session_req.card_id}")

    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    client = get_pc_client()
    request_id = session_req.request_id

    # Check for existing request lock in PowerContext (scoped by space_id + request_id)
    if request_id:
        try:
            existing_lock = client.check_request_lock(scope_id, request_id)
            if existing_lock:
                previous = existing_lock.get("record", {})
                if (previous.get("card_id") != session_req.card_id or
                    previous.get("assessment") != session_req.assessment.value or
                    (previous.get("notes") or "") != (session_req.notes or "")):
                    raise HTTPException(status_code=409, detail="Request ID already used for different study data")
                # Return the existing record without creating a duplicate
                return {
                    "duplicate": True,
                    "request_id": request_id,
                    "record": existing_lock.get("record", {}),
                    "memory_citation": existing_lock.get("citation", {}),
                    "elapsed_ms": 0,
                }
        except PowerContextError as exc:
            raise HTTPException(status_code=503, detail="Cannot verify previous save; retry after PowerContext recovers") from exc

    today = date.today()
    record_id = f"rec-{uuid.uuid4().hex[:12]}"
    next_review = compute_next_review_date(today, session_req.assessment.value)

    record_data = {
        "record_id": record_id,
        "request_id": request_id or record_id,
        "date": str(today),
        "card_id": session_req.card_id,
        "assessment": session_req.assessment.value,
        "next_review_date": next_review,
        "notes": (session_req.notes or "")[:NOTES_MAX_LENGTH],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    start = time.monotonic()
    try:
        citations = client.save_study_record(scope_id, record_data)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc
    elapsed_ms = (time.monotonic() - start) * 1000

    if not citations:
        raise HTTPException(status_code=503, detail="PowerContext returned no valid memory citations")

    citation_dicts = [c.as_dict() for c in citations]
    primary_citation = citation_dicts[0]

    # Save request lock to PowerContext for dedup across restarts
    if request_id:
        try:
            client.save_request_lock(scope_id, request_id, record_data, primary_citation)
        except PowerContextError:
            # Lock save failure is non-fatal, just log it
            logger.warning("Failed to save request lock for %s", request_id)

    study_record = StudyRecord(
        record_id=record_id,
        date=str(today),
        card_id=session_req.card_id,
        assessment=session_req.assessment,
        next_review_date=next_review,
        notes=session_req.notes,
        created_at=record_data["created_at"],
        artifact_id=primary_citation.get("artifact_id"),
        revision=primary_citation.get("revision"),
        scope_id=primary_citation.get("scope_id"),
    )

    return {
        "record": study_record.model_dump(),
        "elapsed_ms": round(elapsed_ms, 2),
        "memory_citation": primary_citation,
        "all_citations": citation_dicts,
        "request_id": request_id,
    }


@app.get("/api/spaces/{space_id}/records")
async def get_records(space_id: str) -> dict[str, Any]:
    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    client = get_pc_client()
    start = time.monotonic()
    try:
        records = client.get_study_records(scope_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc
    elapsed_ms = (time.monotonic() - start) * 1000

    return {
        "space_id": space_id,
        "scope_id": scope_id,
        "records": records,
        "total": len(records),
        "elapsed_ms": round(elapsed_ms, 2),
    }


@app.get("/api/spaces/{space_id}/export")
async def export_data(space_id: str, format: str = "json") -> Any:
    if format not in ("json", "markdown"):
        raise HTTPException(status_code=422, detail="Format must be 'json' or 'markdown'")

    try:
        scope_id = get_scope_id(space_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    client = get_pc_client()
    try:
        records = client.get_study_records(scope_id)
        prefs = client.get_preferences(scope_id)
    except PowerContextError as exc:
        raise HTTPException(status_code=503, detail=f"PowerContext error: {exc}") from exc

    export_payload = {
        "space_id": space_id,
        "scope_id": scope_id,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "preferences": prefs,
        "records": records,
    }

    if format == "json":
        safe_payload = _strip_sensitive(export_payload)
        return JSONResponse(content=safe_payload)

    md = _to_markdown(export_payload)
    return Response(content=md, media_type="text/markdown; charset=utf-8")


def _strip_sensitive(data: Any) -> Any:
    sensitive_keys = {"token", "access_token", "secret", "authorization"}
    if isinstance(data, dict):
        return {
            k: _strip_sensitive(v)
            for k, v in data.items()
            if k.lower() not in sensitive_keys
        }
    if isinstance(data, list):
        return [_strip_sensitive(item) for item in data]
    return data


def _to_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# StudyRelay Export",
        "",
        f"- Space: {data['space_id']}",
        f"- Scope: {data['scope_id']}",
        f"- Exported: {data['exported_at']}",
        "",
    ]

    prefs = data.get("preferences")
    if prefs:
        lines.append("## Preferences")
        lines.append(f"- Daily minutes: {prefs.get('daily_minutes', '?')}")
        lines.append(f"- Learning goal: {prefs.get('learning_goal', '?')}")
        lines.append("")

    records = data.get("records", [])
    lines.append(f"## Study Records ({len(records)})")
    lines.append("")
    for rec in records:
        card_id = rec.get("card_id", "?")
        card = None
        for c in BUILTIN_CARDS:
            if c.id == card_id:
                card = c
                break
        topic = card.topic if card else card_id
        lines.append(f"### {rec.get('date', '?')} - {topic}")
        lines.append(f"- Card ID: {card_id}")
        lines.append(f"- Assessment: {rec.get('assessment', '?')}")
        lines.append(f"- Next review: {rec.get('next_review_date', '?')}")
        if rec.get("_artifact_id"):
            lines.append(f"- Artifact: {rec['_artifact_id']} (rev {rec.get('_revision', '?')})")
        lines.append("")

    return "\n".join(lines)


@app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/showcase")
async def serve_showcase_index() -> RedirectResponse:
    return RedirectResponse('/showcase/')


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if SHOWCASE_DIR.exists():
    app.mount("/showcase", StaticFiles(directory=str(SHOWCASE_DIR), html=True), name="showcase")
