![](resources/banner.png)

**Tianshu** (天枢, *Celestial Pivot*) is the first star of the Big Dipper — the fixed point around which the northern sky revolves.

Name the goal. Tianshu thinks, plans, and executes — step by step, until done.

**枢运北斗，御动九天。**

说出目标，天枢自行思考、拆解、执行，直至完成。

## Installation

```bash
make install
```

## Setup

Create a `.env` file in your project root:

```bash
OPENAI_API_KEY=your_api_key
AGENT_MODEL=gpt-5               # optional; defaults to gpt-5; prefix "claude" → Anthropic, otherwise → OpenAI
TAVILY_API_KEY=your_tavily_key  # optional, for web_search
```

The local proxy (`http://localhost:6655/openai/v1`) is used as the OpenAI-compatible endpoint. Set `OPENAI_API_KEY` to authenticate.

## Usage

```bash
make run
```

Launches the full-screen TUI. Type a goal and press Enter; Ctrl+C to quit.

Prefix `/skill-name` to invoke a named skill directly, e.g. `/code_review`.

## Features

- **TUI**: full-screen terminal interface (Textual), keyboard-driven
- **Chat mode**: multi-turn conversation with full context
- **Auto plan**: the model decides whether to decompose complex tasks — no manual trigger needed
- **Skills**: predefined step sequences for common workflows; auto-matched by semantics or triggered manually with `/skill-name`
- **Tool use**: read/write files, run shell commands, search code, fetch web pages
- **Long-term memory**: important information persisted across sessions; two scopes — global (`~/.tianshu/memory/`) for cross-project preferences, project-level (`<cwd>/.tianshu/memory/`) for project-specific facts; index injected into system prompt, full content loaded on demand
- **Context compression**: long conversations are compressed automatically to stay within the context window
- **Permission control**: a rule engine classifies every tool call as auto-allow / ask / deny before it runs; read-only tools and safe shell commands pass through, writes and command execution ask for confirmation, catastrophic commands (`rm -rf /`, fork bombs, `mkfs`, …) are blocked
- **Hooks**: PreToolUse / PostToolUse extension points — register Python callbacks or declare shell commands in `.tianshu/hooks.json` to rewrite arguments, block calls, transform results, or run side effects (format, audit, notify) without touching the core loop
- **Multi-provider**: Anthropic and OpenAI-compatible backends behind a unified provider interface

## Architecture

![Agent Flow](resources/agent-flow.drawio.svg)

### Single Agent Request Flow

![Agent Request Flow](resources/agent-request-flow.drawio.svg)

## Project Structure

```
tianshu/
├── main.py                    # TUI entry point (Textual app)
└── agent/
    ├── __init__.py            # re-exports Agent
    ├── core.py                # Agent class: chat / execute / execute_skill, system prompt builder
    ├── provider/
    │   ├── __init__.py        # make_provider() factory
    │   ├── base.py            # Provider ABC: call / summarize / complete
    │   ├── anthropic_provider.py
    │   └── openai_provider.py
    ├── planner/
    │   ├── __init__.py        # re-exports Planner, PlanExecutor, Replanner
    │   └── core.py            # goal decomposition, parallel execution, dynamic replanning
    ├── tools/
    │   ├── __init__.py        # re-exports TOOLS, TOOL_MAP, Tool
    │   └── core.py            # 14 built-in tools
    ├── skills/
    │   ├── __init__.py        # re-exports Skill, SkillLoader
    │   ├── core.py            # Skill dataclass + SkillLoader (load / match / find)
    │   └── builtin/           # built-in skill YAMLs
    └── memory/
        ├── __init__.py        # re-exports ContextManager, LongTermMemory
        ├── context.py         # ContextManager: conversation compression
        └── longterm.py        # LongTermMemory: MEMORY.md index + per-entry files; global + project scopes
```

### Chat mode

```
user input
  │
  ▼
Agent.chat()
  │
  ├─ System prompt (built once at init, reused across turns)
  │    ├── base instructions (role, tool-use principles)
  │    ├── project type detection (pyproject.toml / package.json / go.mod …)
  │    ├── top-level directory listing (up to 40 entries)
  │    ├── repo outline (all def / class with line numbers)
  │    ├── git status & branch
  │    └── long-term memory index (global ~/.tianshu/memory/MEMORY.md + project .tianshu/memory/MEMORY.md)
  │
  ├─ ContextManager.prepare()
  │    ├── step 1: spill oversized tool results to .tianshu/tool-results/
  │    ├── step 2: archive message middle to .tianshu/transcripts/ when count ≥ 50
  │    ├── step 3: replace seen tool results with disk refs if chars > 400K
  │    └── step 4: LLM compact as last resort
  │
  └─ Tool-use loop (up to 20 iterations)
       │
       ├── API call (history + tool schemas)
       │
       ├── stop_reason = end_turn ──→ return text to user
       │
       └── stop_reason = tool_use
            ├── file ops      read_file / write_file / edit_file / create_directory
            ├── code nav      get_outline / find_symbol / grep_files / list_files
            ├── shell         bash
            ├── web           web_search / web_fetch
            └── memory        save_memory / delete_memory / read_memory
                 │
                 └── tool result appended to history → next iteration
```

