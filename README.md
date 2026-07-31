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
- **任务规划模式**：输入 `/plan <目标>`，Agent 自动拆解任务并逐步执行
- **工具调用**：读写文件、执行命令、搜索代码、抓取网页等
- **长期记忆**：自动保存重要信息，下次启动时加载
- **上下文压缩**：长对话自动压缩，不会撑爆 context window

## 项目架构

```
lingjiyidong/
├── main.py                  # CLI 入口，banner 渲染，输入循环
└── agent/
    ├── __init__.py          # Agent 主类，chat / execute 循环
    ├── planner.py           # Planner（目标拆解）+ PlanExecutor（逐步执行）
    ├── tools/
    │   └── __init__.py      # 所有内置工具定义（12 个工具）
    └── memory/
        ├── context.py       # ContextManager：对话压缩，防止 context 溢出
        └── longterm.py      # LongTermMemory：持久化记忆，存储于 .agent/memory.md
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

### 普通模式完整示例

**用户输入：** `帮我看看 _print_banner 函数在哪里定义的`

Agent 在发出第一次 API 请求前，完整的 prompt 如下：

```
─── system ────────────────────────────────────────────────

You are an expert coding agent. You help users read, write, edit, and reason about code.
You have access to tools for reading/writing files, running shell commands, searching code,
and fetching web content.
Always prefer targeted edits over rewriting entire files.
To explore code: use get_outline(path) to see a file's symbols, and find_symbol(name) to
locate definitions.

Working directory: /Users/you/projects/lingjiyidong
Project type: Python (pyproject.toml detected)
Top-level structure: README.md, dist, lingjiyidong, pyproject.toml, requirements.txt

Repo outline:
lingjiyidong/main.py:
   13: def _cjk_len(s)
   17: def _print_banner()
   82: def main()
lingjiyidong/agent/__init__.py:
   18: def _build_system_prompt(cwd)
  141: class Agent
  154: def chat(self, user_input)
  ...

Git branch: main

─── messages ──────────────────────────────────────────────

user: 帮我看看 _print_banner 函数在哪里定义的

─── tools ─────────────────────────────────────────────────

read_file, write_file, edit_file, create_directory,
list_files, grep_files, bash, web_search, web_fetch,
save_memory, get_outline, find_symbol
```

Claude 发现 repo outline 里已经直接列出了 `_print_banner` 在 `main.py:17`，**无需调用工具**，直接回复：

```
`_print_banner` 定义在 lingjiyidong/main.py 第 17 行。
```

**如果 outline 里没有**，Claude 会调用 `find_symbol`：

```
tool_use → find_symbol(name="_print_banner", directory=".")

tool_result → "lingjiyidong/main.py:17:def _print_banner():"

end_turn → "_print_banner 定义在 lingjiyidong/main.py 第 17 行。"
```

```
/plan <goal>
  │
  ▼
Planner.decompose()                     ← 单次 LLM 调用，无工具
  │  prompt: "将目标拆解为 3-8 个步骤，返回 JSON"
  │
  └─→ Plan { steps: [步骤1, 步骤2, ...] }
          │
          ▼
    PlanExecutor.execute()
          │
          ├── 打印任务概览
          │
          ├─ Step 1
          │    ├── 新建独立 Agent（复用父 Agent 的 system prompt，跳过重复扫描）
          │    ├── 构建 prompt：总目标 + 当前步骤描述
          │    └── 调用 Agent.chat() → 完整 Tool-Use 循环 → 记录结果
          │
          ├─ Step 2
          │    ├── 新建独立 Agent（history 不跨步骤累积）
          │    ├── 构建 prompt：总目标 + 当前步骤描述 + 上一步结果（前 200 字符）
          │    └── 调用 Agent.chat() → 完整 Tool-Use 循环 → 记录结果
          │
          ├─ Step N ...
          │
          └── 汇总：全部完成 → 输出摘要 / 部分失败 → 列出失败步骤
```
