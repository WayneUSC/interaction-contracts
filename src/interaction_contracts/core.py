"""Check recorded human-input routing contracts without running an agent.

Events are ordered observations, not security attestations. A snapshot establishes
the first revision of a thread; subsequent revision changes require a ``context``
event. A revision identifies a unique interaction epoch within its thread and must
not be reused after departure. Payload contents are checked for JSON compatibility
but never interpreted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
import math
from typing import Any


class TraceFormatError(ValueError):
    """The supplied trace does not conform to the v1 event schema."""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    event_index: int | None
    message: str
    thread_id: str | None


@dataclass
class Report:
    status: str
    counts: dict[str, int]
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        """True only for a passing report, never for an inconclusive one."""
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "status": self.status,
            "counts": dict(self.counts),
            "findings": [asdict(finding) for finding in self.findings],
        }


@dataclass
class _Thread:
    revision: str | None = None
    has_snapshot: bool = False
    pending: dict[str, str | None] = field(default_factory=dict)
    consumed: set[str] = field(default_factory=set)
    seen_revisions: set[str] = field(default_factory=set)


_COMMON = {"type", "thread_id", "revision", "event_id", "metadata"}
_FIELDS = {
    "snapshot": _COMMON | {"pending"},
    "resume": _COMMON | {"answers", "value"},
    "context": _COMMON,
}


def _fail(index: int, message: str) -> None:
    raise TraceFormatError(f"event {index}: {message}")


def _identifier(value: Any, index: int, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(index, f"{name} must be a nonempty string")


def _json_value(
    value: Any, index: int, path: str, active: set[int] | None = None, depth: int = 0
) -> None:
    """Validate JSON data, including cycles and a 128-container nesting limit."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(index, f"{path} must contain only finite JSON numbers")
        return
    if not isinstance(value, (list, dict)):
        _fail(index, f"{path} must be a JSON value")
    if depth >= 128:
        _fail(index, f"{path} exceeds the maximum nesting depth of 128 containers")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        _fail(index, f"{path} must not contain a cycle")
    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    _fail(index, f"{path} object keys must be strings")
                _json_value(item, index, path, active, depth + 1)
        else:
            for item in value:
                _json_value(item, index, path, active, depth + 1)
    finally:
        active.remove(identity)


def _metadata(container: dict[str, Any], index: int, path: str) -> None:
    if "metadata" in container:
        if not isinstance(container["metadata"], dict):
            _fail(index, f"{path} metadata must be an object")
        _json_value(container["metadata"], index, f"{path} metadata")


def _validate(event: Any, index: int) -> None:
    if not isinstance(event, dict):
        _fail(index, "event must be an object")
    kind = event.get("type")
    if not isinstance(kind, str) or kind not in _FIELDS:
        _fail(index, "type must be snapshot, resume, or context")
    if set(event) - _FIELDS[kind]:
        _fail(index, "event contains unsupported fields; use metadata for extensions")
    for name in ("thread_id", "revision"):
        _identifier(event.get(name), index, name)
    if "event_id" in event:
        _identifier(event["event_id"], index, "event_id")
    _metadata(event, index, "event")
    if kind == "snapshot":
        pending = event.get("pending")
        if not isinstance(pending, list):
            _fail(index, "pending must be an array")
        for request in pending:
            if not isinstance(request, dict):
                _fail(index, "each pending request must be an object")
            if set(request) - {"id", "key", "metadata"}:
                _fail(index, "pending request contains unsupported fields")
            _identifier(request.get("id"), index, "pending id")
            if "key" in request:
                _identifier(request["key"], index, "pending key")
            _metadata(request, index, "pending request")
    if kind == "resume":
        if ("answers" in event) == ("value" in event):
            _fail(index, "resume requires exactly one of answers or value")
        if "answers" in event:
            answers = event["answers"]
            if not isinstance(answers, dict) or not answers:
                _fail(index, "answers must be a nonempty object")
            for request_id, value in answers.items():
                _identifier(request_id, index, "answer request id")
                _json_value(value, index, "answer payload")
        else:
            _json_value(event["value"], index, "resume payload")