### Plan mode (auto-triggered or `/skill-name`)

```
user input
  │
  ├─ starts with / → SkillLoader.find() → exact skill match → Agent.execute_skill()
  │
  └─ plain input → Agent.execute()
       │
       ├─ SkillLoader.match() (semantic match) → hit → use predefined steps directly
       │
       └─ Planner.decompose() (LLM decides)
            ├─ needs_plan=false → Agent.chat() (plain conversation)
            └─ needs_plan=true  → Plan { steps: [...] }
                    │
                    ▼
              PlanExecutor.execute()
                    │
                    ├── create shared workspace .tianshu/workspace/<uuid>/
                    │
                    ├─ scheduling loop (ThreadPoolExecutor, max_workers=4)
                    │    └── find all steps whose depends_on are satisfied, submit concurrently
                    │
                    ├─ each step (independent Agent)
                    │    ├── new Agent instance (reuses parent system prompt)
                    │    ├── prompt: overall goal + current step + prerequisite output file paths
                    │    └── Agent.chat() → full tool-use loop → record result
                    │
                    ├─ on step failure → Replanner.replan()
                    │    └── LLM decides: skip / retry (new description) / replace remaining steps
                    │
                    └── summary: all done → output summary / partial failure → list failed steps
```

---

## Agent iteration plan

### Phase 1: Basic agent (complete)

**What:** custom tool system, ReAct loop, memory management.

**Why:** a useful agent needs three primitives — access to the outside world (tools), multi-step reasoning (ReAct loop), and cross-turn memory (short-term compression + long-term persistence). None of these is optional: without tools the agent can only talk, without a loop it cannot handle complex tasks, without memory every conversation starts from zero.

**Key components:**
- `tools/core.py`: 14 built-in tools (file I/O, code navigation, bash, web, memory)
- `agent/core.py`: ReAct loop, up to 20 iterations
- `memory/context.py`: short-term memory — 4-step compression pipeline (spill to disk → archive middle → demote seen results → LLM summary)
- `memory/longterm.py`: long-term memory — `MEMORY.md` index + per-entry files; global (`~/.tianshu/memory/`) + project (`.tianshu/memory/`) scopes

---

### Phase 2: Plan mode (complete)

**What:** Planner (goal decomposition) + PlanExecutor (per-step independent execution).

**Why:** the ReAct loop has two hard limits. First, `_MAX_ITERATIONS = 20` — complex tasks need far more than 20 tool calls. Second, history grows unboundedly — a multi-step task inflates context until the model "forgets" earlier work. Plan mode solves this with divide-and-conquer: one LLM call decomposes the goal into 3–8 steps, then each step runs in its own Agent with its own history.

**Key components:**
- `Planner.decompose()`: single LLM call, outputs a step list
- `PlanExecutor.execute()`: instantiates an independent Agent per step, passes the previous step's result as context

---

### Phase 3: Multi-agent orchestration (complete)

**What:** parallel execution (DAG dependencies), shared workspace, dynamic replanning.

**Why:** phase 2 steps were strictly sequential — even independent steps had to wait for each other. Real tasks (e.g. "analyze 5 files and summarize") can run concurrently. Also, summaries are too small to share large artifacts between steps. And abandoning the entire plan on a single failure is too costly — the model should decide how to recover.

**New capabilities:**
- **Parallel execution**: `Step.depends_on` defines a DAG; `ThreadPoolExecutor` runs all steps whose dependencies are satisfied concurrently
- **Shared workspace**: each plan creates `.tianshu/workspace/<uuid>/`; steps write files there and downstream steps read them by path
- **Dynamic replanning**: on step failure, `Replanner` asks the LLM to `skip` / `retry` / `replace` remaining steps (up to 3 times)

---

### Phase 4: Auto plan triggering and skills (complete)

**What:** remove the explicit `/plan` command; introduce a reusable skill system.

**Why removing `/plan`:** it exposes an internal implementation detail. Complexity judgment is the model's responsibility, not the user's. `Planner` now includes a `needs_plan` field in its prompt — the model returns `None` for simple tasks (falls back to `chat()`) or a `Plan` for complex ones, transparently.

