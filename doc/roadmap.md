# Tianshu 开发路线图

对标 [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 17 章 harness 特性，逐一分析 tianshu 的现状。

---

## 一、已实现，但设计存在问题

### 1. Context Compact（对应 s08）

**现状**：`ContextManager` 基于字符数估算 token（3.5 chars/token），超过阈值后压缩旧消息，只保留最近 `min_window=4` 条。

**问题**：
- 4 条消息窗口太激进，tool_use + tool_result 各算一条，实际保留的可用上下文极少
- 压缩 prompt 产出的 summary 结构固定（Key Facts + Summary），但没有区分"可能还要用到"和"纯历史"的消息
- learn-claude-code s08 设计了四步压缩（budget / snip / micro / summary），tianshu 只有最后一步
- token 估算不准确会导致不该压缩时提前压缩，或该压缩时错过时机

**learn-cc s08 四步压缩详解**（`ContextCompactor.prepare()` 的执行顺序）：

**第一步：`tool_result_budget`**
只处理最新一批 tool_result（最后一条 user 消息）。按内容大小降序遍历，把超过 `LARGE_RESULT_CHAR_LIMIT=30000` chars 的结果 spill 到 `.task_outputs/tool-results/<tool_use_id>.txt`，原位替换成 `<persisted-output>Full output: <path>\nPreview: ...</persisted-output>`。目的是确保这批刚收到的结果不会直接炸掉 context，在送入模型前先瘦身。

**第二步：`snip_compact`**
消息条数达到 `trigger_messages=50` 时触发。保留头部 3 条（系统上下文）和尾部 `target_messages=30` 条，把中间部分整体归档到 `.transcripts/transcript_<uuid>.jsonl`，原位替换成一条 `"[N messages archived at <path>]"` 标记。不做 LLM 摘要，纯结构性归档，速度快、无额外 API 成本。

**第三步：`micro_compact` + `fit_tool_results`**
前两步完成后，如果整体 chars 仍超过 `CONTEXT_CHAR_LIMIT=50000`：
- `micro_compact`：遍历历史中所有已被模型"看过"的 tool_result（排除最新一批 unseen 的和最近 `KEEP_RECENT_RESULTS=3` 条），把内容 > 120 chars 的全部 spill 到磁盘，原位替换成 `"[Earlier tool result saved at <path>]"`。
- `fit_tool_results`：如果 micro_compact 后还超限，再对剩余结果按大小降序，把内容替换成 1000 chars 的 preview + 磁盘路径，直到降到 `target=CONTEXT_CHAR_LIMIT * 0.8`。

**第四步：`compact_history`（LLM 摘要）**
前三步都做完还超限时触发。把当前完整消息列表写入 transcript 文件，然后发一次 LLM 调用生成摘要，把整个 history 替换成一条摘要消息，格式为：`"[Compacted]\nCurrent user request: ...\nConversation summary: ...\nFull transcript: <path>"`。这是最重的一步，也是最后的兜底。

**其他入口**：
- agent 主动调用 `compact` 工具 → 直接触发第四步
- API 返回 `prompt_too_long` → `reactive_compact`：只摘要最近 `KEEP_RECENT_MESSAGES=5` 条之前的历史，保留最新 5 条完整消息，最多重试一次

**与 tianshu 现状的对比**：tianshu `ContextManager` 只有第四步（LLM 摘要），且 `min_window=4` 相当于把第三步的 `KEEP_RECENT_RESULTS=3` 和 `KEEP_RECENT_MESSAGES=5` 都压缩到了最激进的值，还缺少前三步的"降级而非丢弃"机制。

**改进方向**：
- `min_window` 改为动态值，至少保留当前 turn 完整的 tool_use 链
- 增加第一步：对最新一批 tool_result 中超过阈值的结果 spill to disk，而不是截断
- 增加第二步：消息条数触发时先做无损归档，再判断是否需要 LLM 摘要
- token 估算换成 anthropic SDK 提供的 `count_tokens` API

---

### 2. 长期记忆（对应 s09）✅

**完成时间**：2026-11-04

**变更文件**：
- `tianshu/agent/memory/longterm.py` — 完全重写
- `tianshu/agent/tools/core.py` — `save_memory` 参数重设计，新增 `delete_memory` / `read_memory`
- `tianshu/agent/memory/context.py` — 路径 `.agent/` → `.tianshu/`
- `tianshu/agent/core.py` — skip dirs、`_KEY_ARG` 同步更新

**实现内容**：

| 方面 | 旧设计 | 新设计 |
|------|--------|--------|
| 存储路径 | `<project>/.agent/memory.md` | `~/.tianshu/memory/`（全局）+ `<project>/.tianshu/memory/`（项目级） |
| 存储结构 | 单文件追加 | `MEMORY.md` 索引 + 每条记忆一个独立文件 |
| 记忆文件格式 | 纯文本 | frontmatter（name/type/description）+ 正文 |
| 类型 | 无 | `fact` / `decision` / `preference` / `error`（frontmatter 字段） |
| 工具 | `save_memory(note)` | `save_memory(slug, type, description, content, scope)` / `delete_memory(slug, scope)` / `read_memory(slug, scope)` |
| 注入方式 | 全量注入 | 只注入两级 `MEMORY.md` 索引（`[Global]` + `[Project]` 分节）；agent 按需用 `read_memory` 读具体内容 |

**目录约定（`.agent` → `.tianshu`）**：

- 项目级运行时数据：`<project>/.tianshu/tool-results/`、`<project>/.tianshu/transcripts/`
- 项目级记忆：`<project>/.tianshu/memory/`（项目专属，如"此项目优先用中文"）
- 全局记忆：`~/.tianshu/memory/`（跨项目，如用户偏好）

对标 Claude Code 的 `.claude/`（项目级）+ `~/.claude/`（用户级）结构。

**暂未实现（留待后续）**：
- 写入时 LLM 筛选门控（判断是否值得记）
- 相关性召回（按需加载，需 embedding）
- Consolidation（定期去重合并，可配合 cron）

---

### 3. 任务系统 / Planner（对应 s05、s10）

**现状**：`Planner` LLM 调用决定是否拆分，`Plan` / `Step` 保存在内存中，`PlanExecutor` 用 `ThreadPoolExecutor` 并行执行依赖就绪的 step。

**问题**：
- Plan 完全在内存中，进程退出即丢失，无法恢复
- Planner 对每个请求都发一次 LLM 调用来判断 `needs_plan`，即使是简单问题也有额外开销
- `StepStatus` 只有四个值，没有"等待外部依赖"状态
- `depends_on` 只支持同一 Plan 内的步骤，无法跨 session 依赖
- learn-claude-code s10 的 `TaskRecord` 写磁盘、有 `blockedBy` 字段、支持多 agent 共享任务池

**改进方向**：
- Plan 序列化到 `.tianshu/plans/<id>.json`，进程重启后可恢复
- 增加 `blocked` 状态，用于等待后台任务完成
- Planner 判断逻辑前移到规则层（字数、关键词），只有模糊情况才调 LLM

---

### 4. Subagent（对应 s06）

**现状**：`PlanExecutor` 为每个 step 创建新的 `Agent` 实例，共享父 agent 的 `_system_prompt` 和 `cwd`，通过 `workspace` 目录传递文件。

**问题**：
- Subagent 和 Planner 强耦合，不能独立召唤一个 subagent 去做任意子任务
- 父子 agent 之间只能通过文件传递结果，没有结构化 output
- subagent 的 history 是全新的，但 system_prompt 和父 agent 共用，不够隔离
- 没有 subagent 级别的工具限制（子任务可能只需要只读工具）

**改进方向**：
- 提供独立的 `spawn_subagent(goal, tools=None)` 工具，让 agent 在 chat 中主动召唤子 agent
- subagent 返回结构化结果（JSON schema），而非纯文本
- 支持为 subagent 指定工具白名单

---

### 5. Skill 系统（对应 s07）

**现状**：YAML 定义 skill，`SkillLoader.match()` 用 LLM 做语义相似度判断，skill 本质是步骤列表，执行时转成 Plan。

**问题**：
- 每次 `execute()` 都发 LLM 调用做 skill matching，即使没有任何 skill 注册
- skill 只支持线性步骤，无法有条件分支
- skill steps 是自然语言描述，无法直接调用工具或其他 skill
- skill match 提示词要求"80% 语义相似度"，但 LLM 判断不稳定

**改进方向**：
- 先用关键词 / 前缀做快速过滤，匹配失败再 LLM
- skill 支持 `trigger` 字段（正则或关键词），减少不必要的 LLM 调用
- 考虑支持 skill 调用其他 skill 的嵌套

---

## 二、完全缺失的特性

### 6. Permission 系统（对应 s03）— 高优先级

**描述**：在执行破坏性工具（bash、write_file、edit_file）前，经过规则引擎判断是否需要用户确认。

**现状**：完全没有。`bash` 工具可以执行任意命令，`write_file` 可以覆盖任意文件，无任何拦截。

**应有设计**：
- `PermissionRule` 列表：按工具名、参数模式定义"自动允许 / 需要确认 / 永远拒绝"
- 高风险模式举例：`rm -rf`、写入 `.env`、`git push --force`、修改系统目录
- 与 UI 集成：server 侧发出 `permission_request` 事件，前端弹确认框，用户回应后继续

---

### 7. Hooks（对应 s04）— 高优先级

**描述**：在工具调用前后插入扩展逻辑，不修改核心循环。

**现状**：完全没有。工具调用是直接 `tool.func(**block.input)` 调用，无任何扩展点。

**应有设计**：
- `PreToolUse` hook：调用前可以修改参数、记录日志、触发权限检查
- `PostToolUse` hook：调用后可以转换结果、写审计日志、触发通知
- hook 注册表：`HookRegistry.register(tool_name, phase, fn)`
- 和 Permission 系统配合：permission check 可以实现为 `PreToolUse` hook

---

### 8. TodoWrite 工具（对应 s05）

**描述**：agent 在开始复杂任务时，先用 `todo_write` 工具写下任务列表，执行过程中随时更新状态，给用户可见的进度。

**现状**：tianshu 有 `Plan` / `Step`，但这是 planner 自动生成的，agent 自己无法主动管理 todo list；也没有暴露给用户的可视化进度。

**应有设计**：
- 新增 `todo_write(todos: list)` 工具，agent 可主动调用
- todo 状态：pending / in_progress / completed
- 每次 todo 变化 emit 事件，前端实时显示任务列表
- 与 Plan 系统的关系：Plan 是 planner 自动拆分的，TodoWrite 是 agent 自己决策的，两者并行存在

---

### 9. 后台任务（对应 s11）

**描述**：把慢操作（如长时间 bash 命令）放到后台线程执行，agent 继续其他工作，后台完成后注入通知消息到下一个 turn。

**现状**：`bash` 工具是同步阻塞的，超时默认 30s，长时间命令会卡住整个 agent loop。

**应有设计**：
- `bash_background(command, task_id)` 工具：立即返回 `task_id`，命令在线程池中执行
- 完成后向 history 注入 `[Background task <task_id> completed: <output>]` 消息
- agent 可以在后续 turn 中通过 `task_id` 查询状态

---

### 10. Cron 调度器（对应 s12）

**描述**：支持按时间触发任务，不需要用户手动触发。

**现状**：完全没有。

**应有设计**：
- `cron_create(schedule, prompt, recurring)` 工具
- 调度状态持久化到 `.tianshu/cron.json`
- server 进程中有调度线程，按时将 prompt 注入 agent

---

### 11. Agent Teams（对应 s13）

**描述**：多个持久化 agent 作为队友，通过共享任务池认领和执行任务，可以在不同 worktree 中工作互不干扰。

**现状**：PlanExecutor 中的 subagent 是临时的、无状态的，用完即弃，不是持久队友。

**应有设计**：
- 持久化 agent 有 name，可以跨 session 通信
- 共享任务池（磁盘持久化），agent 原子性地认领 `PENDING` 任务
- 每个任务绑定独立的工作目录（worktree），防止多 agent 冲突

---

### 12. MCP 插件（对应 s14）

**描述**：通过 Model Context Protocol 接入外部工具，动态扩展工具池，不修改核心代码。

**现状**：所有工具硬编码在 `tools/core.py` 的 `TOOLS` 列表中。

**应有设计**：
- `MCPClient` 连接外部 MCP server（stdio / SSE / HTTP）
- 工具发现：启动时从 MCP server 拉取工具列表，合并到 `TOOL_SCHEMAS`
- 命名空间隔离：外部工具加前缀（如 `mcp_<server>_<tool>`）
- 配置文件：`.tianshu/mcp.json` 声明要连接的 MCP server

---

### 13. Workflow Runtime（对应 s16）

**描述**：把固定编排形状（DAG / pipeline）写成脚本，可序列化、可续跑（journal 机制）。

**现状**：Plan 是单次执行的，没有 journal，无法断点续跑。

**应有设计**：
- workflow 脚本描述 DAG，可以有条件分支
- `journal.json` 记录每个节点的执行状态和输出
- 续跑时已完成的节点直接复用缓存结果

---

### 14. Goal Loop（对应 s17）

**描述**：每次 agent 准备结束时，由独立的"判断器"检查目标是否真正达成，决定是否继续循环。

**现状**：agent loop 只看 `stop_reason`，不做目标验证。

**应有设计**：
- `GoalChecker`：接受 goal 描述和当前状态，返回 `{achieved: bool, reason: str}`
- agent 在 `end_turn` 后先经过 GoalChecker，未达成则继续
- 设置最大续跑次数和不可能完成时的 fallback

---

## 三、已完成的优化（Phase 5: Optimization）

### O1. Context Manager 四步压缩 ✅

**完成时间**：2026-11-02

**变更文件**：
- `tianshu/agent/memory/context.py` — 完全重写
- `tianshu/agent/core.py` — 移除 `_truncate_result`，更新调用点，加 `prompt_too_long` 兜底

**实现内容**：

| 步骤 | 方法 | 触发条件 | 行为 |
|------|------|----------|------|
| 1 | `_tool_result_budget` | 每次 API 调用前，无条件 | 最新一批 tool_result 总量超 100K chars 时，把单个 > 20K 的结果 spill 到 `.tianshu/tool-results/` |
| 2 | `_snip_compact` | 每次 API 调用前，无条件 | 消息条数 ≥ 50 时，把中间段归档到 `.tianshu/transcripts/`，原位替换为归档标记 |
| 3 | `_micro_compact` + `_fit_tool_results` | 总 chars > 400K 时 | 把已见的旧 tool_result（保留最近 3 条）替换为磁盘引用；仍超限则对剩余结果压缩到 1K preview |
| 4 | `_compact_history` | 步骤 3 后仍超限 | LLM 摘要全部历史，替换为一条 summary 消息 |

**额外**：API 返回 `prompt_too_long` 时触发 `reactive_compact`（保留最近 5 条，摘要其余），最多重试一次。

**与旧设计的核心差异**：旧设计 `min_window=4` 固定截断（丢弃数据）；新设计基于语义位置判断 unseen/seen，旧结果降级到磁盘而非丢弃。

---

## 四、优先级建议

| 优先级 | 特性 | 理由 |
|--------|------|------|
| P0 | Permission 系统 | 安全兜底，没有它 tianshu 在任何真实环境中都是危险的 |
| P0 | Hooks | Permission 和后续所有扩展点的基础，应先建好再往上加 |
| P1 | ~~Memory 改造~~ | ✅ 已完成（见第二节）|
| P1 | Plan 持久化 | 长任务稳定性，现在进程崩一次全丢 |
| P1 | TodoWrite 工具 | 直接影响用户体验，前端已有任务面板可以承接 |
| P2 | 后台任务 | 解锁长时间命令（测试、构建、安装依赖） |
| P2 | ~~Context Compact 改进~~ | ✅ 已完成（O1）|
| P3 | Cron 调度器 | 独立特性，不阻塞其他开发 |
| P3 | MCP 插件 | 扩展性，有 Hooks 后实现更自然 |
| P4 | Agent Teams | 复杂度高，依赖 Plan 持久化和 Permission 先就绪 |
| P4 | Workflow Runtime | 需要 Plan 持久化作为基础 |
| P4 | Goal Loop | 在其他机制稳定后再做收尾 |
