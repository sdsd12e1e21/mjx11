# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Wire protocol, strict scoring, and exact persisted Memory identities."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft


def _hits(count, *, duplicate_text=False):
    return tuple(
        MemoryHit(
            memory_ref=ArtifactRef(family="memory", artifact_id=f"memory-{index % 2}", revision=index + 1),
            entry_id=f"entry-{index}",
            entry_version_id=f"version-{index}",
            text='同一候选 "原文"\n001' if duplicate_text else f"candidate-{index}",
            score=1 / (index + 1),
            matched_by=("fts",),
        )
        for index in range(count)
    )


@pytest.mark.parametrize("batch_size", [1, 7, 32, 200])
async def test_complete_pool_ranks_and_ties_are_independent_of_batch_boundaries(batch_size):
    calls = []
    candidates = _hits(173, duplicate_text=True)
    original = tuple(candidate.model_dump() for candidate in candidates)

    def handler(request):
        body = json.loads(request.content)
        assert set(body) == {"query", "candidates"}
        assert body["query"] == "原始问题\nquery"
        assert 0 < len(body["candidates"]) <= batch_size
        for item in body["candidates"]:
            assert set(item) == {"rank", "text"}
            assert item["text"] == candidates[item["rank"] - 1].text
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "scores": [{"rank": item["rank"], "score": item["rank"] // 2} for item in reversed(body["candidates"])]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        decision = await HTTPMemoryReranker("https://score.invalid/score", client=client, batch_size=batch_size).rerank(
            "原始问题\nquery", candidates, 10
        )
        assert not client.is_closed
    assert decision.selected_ranks == (172, 173, 170, 171, 168, 169, 166, 167, 164, 165)
    assert decision.usage.requests == len(calls) == (173 + batch_size - 1) // batch_size
    assert sorted(item["rank"] for body in calls for item in body["candidates"]) == list(range(1, 174))
    assert tuple(candidate.model_dump() for candidate in candidates) == original
    assert not decision.used_fallback and decision.discarded_rank_count == 0


@pytest.mark.parametrize("batch_size", [0, -1, True, False, 1.5, "2"])
async def test_invalid_batch_sizes_fail_before_any_request(batch_size):
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            HTTPMemoryReranker("https://score.invalid/score", client=client, batch_size=batch_size)


@pytest.mark.parametrize("limit", [0, -1, 3, True, 1.5, "1"])
async def test_invalid_limits_fail_before_any_request(limit):
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _hits(2), limit)
    assert not calls


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {},
        {"scores": None},
        {"scores": {}},
        {"scores": [{"rank": True, "score": 1}]},
        {"scores": [{"rank": 1.0, "score": 1}]},
        {"scores": [{"rank": "1", "score": 1}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "0.9"}]},
        {"scores": [{"rank": 1, "score": None}]},
        {"scores": [{"rank": 1}]},
        {"scores": [1]},
    ],
)
async def test_json_type_coercion_and_missing_schema_are_rejected(payload):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(payload).encode()))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _hits(1), 1)


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b'{"scores":',
        b'{"scores":[],"scores":[{"rank":1,"score":0.1}]}',
        b'{"scores":[{"rank":2,"rank":1,"score":0.1}]}',
        b'{"scores":[{"rank":1,"score":0.9,"score":0.1}]}',
    ],
)
async def test_invalid_json_and_duplicate_json_fields_are_rejected(body):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _hits(1), 1)


