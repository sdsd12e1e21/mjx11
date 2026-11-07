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

"""HTTP scoring with global candidate identities and stable cross-batch order."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, FiniteFloat, StrictInt

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class _Score(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: StrictInt
    # Preserve integer scores exactly, including values beyond float precision.
    score: StrictInt | FiniteFloat


class _BatchScores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scores: list[_Score]


def _unique_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field in reranker response: {key}")  # noqa: TRY003
        result[key] = value
    return result


class HTTPMemoryReranker:
    """Score each candidate once and select using the complete scored pool.

    The caller owns the AsyncClient, including its authentication and timeouts.
    This adapter does not close it, retry failed batches, or follow redirects.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not candidates:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("rerank limit must be an integer between one and the candidate count")  # noqa: TRY003
        # Snapshot text and global rank before the first asynchronous request.
        items = tuple({"rank": rank, "text": candidate.text} for rank, candidate in enumerate(candidates, start=1))
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(items), self._batch_size):
            batch = items[start : start + self._batch_size]
            requests += 1
            response = await self._client.post(
                self._endpoint,
                json={"query": query, "candidates": batch},
                follow_redirects=False,
            )
            response.raise_for_status()
            result = _BatchScores.model_validate(response.json(object_pairs_hook=_unique_json_fields))
            expected = set(range(start + 1, start + len(batch) + 1))
            if len(result.scores) != len(expected) or {item.rank for item in result.scores} != expected:
                raise ValueError("reranker scores must cover exactly the ranks sent in this batch")  # noqa: TRY003
            scores.update((item.rank, item.score) for item in result.scores)
        selected = tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        return MemoryRerankDecision(selected_ranks=selected, usage=InferenceUsage(requests=requests))


__all__ = ["HTTPMemoryReranker"]
