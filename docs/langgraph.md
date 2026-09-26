# LangGraph integration

The adapter reads the complete `graph.invoke()` result's `__interrupt__` list.
It retains interrupt IDs, thread ID and an application-issued interaction epoch
(the schema's `revision` field). It
does not copy prompt values or graph state, and does not import LangGraph.

```python
from interaction_contracts.langgraph import snapshot_from_result

snapshot = snapshot_from_result(
    result, thread_id="session-123", revision="interaction-4"
)
```

Current `Interrupt` objects and serialized `{"id": ..., "value": ...}` mappings
both work. Missing IDs are rejected; the adapter never guesses an ID from list
position or a question's text. A result without `__interrupt__` yields an empty
snapshot. Duplicate IDs are retained so the auditor can flag them.

## Give each input round its own epoch

`revision` identifies both the decision context and the checkpoint/request
generation the user is answering. Issue a fresh token, unique for the lifetime of
that thread, for each new logical input round, changed decision context, or
explicit retry. A monotonic counter or a fresh UUID can serve as the token if
the application reliably stores and compares it. A prompt hash alone cannot:
identical text may belong to a new request. Return this token with the questions
and require the UI to submit that same token with its answers.

LangGraph can reuse one interrupt ID for sequential `interrupt()` calls inside
the same node. We verified this behavior on 1.2.12. After resuming the first
question, record a `context` event for a fresh epoch before recording the second
complete snapshot. The same framework ID is then valid in that new epoch:

```python
events = [
    snapshot_from_result(first, thread_id="t", revision="round-1"),
    {"type": "resume", "thread_id": "t", "revision": "round-1",
     "answers": {request_id: "first answer"}},
    {"type": "context", "thread_id": "t", "revision": "round-2"},
    snapshot_from_result(second, thread_id="t", revision="round-2"),
    {"type": "resume", "thread_id": "t", "revision": "round-2",
     "answers": {request_id: "second answer"}},
]
```

Here `first` and `second` are successive complete invoke results; the UI binds
each answer to the displayed request ID. Record and audit actual events in
their observed order. Replaying a snapshot that contains an already answered ID
in its old epoch is rejected as `RESOLVED_REQUEST_REAPPEARED`. Returning to an
epoch the thread previously left is rejected as `REUSED_REVISION`. A repeated
snapshot cannot silently reopen a request or authorize a retry. An explicit
retry requires a new epoch and the application's own dispatch/idempotency rules.

## Run a real nested parallel graph

From a checkout, in your virtual environment:

```sh
python -m pip install -e . 'langgraph==1.2.12'
python examples/langgraph_parallel.py
python -m unittest discover -s tests -p test_langgraph.py -v
```

The example creates an in-memory parent graph wrapping two parallel interrupting
child nodes. It checks an ambiguous scalar attempt without dispatching it, then
submits an ID-to-answer mapping through the real `Command(resume=...)` API. It
asserts that both distinct answers reached their intended branch. No model,
network service or API key is used during execution.

The unit tests work without LangGraph. The integration test explicitly skips if
the optional dependency is unavailable.

Verified on 2026-09-26 with Python 3.12.14 and LangGraph 1.2.12. The parallel
graph produced:

```json
{
  "langgraph_version": "1.2.12",
  "pending_interrupts": 2,
  "ambiguous_resume": "fail",
  "mapped_resume": "pass",
  "completed_branches": 2
}
```

All eight adapter and integration tests passed. The additional sequential test
confirms that two questions in one real node reuse the same ID, an old-epoch
snapshot is rejected, and a fresh epoch permits both distinct answers to reach
the node correctly.

The validation environment's dependency versions are recorded in
[validation-env.txt](validation-env.txt). This is a tested environment manifest,
not the package's runtime requirements; the adapter itself needs only Python's
standard library.

## Boundaries

- Use a complete invoke result, not a stream chunk. A chunk may expose only one
  of several concurrent interrupts. This adapter cannot detect an incomplete
  snapshot supplied by a caller. Capture the authoritative pending set through a
  single writer per thread and preserve its order in the trace.
- An epoch is not automatically a LangGraph checkpoint ID and must never be
  reused after the thread leaves it. Record a `context` event before a new epoch,
  then capture a matching complete snapshot. Changes to the displayed decision
  context also require a new epoch, even if the framework interrupt ID persists.
- Capture the actual submitted mapping for auditing, then use the same mapping
  to construct `Command(resume=answers)`. Keep the same LangGraph thread ID.
- An offline audit cannot lock a live checkpoint. Another writer may advance the
  graph after validation. A production application still needs atomic revision
  checks and duplicate-dispatch protection, or equivalent per-thread serialized
  state transitions. Passing an audit is not permission to blindly retry a
  failed network request: the original dispatch may already have succeeded.
- A passing report concerns the recorded routing contract. It does not assess
  whether a human approved the content, whether the answer is correct, or whether
  a side effect is safe. LangGraph nodes restart on resume; code before an
  interrupt must tolerate re-execution.

This is application-side validation, not a patch to LangGraph. The example is
motivated by a public report of ambiguous scalar routing for parallel interrupts
inside one subgraph task; it does not claim that the installed framework version
has that bug.

Sources checked 2026-09-26:

- [Official interrupt guide](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Official Command and Interrupt source](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py)
- [Nested parallel scalar-resume report, issue #8579](https://github.com/langchain-ai/langgraph/issues/8579)
- [Pinned LangGraph 1.2.12 release](https://pypi.org/project/langgraph/1.2.12/)
