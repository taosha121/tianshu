import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    steps: list[str] = field(default_factory=list)


_BUILTIN_DIR = Path(__file__).parent / "builtin"

_MATCH_PROMPT = """\
你是一个 skill 路由器。判断用户的目标是否与以下某个预定义 skill 高度匹配。

用户目标：{goal}

可用 skills：
{skill_list}

如果用户目标与某个 skill 高度匹配（80% 以上的语义相似），返回该 skill 的 name。
如果没有匹配，返回 null。
只返回 JSON，格式：{{"match": "skill_name"}} 或 {{"match": null}}
"""


class SkillLoader:
    def __init__(self, extra_dir: str | None = None):
        self._skills: list[Skill] | None = None
        self._extra_dir = Path(extra_dir) if extra_dir else None

    def _load(self) -> list[Skill]:
        if self._skills is not None:
            return self._skills
        import yaml
        skills = []
        dirs = [_BUILTIN_DIR]
        if self._extra_dir and self._extra_dir.is_dir():
            dirs.append(self._extra_dir)
        for d in dirs:
            for f in sorted(d.glob("*.yaml")):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    skills.append(Skill(
                        name=data["name"],
                        description=data["description"],
                        steps=data.get("steps", []),
                    ))
                except Exception:
                    pass
        self._skills = skills
        return skills

    def all(self) -> list[Skill]:
        return self._load()

    def find(self, name: str) -> "Skill | None":
        return next((s for s in self._load() if s.name == name), None)

    def match(self, goal: str, client: Any, model: str) -> "Skill | None":
        skills = self._load()
        if not skills:
            return None
        skill_list = "\n".join(f"  - {s.name}: {s.description}" for s in skills)
        response = client.messages.create(
            model=model,
            max_tokens=128,
            messages=[{"role": "user", "content": _MATCH_PROMPT.format(
                goal=goal,
                skill_list=skill_list,
            )}],
        )
        text = response.content[0].text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            name = data.get("match")
            if name:
                return self.find(name)
        except Exception:
            pass
        return None
