from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    steps: list[str] = field(default_factory=list)


_BUILTIN_DIR = Path(__file__).parent / "builtin"


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

    def to_prompt(self) -> str:
        """Render the skill catalog for injection into the system prompt.

        Empty string when no skills are registered, so the prompt stays clean.
        """
        skills = self._load()
        if not skills:
            return ""
        lines = [
            "\nAvailable skills — call use_skill(name) to load full instructions when the "
            "user's request clearly matches one; otherwise ignore them:"
        ]
        lines += [f"  - {s.name}: {s.description}" for s in skills]
        return "\n".join(lines)
