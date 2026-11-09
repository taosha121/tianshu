# Tianshu vs OpenCode:Agent 设计对比

对照 `mypro/opencode`(TypeScript / Bun monorepo)的 agent 实现,分析 tianshu 的优缺点与可借鉴点。

> 两者体量不在一个量级:tianshu 的 agent 层约 2300 行 Python、单进程、内存态;opencode 是数千文件的 monorepo,基于 Effect(Service/Layer/Fiber)+ SQLite 事件溯源,面向多进程、多端(CLI/TUI/桌面)、可崩溃恢复。所以对比的意义不是"追平",而是看清:**哪些差距是架构定位带来的(不必追),哪些是 tianshu 可以低成本补上的真实短板。**

---

## 一、总览

| 维度 | Tianshu | OpenCode |
|------|---------|----------|
| 主循环 | `Agent.chat()` 单层 for,≤20 轮,看 `stop_reason` | 两层 while(drain/runStep),step 上限后强制文本收尾 |
| 工具分发 | 同步、**串行** | `Effect.forEach(concurrency:"unbounded")` **并发** |
| 工具错误 | `tool.func` 抛异常需调用方处理 | 一律转错误结果回传模型自愈,不抛 |
| Provider | ABC,非流式,一次性返回 | 流式一等公民,70×50 provider×protocol 矩阵 |
| 上下文压缩 | 四步(budget/snip/micro/summary),字符估算 | ceiling/reserve 预算 + native/summary/precompute 三路 + 降级收缩 |
| 会话持久化 | **无**(history 纯内存) | SQLite + 执行 claim 崩溃恢复 + blob 去重 |
| Subagent | `invoke_subagent`,串行,纯文本返回 | 独立 session,结构化 `<subagent>` 返回,background 真并行 |
| 后台任务 | **无**(bash 同步阻塞 30s) | Job 服务 + synthetic 消息唤醒父循环 |
| Permission | ALLOW/ASK/DENY,规则硬编码,无头默认放行 | allow/ask/deny,wildcard ruleset,无头显式降级(默认拒) |
| Hooks | pre/post + shell JSON 协议 | 进程内 Effect 模块,transform + 多事件 hook |
| Skill | LLM 语义匹配 → 线性步骤转 Plan | LLM 读 description 自主 → skill 工具注入上下文 |
| MCP | **无** | stdio/HTTP,server 名命名空间,协议协商 |
| Cron | **无** | 完整 cron,SQLite,leader 选举,幂等 |
| Goal loop | 无 | 无(两者都不做语义终局校验) |

---

## 二、Tianshu 的优点

这些不是"比 opencode 强",而是轻量定位下做对的取舍:

