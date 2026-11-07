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

"""Native Topic eligibility precedes each channel's candidate limit."""

import pytest
from sqlalchemy import delete, insert

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.artifacts.topic_memory import (
    TopicMemoryContent,
    TopicMemoryDraft,
    TopicMemorySearchRequest,
    prepare_topic_memory_projection,
)
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.sqlite.topic_memory_index import (
    SQLiteTopicMemoryFTSIndex,
    SQLiteTopicMemoryVectorIndex,
)
from powercontext.builtin.persistence.tables import BUILTIN_TABLES, SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE
from powercontext.builtin.persistence.topic_memory import TopicMemoryRepository
from powercontext.builtin.persistence.topic_memory_index import CompositeTopicMemoryIndex


@pytest.mark.parametrize("mode", ("fts", "vector", "hybrid"))
async def test_blocked_nearest_topics_do_not_hide_surviving_candidates(mode):
    embedding = EmbeddingProfile(
        profile_id="lifecycle", model="local", dimension=2, distance="l2", normalization="unit"
    )
    index = CompositeTopicMemoryIndex(SQLiteTopicMemoryFTSIndex(), SQLiteTopicMemoryVectorIndex(embedding))
    repository = TopicMemoryRepository(index=index)
    async with (
        SQLiteProfile.open(SQLiteConfig(), tables=BUILTIN_TABLES + index.tables, load_vector_extension=True) as profile,
        profile.database.transaction() as connection,
    ):
        await repository.initialize(connection)
        original = None
        for number in range(5):
            content = TopicMemoryContent(title="shared evidence", summary="shared evidence", detail="shared evidence")
            projection = prepare_topic_memory_projection(content)
            vector = (1.0, 0.0) if number < 4 else (0.8, 0.6)
            projection = projection.model_copy(
                update={
                    "embedding_profile": embedding,
                    "topic_embedding": vector,
                    "chunk_embeddings": tuple(vector for _ in projection.chunks),
                }
            )
            published = await repository.publish_create(
                connection, "scope", f"topic{number}", TopicMemoryDraft(content=content), projection
            )
            if number < 4:
                original = published.topic.as_ref()
                await connection.execute(
                    insert(SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE).values(
                        scope_id="scope",
                        artifact_id=f"topic{number}",
                        revision=1,
                    )
                )
        request = TopicMemorySearchRequest(
            query="shared",
            analyzed_query="shared",
            candidate_limit=1,
            mode=mode,
            query_vector=(1.0, 0.0),
            embedding_profile=embedding,
        )
        channels = await index.search(connection, "scope", request)
        for name in ("topic_fts", "detail_fts", "topic_vector", "detail_vector"):
            hits = getattr(channels, name)
            if ("fts" in name and mode != "vector") or ("vector" in name and mode != "fts"):
                assert [hit.artifact_ref.artifact_id for hit in hits] == ["topic4"]
            else:
                assert hits == ()
        if mode != "vector":
            assert channels.topic_fts_retrieved == channels.detail_fts_retrieved == 1
        assert (await repository.get_exact(connection, "scope", original)).topic.as_ref() == original
        await connection.execute(delete(SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE))
        restored = await index.search(connection, "scope", request)
        for name in ("topic_fts", "detail_fts", "topic_vector", "detail_vector"):
            hits = getattr(restored, name)
            if hits:
                assert hits[0].artifact_ref.artifact_id in {f"topic{number}" for number in range(4)}
