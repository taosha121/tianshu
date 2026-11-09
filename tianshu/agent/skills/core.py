from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    steps: list[str] = field(default_factory=list)


class SkillLoader:
    def __init__(self, cwd: str = "."):
        self._cwd = cwd
        self._skills: list[Skill] | None = None

    def _load(self) -> list[Skill]:
        if self._skills is not None:
            return self._skills
        import yaml
        dirs = [
            Path.home() / ".tianshu" / "skills",
            Path(self._cwd) / ".tianshu" / "skills",
        ]
        seen: set[str] = set()
        skills = []
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.yaml")):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    name = data["name"]
                    if name in seen:
                        skills = [s for s in skills if s.name != name]
                    seen.add(name)
                    skills.append(Skill(
                        name=name,
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

    def to_prompt(self) -> str:
        skills = self._load()
        if not skills:
            return ""
        lines = [
            "\nAvailable skills — call use_skill(name) to load full instructions when the "
            "user's request clearly matches one; otherwise ignore them:"
        ]
        lines += [f"  - {s.name}: {s.description}" for s in skills]
        return "\n".join(lines)
