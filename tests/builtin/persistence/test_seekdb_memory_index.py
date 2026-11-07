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

"""Hybrid statement budget and exact current-head channel decoding."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import CapabilityNotSupportedError, EmbeddingProfile, MemorySearchRequest
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.tags import TagFilter

PROFILE = EmbeddingProfile(profile_id="unit", model="test", dimension=3, distance="l2", normalization="unit")
HEAD = ArtifactRef(family="memory", artifact_id="memory", revision=7)


def _request(**changes):
    return MemorySearchRequest(
        query="alpha",
        analyzed_query="alpha",
        memories=(HEAD,),
        candidate_limit=12,
        mode="hybrid",
        query_vector=(1.0, 0.0, 0.0),
        embedding_profile=PROFILE,
    ).model_copy(update=changes)


@pytest.mark.parametrize("tags", (None, TagFilter(tags=("selected", "reviewed"), match="all")))
async def test_one_candidate_statement_preserves_channels_and_rebases_unchanged_projections(tags):
    index = SeekDBMemoryIndex(PROFILE)
    index.vector_complete = AsyncMock(return_value=True)
    connection = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = (
        {
            "channel": 0,
            "memory_artifact_id": "memory",
            "head_revision": 1,
            "entry_id": "alpha",
            "entry_version_id": "v1",
            "text": "Alpha.",
            "distance": None,
        },
        {
            "channel": 1,
            "memory_artifact_id": "memory",
            "head_revision": 1,
            "entry_id": "alpha",
            "entry_version_id": "v1",
            "text": "Alpha.",
            "distance": 0.0,
        },
    )
    connection.execute.return_value = result
    channels = await index.search(connection, "scope", _request(tag_filter=tags))
    connection.execute.assert_awaited_once()
    assert channels.fts[0].memory_ref == channels.vector[0].memory_ref == HEAD
    assert channels.fts[0].entry_version_id == channels.vector[0].entry_version_id == "v1"
    assert channels.vector[0].distance == 0.0
    statement, parameters = connection.execute.await_args.args
    assert parameters["candidate_limit"] == 12 and parameters["scope_id"] == "scope"
    assert parameters["memory_artifact_ids"] == ("memory",)
    assert parameters["query"] == "alpha"
    assert "MATCH(" in str(statement) and "l2_distance(" in str(statement)
    if tags is not None:
        assert parameters["tag_minimum"] == 2
        assert len(parameters["tag_hashes"]) == 2


@pytest.mark.parametrize("mode", ("fts", "vector"))
async def test_single_channel_requests_still_use_existing_strategies(mode):
    index = SeekDBMemoryIndex(PROFILE)
    from powercontext.builtin.artifacts.memory import MemorySearchChannels

    for strategy in index.indexes:
        strategy.search = AsyncMock(return_value=MemorySearchChannels())
    await index.search(AsyncMock(), "scope", _request(mode=mode))
    for strategy in index.indexes:
        assert strategy.search.await_args.args[2].mode == mode


async def test_invalid_embedding_profile_fails_before_candidate_query():
    index = SeekDBMemoryIndex(PROFILE)
    connection = AsyncMock()
    with pytest.raises(CapabilityNotSupportedError):
        await index.search(connection, "scope", _request(query_vector=None))
    connection.execute.assert_not_awaited()
