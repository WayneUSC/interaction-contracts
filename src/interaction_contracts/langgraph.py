"""Convert LangGraph invoke results without importing the optional framework."""

from collections.abc import Mapping, Sequence
from typing import Any


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def snapshot_from_result(
    result: Mapping[str, Any], *, thread_id: str, revision: str
) -> dict[str, Any]:
    """Normalize a complete ``graph.invoke`` result to a metadata-only snapshot.

    ``revision`` is an application-issued interaction epoch, not inferred from
    LangGraph. Issue a fresh, never-reused token for each new logical input round,
    changed decision context, or explicit retry, even if prompts are unchanged.
    LangGraph can reuse an interrupt ID for sequential calls in one node; a new
    epoch distinguishes that new request from a replay of an answered request.
    A missing ``__interrupt__`` key means no pending interrupts in this result.
    Both current Interrupt objects and their serialized id/value mappings work.
    Prompt values and arbitrary graph state are deliberately not copied.
    Duplicate IDs are retained so the core auditor can report them.

    Supply complete results in order from a single writer per thread: one stream
    chunk need not contain all concurrent interrupts. This function cannot detect
    omitted observations, verify an epoch, check a live checkpoint, or lock it.
    A production dispatcher must atomically verify its current epoch and prevent
    duplicate dispatch; snapshot capture does not silently authorize retries.
    """
    _identifier(thread_id, "thread_id")
    _identifier(revision, "revision")
    if not isinstance(result, Mapping):
        raise ValueError("result must be a mapping from graph.invoke")
    interrupts = result.get("__interrupt__", ())
    if not isinstance(interrupts, Sequence) or isinstance(
        interrupts, (str, bytes, bytearray)
    ):
        raise ValueError("__interrupt__ must be a sequence of interrupts")

    pending = []
    for index, item in enumerate(interrupts):
        interrupt_id = (
            item.get("id") if isinstance(item, Mapping) else getattr(item, "id", None)
        )
        _identifier(interrupt_id, f"interrupt {index} id")
        pending.append({"id": interrupt_id})
    return {
        "type": "snapshot",
        "thread_id": thread_id,
        "revision": revision,
        "pending": pending,
    }
