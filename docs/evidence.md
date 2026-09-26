# Motivation, evidence, and alternatives

Reviewed 2026-09-26. Public issue reports establish concrete failure modes, not prevalence or market size. This package contains original synthetic traces inspired by those reports; it does not contain private user logs or upstream issue code.

- [LangGraph #8579](https://github.com/langchain-ai/langgraph/issues/8579), opened 2026-08-09: a reporter describes an untargeted scalar accepted when one parent task contains two interrupted child branches. Our `parallel_ambiguous` fixture isolates the reply-binding contract. We do not claim to fix LangGraph or that every current version reproduces the reported bug.
- [LangGraph #6792](https://github.com/langchain-ai/langgraph/issues/6792), opened 2026-02-12: a report includes repeated surfaced interrupt IDs and re-executed task work. `duplicate_observation` covers repeated IDs only; this package does not detect re-executed side effects.
- [Paperclip #8179](https://github.com/paperclipai/paperclip/issues/8179), opened 2026-06-15: duplicate approval requests motivate the optional application-defined decision key. This is a warning, because equal keys may reflect deliberate application behavior.

Stale-revision, cross-thread, and duplicate-reply cases are additional contract scenarios authored for this package. They are not claimed as reproduced bugs in these upstream projects.

[LangGraph's native interrupt documentation](https://docs.langchain.com/oss/python/langgraph/interrupts) already describes ID-mapped resumes and stable thread identifiers. Use those mechanisms. This library makes a small set of expectations explicit in recorded fixtures and CI.

## Existing tools

| Tool | Existing focus | Position of this alpha |
|---|---|---|
| [AgentReplay](https://github.com/anzal1/agentreplay) | General trace protocol, replay, assertions | Small human-input case pack; potential future adapter, not a general replacement |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Durable execution, interrupts, checkpoints | Reads complete invoke results; owns no execution or persistence |
| [Ask or Assume](https://github.com/nedwards99/ask-or-assume) | Research into when coding agents seek clarification | Checks routing metadata, not question quality or model uncertainty |
| [KnowU-Bench](https://github.com/ZJU-REAL/KnowU-Bench) | Interactive personalized mobile-agent evaluation | No Android environment, user simulation, or leaderboard |

This is an engineering contribution and an adoption hypothesis. No scientific novelty, first-of-kind claim, user adoption, or performance advantage is established. The testable value proposition is whether a developer can convert a real reply-routing failure into a small repeatable regression with less integration work.

## What would validate usefulness?

1. Integrate with two independent application owners' redacted traces.
2. Record whether a known routing failure is correctly located and whether the corrected trace passes.
3. Count false alarms and integration time, with unchanged traces as controls.
4. Add a second framework only if a user supplies a real trace and expected lifecycle.

Question wording, user effort, and informed decision quality require a separate human evaluation. Successful schema checking is not evidence of improved Theory of Mind.
