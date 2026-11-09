from tianshu.agent.skills.core import SkillLoader


def test_builtin_skills_load():
    names = {s.name for s in SkillLoader().all()}
    assert "code_review" in names


def test_find_returns_none_for_unknown():
    assert SkillLoader().find("does_not_exist") is None


def test_to_prompt_lists_skills():
    prompt = SkillLoader().to_prompt()
    assert "use_skill" in prompt
    assert "code_review" in prompt


def test_to_prompt_empty_without_skills(tmp_path):
    loader = SkillLoader()
    loader._skills = []  # simulate no registered skills
    assert loader.to_prompt() == ""


def test_use_skill_returns_instructions():
    from tianshu.agent.tools.core import use_skill
    out = use_skill("code_review")
    assert "Skill: code_review" in out
    assert "Steps:" in out


def test_use_skill_unknown():
    from tianshu.agent.tools.core import use_skill
    assert use_skill("ghost") == "Unknown skill: ghost"

