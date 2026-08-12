import os
from pathlib import Path

_MEMORY_FILENAME = "memory.md"


class LongTermMemory:
    def __init__(self, workspace: str = "."):
        self._path = Path(workspace) / ".agent" / _MEMORY_FILENAME

    def load(self) -> str:
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8").strip()

    def save(self, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content, encoding="utf-8")

    def append(self, note: str) -> str:
        existing = self.load()
        updated = f"{existing}\n\n{note}".strip()
        self.save(updated)
        return updated

    @property
    def system_addendum(self) -> str:
        content = self.load()
        if not content:
            return ""
        return f"\n\n--- Long-term memory ---\n{content}\n--- End of memory ---"
