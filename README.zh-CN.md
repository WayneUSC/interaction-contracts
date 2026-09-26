# Interaction Contracts

**检查 Agent 工作流中的人工回复是否对应正确的请求和上下文版本。**

[English](README.md) · [事件格式](docs/trace-format.md) · [LangGraph 示例](docs/langgraph.md)

两个并行分支分别问“采用方案 A 吗”和“发布草稿 B 吗”，界面只提交一个 `true`。系统到底把它交给了谁？用户修改了草稿，旧的确认是否仍被使用？

这个小型 Python 库把这些问题转成离线回归检查。核心仅依赖标准库，无须模型 API、联网或启动 Agent。输出 JSON、终端诊断和可接入 CI 的 JUnit XML。

**当前是实验性 alpha。** 示例轨迹是合成的故障与正确对照；另外已运行真实 LangGraph 嵌套并行图。没有声称经过生产用户验证，也不把它称为新的 ToM 科学基准。

## 运行

在仓库根目录，使用 Python 3.10 及以上版本：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
interaction-contracts examples/traces/parallel_ambiguous.jsonl
interaction-contracts examples/traces/parallel_mapped.jsonl --format json
```

第一条检查应失败并返回 `AMBIGUOUS_RESUME`；第二条按请求 ID 分别传入 `true` 和 `false`，应通过。项目尚未发布到 PyPI，需要从仓库安装。

检查覆盖并行回复歧义、未知请求 ID、旧版本回复、上下文更新后缺失快照，以及重复请求。`false`、`null`、`0` 都可以是有效的回复值。空日志和只有提问的日志返回“证据不足”，不会显示通过。

```bash
interaction-contracts my-trace.jsonl --strict --junit report.xml
python -m unittest discover -s tests -v
python -m pip install 'langgraph==1.2.12'
python examples/langgraph_parallel.py
```

退出码：`0` 通过；`1` 发现违约（严格模式也包含警告）；`2` 输入错误或证据不足。

## 使用边界

这是对**记录下来的交互路由**做检查。应用需要记录完整的待回复请求快照，并为上下文变化、新一轮问题或显式重试分配不可复用的交互版本。某些框架的连续问题会复用请求 ID，因此需要用新交互版本区分轮次。它不能从一句自然语言自动判断用户意图变化，也不负责身份认证、权限执行或真实副作用控制。

不要把“ID 对应正确”理解成“用户充分知情”或“任务成功”。下一步需要用真实应用的脱敏轨迹验证这些检查能否帮助开发者定位问题。参见[需求证据与竞品](docs/evidence.md)。

MIT 许可证。Wen Chen 发起，使用 AI 辅助实现与审查。
