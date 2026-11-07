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

"""Apply source eligibility before Topic ranking, pagination, and candidate limits."""

from sqlalchemy import Table, select
from sqlalchemy.sql.elements import ColumnElement

from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE


def topic_lifecycle_predicate(topics: Table) -> ColumnElement[bool]:
    blocked = SOURCE_LIFECYCLE_BLOCKED_TOPICS_TABLE
    return (
        ~select(blocked.c.artifact_id)
        .where(
            blocked.c.scope_id == topics.c.scope_id,
            blocked.c.artifact_id == topics.c.artifact_id,
            blocked.c.revision == topics.c.revision,
        )
        .correlate(topics)
        .exists()
    )
