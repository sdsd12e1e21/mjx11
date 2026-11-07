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

"""Transport validation and exact reconstruction through public interfaces."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from powercontext.builtin.runtime import (
    BuiltinConfig,
    ContextAssembly,
    PrepareContextRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)
from powercontext.builtin.scope import ScopeDraft


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


@pytest.mark.parametrize("size", [0, 1, 512, 6300, 74000])
def test_wire_size_and_digest_are_independently_reproducible(size):
    pack = ContextPack.from_content("海洋🙂\r\n" * size)
    payload = json.loads(pack.to_bytes())
    unsigned = {"schema": "powercontext.context-pack.v1", "items": payload["items"]}
    assert pack.digest == "sha256:" + hashlib.sha256(_json(unsigned)).hexdigest()
    assert pack.byte_count == len(pack.to_bytes()) == payload["byte_count"]
    assert ContextPack.from_bytes(pack.to_bytes()) == pack
    assert pack.to_bytes() == _json(payload)


@pytest.mark.parametrize("limit", [4, 5, 7, 512])
def test_deterministic_bounded_utf8_chunks_preserve_every_byte(limit):
    text = "a\r\n海洋🙂e\u0301\t\x00" * 120
    pack = ContextPack.from_content(text, chunk_bytes=limit)
    assert pack == ContextPack.from_content(text.encode(), chunk_bytes=limit)
    assert b"".join(pack.items) == text.encode()
    assert all(0 < len(item) <= limit and item.decode().encode() == item for item in pack.items)
    assert ContextPack.from_content(None).items == ()


@pytest.mark.parametrize("limit", [True, False, 1.5, 0, -1, "512"])
def test_chunk_limit_requires_a_positive_integer(limit):
    with pytest.raises(ContextPackError):
        ContextPack.from_content("", chunk_bytes=limit)


@pytest.mark.parametrize("text,limit", [("海", 2), ("a🙂", 3), (b"\xff", 512), ("\ud800", 512)])
def test_unrepresentable_chunks_raise_protocol_error(text, limit):
    with pytest.raises(ContextPackError):
        ContextPack.from_content(text, chunk_bytes=limit)


@pytest.mark.parametrize("chunks", [[], ("text",), (b"\xff",), (bytearray(b"text"),)])
def test_build_rejects_mutable_or_invalid_chunks(chunks):
    with pytest.raises(ContextPackError):
        ContextPack.build(chunks)


@pytest.mark.parametrize("kind", ["pack", "delta"])
def test_decoders_validate_exact_fields_schema_json_and_encodings(kind):
    pack = ContextPack.build((b"alpha",))
    value = pack if kind == "pack" else ContextPackDelta.between(pack, ContextPack.build((b"beta",)))
    decode = type(value).from_bytes
    payload = json.loads(value.to_bytes())
    field = "items" if kind == "pack" else "appended"
    mutations = [
        {**payload, "unexpected": 1},
        {**payload, "schema": "unknown"},
        {**payload, field: "YQ=="},
        {**payload, field: [None]},
        {**payload, field: ["YQ==\n"]},
        {**payload, field: ["YQ"]},
        {**payload, field: ["YR=="]},  # Nonzero padding bits are noncanonical.
        {**payload, field: ["/w=="]},  # Valid Base64, invalid UTF-8.
        *[{key: val for key, val in payload.items() if key != missing} for missing in payload],
    ]
    for bad in mutations:
        with pytest.raises(ContextPackError):
            decode(_json(bad))
    duplicate = value.to_bytes().replace(b'{"', b'{"schema":"ignored","', 1)
    for bad in (duplicate, b"[]", b"null", b"{", b"\xff"):
        with pytest.raises(ContextPackError):
            decode(bad)


@pytest.mark.parametrize("field,value", [("digest", "sha256:" + "0" * 64), ("byte_count", 0), ("byte_count", True)])
def test_pack_rejects_incorrect_integrity_fields(field, value):
    pack = ContextPack.build((b"alpha",))
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(_json({**json.loads(pack.to_bytes()), field: value}))


@pytest.mark.parametrize("prefix", [True, 1.5, -1, "1", None])
def test_delta_checks_prefix_on_construction_and_decode(prefix):
    base = ContextPack.build((b"a",))
    with pytest.raises(ContextPackError):
        ContextPackDelta(base.digest, base.digest, prefix, ())
    delta = ContextPackDelta.between(base, base)
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(_json({**json.loads(delta.to_bytes()), "prefix_items": prefix}))


def test_every_valid_prefix_and_chunk_boundaries_reconstruct_exact_target():
    base = ContextPack.build((b"a", b"b", b"c", b"old"))
    target = ContextPack.build((b"a", b"b", b"c", b"new"))
    for prefix in range(4):
        wire = _json({
            "schema": "powercontext.context-pack-delta.v1",
            "base_digest": base.digest,
            "target_digest": target.digest,
            "prefix_items": prefix,
            "appended": [base64.b64encode(item).decode() for item in target.items[prefix:]],
        })
        result = apply_context_pack_delta(ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(wire))
        assert result.to_bytes() == target.to_bytes()
    repartitioned = ContextPack.build((b"ab", b"c", b"new"))
    assert b"".join(target.items) == b"".join(repartitioned.items)
    assert target.digest != repartitioned.digest
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(base, ContextPackDelta(base.digest, target.digest, 0, repartitioned.items))


def test_delta_checks_base_bounds_target_and_truncation():
    base = ContextPack.build((b"a", b"b"))
    for target in (base, ContextPack.build((b"a",)), ContextPack.build(())):
        delta = ContextPackDelta.between(base, target)
        assert delta.byte_count == len(delta.to_bytes())
        assert apply_context_pack_delta(base, ContextPackDelta.from_bytes(delta.to_bytes())) == target
    invalid = (
        ContextPackDelta(base.digest, base.digest, 3, ()),
        ContextPackDelta(base.digest, "sha256:" + "0" * 64, 2, ()),
        ContextPackDelta(ContextPack.build(()).digest, base.digest, 0, base.items),
    )
    for delta in invalid:
        with pytest.raises(ContextPackError):
            apply_context_pack_delta(base, delta)


async def test_runtime_empty_content_and_authorization_are_preserved():
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Empty", summary="Empty", idempotency_key="pack-empty"))
        context = runtime.context.for_scope(scope.scope_id)
        request = PrepareContextRequest(query="nothing", assembly=ContextAssembly(sections=()))
        ordinary = await context.prepare(request)
        assert ordinary.content is None
        first = await context.prepare_incremental(request)
        assert isinstance(first, ContextPack) and first.items == ()
        delta = await context.prepare_incremental(request, ContextPack.from_content("old"))
        assert isinstance(delta, ContextPackDelta)
        assert apply_context_pack_delta(ContextPack.from_content("old"), delta).items == ()

        async def denied(scopes):
            assert scopes == (scope.scope_id,)
            raise PermissionError

        with pytest.raises(PermissionError):
            await context.prepare_incremental(PrepareContextRequest(query="nothing"), authorize_scopes=denied)
