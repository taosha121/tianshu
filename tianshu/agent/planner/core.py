import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from tianshu.agent._ctx import _step_ctx


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Step:
    index: int
    description: str
    depends_on: list[int] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    attempts: int = 0
    outputs: list[str] = field(default_factory=list)


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    replanning_count: int = 0

    def pending_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def failed_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def is_complete(self) -> bool:
        return all(s.status == StepStatus.DONE for s in self.steps)

    def summary(self) -> str:
        lines = [f"Goal: {self.goal}", ""]
        for s in self.steps:
            icon = {"pending": "○", "running": "→", "done": "✓", "failed": "✗"}[s.status.value]
            lines.append(f"  {icon} [{s.index + 1}] {s.description}")
            if s.result:
                lines.append(f"       result: {s.result[:100]}{'...' if len(s.result) > 100 else ''}")
        return "\n".join(lines)


_PLAN_PROMPT = """\
You are a task planner. Determine whether the goal below needs to be broken into multiple steps, then provide the result.

Criteria:
- Needs decomposition (needs_plan=true): task involves multiple independent operations, requires sequential steps, or is likely to need more than 5 tool calls
- No decomposition needed (needs_plan=false): simple Q&A, single-file operations, lookup tasks

If decomposition is needed:
- Keep step count between 3 and 8
- Each step description should be concise and clear — one sentence
- If a step must run after other steps, list those step indices (0-based) in depends_on; otherwise use an empty list
- Steps with no dependencies can run in parallel — minimize unnecessary dependencies

Return JSON:
- No decomposition: {{"needs_plan": false, "steps": []}}
- With decomposition: {{"needs_plan": true, "steps": [{{"desc": "step description", "depends_on": []}}, ...]}}

Goal: {goal}
"""


class Planner:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def decompose(self, goal: str) -> "Plan | None":
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

            if not data.get("needs_plan", True):
                return None

            steps = [
                Step(index=i, description=s["desc"], depends_on=s.get("depends_on", []))
                for i, s in enumerate(data["steps"])
            ]
            if not steps:
                return None
        except Exception:
            return None
        return Plan(goal=goal, steps=steps)


_MAX_RETRIES = 2
_MAX_REPLANNING = 2

_REPLAN_PROMPT = """\
You are a task planner. A step has failed during execution. Decide how to adjust the remaining plan.

Overall goal: {goal}

Completed steps:
{done_steps}

Failed step:
{failed_steps}

Decide how to continue and return JSON:
- Skip the failed step and continue: {{"action": "skip"}}
- Retry the failed step with a new description: {{"action": "retry", "desc": "new step description"}}
- Replace all remaining steps: {{"action": "replace", "steps": [{{"desc": "...", "depends_on": []}}, ...]}}
"""


class Replanner:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def replan(self, plan: Plan, failed_step: Step) -> dict:
        done = [s for s in plan.steps if s.status == StepStatus.DONE]
        done_text = "\n".join(f"  [{s.index + 1}] {s.description}: {s.result[:100]}" for s in done) or "none"
        failed_text = f"  [{failed_step.index + 1}] {failed_step.description}: {failed_step.result[:200]}"

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
            return {"action": "skip"}


