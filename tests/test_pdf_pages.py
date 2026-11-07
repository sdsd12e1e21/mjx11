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

"""PDF parsing boundaries and public-runtime retrieval without model services."""

from __future__ import annotations

import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceMaterialization,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVRowInput
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    PDFPageSource,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def _pdf(texts, *, password=None, broken_last=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=400, height=300)
        if text is None:
            continue
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        literal = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 10 Tf 10 200 Td ({literal}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    if broken_last:
        writer.pages[-1]["/Contents"][NameObject("/Filter")] = NameObject("/UnsupportedFilter")
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner-password")  # noqa: S106
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_all_physical_pages_keep_table_numbers_and_blank_page_positions():
    raw = _pdf(["Printed page iv: Revenue 1,234.50 Expenses (678.90)", None, "Printed page 1: Total assets 98765"])
    pages = parse_pdf_document(PDFDocumentInput(document_id=" financial report ", content=raw))
    assert isinstance(pages, tuple)
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert [page.text for page in pages] == [
        "Printed page iv: Revenue 1,234.50 Expenses (678.90)",
        "",
        "Printed page 1: Total assets 98765",
    ]
    assert all(page.document_id == " financial report " for page in pages)
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)


@pytest.mark.parametrize("document_id", ["", " ", "\n\t"])
def test_blank_document_ids_are_rejected(document_id):
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id=document_id, content=_pdf([None])))


@pytest.mark.parametrize("page_number", [0, -1, True, "1"])
def test_direct_page_inputs_require_positive_physical_page_numbers(page_number):
    with pytest.raises(ValueError):
        PDFPageInput(document_id="report", document_sha256="a" * 64, page_number=page_number, text="raw")


@pytest.mark.parametrize("digest", ["", "A" * 64, "g" * 64, "a" * 63])
def test_direct_page_inputs_require_exact_lowercase_sha256(digest):
    with pytest.raises(ValueError):
        PDFPageInput(document_id="report", document_sha256=digest, page_number=1, text="raw")


def test_password_and_late_content_stream_failures_are_atomic():
    assert (
        len(parse_pdf_document(PDFDocumentInput(document_id="empty-password", content=_pdf(["readable"], password=""))))
        == 1
    )
    for raw in (_pdf(["protected"], password="secret"), _pdf(["first page", "unreadable"], broken_last=True)):  # noqa: S106
        with pytest.raises(ValueError):
            parse_pdf_document(PDFDocumentInput(document_id="bad", content=raw))


async def test_source_revision_identity_and_large_unicode_text_round_trip():
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    text = "完整页正文 00123.450\n" * 10000
    page = PDFPageInput(document_id="文档:" * 1000, document_sha256="a" * 64, page_number=1, text=text)
    source = await registry.resolve(page)
    assert source.materialization is SourceMaterialization.CAPTURED
    assert len(source.name) <= 256
    restored = PDFPageSource.model_validate_json(source.model_dump_json())
    assert await registry.read(restored) == page
    evidence = registry.project(restored, TEXT_EVIDENCE_PROJECTION_KEY)
    assert evidence["content"] == f"{page.document_id}\n{text}"
    assert evidence["metadata"] == {"document_id": page.document_id, "document_sha256": "a" * 64, "page_number": 1}
    names = {source.name}
    for changes in ({"document_id": "other"}, {"document_sha256": "b" * 64}, {"page_number": 2}):
        names.add((await registry.resolve(page.model_copy(update=changes))).name)
    assert len(names) == 4


class _PagePipeline:
    def __init__(self, copies=1):
        self.copies = copies

    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind=f"page-{copy}",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"]
                + ("\nAdditional description." if copy else ""),
                sources=(source,),
            )
            for source in request.sources
            for copy in range(self.copies)
        )


async def _prepare(tmp_path, documents, *, copies=1):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pages.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION, CSV_ROW_SOURCE_DEFINITION))
    observations = []
    for document_id, texts in documents:
        for page in parse_pdf_document(PDFDocumentInput(document_id=document_id, content=_pdf(texts))):
            observations.append(project_source_for_transport(registry, await registry.resolve(page)))
    foreign = await registry.resolve(
        CSVRowInput(
            document_id="not-pdf",
            primary_key="id",
            primary_key_value="1",
            columns=("id", "text"),
            values=("1", "Revenue acquisition cash flow " * 10),
        )
    )
    observations.append(project_source_for_transport(registry, foreign))
    async with open_builtin_runtime(config) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="Evidence", idempotency_key="reports"))
        other = await runtime.scopes.create(
            ScopeDraft(title="Other scope", summary="Isolated", idempotency_key="isolated")
        )
        for definition in registry.definitions:
            await runtime.ingestion.register(manifest_for_definition(definition))
        for observation in observations:
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observations[0]))
    async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline(copies)) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(observations) + 1):
            if not (await memory.flush()).processed:
                break
    async with open_builtin_contexts(config) as contexts:
        entries = await (await contexts.get(scope.scope_id)).sources.journal.entries()
        assert len(entries) == len(observations)
        stored = {entry.source_ref.source_id: entry.source for entry in entries}
    return config, scope.scope_id, other.scope_id, stored


