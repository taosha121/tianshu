# 多 Agent 编排实现计划

## Phase 1：并行执行

无依赖关系的步骤同时跑，而不是排队。

- [ ] `Step` 增加 `depends_on: list[int]` 字段
- [ ] `Planner.decompose()` prompt 改为同时输出依赖关系，返回格式：`{"steps": [{"desc": "...", "depends_on": []}]}`
- [ ] `PlanExecutor.execute()` 改用 `concurrent.futures.ThreadPoolExecutor`，就绪的步骤（依赖全部 DONE）提交到线程池，轮询推进

**完成标志**：相互独立的步骤并行跑，有依赖的等前置完成再启动。

---

## Phase 2：共享工作空间

Agent 之间通过文件系统共享状态，不再只靠 200 字字符串传递结果。

- [ ] 任务开始时在 `.agent/workspace/` 下创建本次任务的子目录
- [ ] `Step` 增加 `outputs: list[str]` 字段，记录该步骤写出了哪些文件路径
- [ ] `_build_context()` 改为把前置步骤的 `outputs` 路径传给当前 Agent，让它自己去读
- [ ] 最终 summary 改为汇报 workspace 里的产物文件列表

**完成标志**：Agent1 写出的文件，Agent2 可以直接读取，不再依赖字符串摘要。

---

## Phase 3：动态重规划

步骤失败或结果偏离目标时，重新生成后续计划，而不是硬重试。

- [ ] 新增 `Replanner` 类，接收当前 plan + 失败信息，输出修订后的剩余步骤列表
- [ ] 失败时不再直接重试，先询问 Replanner：重试 / 跳过 / 换方案
- [ ] `Plan` 增加 `replanning_count` 字段和上限（默认 2 次），防止无限重规划

**完成标志**：任务遇到障碍时能自我调整，不在错误路径上反复撞墙。

---

## Phase 4：角色分工（待评估）

不同类型的步骤派给不同配置的专用 Agent。Phase 1-3 完成后再决定是否推进。

- [ ] `Step` 增加 `role: str` 字段（`"coder"` / `"tester"` / `"reviewer"`）
- [ ] Planner 拆步骤时同时输出每步的 role
- [ ] `PlanExecutor` 维护 role → Agent 配置映射，按 role 实例化不同 Agent（不同 system prompt、不同工具集）

**完成标志**：写代码的 Agent 带完整工具集，review 的 Agent 只有只读工具。