1. **主循环极简、可读**。[chat()](../tianshu/agent/core.py#L221) 一个 for 循环就是全部控制流,`stop_reason` 直接 match,新人 10 分钟能看懂。opencode 的 drain/runStep + Outcome.$match + inbox 插队,是为持久化/插队/恢复付出的复杂度代价,tianshu 不背这个包袱。
2. **Provider 抽象干净**。[Provider](../tianshu/agent/provider/base.py#L20) 只有 `call/summarize/complete` 四个方法,`ProviderResponse`/`ToolCall` 两个 dataclass,anthropic 与 openai 两套实现清爽。对标 opencode 的 70×50 路由矩阵,tianshu 的抽象对一个自用框架完全够用。
3. **停止条件同样不搞 goal-loop**。这一点和 opencode 一致——"完成"= 模型不再调工具。没有引入独立判断器是对的,省掉一类难调的失败模式。
4. **四步上下文压缩方向正确**。[ContextManager](../tianshu/agent/memory/context.py) 的 budget→snip→micro→summary 和 opencode 的"降级优先于丢弃"思路一致,是 roadmap O1 已经补齐的部分。
5. **权限/hooks 已覆盖 subagent**。两者都通过统一 dispatch 路径 + 继承机制让子 agent 自动受约束,没有旁路。

---

## 三、真实短板(建议补)

按性价比排序,都是 tianshu 定位下值得做、且不必引入重型架构的:

### 1. 工具并发 + 错误不抛异常 —— ROI 最高
现状 [chat()](../tianshu/agent/core.py#L284-L300) 对一个 step 的多个 tool_call **串行** for 循环执行,且 `tool.func(**inp)` 异常会直接冒泡。opencode 两点都做对了:
- 同 step 多工具 `asyncio.gather` 并发,结果按调用顺序回填。模型一次要求读 3 个文件时收益明显。
- 工具找不到 / 入参非法 / 执行抛错,一律**转成错误结果字符串回传给模型**让它自愈,绝不抛出中断 loop。tianshu 现在只有 "Unknown tool" 和权限拒绝转了结果,真正的 `tool.func` 异常没兜住。

这两点改动小、鲁棒性收益大,建议优先。

### 2. 后台任务(对应 roadmap 第 9 节,P2)
bash 同步阻塞 30s 是硬伤。opencode 的模式值得照搬:`bash(background=true)` 立即返回 task_id,独立线程/fiber 跑完后,把结果作为一条**合成消息**注入 history 唤醒下一轮;配一条统一约定"完成会自动通知,**禁止轮询**,没事就结束回合"。tianshu 单进程用 `threading` + 一个待注入队列即可,不需要 Job 服务那套。

### 3. 会话持久化 + 崩溃恢复
history 纯内存,进程一崩全丢。但**不要**照搬 opencode 的 SQLite + blob 去重 + event sourcing。最低成本方案就够:
- history 落盘为 `.tianshu/sessions/<id>.jsonl`,每轮 append;
- 借鉴 opencode 的**执行 claim**(store.ts 一列时间戳 + listSuspended):一个标记位记录"turn 进行中",重启后发现未释放的 claim 即可提示 resume。性价比极高,几十行。

> 注意:这才是 roadmap 里被废弃的"Plan 持久化"真正该解决的问题——该落盘的是会话 history / todos,不是已退化为 skill 专用的 Plan。

### 4. token 估算:测量锚点 + 增量字符估
现状纯字符数估算([_estimate_chars](../tianshu/agent/memory/context.py))。opencode 的混合法零成本显著提准:**以最近一条同 provider 的 assistant 响应里 provider 真实回报的 token 为锚点,其后的消息才按字符估**。provider 已经把真实用量回传了,不用白不用。

### 5. Permission 无头降级策略
现状无头(无 `_permission_cb`)时 ASK **默认放行**([core.py:328](../tianshu/agent/core.py#L328))。opencode 的做法更稳:无头时用一套 "Unattended" 规则结算,**允许的放行,其余一律 deny**,而不是无脑放行。一旦将来接入 cron / CI 场景,"没人应答就默认拒"比"默认放行"安全得多。配合 roadmap 第六节"留待后续"的 `.tianshu/permission.json` 用户规则一起做。

---

## 四、架构定位差异(不必追)

这些是 opencode 作为大型多端 monorepo 的必需品,对 tianshu 这种单进程自用框架是过度设计:

- **Effect Layer/Scope/Fiber 全家桶、Bus + projector 事件溯源**:Python 普通 async + 直接写文件/库即可。
- **70 provider × 50 protocol 路由矩阵、native(provider 端)压缩 + 可 replay 加密 window**:强依赖 provider 能力,tianshu 用 LLM 文本摘要足矣。
- **precompute 预计算摘要 + prompt-cache 对齐 + 缓存寿命判断**:纯为降延迟/命中缓存,逻辑复杂、边际收益低。
- **MCP 连接池跨目录共享 + leader 选举 + OAuth Integration + elicitation→Form**:多进程/多 location 协同设施。真要做 MCP(roadmap 第 12 节),只抄**命名空间 = server 名前缀 + 同名遮蔽**即可。
- **schedule 的 SQLite leader 租约 + doorbell latch + 夏令时回拨**:真做 cron(第 10 节)用 `apscheduler` 或简单 asyncio 循环即可;只借鉴 **message-id 幂等 + 失败退避**的思路,保证重启不重复触发。
- **插件 npm 包解析 / 多入口(server/gui/tui/rpc) / GUI 热重载**:与 TUI/桌面端强绑定,tianshu 现有 shell hooks 已够。

---

## 五、几个值得单独拿出来的设计思路

opencode 里有几个**思路零成本、实现可轻量**的点,tianshu 可以直接吸收:

1. **Skill 不做匹配引擎**。opencode 不用关键词/正则/独立匹配器,而是把所有 skill 的 `name/description` 作为 `<available_skills>` 注入系统提示,给一个 `skill(id)` 工具,路由完全交给模型;skill 本身不是线性步骤脚本,而是"把指令 + 资源文件清单注入上下文,之后模型用普通工具自由执行"。

   这正好回应 roadmap 第五节的痛点:tianshu 现在**每次 `execute()` 都发一次 LLM 做 skill matching**(即使没注册任何 skill),且 skill 被硬转成线性 Plan。改成"注入 available 列表 + skill 工具"后,匹配成本归零,skill 也不再受线性步骤束缚。**这是第五节改进方向里最彻底的一个,值得认真考虑。**

2. **Subagent 结构化返回 + 后台唤醒**。opencode 子 agent 是独立 session,返回 `<subagent sessionID=... state=...>…</subagent>` 结构化块,且 background 子 agent 完成后用合成消息唤醒父循环。tianshu 的 [invoke_subagent](../tianshu/agent/core.py#L353) 已有工具白名单(对标到位),缺的是**结构化返回**和**真并行**(roadmap 第八节已列为"留待后续")。

3. **Max-steps 优雅收尾**。tianshu 撞到 20 轮上限直接返回 "Maximum iterations reached"([core.py:312](../tianshu/agent/core.py#L312)),是生硬截断。opencode 到达 step 上限时**注入一条提示 + 把 `tool_choice` 设成 `none`**,强制模型用纯文本把当前进展收尾。小改动,体验提升明显。

---

## 六、落地优先级建议

结合现有 roadmap(✅ = 已落地,2026-11-09):

| 优先级 | 事项 | 对应 | 成本 |
|--------|------|------|------|
| ✅ P0 | 工具错误转结果不抛异常 | 新增 | 极低 |
| ✅ P1 | 同 step 多工具并发(只读并发 + 写殿后) | 新增 | 低 |
| ✅ P1 | Skill 改为注入式(弃 LLM 匹配 + 线性 Plan) | 第 5 节 | 中 |
| P1 | Max-steps 优雅收尾(tool_choice=none) | 新增 | 极低 |
| P2 | 后台任务(bash background + 合成消息) | 第 9 节 | 中 |
| P2 | 会话 history 落盘 + 执行 claim 恢复 | (替代废弃的 Plan 持久化) | 低 |
| P2 | token 估算混合法 | O1 增强 | 极低 |
| P3 | Permission 无头降级 + 用户规则文件 | 第 6 节遗留 | 低 |
| P3 | Subagent 结构化返回 + 真并行 | 第 8 节遗留 | 中 |
| P3+ | MCP / Cron | 第 10/12 节 | 中(只抄轻量核心) |
