# 灵机一动 Agent

一个从零手写的 AI Agent，不依赖 LangChain 等框架，逐阶段实现完整的 Agent 能力。

## 开发路线图

### Phase 1 — 基础对话（已完成）

- [x] 接入 Claude API
- [x] 管理多轮对话历史（messages 数组）
- [x] 基本 CLI 交互循环

---

### Phase 2 — Tool Use / ReAct 循环（已完成）

目标：让 Agent 能够调用工具并根据结果继续推理，这是 Agent 与普通 Chatbot 的本质区别。

- [x] 定义工具规范（JSON Schema）
- [x] 实现内置工具：计算器、读取文件、网络搜索
- [x] 接入 Claude 的 `tool_use` 机制
- [x] 手写 ReAct loop：LLM 决策 → 执行工具 → 结果回传 → 继续推理
- [x] 循环终止条件处理（max_iterations、无工具调用时停止）

---

### Phase 3 — 短期记忆 / Context 管理（已完成）

目标：防止长对话撑爆 context window，保持对话可用性。

- [x] 滑动窗口：超过 N 轮时丢弃最早的消息
- [x] 摘要压缩：用 LLM 将旧对话压缩为摘要注入 system prompt
- [x] Token 计数，接近限制时自动触发压缩

---

### Phase 4 — RAG + 长期记忆（已完成）

目标：给 Agent 接入私有知识库，并持久化重要信息。

- [x] 长期记忆：将重要信息持久化到 `.agent/memory.md`
- [x] 记忆检索：启动时自动加载注入 system prompt
- [x] `save_memory` 工具：Agent 主动调用保存关键信息
- [x] `list_files` 工具：列举目录文件（替代 embedding 检索）
- [x] `grep_files` 工具：全文搜索代码和文本

---

### Phase 5 — Planning（任务规划）

目标：处理需要多步骤的复杂任务。

- [ ] Task Decomposition：将复杂目标拆解为子任务列表
- [ ] Plan-and-Execute：先规划再逐步执行
- [ ] 子任务失败重试与错误恢复
- [ ] 循环检测（防止 Agent 陷入死循环）

---

### Phase 6 — Multi-Agent 编排

目标：多个 Agent 协作完成大型任务。

- [ ] Orchestrator Agent 负责任务分发
- [ ] Worker Agent 各司其职（搜索、写作、代码等）
- [ ] Agent 间通信协议
- [ ] 并行子任务执行

---

## 技术栈

| 层次 | 选型 |
|------|------|
| 语言 | Python 3.11+ |
| LLM | Claude API（Anthropic SDK） |
| 框架 | 无框架，手写核心循环 |
| 向量库 | ChromaDB（本地，零配置） |
| 持久化 | SQLite + JSON 文件 |

## 项目结构（目标）

```
lingjiyidong/
├── agent/
│   ├── __init__.py       # Agent 主类
│   ├── tools/            # 工具定义与执行
│   ├── memory/           # 记忆模块
│   └── planner.py        # 任务规划（Phase 5）
├── knowledge/            # RAG 文档库（Phase 4）
├── data/                 # 持久化数据
├── main.py               # CLI 入口
├── config.py             # 配置管理
└── requirements.txt
```

## 快速开始

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key
python main.py
```
