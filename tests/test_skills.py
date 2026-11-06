from conftest import FakeProvider

from tianshu.agent.skills.core import SkillLoader


def _match(goal, raw):
    return SkillLoader().match(goal, FakeProvider(complete_text=raw),
                               client=None, model="x")


def test_builtin_skills_load():
    names = {s.name for s in SkillLoader().all()}
    assert "code_review" in names


def test_find_returns_none_for_unknown():
    assert SkillLoader().find("does_not_exist") is None


def test_match_extracts_skill_from_noisy_json():
    skill = _match("review my diff", 'Sure!\n{"match": "code_review"} done')
    assert skill is not None and skill.name == "code_review"


def test_match_null_returns_none():
    assert _match("look at the project structure", '{"match": null}') is None


def test_match_invalid_json_returns_none():
    assert _match("whatever", "not json at all") is None


def test_match_unknown_name_returns_none():
    assert _match("whatever", '{"match": "ghost_skill"}') is None
