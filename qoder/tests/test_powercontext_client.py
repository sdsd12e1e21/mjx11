"""Unit tests for the PowerContext client error handling."""

from __future__ import annotations

import pytest
import httpx

from app.powercontext_client import PowerContextClient, PowerContextError


class MockTransport(httpx.BaseTransport):
    """Mock transport that raises specific errors."""

    def __init__(self, error=None, status_code=None, json_data=None):
        self.error = error
        self.status_code = status_code
        self.json_data = json_data or {}

    def handle_request(self, request):
        if self.error:
            raise self.error
        return httpx.Response(
            status_code=self.status_code or 200,
            json=self.json_data,
        )


def test_connect_error_wrapped_as_powercontext_error():
    """Regression: httpx.ConnectError must be wrapped as PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(error=httpx.ConnectError("refused")))
    health = client.check_health()
    assert health.available is False


def test_timeout_error_wrapped_as_powercontext_error():
    """Regression: httpx.TimeoutException must be wrapped as PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(error=httpx.ReadTimeout("timeout")))
    health = client.check_health()
    assert health.available is False


def test_create_scope_409_raises_error():
    """Regression: 409 on scope creation must raise PowerContextError, not silently return a scope."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(status_code=409, json_data={"error": {"code": "conflict"}}))
    with pytest.raises(PowerContextError, match="conflict"):
        client.create_scope("Test", "Summary", "idem-key")


def test_create_scope_connection_error():
    """Connection errors during scope creation must raise PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(error=httpx.ConnectError("refused")))
    with pytest.raises(PowerContextError, match="Connection"):
        client.create_scope("Test", "Summary", "idem-key")


def test_remember_missing_artifact_id_raises():
    """Regression: remember response without artifact_id must raise PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(
        status_code=200,
        json_data={"changed": True, "records": [{"state": "active", "state_version": 0}]},
    ))
    with pytest.raises(PowerContextError, match="valid artifact references"):
        client.remember("scope-1", "test-kind", "test text", "test reason")


def test_remember_valid_response():
    """Valid remember response with artifact references should succeed."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(
        status_code=200,
        json_data={
            "changed": True,
            "records": [{
                "artifact": {"family": "atomic-memory", "artifact_id": "abc123", "revision": 1},
                "state": "active",
                "state_version": 0,
            }],
        },
    ))
    citations = client.remember("scope-1", "test-kind", "test text", "test reason")
    assert len(citations) == 1
    assert citations[0].artifact_id == "abc123"
    assert citations[0].revision == 1


def test_safe_error_detail_no_token_leak():
    """Error details must not contain tokens or sensitive values."""
    resp = httpx.Response(status_code=401, json={"error": {"code": "unauthorized"}})
    detail = PowerContextClient._safe_error_detail(resp)
    assert "Bearer" not in detail
    assert "token" not in detail.lower()


def test_list_memories_connection_error():
    """Connection errors during list must raise PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(error=httpx.ConnectError("refused")))
    with pytest.raises(PowerContextError, match="Connection"):
        client.list_memories("scope-1")


def test_search_memories_timeout_error():
    """Timeout errors during search must raise PowerContextError."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(error=httpx.ReadTimeout("timeout")))
    with pytest.raises(PowerContextError, match="Connection"):
        client.search_memories("scope-1", "query")


def test_check_request_lock_not_found():
    """check_request_lock returns None when no matching lock exists."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(
        status_code=200,
        json_data={"items": [], "next_cursor": None},
    ))
    result = client.check_request_lock("scope-1", "req-123")
    assert result is None


def test_check_request_lock_found():
    """check_request_lock returns the lock data when a matching lock exists."""
    import json as json_module
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    lock_data = {
        "lock_key": "scope-1:req-123",
        "scope_id": "scope-1",
        "request_id": "req-123",
        "record": {"card_id": "db-btree"},
        "citation": {"artifact_id": "abc123"},
    }
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(
        status_code=200,
        json_data={
            "items": [{
                "text": json_module.dumps(lock_data),
                "artifact": {"artifact_id": "lock-artifact", "revision": 1},
                "state": "active",
                "state_version": 0,
            }],
            "next_cursor": None,
        },
    ))
    result = client.check_request_lock("scope-1", "req-123")
    assert result is not None
    assert result["lock_key"] == "scope-1:req-123"
    assert result["record"]["card_id"] == "db-btree"


def test_save_request_lock():
    """save_request_lock persists the lock to PowerContext."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    client._get_client = lambda: httpx.Client(base_url="http://test", transport=MockTransport(
        status_code=200,
        json_data={
            "changed": True,
            "records": [{
                "artifact": {"family": "atomic-memory", "artifact_id": "lock-abc", "revision": 1},
                "state": "active",
                "state_version": 0,
            }],
        },
    ))
    record_data = {"card_id": "db-btree", "date": "2026-11-08"}
    citation = {"artifact_id": "record-abc", "revision": 1, "scope_id": "scope-1"}
    citations = client.save_request_lock("scope-1", "req-456", record_data, citation)
    assert len(citations) == 1
    assert citations[0].artifact_id == "lock-abc"


def test_list_scopes_with_query_field():
    """list_scopes must pass query_field when query is provided."""
    client = PowerContextClient(base_url="http://127.0.0.1:19999")
    captured_params = {}

    class CapturingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            captured_params["url"] = str(request.url)
            captured_params["params"] = dict(request.url.params)
            return httpx.Response(
                status_code=200,
                json={"items": [{"scope_id": "scope-1"}], "next_cursor": None},
            )

    client._get_client = lambda: httpx.Client(base_url="http://test", transport=CapturingTransport())
    scopes = client.list_scopes(query="StudyRelay", query_field="title", limit=100)
    assert len(scopes) == 1
    assert captured_params["params"].get("query") == "StudyRelay"
    assert captured_params["params"].get("query_field") == "title"


def test_retry_recovers_committed_record_when_receipt_was_not_saved():
    """A restart between the record and receipt writes must not duplicate data."""
    import json
    def handler(request):
        body = json.loads(request.content)
        if body['kind'] == 'request-lock':
            return httpx.Response(200, json={'items': [], 'next_cursor': None})
        return httpx.Response(200, json={'items': [{
            'text': json.dumps({'request_id': 'retry-1', 'card_id': 'db-btree', 'assessment': 'needs_work'}),
            'artifact': {'artifact_id': 'original-record', 'revision': 1},
            'state': 'active', 'state_version': 0,
        }], 'next_cursor': None})
    client = PowerContextClient('http://test')
    client._http_client = httpx.Client(base_url='http://test', transport=httpx.MockTransport(handler))
    try:
        result = client.check_request_lock('scope-1', 'retry-1')
        assert result['citation']['artifact_id'] == 'original-record'
        assert result['citation']['scope_id'] == 'scope-1'
    finally:
        client.close()


def test_full_history_reads_every_page():
    import json
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append(body.get('cursor'))
        return httpx.Response(200, json={
            'items': [{'text': str(len(seen))}],
            'next_cursor': 'page-2' if len(seen) == 1 else None,
        })
    client = PowerContextClient('http://test')
    client._http_client = httpx.Client(base_url='http://test', transport=httpx.MockTransport(handler))
    try:
        assert len(client.list_memories('scope-1', limit=None)) == 2
        assert seen == [None, 'page-2']
    finally:
        client.close()
