from conftest import FakeProvider, build_agent

from tianshu.agent.planner.core import Plan, PlanExecutor, Planner, Step, StepStatus


def _decompose(raw):
    return Planner(FakeProvider(complete_text=raw), client=None, model="x").decompose("goal")


def test_no_plan_returns_none():
    assert _decompose('{"needs_plan": false, "steps": []}') is None


def test_plan_with_steps():
    plan = _decompose(
        '{"needs_plan": true, "steps": ['
        '{"desc": "a", "depends_on": []},'
        '{"desc": "b", "depends_on": [0]}]}')
    assert plan is not None
    assert [s.description for s in plan.steps] == ["a", "b"]
    assert plan.steps[1].depends_on == [0]


def test_needs_plan_true_but_empty_steps_is_none():
    assert _decompose('{"needs_plan": true, "steps": []}') is None


def test_invalid_json_returns_none():
    assert _decompose("the model rambled with no json") is None


def test_noisy_wrapping_is_parsed():
    plan = _decompose('ok here:\n{"needs_plan": true, "steps": [{"desc": "x"}]}\nbye')
    assert plan is not None and plan.steps[0].description == "x"


# --- Plan helpers ---

def test_plan_completion_and_pending():
    plan = Plan(goal="g", steps=[Step(0, "a"), Step(1, "b")])
    assert not plan.is_complete()
    assert len(plan.pending_steps()) == 2
    for s in plan.steps:
        s.status = StepStatus.DONE
    assert plan.is_complete()


# --- executor guards (no sub-agents spawned on this path) ---

def test_duplicate_steps_aborted(tmp_path):
    agent = build_agent(FakeProvider(), tmp_path)
    executor = PlanExecutor(agent)
    plan = Plan(goal="g", steps=[Step(0, "same"), Step(1, "same")])
    out = executor.execute(plan)
    assert "Duplicate step detected" in out