async def _locations(memory, citations, stored):
    locations = []
    for citation in citations:
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        assert len(record.entry.sources) == 1
        source = stored[record.entry.sources[0].source_id]
        evidence = source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
        assert evidence["source_type"] == "pdf-page"
        assert record.entry.text == evidence["content"].strip()
        metadata = evidence["metadata"]
        locations.append((metadata["document_id"], metadata["document_sha256"], metadata["page_number"]))
    assert len(set(locations)) == len(locations)
    return locations


async def test_real_runtime_distinct_citations_limits_restart_and_scope_isolation(tmp_path):
    config, scope_id, other_scope_id, stored = await _prepare(
        tmp_path,
        [
            (
                "ACME_2024_10K",
                ["Revenue sales were 120. Research costs were 20.", "Litigation and legal proceedings.", None],
            ),
            ("OTHER_2024_10K", ["Revenue sales were 9000. Revenue sales revenue sales revenue sales."]),
        ],
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        for limit in (1, 2, 20):
            citations = await search_pdf_pages(memory, "What were ACME revenues in 2024?", limit=limit)
            assert isinstance(citations, tuple) and 0 < len(citations) <= limit
            locations = await _locations(memory, citations, stored)
            assert locations[0][0] == "ACME_2024_10K" and locations[0][2] == 1
        assert await search_pdf_pages(memory, "revenue", limit=0) == ()
        assert await search_pdf_pages(memory, "revenue", limit=-1) == ()
        assert await search_pdf_pages(memory, " \n ") == ()
        assert await search_pdf_pages(memory, "a the of") == ()
        assert await search_pdf_pages(memory, "unmatchedzebracriterion") == ()
        assert await search_pdf_pages(runtime.memory.for_scope(other_scope_id), "Revenue sales ACME") == ()


async def test_multi_statement_evidence_survives_repeated_accounting_note_terms(tmp_path):
    # The statements deliberately lack the analyst's EBITDA/capex abbreviations.
    notes = [
        f"Accounting note {index}. EBITDA capital expenditures restructuring operating income " * 3
        for index in range(25)
    ]
    statements = [
        "Consolidated Statements of Income. Sales 300. Cost of sales 100. Operating profit 200.",
        "Consolidated Statements of Cash Flows. Depreciation 20. Amortization 5. Additions to property 10.",
    ]
    config, scope_id, _, stored = await _prepare(tmp_path, [("ACME_2024_10K", [*notes, *statements])])
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(
            memory, "Calculate ACME EBITDA less capex from its income statement and cash flows.", limit=4
        )
        locations = await _locations(memory, citations, stored)
        assert {location[2] for location in locations}.issuperset({26, 27})


@pytest.mark.parametrize("company", ["3M", "GM", "GE"])
async def test_short_and_alphanumeric_company_names_target_the_right_report(tmp_path, company):
    config, scope_id, _, stored = await _prepare(
        tmp_path,
        [(f"{company}_2024_10K", ["Revenue 120 sales 130."]), ("OTHER_2024_10K", ["Revenue sales " * 30])],
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        citations = await search_pdf_pages(memory, f"What were {company} revenues in 2024?", limit=1)
        locations = await _locations(memory, citations, stored)
        assert locations[0][0] == f"{company}_2024_10K"


async def test_multiple_memory_entries_citing_one_page_return_one_page_citation(tmp_path):
    config, scope_id, _, stored = await _prepare(
        tmp_path, [("ACME_2024_10K", ["Revenue sales 100.", "Revenue growth 200."])], copies=2
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        inventory = await memory.list()
        assert (
            sum(any(source.source_type == "pdf-page" for source in row.entry.sources) for row in inventory.entries) == 4
        )
        citations = await search_pdf_pages(memory, "ACME revenue sales growth", limit=20)
        assert len(citations) == 2
        locations = []
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert len(entry.sources) == 1
            locations.append(stored[entry.sources[0].source_id].payload["page_number"])
        assert set(locations) == {1, 2}
