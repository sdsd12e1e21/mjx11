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

"""Count admission preserves journal cardinality and transaction atomicity."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.tables import SOURCES_TABLE
from powercontext.builtin.runtime import artifact_processing as processing
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_discovery import SourceProcessingPendingProvider
from powercontext.builtin.sources import SourceCursor
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _request


async def test_count_uses_actual_journal_rows_after_each_family_cursor(tmp_path):
    async with _profile(tmp_path, "count-positions") as profile, profile.database.transaction() as connection:
        # Sparse imported positions must not be mistaken for the number of identities.
        for scope, positions in (("left", (2, 4, 9)), ("right", (1, 7))):
            for position in positions:
                await connection.execute(
                    insert(SOURCES_TABLE).values(
                        scope_id=scope,
                        source_type="content",
                        source_id=f"source-{position}",
                        payload=b"{}",
                        journal_position=position,
                    )
                )
        memory = SourceProcessingPendingProvider(profile.database, "memory-binding", "memory")
        topic = SourceProcessingPendingProvider(profile.database, "topic-binding", "topic-memory")
        assert await memory.count_ready(connection, ("left", "right"), threshold=3) == frozenset({"left"})
        await SourceCursorRepository().save(
            connection, "left", "memory-binding", SourceCursor(sequence=4), expected_generation=None
        )
        assert await memory.count_ready(connection, ("left", "right"), threshold=2) == frozenset({"right"})
        assert await topic.count_ready(connection, ("left", "right"), threshold=2) == frozenset({"left", "right"})
        assert await topic.count_ready(connection, (), threshold=2) == frozenset()


class _InterruptedAdmission(Exception):
    pass


class _FailingCountIntents(ArtifactProcessingIntentRepository):
    fail = True

    async def request(self, connection, scope_id, binding_name, /):
        result = await super().request(connection, scope_id, binding_name)
        if self.fail and scope_id == "b":
            self.fail = False
            raise _InterruptedAdmission
        return result


async def test_count_page_rollback_accepts_no_partial_work_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(processing, "_DISCOVERY_PAGE_SIZE", 2)
    async with _profile(tmp_path, "count-rollback") as profile:
        for scope in ("a", "b"):
            await _request(profile.database, "memory-binding", scope, requested=False)

        async def ready(connection, scopes):
            return frozenset(scopes)

        supervisor = ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding(
                    "memory-binding", "memory", _Launcher(profile.database), automatic_count_scope_filter=ready
                ),
            ),
            intents=_FailingCountIntents(),
            lease_mode="single-process",
        )
        await supervisor._acquire()
        try:
            state = supervisor._families["memory-binding"]
            with pytest.raises(_InterruptedAdmission):
                await supervisor._discover_count(state)
            assert not state.ready
            assert state.count_after == 0
            for scope in ("a", "b"):
                assert (await _intent(profile.database, "memory-binding", scope)).requested_generation == 0
            await supervisor._discover_count(state)
            assert tuple(state.ready) == ("a", "b")
            for scope in ("a", "b"):
                assert (await _intent(profile.database, "memory-binding", scope)).requested_generation == 1
        finally:
            await supervisor._lose_leadership()


async def test_failed_count_discovery_respects_backoff_instead_of_busy_polling(tmp_path):
    async with _profile(tmp_path, "count-discovery-backoff") as profile:
        await _request(profile.database, "memory-binding", "a", requested=False)

        async def unavailable(connection, scopes):
            raise _InterruptedAdmission

        supervisor = ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding(
                    "memory-binding", "memory", _Launcher(profile.database), automatic_count_scope_filter=unavailable
                ),
            ),
            lease_mode="single-process",
            oceanbase_tick_seconds=10,
        )
        await supervisor._acquire()
        try:
            await supervisor._cycle()
            assert supervisor._next_wake_seconds() > 1
            assert (await _intent(profile.database, "memory-binding", "a")).requested_generation == 0
        finally:
            await supervisor._lose_leadership()
