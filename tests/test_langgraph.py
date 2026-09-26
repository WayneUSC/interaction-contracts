from dataclasses import dataclass
import importlib.util
from pathlib import Path
import runpy
import unittest

from interaction_contracts.langgraph import snapshot_from_result


@dataclass
class FakeInterrupt:
    id: str
    value: object


class SnapshotAdapterTests(unittest.TestCase):
    def test_object_and_serialized_interrupts_keep_only_routing_metadata(self):
        result = {
            "private_state": "must not be copied",
            "__interrupt__": (
                FakeInterrupt("a", {"prompt": "private prompt"}),
                {"id": "b", "value": "another private prompt", "ns": ["private"]},
            ),
        }
        self.assertEqual(
            snapshot_from_result(result, thread_id="t", revision="r"),
            {"type": "snapshot", "thread_id": "t", "revision": "r",
             "pending": [{"id": "a"}, {"id": "b"}]},
        )

    def test_completed_invoke_is_empty_snapshot(self):
        self.assertEqual(
            snapshot_from_result({"answer": 42}, thread_id="t", revision="r")["pending"],
            [],
        )

    def test_duplicate_ids_are_preserved_for_the_auditor(self):
        result = {"__interrupt__": [{"id": "a"}, {"id": "a"}]}
        self.assertEqual(len(snapshot_from_result(
            result, thread_id="t", revision="r"
        )["pending"]), 2)

    def test_missing_or_malformed_ids_never_become_positional_targets(self):
        for item in ({"value": "secret"}, {"id": ""}, {"id": None},
                     {"id": 3}, {"id": True}, FakeInterrupt(" ", "secret")):
            with self.subTest(item=item), self.assertRaises(ValueError):
                snapshot_from_result({"__interrupt__": [item]}, thread_id="t", revision="r")

    def test_rejects_partial_or_malformed_containers(self):
        for result in ([], None, {"__interrupt__": None},
                       {"__interrupt__": "a"}, {"__interrupt__": {"id": "a"}}):
            with self.subTest(result=result), self.assertRaises(ValueError):
                snapshot_from_result(result, thread_id="t", revision="r")

    def test_routing_context_must_be_explicit_nonempty_strings(self):
        for field in ("thread_id", "revision"):
            for value in (None, "", "  ", 1, True):
                args = {"thread_id": "t", "revision": "r", field: value}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    snapshot_from_result({}, **args)


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "optional LangGraph not installed")
class LiveLangGraphTests(unittest.TestCase):
    def test_nested_parallel_interrupts_route_to_distinct_branches(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "langgraph_parallel.py"
        result = runpy.run_path(str(example))["run_demo"]()
        self.assertEqual(result["ambiguous_resume"], "fail")
        self.assertEqual(result["mapped_resume"], "pass")
        self.assertEqual(result["completed_branches"], 2)

    def test_sequential_same_id_uses_a_new_interaction_epoch(self):
        from typing import TypedDict
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, interrupt
        from interaction_contracts import audit

        class State(TypedDict):
            answers: list[str]

        def ask(_state: State):
            first = interrupt("First question")
            second = interrupt("Second question")
            return {"answers": [first, second]}

        graph = (
            StateGraph(State).add_node("ask", ask)
            .add_edge(START, "ask").add_edge("ask", END)
            .compile(checkpointer=InMemorySaver())
        )
        thread_id = "sequential-epoch-test"
        config = {"configurable": {"thread_id": thread_id}}
        first = graph.invoke({"answers": []}, config)
        first_id = first["__interrupt__"][0].id
        first_snapshot = snapshot_from_result(first, thread_id=thread_id, revision="round-1")
        first_resume = {
            "type": "resume", "thread_id": thread_id, "revision": "round-1",
            "answers": {first_id: "first answer"},
        }
        self.assertEqual(audit([first_snapshot, first_resume]).status, "pass")
        second = graph.invoke(Command(resume=first_resume["answers"]), config)
        second_id = second["__interrupt__"][0].id
        self.assertEqual(first_id, second_id, "Pinned LangGraph reuses this task's ID")

        stale = audit([
            first_snapshot, first_resume,
            snapshot_from_result(second, thread_id=thread_id, revision="round-1"),
        ])
        self.assertIn("RESOLVED_REQUEST_REAPPEARED", [f.code for f in stale.findings])

        second_resume = {
            "type": "resume", "thread_id": thread_id, "revision": "round-2",
            "answers": {second_id: "second answer"},
        }
        report = audit([
            first_snapshot, first_resume,
            {"type": "context", "thread_id": thread_id, "revision": "round-2"},
            snapshot_from_result(second, thread_id=thread_id, revision="round-2"),
            second_resume,
        ])
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.counts["accepted_resumes"], 2)
        final = graph.invoke(Command(resume=second_resume["answers"]), config)
        self.assertEqual(final["answers"], ["first answer", "second answer"])
        self.assertFalse(final.get("__interrupt__"))


if __name__ == "__main__":
    unittest.main()