def audit(events: Iterable[dict[str, Any]]) -> Report:
    """Audit one ordered event stream in a single pass.

    Invalid resumes never consume pending requests. Snapshots are authoritative
    for unresolved IDs, but cannot restore IDs consumed during the same revision.
    Invalid snapshots are ignored atomically. Duplicate event IDs produce an
    error and are ignored. ``context`` revision changes invalidate outstanding
    snapshots until a matching fresh snapshot arrives. A departed revision cannot
    become current again; a new interaction epoch needs a fresh revision token.

    A pass requires at least one accepted resume and no errors. Warnings do not
    change pass/fail; traces with no resume evidence remain inconclusive. End-of-
    trace pending requests are informational: a trace may legitimately end paused.
    """
    if isinstance(events, (str, bytes, dict)):
        raise TraceFormatError("trace must be an iterable of event objects, not a single object or string")
    try:
        iterator = iter(events)
    except TypeError as exc:
        raise TraceFormatError("trace must be an iterable of event objects") from exc
    threads: dict[str, _Thread] = {}
    seen_events: set[str] = set()
    findings: list[Finding] = []
    counts = {
        "events": 0,
        "threads": 0,
        "resumes": 0,
        "accepted_resumes": 0,
        "rejected_resumes": 0,
        "pending_requests": 0,
    }

    def add(code: str, severity: str, index: int | None, message: str, thread_id: str | None) -> None:
        findings.append(Finding(code, severity, index, message, thread_id))

    for index, event in enumerate(iterator):
        try:
            _validate(event, index)
        except RecursionError as exc:
            raise TraceFormatError(f"event {index}: JSON validation exceeded the recursion limit") from exc
        counts["events"] += 1
        kind = event["type"]
        thread_id = event["thread_id"]
        revision = event["revision"]
        if kind == "resume":
            counts["resumes"] += 1
        event_id = event.get("event_id")
        if event_id is not None:
            if event_id in seen_events:
                add("DUPLICATE_EVENT_ID", "error", index, "Event ID was already observed; duplicate event ignored.", thread_id)
                if kind == "resume":
                    counts["rejected_resumes"] += 1
                continue
            seen_events.add(event_id)
        state = threads.setdefault(thread_id, _Thread())

        if kind == "context":
            if state.revision != revision:
                if revision in state.seen_revisions:
                    add("REUSED_REVISION", "error", index, "Context returns to a departed interaction revision; event ignored.", thread_id)
                    continue
                state.revision = revision
                state.seen_revisions.add(revision)
                state.has_snapshot = False
                state.pending.clear()
                state.consumed.clear()
            continue

        if kind == "snapshot":
            if state.revision is not None and state.revision != revision:
                add("STALE_SNAPSHOT", "error", index, "Snapshot revision does not match current context; snapshot ignored.", thread_id)
                continue
            pending: dict[str, str | None] = {}
            duplicate_ids = 0
            conflicting_ids: set[str] = set()
            for request in event["pending"]:
                request_id = request["id"]
                request_key = request.get("key")
                if request_id in pending:
                    duplicate_ids += 1
                    prior_key = pending[request_id]
                    if prior_key is not None and request_key is not None and prior_key != request_key:
                        conflicting_ids.add(request_id)
                    elif prior_key is None:
                        pending[request_id] = request_key
                else:
                    pending[request_id] = request_key
            if conflicting_ids:
                add("CONFLICTING_REQUEST_KEY", "error", index, f"Snapshot assigns conflicting explicit keys to {len(conflicting_ids)} request ID(s); snapshot ignored.", thread_id)
                continue
            reappeared = set(pending) & state.consumed
            if reappeared:
                add("RESOLVED_REQUEST_REAPPEARED", "error", index, f"Snapshot restores {len(reappeared)} request ID(s) already resolved in this interaction revision; snapshot ignored.", thread_id)
                continue
            if duplicate_ids:
                add("DUPLICATE_REQUEST_ID", "warning", index, f"Snapshot repeats {duplicate_ids} request ID observation(s); each distinct ID counts once.", thread_id)
            keys = [key for key in pending.values() if key is not None]
            duplicate_keys = len(keys) - len(set(keys))
            if duplicate_keys:
                add("DUPLICATE_PENDING_KEY", "warning", index, f"Distinct pending requests share {duplicate_keys} caller-defined logical key occurrence(s).", thread_id)
            state.revision = revision
            state.seen_revisions.add(revision)
            state.pending = pending
            state.has_snapshot = True
            continue

        error: tuple[str, str] | None = None
        targets: set[str] = set()
        if state.revision is not None and state.revision != revision:
            error = ("STALE_REVISION", "Resume revision does not match current context.")
        elif not state.has_snapshot:
            error = ("NO_CURRENT_SNAPSHOT", "No pending-request snapshot is available for this context revision.")
        elif "answers" in event:
            targets = set(event["answers"])
            unknown = targets - set(state.pending)
            if unknown:
                error = ("UNKNOWN_REQUEST", f"Resume targets {len(unknown)} request ID(s) absent from the current pending snapshot.")
        elif not state.pending:
            error = ("NO_PENDING_REQUEST", "Scalar resume has no pending request to answer.")
        elif len(state.pending) > 1:
            error = ("AMBIGUOUS_RESUME", "Scalar resume cannot select among multiple distinct pending requests; use an ID-to-answer mapping.")
        else:
            targets = set(state.pending)

        if error is not None:
            counts["rejected_resumes"] += 1
            add(error[0], "error", index, error[1], thread_id)
        else:
            for target in targets:
                del state.pending[target]
            state.consumed.update(targets)
            counts["accepted_resumes"] += 1

    counts["threads"] = len(threads)
    counts["pending_requests"] = sum(len(state.pending) for state in threads.values())
    for thread_id, state in threads.items():
        if state.pending:
            add("PENDING_AT_END", "info", None, f"Trace ends with {len(state.pending)} distinct pending request(s).", thread_id)
    counts["errors"] = sum(finding.severity == "error" for finding in findings)
    counts["warnings"] = sum(finding.severity == "warning" for finding in findings)
    counts["info"] = sum(finding.severity == "info" for finding in findings)
    if counts["errors"]:
        status = "fail"
    elif counts["accepted_resumes"]:
        status = "pass"
    else:
        status = "inconclusive"
    return Report(status, counts, findings)
