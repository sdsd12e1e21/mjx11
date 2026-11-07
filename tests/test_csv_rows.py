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

"""CSV contract boundaries beyond the public airport workload."""

import asyncio
import json

import pytest

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, project_source_for_transport
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    CSVRowInput,
    CSVRowSource,
    csv_row_source_id,
    parse_csv_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


@pytest.mark.parametrize(
    ("document_id", "primary_key", "content"),
    [
        ("", "id", b"id\n"),
        ("\tdoc", "id", b"id\n"),
        ("doc\n", "id", b"id\n"),
        ("doc", "", b"id\n"),
        ("doc", "id", b"\n"),
        ("doc", "id", b"\xef\xbb\xbf"),
        ("doc", "id", b'"id","id"\n'),
        ("doc", "id", b" id \n"),
        ("doc", "id", b"id,name\nvalid,first\n\t ,blank-key\n"),
        ("doc", "id", b"id,name\nvalid,first\nextra,second,field\n"),
        ("doc", "id", b'id,name\nvalid,first\nbad,"closed"trailing\n'),
        ("doc", "id", b"id,name\nvalid,first\nbad,\xc0\xaf\n"),
        ("doc", "id", b"id\nvalid\n" + b"x" * 249 + b"\n"),
        ("doc", "id", b'id\nvalid\n""\n'),
    ],
)
def test_invalid_documents_including_late_errors_raise_value_error(document_id, primary_key, content):
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id=document_id, primary_key=primary_key, content=content))


def test_identity_limit_applies_after_utf8_percent_encoding():
    assert len(csv_row_source_id("doc", "x" * 248)) == 256
    assert len(csv_row_source_id("doc", "界" * 27 + "abcde")) == 256
    with pytest.raises(ValueError):
        csv_row_source_id("doc", "界" * 28)
    assert csv_row_source_id("doc:a", "b") != csv_row_source_id("doc", "a:b")
    assert csv_row_source_id("doc", "%2F") != csv_row_source_id("doc", "/")


def test_unicode_and_crlf_fields_survive_source_serialization_and_transport():
    rows = parse_csv_document(
        CSVDocumentInput(
            document_id="表:一/二",
            primary_key=" id ",
            content='\ufeff" id ",name,note,empty,number\r\n\r\n" 键/一 ",机场,"a\r\nb ""c""",,0001\r\n'.encode(),
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.values == (" 键/一 ", "机场", 'a\r\nb "c"', "", "0001")
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(row))
    assert source.materialization is SourceMaterialization.CAPTURED
    restored = CSVRowSource.model_validate_json(source.model_dump_json())
    assert asyncio.run(registry.read(restored)) == row
    observation = project_source_for_transport(registry, restored)
    evidence = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
    expected_row = dict(zip(row.columns, row.values, strict=True))
    assert evidence["content"] == json.dumps(expected_row, ensure_ascii=False, separators=(",", ":"))
    assert evidence["metadata"]["columns"] == list(row.columns)
    assert list(json.loads(evidence["content"])) == list(row.columns)


def test_direct_row_inputs_cannot_disagree_with_their_key_field():
    with pytest.raises(ValueError):
        CSVRowInput(
            document_id="doc", primary_key="id", primary_key_value="different", columns=("id",), values=("actual",)
        )
