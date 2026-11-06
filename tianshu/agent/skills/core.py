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
You are a skill router. Each skill below is a specific predefined workflow, not a general topic.
Your default answer is null. Only return a skill when the user is clearly asking to run that exact workflow.

User goal: {goal}

Available skills:
{skill_list}

Rules:
- Match only if the goal explicitly requests the skill's specific action on its specific object.
  Both the action and the object must match, not just the general theme.
- Casual verbs like "look at", "check", "show me", "explain", "understand" are NOT a request
  to run a skill. "Look at the project structure" is exploration, not a code review.
- When uncertain, return null. A wrong match is worse than no match.

Return JSON only, format: {{"match": "skill_name"}} or {{"match": null}}
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

    def match(self, goal: str, provider: Any, client: Any, model: str) -> "Skill | None":
        skills = self._load()
        if not skills:
            return None
        skill_list = "\n".join(f"  - {s.name}: {s.description}" for s in skills)
        text = provider.complete(client, model, _MATCH_PROMPT.format(
            goal=goal,
            skill_list=skill_list,
        ))
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
