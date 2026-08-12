import os
import subprocess
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from tianshu.agent.memory import ContextManager, LongTermMemory
from tianshu.agent.planner import Planner, PlanExecutor, Plan, Step
from tianshu.agent.tools import TOOLS, TOOL_MAP

load_dotenv()

_TOOL_SCHEMAS = [t.to_api_dict() for t in TOOLS]
_MAX_ITERATIONS = 10

_TOOL_MAX_CHARS: dict[str, int] = {
    "read_file": 4_000,
    "bash": 3_000,
    "grep_files": 2_000,
    "web_fetch": 5_000,
    "write_file": 500,
    "edit_file": 500,
    "create_directory": 500,
    "save_memory": 500,
}
_TOOL_MAX_CHARS_DEFAULT = 8_000


def _truncate_result(tool_name: str, result: str) -> str:
    limit = _TOOL_MAX_CHARS.get(tool_name, _TOOL_MAX_CHARS_DEFAULT)
    if len(result) <= limit:
        return result
    head = int(limit * 0.6)
    tail = limit - head
    return (
        result[:head]
        + f"\n\n[Truncated {len(result) - limit} characters, head and tail preserved]\n\n"
        + result[-tail:]
    )


def _build_system_prompt(cwd: str) -> str:
    lines = [
        "You are an expert coding agent. You help users read, write, edit, and reason about code.",
        "You have access to tools for reading/writing files, running shell commands, searching code, and fetching web content.",
        "Always prefer targeted edits over rewriting entire files. Verify your changes work before reporting completion.",
        "To explore code: use get_outline(path) to see a file's symbols before reading it, and find_symbol(name) to locate definitions.",
        "",
        f"Working directory: {cwd}",
    ]

    _SKIP_DIRS = {".venv", "venv", "__pycache__", "dist", "build", "node_modules", ".git", "vendor", "site-packages"}
    _MAX_OUTLINE_CHARS = 500

    p = Path(cwd)
    project_type = "unknown"

    for marker, label in [
        ("pyproject.toml", "Python"),
        ("package.json", "Node.js"),
        ("go.mod", "Go"),
        ("Cargo.toml", "Rust"),
    ]:
        if (p / marker).exists():
            project_type = label
            lines.append(f"Project type: {label} ({marker} detected)")
            if label == "Node.js" and ((p / "webapp").exists() or (p / "webapp" / "manifest.json").exists()):
                lines.append("UI5 project detected (webapp/ directory found)")
                project_type = "UI5"
            break

    try:
        entries = sorted(
            e.name for e in p.iterdir()
            if not e.name.startswith(".") and e.name not in _SKIP_DIRS
        )
        lines.append(f"Top-level structure: {', '.join(entries[:40])}")
    except Exception:
        pass

    if project_type in ("Node.js", "UI5"):
        _EXTS = ("*.js", "*.ts", "*.mjs")
    else:
        _EXTS = ("*.py",)

    try:
        import re
        _JS_SYMBOL = re.compile(
            r"^\s*(?:"
            r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+\w+"
            r"|(?:export\s+)?class\s+\w+"
            r"|(?:export\s+)?const\s+\w+\s*=\s*(?:async\s+)?\("
            r"|(?:export\s+)?const\s+\w+\s*=\s*function"
            r"|[\w.]+\.extend\s*\("
            r"|sap\.ui\.define\s*\("
            r")"
        )
        outline_lines = []
        total_chars = 0
        truncated = False

        all_files = []
        for ext in _EXTS:
            all_files.extend(p.rglob(ext))
        all_files = sorted(
            f for f in all_files
            if not any(part in _SKIP_DIRS for part in f.relative_to(p).parts)
            and len(f.relative_to(p).parts) <= 4
        )

        for src_file in all_files:
            rel = str(src_file.relative_to(p))
            file_lines = src_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            symbols = []
            if src_file.suffix == ".py":
                for i, line in enumerate(file_lines, 1):
                    s = line.lstrip()
                    if s.startswith(("def ", "async def ", "class ")):
                        symbols.append(f"  {i}: {s.split(':', 1)[0]}")
            else:
                for i, line in enumerate(file_lines, 1):
                    if _JS_SYMBOL.match(line):
                        symbols.append(f"  {i}: {line.rstrip()}")
            if not symbols:
                continue

            block = f"{rel}:\n" + "\n".join(symbols[:10]) + "\n"
            if total_chars + len(block) > _MAX_OUTLINE_CHARS:
                truncated = True
                break
            outline_lines.append(block)
            total_chars += len(block)

        if outline_lines:
            suffix = "\n  ... (use get_outline/find_symbol to explore further)" if truncated else ""
            lines.append("\nRepo outline:\n" + "\n".join(outline_lines) + suffix)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            lines.append(f"Git status:\n{result.stdout.strip()}")
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if branch.stdout.strip():
            lines.append(f"Git branch: {branch.stdout.strip()}")
    except Exception:
        pass

    return "\n".join(lines)


class Agent:
    def __init__(
        self,
        model: str = "anthropic--claude-4.5-sonnet",
        cwd: str | None = None,
        # plan-mode steps reuse the parent Agent's system prompt to avoid
        # re-running the rglob + git status scan for every step
        _system_prompt: str | None = None,
    ):
        self.client = anthropic.Anthropic(
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        self.model = model
        self.cwd = cwd or os.getcwd()
        self.history = []
        self.context = ContextManager()
        self.longterm = LongTermMemory(self.cwd)
        self._system_prompt = _system_prompt or _build_system_prompt(self.cwd)

    def chat(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        self.history = self.context.maybe_compress(self.history, self.client, self.model)

        system = self._system_prompt + self.longterm.system_addendum + self.context.system_addendum

        for _ in range(_MAX_ITERATIONS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system,
                messages=self.history,
                tools=_TOOL_SCHEMAS,
            )

            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return response.content[0].text

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool = TOOL_MAP.get(block.name)
                result = tool.func(**block.input) if tool else f"Unknown tool: {block.name}"
                result = _truncate_result(block.name, result)
                preview = result if len(result) <= 100 else result[:100] + "..."
                print(f"  [tool] {block.name}({block.input}) -> {preview}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            self.history.append({"role": "user", "content": tool_results})

        return "Maximum iterations reached without completing the task."

    def execute(self, goal: str) -> str:
        planner = Planner(self.client, self.model)
        plan = planner.decompose(goal)
        if plan is None:
            return self.chat(goal)
        return PlanExecutor(self).execute(plan)

    def execute_skill(self, skill) -> str:
        steps = [Step(index=i, description=d) for i, d in enumerate(skill.steps)]
        plan = Plan(goal=skill.description, steps=steps)
        return PlanExecutor(self).execute(plan)
