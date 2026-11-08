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

"""Query-local lexical ranking over actual scoped Memory page records."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from powercontext.artifacts import MemoryCitation

if TYPE_CHECKING:
    from powercontext.builtin.runtime import MemoryEntryRecord, ScopedMemoryApplication

_WORDS = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)
_STOP_WORDS = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "during",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "of",
    "on",
    "or",
    "our",
    "per",
    "please",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "s",
    "fy",
    "answer",
    "assuming",
    "based",
    "calculate",
    "calculated",
    "define",
    "details",
    "directly",
    "explicitly",
    "following",
    "give",
    "given",
    "important",
    "information",
    "less",
    "materially",
    "outlined",
    "perspective",
    "primarily",
    "quantity",
    "reported",
    "respond",
    "response",
    "relying",
    "shown",
    "state",
    "unadjusted",
    "use",
    "using",
    "analyst",
    "investment",
    "usd",
    "millions",
    "billion",
    "million",
])
_DOCUMENT_WORDS = frozenset([
    "annual",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "plc",
    "group",
    "holdings",
    "holding",
    "report",
    "annualreport",
    "earnings",
    "k",
    "q",
    "f",
    "fy",
])

# General accounting vocabulary, independent of any company or evaluation query.
_CONCEPTS = (
    (
        "geography geographic geographical geographies region regions country countries",
        "geographic segments international domestic markets",
    ),
    (
        "legal litigation lawsuit lawsuits battle battles proceeding proceedings",
        "legal litigation proceedings contingencies",
    ),
    ("restructuring reorganization realignment", "restructuring reorganization charges"),
    ("revenue revenues sales turnover", "revenue sales"),
    ("ebitda", "operating income depreciation amortization"),
    ("capex", "capital expenditures property plant equipment"),
    ("earnings profit profits profitability", "income earnings profit"),
    ("debt borrowings borrowing indebtedness", "debt borrowings obligations"),
    ("dividend dividends distribution distributions", "dividends distributions"),
    ("acquisition acquisitions acquired", "acquisitions business combinations"),
    ("pension retirement", "pension retirement benefits"),
    ("buyback buybacks repurchase repurchases", "share repurchases treasury stock"),
    ("liquidity", "cash equivalents financing credit"),
    ("ppne ppe", "property plant equipment net"),
    ("segment segments", "segment organic sales growth revenue"),
)


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return word[:-1] if len(word) > 4 and word.endswith("e") else word


def _tokens(text: str) -> list[str]:
    return [_stem(word) for word in _WORDS.findall(text.casefold()) if word not in _STOP_WORDS]


def _query_weights(question: str) -> dict[str, float]:
    words = set(_WORDS.findall(question.casefold()))
    weights = {term: 0.15 if term.isdigit() else 1.0 for term in _tokens(question)}
    for triggers, expansion in _CONCEPTS:
        if words.intersection(triggers.split()):
            for term in _tokens(expansion):
                weights.setdefault(term, 0.6)
    for pattern, expansion in (
        (r"\bd\s*&\s*a\b", "depreciation amortization"),
        (r"\bp\s*&\s*l\b", "income earnings statement"),
        (r"\bm\s*&\s*a\b", "merger acquisition divestiture organic sales growth"),
        (r"\bcapital[\s-]+intensive\b", "property plant equipment assets revenue capital expenditures"),
    ):
        if re.search(pattern, question, re.IGNORECASE):
            for term in _tokens(expansion):
                weights.setdefault(term, 0.8)
    return weights


@dataclass(frozen=True)
class _Page:
    record: MemoryEntryRecord
    source_id: str
    document_id: str
    terms: Counter[str]
    sequence: str
    heading: str
    sections: frozenset[str]


def _sections(body: str) -> frozenset[str]:
    """Classify actual early titles, rather than mentions in notes or columns."""
    lines = [line.strip() for line in body[:2000].splitlines() if line.strip()]
    # PDF text runs can split a navigation header even inside a single word.
    for index in range(min(6, len(lines))):
        for width in (1, 2, 3, 4):
            if re.sub(r"\W+", "", "".join(lines[index : index + width])).casefold() == "tableofcontents":
                del lines[index : index + width]
                break
    lines = [line for line in lines if not re.fullmatch(r"\d{1,4}", line)]
    sections: set[str] = set()
    # Match titles without layout whitespace: a PDF can split even the final
    # letter of "Sheet" onto a separate text run/line. Keep the grammar anchored
    # to complete early titles, so mentions inside accounting notes do not match.
    prefix = r"(?:(?:consolidated|combined|condensed|unaudited|financial))*"
    patterns = {
        "income": prefix
        + r"statements?(?:of)?(?:income|operations|earnings)(?:loss)?(?:comprehensiveincome)?(?:unaudited)?",
        "cash_flow": prefix + r"statements?(?:of)?cashflows?(?:unaudited)?",
        "balance": prefix + r"(?:balancesheets?|statements?(?:of)?financialposition)(?:unaudited)?",
    }
    for index in range(min(8, len(lines))):
        if any(len(line) > 110 or len(_WORDS.findall(line)) > 16 for line in lines[:index]):
            break
        for width in (1, 2, 3):
            heading = " ".join(lines[index : index + width])
            heading = re.split(r"(?<=[.!?])\s+", heading, maxsplit=1)[0]
            normalized = " ".join(_tokens(heading))
            strong = normalized.startswith(("consolidat ", "combin ", "condens "))
            if index < 2 or strong:
                compact = re.sub(r"[^a-z]", "", heading.casefold())
                sections.update(name for name, pattern in patterns.items() if re.fullmatch(pattern, compact))
        heading = re.sub(r"^(?:item|note)\s+\d+[a-z]?\s*[.:]?\s*", "", lines[index], flags=re.IGNORECASE)
        heading = re.split(r"(?<=[.!?])\s+", heading, maxsplit=1)[0].strip(" .:")
        titles = {
            "business": r"(?:our )?(?:business|operations|company|divisions)|business overview|operating segments|reportable segments|geographic information",
            "segment": r"(?:(?:business|operating|reportable)\s+)?segments?(?:\s+(?:information|results|performance))?"
            r"|results\s+by\s+(?:business\s+)?(?:segment|group)s?",
        }
        sections.update(name for name, pattern in titles.items() if re.fullmatch(pattern, heading, re.IGNORECASE))
    index_lines = sum(
        bool(re.fullmatch(r"[A-Za-z][A-Za-z ,/'()\-\u2013\u2014]{2,80}\s+\d{1,3}", line)) for line in lines
    )
    if index_lines >= 6 or re.search(r"cross[\s-]*reference\s+index", body[:500], re.IGNORECASE):
        sections.discard("business")
    return frozenset(sections)


def _page(record: MemoryEntryRecord) -> _Page | None:
    sources = record.entry.sources
    identities = {source.source_id for source in sources if source.source_type == "pdf-page"}
    if len(identities) != 1 or any(source.source_type != "pdf-page" for source in sources):
        return None
    document_id, _, body = record.entry.text.partition("\n")
    terms = _tokens(body)
    if not terms:
        return None
    return _Page(
        record,
        next(iter(identities)),
        document_id,
        Counter(terms),
        " ".join(terms),
        " ".join(_tokens(body[:500])),
        _sections(body),
    )


def _document_match(document_id: str, question: str) -> bool:
    parts = re.split(r"[_\s-]+", document_id.casefold())
    for index, part in enumerate(parts):
        if index and re.fullmatch(r"(?:19|20)\d{2}(?:q[1-4])?", part):
            parts = parts[:index]
            break
    name = "".join(
        part
        for part in parts
        if part not in _DOCUMENT_WORDS
        and not part.isdigit()
        and not re.fullmatch(r"(?:19|20)\d{2}q[1-4]|(?:10|8)[kq]|20f", part)
    )
    words = re.findall(r"[^\W_]+", question.casefold())
    if len(name) <= 3:
        return bool(name) and name in words
    return name in "".join(words)


def _target_documents(pages: tuple[_Page, ...], question: str) -> frozenset[str]:
    """Resolve report identity before ranking repeated comparative-year text."""
    documents = {page.document_id for page in pages}
    companies = {document for document in documents if _document_match(document, question)}
    targeted = companies
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question))
    for year in sorted(years, reverse=True):
        dated = {
            document
            for document in (companies or documents)
            if year in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", document)
        }
        if dated:
            targeted = dated
            break
    quarters = set(re.findall(r"(?<![a-z])q([1-4])(?!\d)", question, re.IGNORECASE))
    quarterly = {
        document
        for document in (targeted or documents)
        if quarters.intersection(re.findall(r"(?<![a-z])q([1-4])(?!\d)", document, re.IGNORECASE))
    }
    return frozenset(quarterly or targeted)


def _rank_pages(pages: tuple[_Page, ...], question: str, prior: dict[str, float]) -> list[tuple[float, _Page]]:
    weights = _query_weights(question)
    frequencies: Counter[str] = Counter(term for page in pages for term in page.terms)
    idf = {term: math.log1p((len(pages) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)) for term in weights}
    average_length = sum(sum(page.terms.values()) for page in pages) / len(pages)
    raw_terms = _tokens(question)
    phrases = {f"{left} {right}" for left, right in pairwise(raw_terms) if not left.isdigit() and not right.isdigit()}
    targeted = _target_documents(pages, question)
    ranked = []
    for page in pages:
        normalization = 1.2 * (0.6 + 0.4 * sum(page.terms.values()) / max(average_length, 1))
        score = sum(
            weight * idf[term] * (page.terms[term] * 2.2) / (page.terms[term] + normalization)
            for term, weight in weights.items()
            if term in page.terms
        )
        for phrase in phrases:
            if phrase in page.sequence:
                score += 0.3 * sum(idf.get(term, 0) for term in phrase.split())
            if phrase in page.heading:
                score += 0.15 * sum(idf.get(term, 0) for term in phrase.split())
        if targeted:
            score *= 2.5 if page.document_id in targeted else 0.3
        score += prior.get(page.record.entry.entry_id, 0) * 0.1
        ranked.append((score, page))
    return sorted(
        ranked,
        key=lambda item: (
            bool(targeted) and item[1].document_id not in targeted,
            -item[0],
            item[1].source_id,
            item[1].record.entry.entry_id,
        ),
    )


def _evidence_facets(question: str) -> tuple[str, ...]:
    """Recognize general statement and business-overview evidence requests."""
    query = " ".join(_tokens(question))
    if " ".join(_tokens("capital intensive")) in query:
        return ("balance", "income", "cash_flow")
    groups = []
    for triggers, section in (
        (
            (
                "income statement",
                "statement income",
                "statement earnings",
                "profit loss",
                "p l",
                "ebitda",
                "operating income",
                "net income",
                "net sales",
                "revenue",
                "gross profit",
            ),
            "income",
        ),
        (
            ("cash flow", "cashflow", "capex", "capital expenditure", "ebitda"),
            "cash_flow",
        ),
        (
            (
                "balance sheet",
                "financial position",
                "total assets",
                "total liabilities",
                "current ratio",
                "working capital",
                "shareholders equity",
                "ppne",
                "ppe",
            ),
            "balance",
        ),
        (
            ("geography", "geographic", "geographical", "country", "region"),
            "business",
        ),
        (("segment",), "segment"),
    ):
        if any(" ".join(_tokens(trigger)) in query for trigger in triggers):
            groups.append(section)
    return tuple(groups)


def _diversify(ranked: list[tuple[float, _Page]], question: str) -> list[tuple[float, _Page]]:
    # Multi-statement questions need evidence from each requested statement,
    # even when repeated accounting-note terms dominate the lexical ranking.
    targeted = _target_documents(tuple(page for _, page in ranked), question)
    preferred = []
    for section in _evidence_facets(question):
        matches = [
            (score, page)
            for score, page in ranked
            if section in page.sections and (not targeted or page.document_id in targeted)
        ]
        preferred.extend((max(score, 1.0), page) for score, page in matches[:2])
    return [*preferred, *ranked]


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Return real, distinct page citations from the supplied Memory scope.

    FTS supplies a coarse ranking. Public active-entry listing lets the local
    ranker also consider pages excluded by strict multi-term FTS admission.
    For P pages, T text tokens and Q query terms, this costs
    O(T + P*Q + P*log(P)) per query;
    it keeps no global corpus or state that could outlive a revision or Scope.
    """
    from powercontext.builtin.runtime import SearchMemoryRequest

    if limit <= 0 or not question.strip():
        return ()
    terms = [word for word in _WORDS.findall(question.casefold()) if word not in _STOP_WORDS]
    if not terms:
        return ()
    search = await memory.search(SearchMemoryRequest(query=" ".join(terms[:12]), mode="fts", limit=max(32, limit * 4)))
    inventory = await memory.list()
    pages = tuple(page for record in inventory.entries if (page := _page(record)) is not None)
    if not pages:
        return ()
    prior = {hit.entry_id: 1 / (rank + 1) for rank, hit in enumerate(search.hits)}
    selected: list[MemoryCitation] = []
    seen: set[str] = set()
    for score, page in _diversify(_rank_pages(pages, question, prior), question):
        if score <= 0 or page.source_id in seen:
            continue
        seen.add(page.source_id)
        selected.append(page.record.citation)
        if len(selected) == limit:
            break
    return tuple(selected)
