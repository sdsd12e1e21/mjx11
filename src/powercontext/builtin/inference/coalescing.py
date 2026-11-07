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

"""Event-loop-local embedding coalescing, cancellation isolation and bounded LRU."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeAlias

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel

_Key: TypeAlias = tuple[bool, str]


@dataclass(eq=False, frozen=True, slots=True)
class _BatchCharge:
    # Identity distinguishes different provider batches even with equal usage.
    usage: InferenceUsage


@dataclass(frozen=True, slots=True)
class _EmbeddedText:
    vector: EmbeddingVector
    batch: _BatchCharge


def _observe_future(future: asyncio.Future[_EmbeddedText]) -> None:
    # All consumers may cancel before a provider failure. Observe the exception
    # without changing what an existing or late consumer receives.
    if not future.cancelled():
        future.exception()


def _sum_tokens(values: list[int | None]) -> int | None:
    return sum(value or 0 for value in values) if any(value is not None for value in values) else None


class CoalescingEmbeddingModel:
    """Share pending text computations and successful vectors on one event loop.

    Query-aware providers keep separate document/query computations. Providers
    without that distinction share both paths and their cached vectors.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size <= 0:
            raise ValueError("max-batch-size-must-be-a-positive-integer")
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache-size-must-be-a-nonnegative-integer")
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce-ms-must-be-finite-and-nonnegative")
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[_Key, EmbeddingVector] = OrderedDict()
        self._inflight: dict[_Key, asyncio.Future[_EmbeddedText]] = {}
        self._queued: dict[_Key, None] = {}
        self._dispatcher: asyncio.Task[None] | None = None
        self._batches: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(texts, query=False)

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(texts, query=isinstance(self._model, QueryEmbeddingModel))

    async def _embed(self, texts: tuple[str, ...], *, query: bool) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=())
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("embedding-wrapper-belongs-to-another-event-loop")
        self._loop = loop
        resolved: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_EmbeddedText]] = {}
        for text in texts:
            key = (query, text)
            if key in self._cache:
                resolved[text] = self._cache[key]
                self._cache.move_to_end(key)
            elif text not in waiting:
                future = self._inflight.get(key)
                if future is None:
                    future = loop.create_future()
                    future.add_done_callback(_observe_future)
                    self._inflight[key] = future
                    self._queued[key] = None
                waiting[text] = future
        if self._queued and self._dispatcher is None:
            self._dispatcher = asyncio.create_task(self._dispatch())
        # The caller owns only these shields, never shared provider work.
        values = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        batches = {value.batch for value in values}
        resolved.update((text, value.vector) for text, value in zip(waiting, values, strict=True))
        return EmbeddingResult(
            vectors=tuple(resolved[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(batch.usage.requests for batch in batches),
                input_tokens=_sum_tokens([batch.usage.input_tokens for batch in batches]),
                output_tokens=_sum_tokens([batch.usage.output_tokens for batch in batches]),
            ),
        )

    async def _dispatch(self) -> None:
        try:
            # sleep(0) still lets concurrently awakened calls join this turn.
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            for key in self._queued:
                self._inflight.pop(key).cancel()
            self._queued.clear()
            raise
        finally:
            self._dispatcher = None
        queued = tuple(self._queued)
        self._queued.clear()
        for query in (False, True):
            keys = tuple(key for key in queued if key[0] == query)
            for start in range(0, len(keys), self._max_batch_size):
                task = asyncio.create_task(self._run_batch(keys[start : start + self._max_batch_size]))
                self._batches.add(task)
                task.add_done_callback(self._batches.discard)

    async def _run_batch(self, keys: tuple[_Key, ...]) -> None:
        texts = tuple(key[1] for key in keys)
        try:
            if keys[0][0] and isinstance(self._model, QueryEmbeddingModel):
                result = await self._model.embed_query(texts)
            else:
                result = await self._model.embed(texts)
            self._publish_batch(keys, result)
        except asyncio.CancelledError:
            for key in keys:
                self._inflight.pop(key).cancel()
            raise
        except Exception as error:
            for key in keys:
                self._inflight.pop(key).set_exception(error)

    def _publish_batch(self, keys: tuple[_Key, ...], result: EmbeddingResult) -> None:
        """Validate the entire batch before caching or delivering any vector."""
        if len(result.vectors) != len(keys):
            raise ValueError("embedding-vector-count-mismatch")
        charge = _BatchCharge(result.usage.model_copy())
        for key, vector in zip(keys, result.vectors, strict=True):
            if self._cache_size:
                self._cache[key] = vector
                self._cache.move_to_end(key)
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            self._inflight.pop(key).set_result(_EmbeddedText(vector, charge))


__all__ = ["CoalescingEmbeddingModel"]
