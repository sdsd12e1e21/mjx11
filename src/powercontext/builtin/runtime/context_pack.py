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

"""Stateless, canonical context transport with verified prefix reuse."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import cast

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context chunks, wire data, or delta reconstruction."""


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate-wire-field")
        result[key] = value
    return result


def _decode(data: bytes, schema: str, fields: set[str]) -> dict[str, object]:
    if not isinstance(data, bytes):
        raise ContextPackError("wire-data-must-be-bytes")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ContextPackError("invalid-utf-8-json-wire-data") from error
    if not isinstance(payload, dict) or set(payload) != fields or payload["schema"] != schema:
        raise ContextPackError("unexpected-wire-schema-or-fields")
    return payload


def _validate_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("chunks-must-be-a-tuple-of-bytes")
    try:
        for item in items:
            item.decode("utf-8")
    except UnicodeError as error:
        raise ContextPackError("each-chunk-must-be-valid-utf-8") from error


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ContextPackError("wire-chunks-must-be-a-base64-string-array")
    try:
        items = tuple(base64.b64decode(value, validate=True) for value in cast(list[str], values))
    except (ValueError, binascii.Error) as error:
        raise ContextPackError("invalid-base64-chunk") from error
    if _encode_items(items) != values:
        raise ContextPackError("noncanonical-base64-chunk")
    _validate_items(items)
    return items


def _validate_digest(digest: object) -> None:
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ContextPackError("invalid-sha-256-digest")


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Complete UTF-8 chunks, with a digest that also binds their boundaries."""

    items: tuple[bytes, ...]
    digest: str = field(init=False)
    byte_count: int = field(init=False)

    def __post_init__(self) -> None:
        _validate_items(self.items)
        unsigned: dict[str, object] = {"schema": _PACK_SCHEMA, "items": _encode_items(self.items)}
        digest = "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()
        payload = {**unsigned, "digest": digest, "byte_count": 0}
        # The decimal byte_count contributes to its own serialized length.
        while payload["byte_count"] != (size := len(_canonical(payload))):
            payload["byte_count"] = size
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "byte_count", size)

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        return cls(items)

    @classmethod
    def from_content(cls, content: str | bytes | None, *, chunk_bytes: int = 512) -> ContextPack:
        """Split greedily at UTF-8 boundaries, without normalizing any bytes."""
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes-must-be-a-positive-integer")
        if content is None:
            content = ""
        if not isinstance(content, (str, bytes)):
            raise ContextPackError("content-must-be-utf-8-text-or-bytes")
        try:
            raw = content.encode("utf-8") if isinstance(content, str) else content
            raw.decode("utf-8")
        except UnicodeError as error:
            raise ContextPackError("content-must-be-valid-utf-8") from error
        items = []
        start = 0
        while start < len(raw):
            end = min(start + chunk_bytes, len(raw))
            while end < len(raw) and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("chunk_bytes-cannot-hold-the-next-utf-8-character")
            items.append(raw[start:end])
            start = end
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        return _canonical({
            "schema": _PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _decode(data, _PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        pack = cls.build(_decode_items(payload["items"]))
        if payload["digest"] != pack.digest:
            raise ContextPackError("pack-digest-does-not-match-its-chunks")
        if type(payload["byte_count"]) is not int or payload["byte_count"] != pack.byte_count:
            raise ContextPackError("pack-byte_count-does-not-match-its-encoding")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A complete suffix plus the identity and retained prefix of its base."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items-must-be-a-nonnegative-integer")
        _validate_items(self.appended)

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta-endpoints-must-be-complete-contextpacks")
        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _canonical({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _decode(data, _DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"})
        # Validation above the transport boundary also applies to direct construction.
        return cls(
            base_digest=cast(str, payload["base_digest"]),
            target_digest=cast(str, payload["target_digest"]),
            prefix_items=cast(int, payload["prefix_items"]),
            appended=_decode_items(payload["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Reconstruct using only the supplied values and verify the exact target."""
    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("expected-a-contextpack-base-and-contextpackdelta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta-base-digest-mismatch")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta-prefix-exceeds-the-base-chunk-count")
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("delta-target-digest-mismatch")
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
