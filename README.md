# 灵机一动 (lingjiyidong)

灵光乍现，代码自成。*Spark once. Code forever.*

## 安装

```bash
pip install lingjiyidong
```

## 使用

需要先设置 Anthropic API Key：

```bash
export ANTHROPIC_API_KEY=your_key
```

然后直接启动：

```bash
lj
```

## 功能

- **对话模式**：直接与 Agent 对话，支持多轮上下文
- **任务规划模式**：输入 `/plan <目标>`，Agent 自动拆解任务、并行执行、动态重规划
- **工具调用**：读写文件、执行命令、搜索代码、抓取网页等
- **长期记忆**：自动保存重要信息，下次启动时加载
- **上下文压缩**：长对话自动压缩，不会撑爆 context window

## 项目架构

```
lingjiyidong/
├── main.py                    # CLI 入口，banner 渲染，输入循环
└── agent/
    ├── __init__.py            # re-export Agent
    ├── core.py                # Agent 主类，chat / execute，system prompt 构建
    ├── planner/
    │   ├── __init__.py        # re-export Planner, PlanExecutor, Replanner
    │   └── core.py            # 目标拆解、并行执行、动态重规划
    ├── tools/
    │   ├── __init__.py        # re-export TOOLS, TOOL_MAP, Tool
    │   └── core.py            # 所有内置工具定义（12 个工具）
    └── memory/
        ├── __init__.py        # re-export ContextManager, LongTermMemory
        ├── context.py         # ContextManager：对话压缩，防止 context 溢出
        └── longterm.py        # LongTermMemory：持久化记忆，存储于 .agent/memory.md
```

### 普通对话模式

```
用户输入
  │
  ▼
Agent.chat()
  │
  ├─ System Prompt（Agent 初始化时构建一次，后续复用）
  │    ├── 基础指令（角色、工具使用原则）
  │    ├── 项目类型检测（pyproject.toml / package.json / go.mod …）
  │    ├── 顶层目录结构（最多 40 个条目）
  │    ├── Repo Outline（所有 def / class 的行号和签名）
  │    ├── Git Status & Branch
  │    ├── 长期记忆（.agent/memory.md，若存在）
  │    └── 对话摘要（超过压缩阈值后由 ContextManager 生成）
  │
  ├─ ContextManager.maybe_compress()
  │    └── 估算 token 数，超过 60k 时
  │         └── LLM 将旧消息压缩为摘要，history 只保留最近 4 条
  │
  └─ Tool-Use 循环（最多 10 次迭代）
       │
       ├── API Call（携带 history + 12 个工具 schema）
       │
       ├── stop_reason = end_turn ──→ 返回文本给用户
       │
       └── stop_reason = tool_use
            ├── 文件操作   read_file / write_file / edit_file / create_directory
            ├── 代码导航   get_outline / find_symbol / grep_files / list_files
            ├── 命令执行   bash
            ├── 网络       web_search / web_fetch
            └── 记忆       save_memory
                 │
                 └── 工具结果按类型截断后追加到 history，进入下一次迭代
```

### Plan 模式（`/plan <目标>`）

```
/plan <goal>
  │
  ▼
Planner.decompose()                     ← 单次 LLM 调用，无工具
  │  返回 JSON：steps[{desc, depends_on[]}]
  │
  └─→ Plan { steps: [步骤1, 步骤2, ...] }
          │
          ▼
    PlanExecutor.execute()
          │
          ├── 创建共享工作空间 .agent/workspace/<uuid>/
          │
          ├─ 调度循环（ThreadPoolExecutor，max_workers=4）
          │    └── 按 depends_on DAG 找出"所有依赖已完成"的步骤，并发提交
          │
          ├─ 每个步骤（独立 Agent）
          │    ├── 新建独立 Agent（复用父 Agent 的 system prompt）
          │    ├── 构建 prompt：总目标 + 当前步骤描述 + 已完成步骤的输出文件路径
          │    └── 调用 Agent.chat() → 完整 Tool-Use 循环 → 记录结果
          │
          ├─ 步骤失败时 → Replanner.replan()
          │    └── LLM 决策：skip（跳过）/ retry（重试）/ replace（替换描述后重试）
          │
          └── 汇总：全部完成 → 输出摘要 / 部分失败 → 列出失败步骤
```

---

## Agent 迭代计划

### 第一阶段：基础 Agent（已完成）