**Why skills:** high-frequency workflows (e.g. "run tests and fix failures", "review recent changes") had to be re-planned from scratch every time, wasting tokens and risking inconsistent plans. Skills are predefined step sequences stored as YAML — they can be auto-matched when the user's input is semantically close, or triggered precisely with `/skill-name`.

**Key components:**
- `Skill`: pure data class with `name`, `description`, `steps`
- `SkillLoader`: loads `builtin/*.yaml`; provides `find()` (exact match) and `match()` (single LLM semantic match)
- `Planner.decompose()`: tries skill match first; falls back to LLM planning; returns `None` if `needs_plan=false`
- `Agent.execute_skill()`: converts Skill → Plan → PlanExecutor

---

### Phase 5: Optimization (complete)

#### O1: Context compression — 4-step pipeline

**What:** replaced the single-step LLM summarization with a four-step compression pipeline.

| Step | When | What happens |
|------|------|--------------|
| 1. `_tool_result_budget` | always | Latest tool batch total > 100K chars → spill oversized individual results (> 20K) to `.tianshu/tool-results/` |
| 2. `_snip_compact` | always | Message count ≥ 50 → archive the middle to `.tianshu/transcripts/`, replace with a one-line marker |
| 3. `_micro_compact` + `_fit_tool_results` | total chars > 400K | Replace seen old tool results with disk references; keep most recent 3 intact |
| 4. `_compact_history` | still over after step 3 | LLM summarization as last resort; entire history → one summary message |

**Key design shift — demotion not deletion:** every piece of data lands on disk before it leaves context. The model sees a path reference and can retrieve it via `read_file` if needed.

#### O2: Long-term memory — index + per-entry files, two scopes

**What:** replaced the single append-only `memory.md` with a structured two-tier memory system.

| Aspect | Old | New |
|--------|-----|-----|
| Storage | `<project>/.agent/memory.md` (append-only) | `MEMORY.md` index + one file per entry |
| Scopes | project-only | global (`~/.tianshu/memory/`) + project (`<cwd>/.tianshu/memory/`) |
| Entry format | plain text | frontmatter (`name` / `type` / `description`) + body |
| Types | none | `fact` / `decision` / `preference` / `error` |
| Tools | `save_memory(note)` | `save_memory(slug, type, description, content, scope)` / `delete_memory` / `read_memory` |
| Injection | full file contents | index only; full entry loaded on demand via `read_memory` |

#### O3: Multi-provider abstraction + TUI

**What:** unified provider interface supporting Anthropic and OpenAI-compatible backends; replaced web UI + FastAPI server with a native terminal UI (Textual).

**Provider layer:** `Provider` ABC with `call()` / `summarize()` / `complete()`. `make_provider(model)` selects by model name prefix — `"claude-*"` → `AnthropicProvider`, everything else → `OpenAIProvider` (default). All internal LLM calls go through this interface; the default model is `gpt-5`.

**TUI:** `TianshuApp` (Textual) replaces the `input()` REPL and the FastAPI + browser UI. The agent runs in a thread worker; tool calls stream into the log panel in real time via the `_emit` callback.

---

### Phase 6: Permission and hooks (complete)

**What:** a permission rule engine and a PreToolUse / PostToolUse hook layer, both wrapping the single tool-execution site.

**Why:** an agent that can run arbitrary `bash` and overwrite any file is unsafe in any real environment — it needs a deterministic gate in front of destructive actions. And "always format after editing" / "never write `.env`" / "audit every shell command" are rules that must fire every time, not depend on the model remembering. Both are deterministic concerns that belong outside the probabilistic loop.

**Execution order** (inside `Agent._dispatch_tool`):

```
PreToolUse hooks → permission.check → tool.func → PostToolUse hooks
```

**Permission** (`agent/permission/core.py`):
- `PermissionEngine.check(tool, input) → (Decision, reason)`, first matching rule wins
- `Decision`: `ALLOW` (auto) / `ASK` (confirm) / `DENY` (never)
- defaults: read-only tools and safe shell auto-allow; writes and command execution ask; catastrophic bash denied
- UI integration: on `ASK` the server emits `permission_request`, the browser confirms, the response unblocks the agent worker thread via a thread-safe queue

**Hooks** (`agent/hooks/core.py`):
- `HookRegistry`: register Python callbacks (`@reg.pre(matcher)` / `@reg.post(matcher)`); pre hooks may rewrite input or block, post hooks may rewrite the result or run side effects
- `load_shell_hooks`: shell-command hooks declared in global and project `.tianshu/hooks.json`, following the Claude Code protocol (JSON over stdin, exit 2 blocks, stdout JSON rewrites)
- hook failures and timeouts are caught and degrade to no-op — they never crash the agent loop

Both cover sub-agents automatically: every step routes through the same `_dispatch_tool` and inherits the parent's permission callback and hook registry.
