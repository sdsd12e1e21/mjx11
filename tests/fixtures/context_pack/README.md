# Context Pack transport measurement

This is a local reproducible workload, separate from the competition's published
acceptance tests and unavailable full evaluation sequence.

The unchanged speaker and complete turn texts come from QMSum, commit
`83d7768c1f2b4dfeb091385d3dc7e239b8e5bb7e`, file
`data/ALL/test/ES2004a.json` (SHA-256
`911e56db0d8482f1e730bae0a8fcf0ab0095c94abb000ba0516e975fa6e48b31`).
The upstream MIT license is included in `LICENSE`.

Start with the first eight turns containing “remote” in their original order.
Append the remaining such turn and the next two original turns at zero-based
rounds 10, 20 and 30. The four query blocks use `remote`, `controls`, `design`,
and `programme`, respectively. The supplied JSON records the original turn
indices and measurement settings. No text is generated or padded.

From the repository root, with this checkout's `src` on `PYTHONPATH`, run:

```sh
python scripts/benchmark_context_pack.py tests/fixtures/context_pack/meeting_sequence.json --output report.json
```

The script runs actual Runtime capture, Memory flush and ordinary/incremental
prepare for all 40 rounds. It counts the first full pack and every subsequent
delta, including their complete serialized overhead. It closes the Runtime,
then replays only the wire bytes in a fresh receiver process and compares every
reconstructed byte with ordinary prepare, including citation text.

The report includes raw UTF-8, full v1 pack and per-round deterministic gzip-9
totals, the savings against each baseline, and the number of distinct contexts.
These are local workload measurements, not an official competition score or a
general compression claim.
