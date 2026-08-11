# ReAct 循环实现

## 什么是 ReAct

ReAct（Reasoning and Acting）是一种 Agent 思考范式，核心思路是让模型在行动之前先输出推理，行动后把结果观察回来再推理，形成闭环。

三个步骤循环往复：

```
Reasoning（推理）→ Acting（行动）→ Observation（观察）→ Reasoning ...
```

这个范式解决了纯推理模型（只会说不会做）和纯执行脚本（只会做不会想）之间的断层——Agent 既能思考，又能操作外部世界，还能根据结果调整下一步。

---

## 在这个项目里的对应关系

ReAct 的三个步骤直接映射到 Anthropic API 的响应结构上：

| ReAct 步骤 | API 对应 | 代码位置 |
|---|---|---|
| Reasoning | `response.content` 里的 `TextBlock` | `Agent.chat()` |
| Acting | `response.content` 里的 `ToolUseBlock`，`stop_reason == "tool_use"` | `Agent.chat()` L217 |
| Observation | 工具执行结果作为 `tool_result` 追加回 `history` | `Agent.chat()` L229-235 |

模型不是"先推理再行动"两个独立请求——同一次响应里，`TextBlock` 是推理，`ToolUseBlock` 是行动决策，两者可以同时出现在 `content` 列表里。

---

## 核心循环代码

完整实现在 [lingjiyidong/agent/__init__.py](../lingjiyidong/agent/__init__.py) 的 `Agent.chat()` 方法：

```python
for _ in range(_MAX_ITERATIONS):          # 最多 10 轮，防止无限循环
    response = self.client.messages.create(
        model=self.model,
        max_tokens=8192,
        system=system,
        messages=self.history,
        tools=_TOOL_SCHEMAS,
    )

    self.history.append({"role": "assistant", "content": response.content})

    # stop_reason 可能的值：
    #   "end_turn"       → 模型正常结束，直接返回给用户（最常见）
    #   "tool_use"       → 模型要调用工具，继续循环
    #   "max_tokens"     → 达到 max_tokens 上限，输出被截断，此处未单独处理
    #   "stop_sequence"  → 命中自定义停止串，此项目未设置 stop_sequences
    #   "pause_turn"     → 服务端工具单轮迭代上限，需重新发起请求（较新模型）
    #   "refusal"        → 安全拒绝，Opus 5 / Fable 5 等新模型才会出现
    if response.stop_reason != "tool_use":
        return response.content[0].text         # ← Reasoning 输出，最终答案

    # Acting：执行所有工具调用
    tool_results = []
    for block in response.content:
        if block.type != "tool_use":
            continue
        tool = TOOL_MAP.get(block.name)
        result = tool.func(**block.input) if tool else f"未知工具: {block.name}"
        result = _truncate_result(block.name, result)   # 截断过长的结果
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result,
        })

    # Observation：把工具结果写回历史，触发下一轮 Reasoning
    self.history.append({"role": "user", "content": tool_results})
```

循环结构极简：一个 `for`，一个 `if`，剩下的是工具 dispatch。

---

## 对话历史的结构演变

每轮循环后 `history` 的增长方式：

```
初始：
  [{"role": "user", "content": "帮我读一下 main.py"}]

第 1 轮后（模型决定调工具）：
  [
    {"role": "user",      "content": "帮我读一下 main.py"},
    {"role": "assistant", "content": [TextBlock("好的"), ToolUseBlock("read_file", ...)]},
    {"role": "user",      "content": [{"type": "tool_result", "content": "...文件内容..."}]},
  ]

第 2 轮后（模型不再调工具）：
  [
    ...
    {"role": "assistant", "content": [TextBlock("这个文件的入口是...")]},
  ]
  → 返回最终答案，退出循环
```

Observation 是以 `role: "user"` 的形式写回历史的——这是 Anthropic API 的协议要求，工具结果必须挂在 user 轮次里，模型才能在下一轮"看到"它。

---

## 两个关键的工程细节

**`_MAX_ITERATIONS = 10`**

硬上限，防止模型陷入无限工具调用循环。达到上限后返回错误提示而不是静默挂死。实际上绝大多数任务 3-5 轮就完成，这个上限是安全边界。

**`_truncate_result()`**

工具返回的 Observation 如果太长（比如读了一个几千行的文件），会把后续的 Reasoning 上下文挤掉，影响推理质量，也浪费 token。截断策略是保留头部 60% + 尾部 40%，而不是只截头，因为文件末尾往往也有关键信息。

不同工具设有不同的字符上限：

```python
_TOOL_MAX_CHARS = {
    "read_file": 4_000,
    "bash":      3_000,
    "grep_files": 2_000,
    "web_fetch":  5_000,
    ...
}
```

---

## 为什么不用框架

LangChain 的 `AgentExecutor` 内部也是同一个循环，但它被封装在多层抽象里——调试困难，行为不透明，出问题时很难定位到具体哪一轮出了什么错。

这个项目直接手写循环，ReAct 的每一步在代码里都清晰可见，也方便后续在循环中加入任何定制逻辑（比如打印中间推理、插入人工确认、限制特定工具的调用频率）。