class PlanExecutor:
    def __init__(self, agent: Any):
        self.agent = agent
        self._lock = threading.Lock()
        self.workspace = Path(agent.cwd) / ".agent" / "workspace" / uuid.uuid4().hex[:8]
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.replanner = Replanner(agent.client, agent.model)

    def execute(self, plan: Plan) -> str:
        print(f"\n{plan.summary()}\n")

        seen_descriptions: set[str] = set()
        for step in plan.steps:
            if step.description in seen_descriptions:
                return f"Duplicate step detected: '{step.description}'. Task aborted."
            seen_descriptions.add(step.description)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            def is_ready(step: Step) -> bool:
                return (
                    step.status == StepStatus.PENDING
                    and all(
                        plan.steps[i].status == StepStatus.DONE
                        for i in step.depends_on
                    )
                )

            def run_step(step: Step) -> None:
                _step_ctx.label = f"[{step.index + 1}]"
                with self._lock:
                    step.status = StepStatus.RUNNING
                    print(f"[{step.index + 1}/{len(plan.steps)}] Starting: {step.description}")

                context = self._build_context(plan, step)
                before = set(self.workspace.rglob("*"))

                while step.attempts < _MAX_RETRIES:
                    step.attempts += 1
                    try:
                        from tianshu.agent import Agent
                        step_agent = Agent(
                            model=self.agent.model,
                            cwd=self.agent.cwd,
                            _system_prompt=self.agent._system_prompt,
                        )
                        result = step_agent.chat(context)
                        after = set(self.workspace.rglob("*"))
                        new_files = [str(p) for p in (after - before) if p.is_file()]
                        with self._lock:
                            step.result = result
                            step.outputs = new_files
                            step.status = StepStatus.DONE
                            print(f"  ✓ [{step.index + 1}] Done: {result[:80]}{'...' if len(result) > 80 else ''}\n")
                            if new_files:
                                print(f"     Output files: {', '.join(new_files)}\n")
                        return
                    except Exception as e:
                        if step.attempts >= _MAX_RETRIES:
                            with self._lock:
                                step.status = StepStatus.FAILED
                                step.result = str(e)
                                print(f"  ✗ [{step.index + 1}] Failed ({_MAX_RETRIES} attempts): {e}\n")
                        else:
                            print(f"  [{step.index + 1}] Attempt {step.attempts} failed, retrying: {e}")

            submitted: set[int] = set()
            while True:
                with self._lock:
                    terminal = [
                        s for s in plan.steps
                        if s.status in (StepStatus.DONE, StepStatus.FAILED)
                    ]
                    if len(terminal) == len(plan.steps):
                        break

                    for step in plan.steps:
                        if step.status != StepStatus.FAILED:
                            continue
                        if plan.replanning_count >= _MAX_REPLANNING:
                            continue
                        plan.replanning_count += 1
                        print(f"  ↻ Replanning (attempt {plan.replanning_count}): step {step.index + 1} failed")
                        decision = self.replanner.replan(plan, step)
                        action = decision.get("action", "skip")

                        if action == "retry":
                            step.description = decision.get("desc", step.description)
                            step.status = StepStatus.PENDING
                            step.attempts = 0
                            step.result = ""
                            submitted.discard(step.index)
                            print(f"    -> Retry: {step.description}")

                        elif action == "replace":
                            base_index = len([s for s in plan.steps if s.status == StepStatus.DONE])
                            plan.steps = [s for s in plan.steps if s.status != StepStatus.PENDING]
                            step.status = StepStatus.DONE
                            new_steps = [
                                Step(
                                    index=base_index + i,
                                    description=s["desc"],
                                    depends_on=s.get("depends_on", []),
                                )
                                for i, s in enumerate(decision.get("steps", []))
                            ]
                            plan.steps.extend(new_steps)
                            print(f"    -> Replace remaining steps: {[s.description for s in new_steps]}")

                        else:
                            step.status = StepStatus.DONE
                            print(f"    -> Skip")

                    for step in plan.steps:
                        if step.index not in submitted and is_ready(step):
                            submitted.add(step.index)
                            futures[step.index] = pool.submit(run_step, step)

                if futures:
                    pending = {idx: f for idx, f in futures.items() if not f.done()}
                    if pending:
                        next(as_completed(pending.values()))

        if plan.is_complete():
            return self._final_summary(plan)

        failed = [s.description for s in plan.failed_steps()]
        return f"Task partially completed. Failed steps: {', '.join(failed)}"

    def _build_context(self, plan: Plan, current: Step) -> str:
        parts = [f"Overall goal: {plan.goal}", f"Current step: {current.description}"]
        parts.append(f"Shared workspace directory: {self.workspace} (read/write files here to share results between steps)")

        prior_outputs = []
        for i in current.depends_on:
            prior_outputs.extend(plan.steps[i].outputs)
        if prior_outputs:
            parts.append("Output files from prerequisite steps (available to read):\n" + "\n".join(f"  - {p}" for p in prior_outputs))

        return "\n".join(parts)

    def _final_summary(self, plan: Plan) -> str:
        lines = ["All steps completed.", ""]
        all_outputs = []
        for s in plan.steps:
            lines.append(f"Step {s.index + 1}: {s.result[:100]}")
            all_outputs.extend(s.outputs)
        if all_outputs:
            lines.append("\nOutput files:")
            lines.extend(f"  - {p}" for p in all_outputs)
        return "\n".join(lines)
