# Trace format v1

Each nonblank JSONL line is one event. In Python, pass an iterable of event dictionaries. The input order is authoritative; the auditor neither sorts timestamps nor reconstructs missing events. Finding `event_index` is zero-based among events, not physical file lines.

Every event requires nonempty string `type`, `thread_id`, and `revision`. Optional `event_id` is globally unique within the input trace. Optional `metadata` is a JSON object ignored by the rules. Other fields are rejected to catch typos. IDs are opaque and exact. A revision identifies a unique **interaction epoch** within a thread: decision context plus request generation. Generate a fresh token for a new question round, changed decision context, or explicit retry. Tokens are not numerically ordered and must never be reused after leaving an epoch.

## Snapshot

```json
{"type":"snapshot","thread_id":"case-1","revision":"draft-3","pending":[{"id":"request-1","key":"review:42"}]}
```

This is the **complete** pending set for one thread. `pending` may be empty. Each item requires `id`, with optional `key` and `metadata`. `key` is an application-owned equivalence label: use it only when two pending prompts concern the same logical decision. No prompt-text similarity or natural-language inference is performed.

The first valid snapshot establishes the current revision. Later snapshots replace the pending set at that same revision, but cannot restore IDs already consumed there. Reappearing consumed IDs reject the whole snapshot with `RESOLVED_REQUEST_REAPPEARED`. A snapshot at another revision is rejected as `STALE_SNAPSHOT` until a `context` event declares the transition. Repeated observations within a snapshot are deduplicated by ID with a warning. Missing keys merge with explicit keys on another observation of that ID; conflicting explicit keys reject the snapshot with `CONFLICTING_REQUEST_KEY`. Different IDs sharing a `key` produce a separate warning. Invalid snapshots preserve prior state.

## Resume

```json
{"type":"resume","thread_id":"case-1","revision":"draft-3","answers":{"request-1":false}}
```

Supply exactly one of a nonempty `answers` object or a `value` JSON payload. `answers` names request IDs; `value` is an untargeted response and is only unambiguous with exactly one pending request. A dictionary answer to one question can be represented as `{"answers":{"request-1":{"choice":"A"}}}`.

The auditor checks against the thread's current snapshot. An accepted resume consumes only the targeted IDs in the audit state. One unknown target rejects an entire mapping. Rejected resumes consume nothing. This simulated acceptance does not assert that a runtime invocation occurred or succeeded. If an invocation fails and the application intentionally retries, record a fresh context epoch followed by an authoritative snapshot. The auditor does not infer a retry or treat duplicate dispatch as harmless.

## Context change

```json
{"type":"context","thread_id":"case-1","revision":"draft-4"}
```

A new revision invalidates the old snapshot and pending set. Supply a complete fresh snapshot before resuming. Repeating the current revision does nothing; returning to a departed revision yields `REUSED_REVISION` and is ignored. The application must record transitions in order; the auditor cannot detect an omitted update. Some frameworks reuse an interrupt ID for sequential questions: those are separate epochs even if the rest of the application state has not changed.

## Results

| Code | Severity | Meaning |
|---|---|---|
| `AMBIGUOUS_RESUME` | error | Untargeted answer has more than one candidate |
| `UNKNOWN_REQUEST` | error | At least one mapped ID is not currently pending |
| `NO_PENDING_REQUEST` | error | Untargeted answer has no candidate |
| `NO_CURRENT_SNAPSHOT` | error | No usable snapshot exists for the current context |
| `STALE_REVISION` | error | Reply names a different context revision |
| `STALE_SNAPSHOT` | error | Snapshot disagrees with established context |
| `DUPLICATE_EVENT_ID` | error | Repeated event is ignored |
| `RESOLVED_REQUEST_REAPPEARED` | error | Snapshot attempts to restore an answered ID in the same epoch |
| `REUSED_REVISION` | error | Context attempts to return to a departed epoch |
| `CONFLICTING_REQUEST_KEY` | error | One snapshot ID has conflicting explicit logical keys |
| `DUPLICATE_REQUEST_ID` | warning | Snapshot repeats an ID; it counts once |
| `DUPLICATE_PENDING_KEY` | warning | Different IDs share a logical decision key |
| `PENDING_AT_END` | info | Trace ends while waiting for a person |

Malformed schema raises `TraceFormatError` instead of producing a pass/fail report. The CLI also rejects duplicate JSON object keys, non-finite numbers, and non-object lines. Python payloads must be finite JSON-compatible values, without reference cycles; at most 128 nested containers are supported.

No errors and at least one accepted resume yields `pass`; any error yields `fail`; otherwise the report is `inconclusive`. This is trace-level evidence, not complete coverage of each thread or possible workflow. Counts show the observed workload. Do not treat an untested branch as validated.

Reports omit answer contents and arbitrary metadata. Application-supplied identifiers, file names, and format errors may still disclose information; use pseudonymous IDs before sharing a report.
