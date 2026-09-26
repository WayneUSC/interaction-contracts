# Local validation record

Date: 2026-09-26. Version: 0.1.0a1.

- Python 3.12.14, macOS arm64.
- LangGraph 1.2.12 installed in a task-specific virtual environment.
- `python -m unittest discover -s tests -v`: **52 tests passed**, no skips with LangGraph installed.
- `python examples/langgraph_parallel.py`: two pending interrupts; ambiguous audit fails; ID-mapped audit passes; both branches finish with their intended distinct answers.
- A second actual graph confirms that sequential questions inside one node reuse an interrupt ID. Reappearing answered IDs fail in the old epoch and succeed after an explicit fresh epoch.
- `python -m pip install --no-deps .`: built and installed the wheel successfully.
- The installed `interaction-contracts` command was invoked outside the source checkout: version, passing fixture and JUnit output verified.

Independent code review found and prompted fixes for stale snapshot resurrection, revision reuse, conflicting duplicate logical keys, and deeply nested JSON error handling. The regression tests include those counterexamples.

The GitHub Actions configuration includes Python 3.10, 3.12 and 3.13 plus a pinned LangGraph integration job. Those remote jobs are not claimed as run in this local record. No real customer traces, human participants, hardware, or paid model calls were used. Synthetic corpus outcomes verify checker behavior, not real-world incident detection rates.

The package list for the live integration environment is in [validation-env.txt](validation-env.txt).
