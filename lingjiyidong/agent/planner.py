import json
from dataclasses import dataclass, field
from enum import Enum
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
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    attempts: int = 0


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)

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
- 返回 JSON 格式：{{"steps": ["步骤1", "步骤2", ...]}}

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
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            steps = [Step(index=i, description=desc) for i, desc in enumerate(data["steps"])]
        except Exception:
            steps = [Step(index=0, description=goal)]
        return Plan(goal=goal, steps=steps)


_MAX_RETRIES = 2
_MAX_STEPS = 20


class PlanExecutor:
    def __init__(self, agent: Any):
        self.agent = agent

    def execute(self, plan: Plan) -> str:
        print(f"\n{plan.summary()}\n")

        step_count = 0
        seen_descriptions: set[str] = set()

        for step in plan.steps:
            if step_count >= _MAX_STEPS:
                return "已达到最大步骤数，任务终止。"

            if step.description in seen_descriptions:
                return f"检测到循环：步骤 '{step.description}' 重复执行，任务终止。"
            seen_descriptions.add(step.description)

            step.status = StepStatus.RUNNING
            print(f"[{step.index + 1}/{len(plan.steps)}] {step.description}")

            context = self._build_context(plan, step)

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
                    step.result = result
                    step.status = StepStatus.DONE
                    print(f"  完成: {result[:80]}{'...' if len(result) > 80 else ''}\n")
                    break
                except Exception as e:
                    if step.attempts >= _MAX_RETRIES:
                        step.status = StepStatus.FAILED
                        step.result = str(e)
                        print(f"  失败（{_MAX_RETRIES} 次尝试）: {e}\n")
                    else:
                        print(f"  第 {step.attempts} 次失败，重试中: {e}")

            step_count += 1

        if plan.is_complete():
            return self._final_summary(plan)

        failed = [s.description for s in plan.failed_steps()]
        return f"任务部分完成。失败步骤：{', '.join(failed)}"

    def _build_context(self, plan: Plan, current: Step) -> str:
        completed = [s for s in plan.steps if s.status == StepStatus.DONE]
        parts = [f"总目标：{plan.goal}", f"当前步骤：{current.description}"]
        if completed:
            prev = completed[-1]
            parts.append(f"上一步结果：{prev.result[:200]}")
        return "\n".join(parts)

    def _final_summary(self, plan: Plan) -> str:
        results = "\n".join(
            f"步骤 {s.index + 1}: {s.result[:100]}" for s in plan.steps
        )
        return f"所有步骤完成。\n\n{results}"
