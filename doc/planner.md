# Planner 与 Executor 设计

## 为什么需要 Plan 模式

ReAct 循环有两个硬限制：单次最多 10 轮工具调用，且 history 随对话增长。对于"写一个带测试的 REST API"这类复杂任务，10 轮不够用，history 里堆满中间过程也会干扰模型判断。

Plan 模式的解法：把大任务拆成若干步骤，每步启动一个独立的 Agent 实例，各自只看与自己相关的上下文。

用户通过 `/plan <goal>` 触发，普通对话仍走 ReAct 循环。

---

## 数据结构

```
Plan
├── goal: str              # 用户的原始目标
└── steps: list[Step]
        ├── index: int         # 步骤序号（从 0 开始）
        ├── description: str   # 一句话描述要做什么
        ├── status: StepStatus # PENDING / RUNNING / DONE / FAILED
        ├── result: str        # 执行结果（完成后填入）
        └── attempts: int      # 已尝试次数
```

`StepStatus` 是枚举，四个状态构成步骤的生命周期：

```
PENDING → RUNNING → DONE
                 ↘ FAILED（重试次数耗尽）
```

---

## Planner：目标 → 步骤列表

实现在 [tianshu/agent/planner.py](../tianshu/agent/planner.py) 的 `Planner` 类。

只做一件事：调用一次 API，让模型把目标拆成 3-8 个步骤，返回 JSON。

```python
_PLAN_PROMPT = """
你是一个任务规划器。将下面的目标拆解为有序步骤列表。
返回 JSON 格式：{"steps": ["步骤1", "步骤2", ...]}
目标：{goal}
"""
```

拿到响应后从文本里提取 JSON（`text.find("{")` 到 `text.rfind("}")`），构造 `Step` 列表。JSON 解析失败时 fallback 为把整个 goal 当成一步，不崩溃。

这是一次**不带工具的普通 API 调用**，不走 ReAct 循环，`max_tokens=1024` 够用。

---

## PlanExecutor：驱动步骤执行

实现在同文件的 `PlanExecutor` 类。

### 执行流程

```
打印初始 plan 状态图
  ↓
for 每个步骤:
    标记 RUNNING，打印进度
    构造上下文（总目标 + 当前步骤 + 上一步结果）
    while attempts < MAX_RETRIES(2):
        新建 step_agent，调用 chat()
        成功 → 记录结果，标记 DONE，break
        失败 → 打印错误，attempts++
    attempts 耗尽 → 标记 FAILED
  ↓
全部 DONE → 返回汇总
有 FAILED  → 返回失败步骤列表
```

### 每步的上下文

每个步骤只拿到三样东西：

```python
parts = [
    f"总目标：{plan.goal}",
    f"当前步骤：{current.description}",
    f"上一步结果：{prev.result[:200]}",   # 只有前 200 字符
]
```

信息故意精简——让模型注意力集中在当前步骤，不被其他步骤的中间过程干扰。

### 每步是独立的 Agent 实例

```python
step_agent = Agent(
    model=self.agent.model,
    cwd=self.agent.cwd,
    _system_prompt=self.agent._system_prompt,   # 复用已构建好的 system prompt
)
result = step_agent.chat(context)
```

`history=[]` 全新开始，各步骤之间的工具调用互不干扰。`_system_prompt` 直接复用父 Agent 的，跳过重复的文件扫描和 git 调用（对大项目有明显性能差异）。

### 安全边界

两个防护：

- `_MAX_STEPS = 20`：总步骤数上限，防止 Planner 生成过多步骤
- `seen_descriptions`：检测重复步骤描述，避免 Planner 输出循环依赖时无限执行

---

## 完整调用链

```
main.py
  └─ /plan <goal>
       └─ agent.execute(goal)
            ├─ Planner.decompose(goal)        # 一次 API 调用，返回 Plan
            └─ PlanExecutor.execute(plan)
                 └─ for step in plan.steps:
                      └─ step_agent.chat(context)   # 每步一个独立 Agent，走完整 ReAct 循环
```

---

## 当前局限

- **顺序执行**：步骤之间没有依赖声明，只能一个接一个，无法并行
- **结果传递粗糙**：只传上一步的 200 字字符串，Agent 之间没有共享工作空间
- **失败不重规划**：步骤失败只是原地重试，不会调整后续计划
- **角色单一**：所有步骤用的是完全相同的 Agent 配置，没有专用角色

这些局限是下一阶段多 Agent 编排要解决的问题，见 [multi_agent_todo.md](./multi_agent_todo.md)。
