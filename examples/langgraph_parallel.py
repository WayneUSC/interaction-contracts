"""Run two nested parallel interrupts, reject ambiguity, then resume by ID.

Requires the optional LangGraph dependency; no model or API key is used.
Run from the repository root: python examples/langgraph_parallel.py
"""

from importlib.metadata import version
import json
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from interaction_contracts import audit
from interaction_contracts.langgraph import snapshot_from_result


class State(TypedDict):
    answers: Annotated[list[tuple[str, str]], operator.add]


def run_demo() -> dict:
    def left(_state: State):
        answer = interrupt({"branch": "left", "question": "Choose left's value"})
        return {"answers": [("left", answer)]}

    def right(_state: State):
        answer = interrupt({"branch": "right", "question": "Choose right's value"})
        return {"answers": [("right", answer)]}

    child = (
        StateGraph(State)
        .add_node("left", left)
        .add_node("right", right)
        .add_edge(START, "left")
        .add_edge(START, "right")
        .add_edge("left", END)
        .add_edge("right", END)
        .compile()
    )
    graph = (
        StateGraph(State)
        .add_node("child", child)
        .add_edge(START, "child")
        .add_edge("child", END)
        .compile(checkpointer=InMemorySaver())
    )
    thread_id = "interaction-contracts-parallel-demo"
    config = {"configurable": {"thread_id": thread_id}}
    first = graph.invoke({"answers": []}, config)
    snapshot = snapshot_from_result(first, thread_id=thread_id, revision="form-1")
    assert len(snapshot["pending"]) == 2, "Expected two visible pending interrupts"

    # Validate this attempted input only. Never dispatch the ambiguous command.
    ambiguous = audit([
        snapshot,
        {"type": "resume", "thread_id": thread_id, "revision": "form-1",
         "value": "an answer with no target"},
    ])
    assert ambiguous.status == "fail", "Ambiguous routing must fail the contract"

    # A UI binds each submitted value to the ID of the question it displayed.
    answers = {
        item.id: f"{item.value['branch']}-choice" for item in first["__interrupt__"]
    }
    mapped = audit([
        snapshot,
        {"type": "resume", "thread_id": thread_id, "revision": "form-1",
         "answers": answers},
    ])
    assert mapped.status == "pass", "Mapped input must pass before dispatch"
    final = graph.invoke(Command(resume=answers), config)
    assert sorted(final["answers"]) == [
        ("left", "left-choice"), ("right", "right-choice")
    ]
    assert not final.get("__interrupt__"), "Both branches must finish"
    return {
        "langgraph_version": version("langgraph"),
        "pending_interrupts": len(snapshot["pending"]),
        "ambiguous_resume": ambiguous.status,
        "mapped_resume": mapped.status,
        "completed_branches": len(final["answers"]),
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2))
