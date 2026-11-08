"""HTTP client for PowerContext Server API (v1.5.0).

All memory reads and writes go through this module. No fallback to
localStorage, in-memory dicts, or ad-hoc SQLite.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

POWERCONTEXT_KIND_PREFERENCES = "study-preferences"
POWERCONTEXT_KIND_RECORD = "study-record"
POWERCONTEXT_KIND_SPACE_META = "space-meta"
POWERCONTEXT_KIND_REQUEST_LOCK = "request-lock"


@dataclass
class MemoryCitation:
    artifact_id: str
    revision: int
    scope_id: str
    state: str
    state_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "revision": self.revision,
            "scope_id": self.scope_id,
            "state": self.state,
            "state_version": self.state_version,
        }


@dataclass
class PowerContextHealth:
    available: bool
    detail: str = ""


class PowerContextError(Exception):
    """Raised when PowerContext is unreachable or returns an error."""


class PowerContextClient:
    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._http_client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._http_client

    def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            self._http_client.close()
            self._http_client = None

    @staticmethod
    def _safe_error_detail(resp: httpx.Response) -> str:
        """Return error detail without leaking tokens or sensitive values."""
        try:
            data = resp.json()
            code = data.get("error", {}).get("code", "") if isinstance(data, dict) else ""
            if code:
                return f"HTTP {resp.status_code}, code={code}"
            return f"HTTP {resp.status_code}"
        except Exception:
            return f"HTTP {resp.status_code}"

    def check_health(self) -> PowerContextHealth:
        try:
            c = self._get_client()
            resp = c.get("/health/live")
            if resp.status_code == 200:
                return PowerContextHealth(available=True, detail="PowerContext server is live")
            return PowerContextHealth(available=False, detail=f"HTTP {resp.status_code}")
        except httpx.ConnectError:
            return PowerContextHealth(available=False, detail="Connection refused")
        except httpx.TimeoutException:
            return PowerContextHealth(available=False, detail="Connection timed out")
        except httpx.HTTPError as exc:
            return PowerContextHealth(available=False, detail=f"HTTP error: {type(exc).__name__}")

    def create_scope(self, title: str, summary: str, idempotency_key: str) -> str:
        body = {
            "title": title,
            "summary": summary,
            "idempotency_key": idempotency_key,
        }
        try:
            c = self._get_client()
            resp = c.post("/v1/scopes", json=body)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            raise PowerContextError(f"Connection to PowerContext failed: {type(exc).__name__}") from exc

        if resp.status_code in (200, 201):
            data = resp.json()
            scope_id = data.get("scope_id")
            if not scope_id:
                raise PowerContextError(f"No scope_id in response")
            return scope_id

        if resp.status_code == 409:
            raise PowerContextError(
                f"Scope creation conflict for idempotency_key={idempotency_key!r}: "
                f"{self._safe_error_detail(resp)}"
            )

        raise PowerContextError(
            f"Create scope failed: {self._safe_error_detail(resp)}"
        )

    def list_scopes(
        self,
        query: str = "",
        query_field: str = "title",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List scopes with optional query filter.

        The API requires query_field when query is provided.
        Valid query_field values: scope_id, title, summary, external_reference_value, binding_external_id.
        """
        all_items: list[dict[str, Any]] = []
        cursor: Optional[str] = None

        while True:
            params: dict[str, Any] = {"limit": min(limit - len(all_items), 100)}
            if query:
                params["query"] = query
                params["query_field"] = query_field
            if cursor:
                params["cursor"] = cursor

            try:
                c = self._get_client()
                resp = c.get("/v1/scopes", params=params)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
                raise PowerContextError(f"Connection to PowerContext failed: {type(exc).__name__}") from exc

            if resp.status_code != 200:
                raise PowerContextError(f"List scopes failed: {self._safe_error_detail(resp)}")
            data = resp.json()
            items = data.get("items", [])
            all_items.extend(items)
            cursor = data.get("next_cursor")
            if not cursor or len(all_items) >= limit:
                break

        return all_items

    def remember(
        self,
        scope_id: str,
        kind: str,
        text: str,
        reason: str,
        description: Optional[str] = None,
    ) -> list[MemoryCitation]:
        body: dict[str, Any] = {
            "scope_id": scope_id,
            "kind": kind,
            "text": text,
            "reason": reason,
        }
        if description:
            body["description"] = description[:200]

        start = time.monotonic()
        try:
            c = self._get_client()
            resp = c.post("/v1/memory/remember", json=body)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            raise PowerContextError(f"Connection to PowerContext failed: {type(exc).__name__}") from exc
        elapsed_ms = (time.monotonic() - start) * 1000

        if resp.status_code not in (200, 201):
            raise PowerContextError(f"Remember failed: {self._safe_error_detail(resp)}")

        data = resp.json()
        records = data.get("records", [])
        citations: list[MemoryCitation] = []
        for rec in records:
            artifact = rec.get("artifact")
            if not artifact or not artifact.get("artifact_id") or not artifact.get("revision"):
                logger.warning(
                    "remember kind=%s: record missing artifact_id/revision, skipping citation",
                    kind,
                )
                continue
            citations.append(MemoryCitation(
                artifact_id=artifact["artifact_id"],
                revision=artifact["revision"],
                scope_id=scope_id,
                state=rec.get("state", "active"),
                state_version=rec.get("state_version", 0),
            ))

        if not citations and records:
            raise PowerContextError(
                f"Remember returned {len(records)} records but none had valid artifact references"
            )

        logger.info("remember kind=%s elapsed=%.1fms records=%d", kind, elapsed_ms, len(citations))
        return citations

    def list_memories(
        self,
        scope_id: str,
        kind: Optional[str] = None,
        limit: Optional[int] = 100,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "scope_id": scope_id,
            "limit": min(limit, 100) if limit is not None else 100,
        }
        if kind:
            body["kind"] = kind
        if include_inactive:
            body["states"] = ["active", "forgotten", "merged", "retired"]
        else:
            body["states"] = ["active"]

        all_items: list[dict[str, Any]] = []
        cursor: Optional[str] = None

        while True:
            if cursor:
                body["cursor"] = cursor
            try:
                c = self._get_client()
                resp = c.post("/v1/atomic-memory/list", json=body)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
                raise PowerContextError(f"Connection to PowerContext failed: {type(exc).__name__}") from exc

            if resp.status_code != 200:
                raise PowerContextError(f"List memories failed: {self._safe_error_detail(resp)}")
            data = resp.json()
            items = data.get("items", [])
            all_items.extend(items)
            cursor = data.get("next_cursor")
            if not cursor or (limit is not None and len(all_items) >= limit):
                break

        return all_items if limit is None else all_items[:limit]

    def search_memories(
        self,
        scope_id: str,
        query: str,
        kind: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "scope_id": scope_id,
            "query": query,
            "mode": "text",
            "limit": min(limit, 100),
        }
        if kind:
            body["kind"] = kind

        try:
            c = self._get_client()
            resp = c.post("/v1/atomic-memory/search", json=body)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            raise PowerContextError(f"Connection to PowerContext failed: {type(exc).__name__}") from exc

        if resp.status_code != 200:
            raise PowerContextError(f"Search memories failed: {self._safe_error_detail(resp)}")
        data = resp.json()
        return data.get("hits", [])

    def _find_latest_by_timestamp(self, items: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Select the item with the latest created_at or updated_at from its text payload."""
        best: Optional[dict[str, Any]] = None
        best_ts: Optional[str] = None

        for item in items:
            text = item.get("text", "")
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            ts = parsed.get("updated_at") or parsed.get("created_at") or ""
            if best_ts is None or ts > best_ts:
                best = item
                best_ts = ts
        return best

    def get_preferences(self, scope_id: str) -> Optional[dict[str, Any]]:
        items = self.list_memories(scope_id, kind=POWERCONTEXT_KIND_PREFERENCES, limit=100)
        if not items:
            return None
        latest = self._find_latest_by_timestamp(items)
        if latest is None:
            return None
        text = latest.get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Corrupt preferences text in artifact")
            return None

    def save_preferences(self, scope_id: str, preferences: dict[str, Any]) -> list[MemoryCitation]:
        text = json.dumps(preferences, ensure_ascii=False)
        reason = f"Study preferences updated at {preferences.get('updated_at', 'unknown')}"
        return self.remember(
            scope_id=scope_id,
            kind=POWERCONTEXT_KIND_PREFERENCES,
            text=text,
            reason=reason,
            description="Study session preferences (daily minutes, learning goal)",
        )

    def get_study_records(self, scope_id: str, limit: Optional[int] = None) -> list[dict[str, Any]]:
        items = self.list_memories(scope_id, kind=POWERCONTEXT_KIND_RECORD, limit=limit)
        records: list[dict[str, Any]] = []
        for item in items:
            text = item.get("text", "")
            try:
                parsed = json.loads(text)
                artifact = item.get("artifact", {})
                parsed["_artifact_id"] = artifact.get("artifact_id", "")
                parsed["_revision"] = artifact.get("revision", 0)
                parsed["_state"] = item.get("state", "active")
                parsed["_state_version"] = item.get("state_version", 0)
                records.append(parsed)
            except json.JSONDecodeError:
                logger.warning("Corrupt study record text in artifact")
        return records

    def save_study_record(self, scope_id: str, record: dict[str, Any]) -> list[MemoryCitation]:
        text = json.dumps(record, ensure_ascii=False)
        reason = f"Study session on {record.get('date', 'unknown')} for card {record.get('card_id', 'unknown')}"
        return self.remember(
            scope_id=scope_id,
            kind=POWERCONTEXT_KIND_RECORD,
            text=text,
            reason=reason,
            description=f"Study record: card={record.get('card_id', '?')} assessment={record.get('assessment', '?')}",
        )

    def get_space_meta(self, scope_id: str) -> Optional[dict[str, Any]]:
        items = self.list_memories(scope_id, kind=POWERCONTEXT_KIND_SPACE_META, limit=100)
        if not items:
            return None
        latest = self._find_latest_by_timestamp(items)
        if latest is None:
            return None
        text = latest.get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def save_space_meta(self, scope_id: str, space_meta: dict[str, Any]) -> list[MemoryCitation]:
        text = json.dumps(space_meta, ensure_ascii=False)
        return self.remember(
            scope_id=scope_id,
            kind=POWERCONTEXT_KIND_SPACE_META,
            text=text,
            reason=f"Space metadata for {space_meta.get('space_id', '?')}",
            description=f"Space metadata: {space_meta.get('name', '?')}",
        )

    def list_all_space_metas(self) -> list[dict[str, Any]]:
        """List all space metadata across all scopes by searching for StudyRelay in title."""
        try:
            scopes = self.list_scopes(query="StudyRelay", query_field="title", limit=100)
        except PowerContextError:
            return []

        metas: list[dict[str, Any]] = []
        for scope in scopes:
            sid = scope.get("scope_id", "")
            if not sid:
                continue
            try:
                meta = self.get_space_meta(sid)
                if meta:
                    meta["_scope_id"] = sid
                    metas.append(meta)
            except PowerContextError:
                continue
        return metas

    def check_request_lock(self, scope_id: str, request_id: str) -> Optional[dict[str, Any]]:
        """Check if a request_id has already been processed in this scope.

        Returns the existing record data if found, None otherwise.
        """
        lock_key = f"{scope_id}:{request_id}"
        items = self.list_memories(scope_id, kind=POWERCONTEXT_KIND_REQUEST_LOCK, limit=None)
        for item in items:
            text = item.get("text", "")
            try:
                parsed = json.loads(text)
                if parsed.get("lock_key") == lock_key:
                    return parsed
            except json.JSONDecodeError:
                continue
        # The committed study record is authoritative. A process may have stopped
        # after saving it but before the optional request-receipt write completed.
        for record in self.get_study_records(scope_id):
            if record.get("request_id") == request_id:
                return {
                    "record": record,
                    "citation": {
                        "scope_id": scope_id,
                        "artifact_id": record["_artifact_id"],
                        "revision": record["_revision"],
                        "state": record.get("_state", "active"),
                        "state_version": record.get("_state_version", 0),
                    },
                }
        return None

    def save_request_lock(
        self,
        scope_id: str,
        request_id: str,
        record_data: dict[str, Any],
        citation: dict[str, Any],
    ) -> list[MemoryCitation]:
        """Save a request lock to prevent duplicate processing."""
        lock_data = {
            "lock_key": f"{scope_id}:{request_id}",
            "scope_id": scope_id,
            "request_id": request_id,
            "record": record_data,
            "citation": citation,
            "created_at": record_data.get("created_at", ""),
        }
        text = json.dumps(lock_data, ensure_ascii=False)
        return self.remember(
            scope_id=scope_id,
            kind=POWERCONTEXT_KIND_REQUEST_LOCK,
            text=text,
            reason=f"Request lock for {request_id}",
            description=f"Request lock: {request_id}",
        )
