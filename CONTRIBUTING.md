# Contributing

Start with an observable failure. Include a minimal JSONL trace, the expected finding, a corrected trace, and the framework/version if relevant. Replace prompts and answer contents with placeholders unless they are necessary; the current rules only need routing metadata.

Run `python -m unittest discover -s tests -v`. Without LangGraph, its real integration test is explicitly skipped. Install `langgraph==1.2.12` to run it and `python examples/langgraph_parallel.py`.

Preserve these invariants: empty evidence must not pass; invalid resumes are atomic; thread state is isolated; duplicate observations must not become extra human decisions; reports must not echo answer contents. Add tests for both a failing case and a legitimate workflow before adding a rule.

Please discuss lifecycle/schema changes before expanding this small package into a framework. A useful bug report is more valuable than a new abstraction without a consumer.
