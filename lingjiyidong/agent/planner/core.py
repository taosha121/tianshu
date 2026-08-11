import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Step:
    index: int
    description: str
    depends_on: list[int] = field(default_factory=list)  # 前置步骤的 index 列表，空列表表示无依赖可并行
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    attempts: int = 0
    outputs: list[str] = field(default_factory=list)  # 该步骤写出的文件路径列表，供后续步骤读取


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    replanning_count: int = 0  # 已重规划次数，达到上限后不再重规划直接退出

    def pending_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def failed_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def is_complete(self) -> bool:
        return all(s.status == StepStatus.DONE for s in self.steps)

    def summary(self) -> str:
        lines = [f"目标: {self.goal}", ""]
        for s in self.steps:
            icon = {"pending": "○", "running": "→", "done": "✓", "failed": "✗"}[s.status.value]
            lines.append(f"  {icon} [{s.index + 1}] {s.description}")
            if s.result:
                lines.append(f"       结果: {s.result[:100]}{'...' if len(s.result) > 100 else ''}")
        return "\n".join(lines)


_PLAN_PROMPT = """\
你是一个任务规划器。将下面的目标拆解为一个有序的步骤列表，每个步骤应该是一个独立、可执行的具体操作。

要求：
- 步骤数量控制在 3-8 步
- 每步描述简洁明确，一句话说清楚要做什么
- 如果某步骤必须在其他步骤完成后才能执行，在 depends_on 里填入那些步骤的序号（从 0 开始），否则填空列表
- 没有依赖关系的步骤可以并行执行，尽量减少不必要的依赖
- 返回 JSON 格式：{{"steps": [{{"desc": "步骤描述", "depends_on": []}}, ...]}}

目标：{goal}
"""


class Planner:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def decompose(self, goal: str) -> Plan:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": _PLAN_PROMPT.format(goal=goal)}],
        )
        text = response.content[0].text
        try:
            # 从模型输出中提取 JSON，模型可能在 JSON 前后输出多余文字
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            # depends_on 是可选字段，模型可能不输出，get 避免 KeyError
            steps = [
                Step(index=i, description=s["desc"], depends_on=s.get("depends_on", []))
                for i, s in enumerate(data["steps"])
            ]
        except Exception:
            # JSON 解析失败时退化为单步执行，保证不崩溃
            steps = [Step(index=0, description=goal)]
        return Plan(goal=goal, steps=steps)


_MAX_RETRIES = 2
_MAX_REPLANNING = 2

_REPLAN_PROMPT = """\
你是一个任务规划器。当前任务执行中有步骤失败，请根据情况调整后续计划。

总目标：{goal}

已完成的步骤：
{done_steps}

失败的步骤：
{failed_steps}

请决定如何继续，返回 JSON：
- 如果可以跳过失败步骤继续：{{"action": "skip"}}
- 如果需要重试失败步骤（换一种描述方式）：{{"action": "retry", "desc": "新的步骤描述"}}
- 如果需要替换后续所有步骤：{{"action": "replace", "steps": [{{"desc": "...", "depends_on": []}}, ...]}}
"""


class Replanner:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def replan(self, plan: Plan, failed_step: Step) -> dict:
        done = [s for s in plan.steps if s.status == StepStatus.DONE]
        done_text = "\n".join(f"  [{s.index + 1}] {s.description}：{s.result[:100]}" for s in done) or "无"
        failed_text = f"  [{failed_step.index + 1}] {failed_step.description}：{failed_step.result[:200]}"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": _REPLAN_PROMPT.format(
                goal=plan.goal,
                done_steps=done_text,
                failed_steps=failed_text,
            )}],
        )
        text = response.content[0].text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception:
            # 解析失败时默认跳过，避免卡死
            return {"action": "skip"}