**实现内容：** 自定义工具系统、ReAct 范式、Memory 管理。

**为什么这样设计：** 一个有用的 Agent 需要三个基本能力——访问外部世界（工具）、多步推理（ReAct 循环）、跨轮次记忆（短期压缩 + 长期持久化）。这三者缺一不可：没有工具 Agent 只能空谈，没有循环 Agent 无法拆解复杂任务，没有记忆每次对话都从零开始。

**核心组件：**
- `tools/core.py`：12 个内置工具（文件读写、代码导航、bash、网络、记忆）
- `agent/core.py`：ReAct 循环，最多 10 次迭代，工具结果按类型截断防止 context 溢出
- `memory/context.py`：短期记忆，对话超过 60k token 时自动压缩为摘要
- `memory/longterm.py`：长期记忆，持久化到 `.agent/memory.md`，每次启动时注入 system prompt

---

### 第二阶段：Plan 模式（已完成）

**实现内容：** Planner（目标拆解）+ PlanExecutor（按步骤独立执行）。

**为什么需要 Plan 模式：** ReAct 循环有两个硬限制。第一，`_MAX_ITERATIONS = 10`——复杂任务需要的工具调用次数远超 10 步。第二，history 会无限累积——多步任务会让 context 越来越长，超出限制或导致模型"遗忘"前面的工作。Plan 模式的解法是"分而治之"：先用一次 LLM 调用把目标拆解成 3–8 个步骤，然后每个步骤都启动一个独立的 Agent，拥有独立的 history，互不干扰，互不污染。

**核心组件：**
- `Planner.decompose()`：单次调用，输出步骤列表
- `PlanExecutor.execute()`：为每个步骤实例化独立 Agent，串行执行，步骤结果（前 200 字符）作为下一步 context

---

### 第三阶段：多 Agent 编排（已完成）

**实现内容：** 并行执行（DAG 依赖）、共享工作空间、动态重规划。

**为什么需要多 Agent 编排：** 第二阶段的步骤是严格串行的——即使步骤之间没有依赖关系，也只能一个接一个等待。真实任务（如"分析 5 个文件并汇总"）中，独立的子任务完全可以并发执行。此外，串行传递的 200 字符摘要远不足以在步骤间共享大量数据（如生成的代码、分析报告）。最后，某个步骤失败时直接放弃整个计划代价过高，需要模型介入决策如何恢复。

**新增能力：**
- **并行执行**：`Step.depends_on` 定义 DAG，`ThreadPoolExecutor` 并发执行所有"依赖已满足"的步骤
- **共享工作空间**：每次 `/plan` 创建 `.agent/workspace/<uuid>/`，步骤写文件到此，后续步骤通过文件路径读取，突破 200 字符限制
- **动态重规划**：步骤失败时调用 `Replanner`，由 LLM 决策 `skip`（跳过）/ `retry`（重试）/ `replace`（修改描述后重试），最多重规划 3 次

---

### 第四阶段：自动 Plan 触发与 Skills

**目标：** 去掉需要用户手动输入 `/plan` 的设计缺陷，引入可复用的 Skill 系统。

**为什么去掉手动 `/plan`：** `/plan` 是内部实现细节，不应暴露给用户。复杂度判断是模型的职责，而不是用户的。改为让 `Planner` 在 prompt 里加入 `needs_plan` 字段，由模型自己决定是否需要拆解——返回 `null` 则直接走普通 `chat()`，返回 `Plan` 则走 `PlanExecutor`，用户无感知。

**为什么需要 Skills：** 某些高频操作（如"运行测试并修复失败"、"检查代码风格"）每次都要从头规划，浪费 token 也容易出错。Skills 是预定义的步骤序列，存储为 YAML，既可以在用户输入与 skill 描述语义匹配时自动命中，也可以通过 `/skill-name` 手动精确触发。

**核心组件：**
- `Skill`：纯数据类，含 `name`、`description`、`steps`
- `SkillLoader`：加载 `builtin/*.yaml`，提供 `find()`（精确匹配）和 `match()`（单次 LLM 语义匹配）
- `Planner.decompose()`：入口处先做 skill 语义匹配，命中则直接返回预定义步骤；未命中则 LLM 规划，模型判断 `needs_plan=false` 时返回 `None`
- `Agent.execute_skill()`：封装 Skill → Plan → PlanExecutor 的转换，`main.py` 无需感知内部结构
