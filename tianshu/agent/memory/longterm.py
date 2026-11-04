import re
from pathlib import Path


_GLOBAL_MEMORY_DIR = Path.home() / ".tianshu" / "memory"
_INDEX_FILE = "MEMORY.md"
_VALID_TYPES = {"fact", "decision", "preference", "error"}


def _slug_to_path(directory: Path, slug: str) -> Path:
    return directory / f"{slug}.md"


def _read_index(directory: Path) -> str:
    index = directory / _INDEX_FILE
    if not index.exists():
        return ""
    return index.read_text(encoding="utf-8").strip()


def _write_index(directory: Path, content: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _INDEX_FILE).write_text(content + "\n", encoding="utf-8")


class LongTermMemory:
    def __init__(self, cwd: str = "."):
        self._project_dir = Path(cwd) / ".tianshu" / "memory"

    def _dir(self, scope: str) -> Path:
        return _GLOBAL_MEMORY_DIR if scope == "global" else self._project_dir

    def save(self, slug: str, memory_type: str, description: str, content: str,
             scope: str = "project") -> str:
        if memory_type not in _VALID_TYPES:
            memory_type = "fact"
        slug = re.sub(r"[^a-z0-9_-]", "-", slug.lower()).strip("-")
        if not slug:
            return "Invalid slug"

        directory = self._dir(scope)
        directory.mkdir(parents=True, exist_ok=True)
        file_content = (
            f"---\n"
            f"name: {slug}\n"
            f"type: {memory_type}\n"
            f"description: {description}\n"
            f"---\n\n"
            f"{content.strip()}\n"
        )
        _slug_to_path(directory, slug).write_text(file_content, encoding="utf-8")

        existing = _read_index(directory)
        new_line = f"- [{slug}]({slug}.md) — {description}"
        lines = [l for l in existing.splitlines()
                 if not re.match(rf"^- \[{re.escape(slug)}\]", l)]
        lines.append(new_line)
        _write_index(directory, "\n".join(lines))

        return f"Saved memory ({scope}): {slug}"

    def delete(self, slug: str, scope: str = "project") -> str:
        directory = self._dir(scope)
        path = _slug_to_path(directory, slug)
        if not path.exists():
            return f"Memory not found: {slug}"
        path.unlink()
        existing = _read_index(directory)
        lines = [l for l in existing.splitlines()
                 if not re.match(rf"^- \[{re.escape(slug)}\]", l)]
        _write_index(directory, "\n".join(lines))
        return f"Deleted memory ({scope}): {slug}"

    def load_entry(self, slug: str, scope: str = "project") -> str:
        path = _slug_to_path(self._dir(scope), slug)
        if not path.exists():
            return f"Memory not found: {slug}"
        return path.read_text(encoding="utf-8").strip()

    def to_system_prompt(self) -> str:
        global_index = _read_index(_GLOBAL_MEMORY_DIR)
        project_index = _read_index(self._project_dir)
        if not global_index and not project_index:
            return ""
        parts = []
        if global_index:
            parts.append(f"[Global]\n{global_index}")
        if project_index:
            parts.append(f"[Project]\n{project_index}")
        body = "\n\n".join(parts)
        return f"\n\n--- Long-term memory ---\n{body}\n--- End of memory ---"
