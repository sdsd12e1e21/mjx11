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

"""Measure native context transport; replay wire bytes in a fresh receiver process."""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, PrepareContextRequest, open_builtin_runtime
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class _CandidatePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="conversation-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def _receive() -> None:
    base = None
    for wire in sys.stdin.buffer:
        wire = wire.rstrip(b"\r\n")
        base = (
            ContextPack.from_bytes(wire)
            if base is None
            else apply_context_pack_delta(base, ContextPackDelta.from_bytes(wire))
        )
        sys.stdout.buffer.write(base64.b64encode(b"".join(base.items)) + b"\n")


async def _drain(memory, maximum: int) -> None:
    for _ in range(maximum):
        if not (await memory.flush()).processed:
            return
    raise RuntimeError("flush-did-not-drain")


async def _measure_sequence(workload: dict) -> tuple[list[dict], list[bytes], list[bytes]]:
    turns = workload["turns"]
    rounds = workload["rounds"]
    initial = workload["initial_turns"]
    append_rounds = workload["append_rounds"]
    queries = workload["queries"]
    if not (rounds >= 1 and 1 <= initial <= len(turns) and queries):
        raise ValueError("invalid-workload")
    rows, wires, expected = [], [], []
    base = None
    cursor = initial
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=_CandidatePipeline()) as runtime:
        if runtime.scopes is None:
            raise RuntimeError("scope-management-unavailable")
        scope = await runtime.scopes.create(
            ScopeDraft(title="Context transport", summary="Measured native prepare", idempotency_key="pack-benchmark")
        )
        sources = runtime.sources.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        context = runtime.context.for_scope(scope.scope_id)

        async def capture(index: int) -> None:
            await sources.capture(CaptureSource(source_id=f"turn-{index}", content=turns[index]["text"], metadata={}))

        for index in range(initial):
            await capture(index)
        await _drain(memory, len(turns) + 1)
        for index in range(rounds):
            if index in append_rounds:
                await capture(cursor)
                cursor += 1
                await _drain(memory, len(turns) + 1)
            query = queries[min(index * len(queries) // rounds, len(queries) - 1)]
            request = PrepareContextRequest(query=query, max_bytes=workload.get("max_bytes", 8000))
            ordinary = await context.prepare(request)
            content = (ordinary.content or "").encode("utf-8")
            if not content:
                raise AssertionError("measurement-round-must-be-nonempty")
            message = await context.prepare_incremental(request, base_pack=base)
            wire = message.to_bytes()
            base = (
                ContextPack.from_bytes(wire)
                if base is None
                else apply_context_pack_delta(base, ContextPackDelta.from_bytes(wire))
            )
            if b"".join(base.items) != content:
                raise AssertionError("ordinary-content-and-citations-differ")
            expected.append(content)
            wires.append(wire)
            rows.append({
                "round": index + 1,
                "query": query,
                "captured_turns": cursor,
                "raw_full_bytes": len(content),
                "incremental_bytes": len(wire),
                "full_pack_bytes": len(ContextPack.from_content(content).to_bytes()),
                "gzip_bytes": len(gzip.compress(content, compresslevel=9, mtime=0)),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            })

    return rows, wires, expected


def benchmark(workload: dict) -> dict:
    rows, wires, expected = asyncio.run(_measure_sequence(workload))
    # Runtime is closed. Only this script is executed, with serialized data on stdin.
    replay = subprocess.run(  # noqa: S603
        [sys.executable, str(Path(__file__).resolve()), "--receive"],
        input=b"\n".join(wires) + b"\n",
        capture_output=True,
        check=True,
        timeout=60,
    )
    if [base64.b64decode(line, validate=True) for line in replay.stdout.splitlines()] != expected:
        raise AssertionError("independent-receiver-content-and-citations-differ")
    totals = {
        key: sum(row[key] for row in rows)
        for key in ("raw_full_bytes", "incremental_bytes", "full_pack_bytes", "gzip_bytes")
    }
    return {
        "rounds": workload["rounds"],
        "initial_turns": workload["initial_turns"],
        "distinct_contexts": len(set(expected)),
        "independent_receiver_verified": True,
        **totals,
        "savings_vs_raw": 1 - totals["incremental_bytes"] / totals["raw_full_bytes"],
        "savings_vs_full_pack": 1 - totals["incremental_bytes"] / totals["full_pack_bytes"],
        "savings_vs_gzip": 1 - totals["incremental_bytes"] / totals["gzip_bytes"],
        "sequence": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workload", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receive", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.receive:
        _receive()
        return
    if args.workload is None:
        parser.error("workload is required")
    report = benchmark(json.loads(args.workload.read_text(encoding="utf-8")))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sequence"}, sort_keys=True))


if __name__ == "__main__":
    main()
