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

"""Shared provider work, cancellation boundaries and per-caller usage."""

from __future__ import annotations

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import CoalescingEmbeddingModel, EmbeddingResult, InferenceUsage, embed_query


class _Model:
    profile = EmbeddingProfile(profile_id="coalescing-unit", model="offline", dimension=1)

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)),) for text in texts),
            usage=InferenceUsage(requests=3, input_tokens=7, output_tokens=2),
        )


async def test_late_call_shares_running_work_with_cache_disabled():
    started, release, other_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Blocked(_Model):
        async def embed(self, texts):
            self.calls.append(texts)
            if texts == ("shared",):
                started.set()
                await release.wait()
            else:
                other_started.set()
            return EmbeddingResult(
                vectors=tuple((float(len(text)),) for text in texts),
                usage=InferenceUsage(requests=2, input_tokens=9, output_tokens=0),
            )

    base = Blocked()
    model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0, cache_size=0)
    first = asyncio.create_task(model.embed(("shared", "shared")))
    await asyncio.wait_for(started.wait(), 2)
    late = asyncio.create_task(model.embed(("shared", "other", "shared")))
    await asyncio.wait_for(other_started.wait(), 2)
    release.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, late), 2)
    assert a.vectors == ((6.0,), (6.0,)) and a.usage.requests == 2
    assert b.vectors == ((6.0,), (5.0,), (6.0,))
    assert (b.usage.requests, b.usage.input_tokens, b.usage.output_tokens) == (4, 18, 0)
    assert base.calls.count(("shared",)) == 1
    await model.embed(("shared",))
    assert base.calls.count(("shared",)) == 2


async def test_shared_failure_does_not_cancel_an_independent_batch_and_is_retryable():
    good_started, release_good = asyncio.Event(), asyncio.Event()

    class Flaky(_Model):
        fail = True

        async def embed(self, texts):
            self.calls.append(texts)
            if texts == ("bad",) and self.fail:
                raise RuntimeError("temporary-provider-error")
            if texts == ("good",):
                good_started.set()
                await release_good.wait()
            return EmbeddingResult(vectors=tuple((1.0,) for _ in texts))

    base = Flaky()
    model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
    mixed = asyncio.create_task(model.embed(("bad", "good")))
    shared_failure = asyncio.create_task(model.embed(("bad",)))
    independent = asyncio.create_task(model.embed(("good",)))
    await asyncio.wait_for(good_started.wait(), 2)
    for task in (mixed, shared_failure):
        with pytest.raises(RuntimeError, match="temporary-provider-error"):
            await task
    release_good.set()
    assert (await asyncio.wait_for(independent, 2)).vectors == ((1.0,),)
    base.fail = False
    assert (await model.embed(("bad",))).vectors == ((1.0,),)
    assert base.calls.count(("bad",)) == 2
    assert base.calls.count(("good",)) == 1
    assert (await model.embed(("good", "bad"))).usage.requests == 0


async def test_usage_counts_batch_identity_once_even_with_equal_provider_usage():
    base = _Model()
    model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=10, cache_size=8)
    await model.embed(("cached",))
    first, second = await asyncio.gather(
        model.embed(("cached", "b", "b", "cc", "ddd")),
        model.embed(("cc", "ddd", "cc")),
    )
    assert first.vectors == ((6.0,), (1.0,), (1.0,), (2.0,), (3.0,))
    assert second.vectors == ((2.0,), (3.0,), (2.0,))
    for result in (first, second):
        assert result.usage == InferenceUsage(requests=6, input_tokens=14, output_tokens=4)
    assert len(base.calls) == 3
    assert (await model.embed(("ddd", "b"))).usage.requests == 0


async def test_invalid_batch_count_caches_no_partial_success():
    class Incomplete(_Model):
        fail = True

        async def embed(self, texts):
            self.calls.append(texts)
            count = len(texts) - 1 if self.fail else len(texts)
            return EmbeddingResult(vectors=((1.0,),) * count)

    base = Incomplete()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0)
    with pytest.raises(ValueError):
        await model.embed(("one", "two"))
    base.fail = False
    assert (await model.embed(("one", "two"))).vectors == ((1.0,), (1.0,))
    assert base.calls == [("one", "two"), ("one", "two")]


async def test_small_cache_does_not_lose_vectors_for_the_current_call():
    base = _Model()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=1)
    result = await model.embed(("one", "four", "three", "one"))
    assert result.vectors == ((3.0,), (4.0,), (5.0,), (3.0,))
    assert result.usage.requests == 3
    assert (await model.embed(("three",))).usage.requests == 0
    assert (await model.embed(("one",))).usage.requests == 3


async def test_repeated_cached_positions_refresh_recency_in_input_order():
    base = _Model()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=2)
    await model.embed(("a", "b"))
    assert (await model.embed(("a", "b", "a"))).usage.requests == 0
    await model.embed(("c",))
    assert (await model.embed(("a",))).usage.requests == 0
    assert (await model.embed(("b",))).usage.requests == 3


async def test_cancellation_during_the_window_retains_work_for_late_waiter():
    base = _Model()
    model = CoalescingEmbeddingModel(base, coalesce_ms=20, cache_size=0)
    abandoned = asyncio.create_task(model.embed(("shared",)))
    await asyncio.sleep(0)
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned
    survivor = await asyncio.wait_for(model.embed(("shared",)), 2)
    assert survivor.vectors == ((6.0,),)
    assert base.calls == [("shared",)]


async def test_orphaned_failure_is_observed_and_does_not_poison_retry():
    started, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    unhandled = []

    class Orphaned(_Model):
        fail = True

        async def embed(self, texts):
            self.calls.append(texts)
            started.set()
            await release.wait()
            if self.fail:
                raise RuntimeError("unobserved-provider-failure")
            return EmbeddingResult(vectors=((1.0,),))

    loop.set_exception_handler(lambda current_loop, context: unhandled.append(context))
    try:
        base = Orphaned()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        task = asyncio.create_task(model.embed(("shared",)))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        # Let the provider finish and publish its failure before retrying.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        base.fail = False
        assert (await model.embed(("shared",))).vectors == ((1.0,),)
        assert base.calls == [("shared",), ("shared",)]
        assert not unhandled
    finally:
        loop.set_exception_handler(previous)


async def test_query_aware_provider_keeps_separate_vectors_with_one_shared_lru():
    class Asymmetric(_Model):
        async def embed_query(self, texts):
            self.calls.append(("query", *texts))
            return EmbeddingResult(vectors=tuple((100.0,) for _ in texts), usage=InferenceUsage(requests=1))

    base = Asymmetric()
    model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=1)
    assert model.profile is base.profile
    assert (await model.embed(("same",))).vectors == ((4.0,),)
    assert (await embed_query(model, ("same",))).vectors == ((100.0,),)
    assert (await embed_query(model, ("same",))).usage.requests == 0
    assert (await model.embed(("same",))).usage.requests == 3
    assert base.calls == [("same",), ("query", "same"), ("same",)]


@pytest.mark.parametrize(
    "settings",
    [
        {"max_batch_size": 0},
        {"max_batch_size": True},
        {"max_batch_size": 1.5},
        {"cache_size": -1},
        {"cache_size": False},
        {"coalesce_ms": -1},
        {"coalesce_ms": float("nan")},
        {"coalesce_ms": float("inf")},
    ],
)
def test_invalid_limits_fail_before_scheduling_any_provider_work(settings):
    base = _Model()
    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(base, **settings)
    assert base.calls == []