async def test_cross_batch_rank_is_rejected_and_later_batches_are_not_sent():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        ranks = [item["rank"] for item in body["candidates"]] if len(calls) == 1 else [1, 4]
        return httpx.Response(200, json={"scores": [{"rank": rank, "score": 0.5} for rank in ranks]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://score.invalid", client=client, batch_size=2).rerank("q", _hits(6), 2)
    assert len(calls) == 2


@pytest.mark.parametrize("status", [301, 307, 400, 429, 500, 503])
async def test_non_success_status_is_not_followed_or_retried(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://other.invalid"}, content=b"not JSON")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await HTTPMemoryReranker("https://score.invalid", client=client, batch_size=1).rerank("q", _hits(3), 1)
        assert error.value.response.status_code == status
    assert len(calls) == 1


async def test_timeouts_propagate_and_reused_adapter_counts_only_the_current_run():
    failing = True
    original_error = None

    def handler(request):
        nonlocal original_error
        if failing:
            original_error = httpx.ReadTimeout("test timeout", request=request)
            raise original_error
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"scores": [{"rank": item["rank"], "score": -1} for item in body["candidates"]]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=2)
        with pytest.raises(httpx.ReadTimeout) as error:
            await reranker.rerank("q", _hits(3), 1)
        assert error.value is original_error
        failing = False
        assert (await reranker.rerank("q", _hits(3), 2)).usage.requests == 2
        assert (await reranker.rerank("q", _hits(1), 1)).usage.requests == 1
        assert not client.is_closed


async def test_large_integer_scores_are_not_rounded_into_false_ties():
    payload = {"scores": [{"rank": 1, "score": 2**100}, {"rank": 2, "score": 2**100 + 1}, {"rank": 3, "score": -0.5}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        result = await HTTPMemoryReranker("https://score.invalid", client=client).rerank("q", _hits(3), 3)
    assert result.selected_ranks == (2, 1, 3)


async def test_concurrent_queries_have_independent_usage_and_scores():
    async def handler(request):
        await asyncio.sleep(0)
        body = json.loads(request.content)
        direction = 1 if body["query"] == "ascending" else -1
        return httpx.Response(
            200,
            json={"scores": [{"rank": item["rank"], "score": direction * item["rank"]} for item in body["candidates"]]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reranker = HTTPMemoryReranker("https://score.invalid", client=client, batch_size=2)
        first, second = await asyncio.gather(
            reranker.rerank("ascending", _hits(5), 2), reranker.rerank("descending", _hits(3), 2)
        )
    assert first.selected_ranks == (5, 4) and first.usage.requests == 3
    assert second.selected_ranks == (1, 2) and second.usage.requests == 2


@contextmanager
def _scoring_server(scores):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/score"
            assert self.headers["X-Rerank-Test"] == "provided-client"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            encoded = json.dumps({
                "scores": [
                    {"rank": item["rank"], "score": scores[item["text"]]} for item in reversed(body["candidates"])
                ]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/score", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def test_real_http_scoring_after_runtime_restart_keeps_exact_memory_versions(tmp_path):
    scores = {f"Project evidence {index}.": index for index in range(9)}
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'rerank.db'}"))
    async with open_builtin_runtime(config) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Ranking", summary="Evidence", idempotency_key="ranking"))
        await runtime.memory.for_scope(scope.scope_id).remember(
            RememberMemoryRequest(entries=tuple(MemoryEntryInput(kind="fact", text=text) for text in scores))
        )
    with _scoring_server(scores) as (endpoint, calls):
        async with httpx.AsyncClient(headers={"X-Rerank-Test": "provided-client"}, trust_env=False) as client:
            reranker = HTTPMemoryReranker(endpoint, client=client, batch_size=4, policy_id="test-http-policy")
            async with open_builtin_runtime(config, memory_reranker=reranker) as runtime:
                memory = runtime.memory.for_scope(scope.scope_id)
                result = await memory.search(SearchMemoryRequest(query="project", mode="fts", limit=4))
                assert result.rerank is not None
                assert result.rerank.policy_id == "test-http-policy"
                assert result.rerank.usage.requests == len(calls) == 3
                assert len(result.rerank.candidate_hits) == 9
                pool = {hit.text: hit for hit in result.rerank.candidate_hits}
                assert result.hits == tuple(pool[f"Project evidence {index}."] for index in (8, 7, 6, 5))
                for hit in result.hits:
                    citation = MemoryCitation(
                        memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
                    )
                    record = await memory.get(GetMemoryEntryRequest(citation=citation))
                    assert record.entry.text == hit.text
                    assert record.entry.entry_version_id == hit.entry_version_id
                    assert record.memory_ref == hit.memory_ref
            assert not client.is_closed
    assert sorted(item["rank"] for call in calls for item in call["candidates"]) == list(range(1, 10))
    assert all(len(call["candidates"]) <= 4 for call in calls)