class PlanExecutor:
    def __init__(self, agent: Any):
        self.agent = agent
        self._lock = threading.Lock()  # 保护多线程对 step.status / step.result 的并发写入
        # 每次任务创建独立的 workspace 子目录，避免多次任务互相污染
        self.workspace = Path(agent.cwd) / ".agent" / "workspace" / uuid.uuid4().hex[:8]
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.replanner = Replanner(agent.client, agent.model)

    def execute(self, plan: Plan) -> str:
        print(f"\n{plan.summary()}\n")

        # 前置校验：检测重复步骤描述，防止 Planner 输出循环依赖
        seen_descriptions: set[str] = set()
        for step in plan.steps:
            if step.description in seen_descriptions:
                return f"检测到循环：步骤 '{step.description}' 重复，任务终止。"
            seen_descriptions.add(step.description)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            def is_ready(step: Step) -> bool:
                # 就绪条件：自身是 PENDING 且所有前置步骤已 DONE
                return (
                    step.status == StepStatus.PENDING
                    and all(
                        plan.steps[i].status == StepStatus.DONE
                        for i in step.depends_on
                    )
                )

            def run_step(step: Step) -> None:
                with self._lock:
                    step.status = StepStatus.RUNNING
                    print(f"[{step.index + 1}/{len(plan.steps)}] 开始: {step.description}")

                context = self._build_context(plan, step)

                # 执行前快照 workspace，用于之后推断本步写出了哪些文件
                before = set(self.workspace.rglob("*"))

                while step.attempts < _MAX_RETRIES:
                    step.attempts += 1
                    try:
                        from lingjiyidong.agent import Agent
                        # 复用父 Agent 的 system prompt，跳过重复的文件扫描和 git 调用
                        step_agent = Agent(
                            model=self.agent.model,
                            cwd=self.agent.cwd,
                            _system_prompt=self.agent._system_prompt,
                        )
                        result = step_agent.chat(context)
                        # 对比执行后的 workspace，新增文件即为本步的输出
                        after = set(self.workspace.rglob("*"))
                        new_files = [str(p) for p in (after - before) if p.is_file()]
                        with self._lock:
                            step.result = result
                            step.outputs = new_files
                            step.status = StepStatus.DONE
                            print(f"  ✓ [{step.index + 1}] 完成: {result[:80]}{'...' if len(result) > 80 else ''}\n")
                            if new_files:
                                print(f"     产出文件: {', '.join(new_files)}\n")
                        return
                    except Exception as e:
                        if step.attempts >= _MAX_RETRIES:
                            with self._lock:
                                step.status = StepStatus.FAILED
                                step.result = str(e)
                                print(f"  ✗ [{step.index + 1}] 失败（{_MAX_RETRIES} 次尝试）: {e}\n")
                        else:
                            print(f"  [{step.index + 1}] 第 {step.attempts} 次失败，重试中: {e}")

            # 调度循环：持续扫描就绪步骤提交到线程池，有步骤失败时触发重规划
            submitted: set[int] = set()
            while True:
                with self._lock:
                    terminal = [
                        s for s in plan.steps
                        if s.status in (StepStatus.DONE, StepStatus.FAILED)
                    ]
                    if len(terminal) == len(plan.steps):
                        break

                    # 检查是否有失败步骤需要重规划
                    for step in plan.steps:
                        if step.status != StepStatus.FAILED:
                            continue
                        if plan.replanning_count >= _MAX_REPLANNING:
                            continue
                        plan.replanning_count += 1
                        print(f"  ↻ 重规划（第 {plan.replanning_count} 次）：步骤 {step.index + 1} 失败")
                        decision = self.replanner.replan(plan, step)
                        action = decision.get("action", "skip")

                        if action == "retry":
                            # 用新描述重置步骤，重新加入调度
                            step.description = decision.get("desc", step.description)
                            step.status = StepStatus.PENDING
                            step.attempts = 0
                            step.result = ""
                            submitted.discard(step.index)
                            print(f"    → 重试：{step.description}")

                        elif action == "replace":
                            # 移除所有 PENDING 步骤，替换为新的后续步骤
                            base_index = len([s for s in plan.steps if s.status == StepStatus.DONE])
                            plan.steps = [s for s in plan.steps if s.status != StepStatus.PENDING]
                            step.status = StepStatus.DONE  # 视为已处理，不再卡住调度
                            new_steps = [
                                Step(
                                    index=base_index + i,
                                    description=s["desc"],
                                    depends_on=s.get("depends_on", []),
                                )
                                for i, s in enumerate(decision.get("steps", []))
                            ]
                            plan.steps.extend(new_steps)
                            print(f"    → 替换后续步骤：{[s.description for s in new_steps]}")

                        else:  # skip
                            step.status = StepStatus.DONE  # 标记为 DONE 让后续步骤可以继续
                            print(f"    → 跳过")

                    for step in plan.steps:
                        if step.index not in submitted and is_ready(step):
                            submitted.add(step.index)
                            futures[step.index] = pool.submit(run_step, step)

                # as_completed 阻塞直到有任意 future 完成，避免忙等（busy-wait）
                if futures:
                    pending = {idx: f for idx, f in futures.items() if not f.done()}
                    if pending:
                        next(as_completed(pending.values()))

        if plan.is_complete():
            return self._final_summary(plan)

        failed = [s.description for s in plan.failed_steps()]
        return f"任务部分完成。失败步骤：{', '.join(failed)}"

    def _build_context(self, plan: Plan, current: Step) -> str:
        parts = [f"总目标：{plan.goal}", f"当前步骤：{current.description}"]
        parts.append(f"共享工作空间目录：{self.workspace}（可在此读写文件与其他步骤共享结果）")

        # 收集所有前置步骤的输出文件，告知当前 Agent 可以读取哪些文件
        prior_outputs = []
        for i in current.depends_on:
            prior_outputs.extend(plan.steps[i].outputs)
        if prior_outputs:
            parts.append("前置步骤产出的文件（可直接读取）：\n" + "\n".join(f"  - {p}" for p in prior_outputs))

        return "\n".join(parts)

    def _final_summary(self, plan: Plan) -> str:
        lines = ["所有步骤完成。", ""]
        all_outputs = []
        for s in plan.steps:
            lines.append(f"步骤 {s.index + 1}: {s.result[:100]}")
            all_outputs.extend(s.outputs)
        if all_outputs:
            lines.append("\n产出文件：")
            lines.extend(f"  - {p}" for p in all_outputs)
        return "\n".join(lines)
