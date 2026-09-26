# Interaction Contracts

**Catch ambiguous and stale human replies in agent workflows before they become regressions.**

[中文](README.zh-CN.md) · [Trace format](docs/trace-format.md) · [LangGraph example](docs/langgraph.md) · [Evidence and alternatives](docs/evidence.md)

Two branches ask different questions. The interface submits one `true`. Which question did the person answer?

Interaction Contracts checks this boundary in recorded traces. It is a small, offline Python library and CLI for teams building human-in-the-loop agents. The core uses only the standard library; no API key, model judge, telemetry, or running agent is required.

**Status: experimental alpha.** The included cases are synthetic regression fixtures, not a benchmark of model intelligence or evidence of production adoption. A real nested LangGraph example is also tested. This tool checks the supplied observations; it does not authenticate a user, validate consent meaning, inspect side effects, or enforce authorization.

## Try it

From a checkout, with Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
interaction-contracts examples/traces/parallel_ambiguous.jsonl
```

Expected result: `FAIL` with `AMBIGUOUS_RESUME`, exit code `1`. The failing input contains:

```jsonl
{"type":"snapshot","thread_id":"demo","revision":"v1","pending":[{"id":"left"},{"id":"right"}]}
{"type":"resume","thread_id":"demo","revision":"v1","value":true}
```

Bind answers explicitly:

```bash
interaction-contracts examples/traces/parallel_mapped.jsonl --format json
```

That trace submits `{"left": true, "right": false}` under `answers`, and passes. `false` is a valid answer, not an absent answer. Install from the checkout; this alpha has not been published to PyPI.

## What it checks

| Recorded condition | Result |
|---|---|
| Untargeted reply with several distinct pending IDs | `AMBIGUOUS_RESUME` error |
| Reply targets an ID outside this thread's current pending set | `UNKNOWN_REQUEST` error |
| Context changed; reply still names the previous revision | `STALE_REVISION` error |
| New context has no fresh pending snapshot | `NO_CURRENT_SNAPSHOT` error |
| Duplicate event ID | Error; duplicate ignored |
| Old snapshot restores an answered ID in the same epoch | `RESOLVED_REQUEST_REAPPEARED` error |
| Same request ID surfaced twice in one snapshot | Warning; counted once |
| Different IDs share an explicit application-defined logical key | Warning for possible repeated questioning |
| No checked resume, including an empty trace | `inconclusive`, never a pass |

An error rejects the whole resume in the audit's simulated state. Pending requests at the end are informational because a workflow may legitimately remain paused. Warnings fail CI only with `--strict`.

## Python and CI

```python
from interaction_contracts import audit

report = audit([
    {"type": "snapshot", "thread_id": "review-42", "revision": "draft-3",
     "pending": [{"id": "review-request"}]},
    {"type": "resume", "thread_id": "review-42", "revision": "draft-3",
     "answers": {"review-request": False}},
])
assert report.ok
```

```bash
interaction-contracts my-trace.jsonl --strict --junit report.xml --format json
python -m unittest discover -s tests -v
```

Exit codes: `0` passing evidence; `1` contract failure (or a strict warning); `2` malformed/unreadable input or inconclusive evidence. With several files, each is audited independently; code `2` takes precedence over `1`. JSON output retains every file's result. JUnit marks inconclusive traces skipped, and the CLI still exits `2` so missing evidence cannot silently green a job.

## Use with LangGraph

```bash
python -m pip install 'langgraph==1.2.12'
python examples/langgraph_parallel.py
```

The example runs a parent graph containing two parallel interrupted branches, converts actual returned IDs into a snapshot, demonstrates rejection of an ambiguous reply, and resumes the graph with distinct ID-mapped answers. It uses no LLM or external service. See the [adapter guide](docs/langgraph.md) for the measured result and integration limits.

## Why a separate small package?

Native LangGraph interrupt IDs are the right mechanism for routing replies. Existing systems such as [AgentReplay](https://github.com/anzal1/agentreplay) cover broader trace testing. This package focuses on portable, issue-inspired human-input cases, explicit revisions, and simple reports that fit an existing test suite. It does not replace a checkpointer, observability platform, or general evaluation harness. [Read the evidence and comparison](docs/evidence.md).

## Limits that matter

- A `snapshot` must contain the complete pending set for one thread, not one streaming chunk. Event order must already be correct.
- The application supplies unique interaction-epoch revisions and emits a `context` event for changed context, a new question round, or an explicit retry. Some frameworks reuse IDs between sequential questions; those require fresh epochs. The checker cannot infer transitions from natural language.
- A pass means the recorded routing conforms to these rules. It does not prove that the right person answered, the UI showed the right question, the runtime consumed the answer, or a later action respected it.
- Prompts are not copied by the adapter and reply values do not appear in audit reports. Input files can still contain sensitive data. Use redacted placeholders when only routing matters.
- No hardware validation, human study, model ranking, or measured reduction in real incident rates is claimed.

## Contribute

Useful contributions start with a minimal failing trace and a corrected trace. See [CONTRIBUTING.md](CONTRIBUTING.md). The next milestone is validation against several real application traces and one more framework, before extending the protocol.

MIT licensed. Created by Wen Chen, with AI-assisted implementation and review.
