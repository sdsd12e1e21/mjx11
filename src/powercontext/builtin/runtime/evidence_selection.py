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

"""Offline query-focused extraction with literal spans and complete wire accounting."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

if TYPE_CHECKING:
    from powercontext.builtin.runtime.prepared_context import MemoryEntryAddress

_STOP_WORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "for",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "that",
    "which",
    "who",
    "whom",
    "this",
    "these",
    "those",
    "it",
    "its",
    "their",
    "there",
    "than",
    "then",
    "also",
    "both",
    "can",
    "could",
    "may",
    "might",
    "must",
    "should",
    "would",
    "will",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "we",
    "our",
    "they",
    "them",
    "he",
    "she",
    "his",
    "her",
    "you",
    "your",
    "using",
    "used",
    "use",
])
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])\s*|[\r\n]+")  # noqa: RUF001 -- CJK sentence endings
_ABBREVIATION = re.compile(r"\b(?:(?:[a-z]\.){2,}|(?:et al|vs|dr|mr|mrs|fig|no|approx)\.)$", re.IGNORECASE)
_RESULT_CUES = re.compile(
    r"\b(?:results?|found|showed|demonstrat\w*|observed|significant\w*|associated|"
    r"correlat\w*|compared|increased|decreased|reduced|conclu\w*)\b",
    re.IGNORECASE,
)
_MEASURED_RESULT = re.compile(
    r"\b(?:p\s*[=<>]|confidence\s+interval|odds\s+ratio|hazard\s+ratio|relative\s+risk|\d{2}%\s*ci\b)",
    re.IGNORECASE,
)
_SCIENTIFIC_BOILERPLATE = frozenset([
    "study",
    "research",
    "result",
    "analysis",
    "method",
    "conclusion",
    "patient",
    "clinical",
    "individual",
    "group",
    "population",
    "subject",
    "associate",
    "increase",
    "decrease",
    "effect",
    "risk",
    "age",
    "year",
    "lead",
    "development",
    "develop",
    "significant",
    "promote",
])


def _normalize_terms(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"(?<=[A-Za-z])[-‐–](?=\d)", "", normalized)  # noqa: RUF001 -- scientific identifier hyphens


@dataclass(frozen=True)
class PreparedEvidenceFragment:
    """A literal Python character interval in one exact, scope-qualified entry."""

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EvidenceCandidate:
    address: MemoryEntryAddress
    text: str


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    terms: Counter[str]


def render_evidence(fragments: Sequence[PreparedEvidenceFragment]) -> str:
    """Render the same complete envelope used while selecting the fragments."""

    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    # These legal JSON characters are Python splitlines() boundaries. Keep the
    # envelope's JSON on one physical line without changing the decoded evidence.
    for character in ("\x85", "\u2028", "\u2029"):
        encoded = encoded.replace(character, f"\\u{ord(character):04x}")
    return f"{TRUST_POLICY}\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{encoded}\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _stem(word: str) -> str:
    if len(word) < 5 or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            if len(word) > 4 and word[-1] == word[-2]:
                word = word[:-1]
            break
    for suffix, replacement in (("ation", "ate"), ("ative", "ate"), ("ction", "ct"), ("ment", ""), ("ly", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + replacement
            break
    return word.rstrip("e") if len(word) > 4 else word


def _terms(text: str) -> Counter[str]:
    terms: Counter[str] = Counter()
    for match in _WORDS.finditer(_normalize_terms(text).casefold()):
        word = match.group()
        if word in _STOP_WORDS:
            continue
        if any("\u3400" <= character <= "\u9fff" for character in word):
            # Overlapping bigrams allow query phrases inside unsegmented CJK text.
            terms.update(word[index : index + 2] for index in range(max(1, len(word) - 1)))
        else:
            terms[_stem(word)] += 1
    return terms


def _sentence_spans(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.start()
        if _ABBREVIATION.search(text[max(start, end - 12) : end]):
            continue
        yield start, end
        start = match.end()
    yield start, len(text)


def _piece_end(text: str, start: int, end: int, piece_bytes: int) -> int:
    stop = start
    size = 0
    while stop < end:
        # JSON escaping, as well as Unicode encoding, consumes the budget.
        cost = (
            6
            if text[stop] in "\x85\u2028\u2029"
            else len(json.dumps(text[stop], ensure_ascii=False)[1:-1].encode("utf-8"))
        )
        if size + cost > piece_bytes:
            break
        size += cost
        stop += 1
    if stop < end:
        boundary = text.rfind(" ", start + (stop - start) // 2, stop)
        if boundary > start:
            stop = boundary
    return stop


def _units(text: str, piece_bytes: int) -> tuple[_Unit, ...]:
    units: list[_Unit] = []
    for start, end in _sentence_spans(text):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        while start < end:
            stop = _piece_end(text, start, end, piece_bytes)
            if stop == start:
                break
            units.append(_Unit(start, stop, _terms(text[start:stop])))
            start = stop
            while start < end and text[start].isspace():
                start += 1
    return tuple(units)


def _query_weights(query: str, units: Sequence[Sequence[_Unit]]) -> dict[str, float]:
    query_terms = _terms(query)
    flat = [unit for group in units for unit in group]
    if not flat or not query_terms:
        return {}
    frequencies: Counter[str] = Counter(term for unit in flat for term in unit.terms if term in query_terms)
    weights = {term: math.log1p(len(flat) / (1 + frequencies[term])) for term in query_terms}
    generic = {_stem(word) for word in _SCIENTIFIC_BOILERPLATE}
    for term in weights.keys() & generic:
        weights[term] *= 0.4
    # Preserve discriminating identifiers rather than letting many generic words
    # outweigh one exact entity, such as a gene, standard, instrument or model name.
    for match in _WORDS.finditer(_normalize_terms(query)):
        token = match.group()
        if len(token) >= 3 and (
            token.isupper()
            or (any(character.isdigit() for character in token) and any(character.isalpha() for character in token))
        ):
            term = _stem(token.casefold())
            if term in weights:
                weights[term] *= 4
    return weights


def _scores(
    weights: dict[str, float], candidates: Sequence[EvidenceCandidate], units: Sequence[Sequence[_Unit]]
) -> list[list[float]]:
    if not weights:
        return [[0.0] * len(group) for group in units]
    flat = [unit for group in units for unit in group]
    total_weight = sum(weights.values())
    average_length = sum(sum(unit.terms.values()) for unit in flat) / len(flat)
    scores: list[list[float]] = []
    document_scores: list[float] = []
    for candidate, group in zip(candidates, units, strict=True):
        group_scores: list[float] = []
        seen: set[str] = set()
        for position, unit in enumerate(group):
            content = candidate.text[unit.start : unit.end]
            normalized = " ".join(content.casefold().split())
            covered = sum(weight for term, weight in weights.items() if term in unit.terms)
            length = sum(unit.terms.values())
            bm25 = sum(
                weight
                * unit.terms[term]
                * 2.2
                / (unit.terms[term] + 1.2 * (0.75 + 0.25 * length / max(1, average_length)))
                for term, weight in weights.items()
                if term in unit.terms
            )
            score = bm25 * (0.5 + covered / total_weight)
            if _RESULT_CUES.search(content):
                score *= 1.2
            if _MEASURED_RESULT.search(content):
                score *= 1.4
            if position == 0 and len(group) > 2:
                # Titles and introductory statements often repeat the query, but
                # measured findings occur later. Keep them eligible without allowing
                # a short title to crowd out a longer factual result.
                score *= 0.85
            score *= 1 + 0.12 * position / max(1, len(group) - 1)
            group_scores.append(0.0 if normalized in seen else score)
            seen.add(normalized)
        scores.append(group_scores)
        best = sorted(group_scores, reverse=True)
        document_scores.append(sum(best[:2]) + 0.2 * sum(best[2:4]))
    maximum = max(document_scores, default=0.0)
    if maximum == 0:
        return scores
    for document, group_scores in enumerate(scores):
        # Related abstracts share vocabulary. Prefer coherent evidence in the best
        # matching document, while allowing other documents to supply distinct facts.
        prior = (0.3 + 0.7 * document_scores[document] / maximum) ** 2
        original = tuple(group_scores)
        for position, score in enumerate(original):
            adjacent = max(original[max(0, position - 1) : position + 2], default=0.0)
            group_scores[position] = max(score, adjacent * 0.15) * prior
    return scores


def _fragments(
    selected: set[tuple[int, int]],
    candidates: Sequence[EvidenceCandidate],
    units: Sequence[Sequence[_Unit]],
) -> tuple[PreparedEvidenceFragment, ...]:
    fragments: list[PreparedEvidenceFragment] = []
    for document, candidate in enumerate(candidates):
        positions = sorted(position for index, position in selected if index == document)
        for position in positions:
            unit = units[document][position]
            if fragments and fragments[-1].address == candidate.address:
                previous = fragments[-1]
                previous_position = position - 1
                if (document, previous_position) in selected:
                    fragments[-1] = PreparedEvidenceFragment(
                        candidate.address,
                        previous.start,
                        unit.end,
                        candidate.text[previous.start : unit.end],
                    )
                    continue
            fragments.append(
                PreparedEvidenceFragment(candidate.address, unit.start, unit.end, candidate.text[unit.start : unit.end])
            )
    return tuple(fragments)


def select_evidence(
    query: str,
    max_bytes: int,
    candidates: Sequence[EvidenceCandidate],
) -> tuple[PreparedEvidenceFragment, ...]:
    """Greedily pack high-value passages using their marginal *rendered* byte cost.

    Neighboring selections merge into one literal interval, so their citation is paid
    once. Disjoint evidence retains separate intervals and exact provenance. Candidate
    generation is bounded per document; original text, not rank, supplies every offset.
    """

    units: list[tuple[_Unit, ...]] = []
    for candidate in candidates:
        probe = PreparedEvidenceFragment(candidate.address, len(candidate.text), len(candidate.text), "")
        overhead = len(render_evidence((probe,)).encode("utf-8"))
        available = max_bytes - overhead
        units.append(_units(candidate.text, available) if available > 0 else ())
    weights = _query_weights(query, units)
    scores = _scores(weights, candidates, units)
    return _pack(candidates, units, scores, _passages(units, scores), max_bytes)


def _passages(units: Sequence[Sequence[_Unit]], scores: Sequence[Sequence[float]]) -> list[tuple[int, int, int]]:
    passages: set[tuple[int, int, int]] = set()
    for document, group in enumerate(units):
        anchors = sorted(range(len(group)), key=lambda position: (-scores[document][position], position))[:32]
        for anchor in anchors:
            if scores[document][anchor] <= 0:
                continue
            for start in range(max(0, anchor - 3), anchor + 1):
                for end in range(anchor + 1, min(len(group), start + 4) + 1):
                    passages.add((document, start, end))
        if anchors and any(scores[document]):
            passages.add((document, 0, len(group)))
    return sorted(passages)


def _pack(
    candidates: Sequence[EvidenceCandidate],
    units: Sequence[Sequence[_Unit]],
    scores: Sequence[Sequence[float]],
    ordered: list[tuple[int, int, int]],
    max_bytes: int,
) -> tuple[PreparedEvidenceFragment, ...]:
    selected: set[tuple[int, int]] = set()
    content_bytes = len(render_evidence(()).encode("utf-8"))
    while ordered:
        best = None
        best_value = 0.0
        for document, start, end in ordered:
            addition = {(document, position) for position in range(start, end)} - selected
            if not addition:
                continue
            gain = sum(scores[index][position] for index, position in addition)
            if gain <= 0:
                continue
            trial = _fragments(selected | addition, candidates, units)
            size = len(render_evidence(trial).encode("utf-8"))
            if size > max_bytes:
                continue
            value = gain / max(1, size - content_bytes) ** 0.65
            if value > best_value:
                best_value = value
                best = (addition, size)
        if best is None:
            break
        selected.update(best[0])
        content_bytes = best[1]
        ordered = [
            passage
            for passage in ordered
            if any((passage[0], position) not in selected for position in range(passage[1], passage[2]))
        ]
    return _fragments(selected, candidates, units)
