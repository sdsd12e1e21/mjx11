---
title: Configure vector search
description: Enable embedding-backed vector and hybrid Memory search, then verify the Runtime capability.
---

# Configure vector search

Vector search needs an embedding model, a stable profile ID, and the model's output dimension.

## 1. Set one embedding profile

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL=provider:embedding-model
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID=embedding-model-v1
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION=1024
```

Replace the example values with one supported provider model, a profile ID you keep stable for that model, and its
documented output dimension. `POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_NORMALIZATION` defaults to `unit`.

The output dimension is always required. It fixes the local vector index width and validates returned vectors. By
default that value is also sent as the `dimensions` request field. Some OpenAI-compatible services reject the field,
including SiliconFlow `BAAI/bge-m3`. Keep the documented output dimension (1024 for bge-m3) and disable sending:

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_SEND_DIMENSIONS=false
```

## 2. Start the Server

```bash
powercontext server run
```

With SQLite, PowerContext loads the bundled sqlite-vec extension when it opens the database. Startup fails if the
installed extension is incompatible with the platform or SQLite build.

## 3. Verify the capability

```bash
powercontext capabilities
```

The result reports the enabled search modes. Without an embedding profile, SQLite full-text search remains available.

For timeouts, batch size, storage settings, and exact defaults, see [Configuration](../operate/configuration.md).

## Embedded seekdb hybrid candidates

With an embedding profile configured, the embedded seekdb backend retrieves full-text and vector candidates in one
native SQL statement for `hybrid` search. Each channel applies Scope, Memory artifact, optional tag filters, and its
candidate limit in the database. The shared admission and reciprocal-rank fusion stages then process the two channels.
FTS-only and vector-only requests retain their existing strategies.

References use the validated current Memory head. Unchanged active projections can retain an older stored
`head_revision`; this does not exclude them from search. Body revisions and eligibility changes continue to update
the existing projections transactionally. This optimization reduces candidate-query round trips; it does not remove
head validation, embedding completeness checks, or exact body reads.
