import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from tianshu.agent.memory import ContextManager, LongTermMemory
from tianshu.agent.planner import Planner, PlanExecutor, Plan, Step
from tianshu.agent.provider import make_provider
from tianshu.agent.skills import SkillLoader
from tianshu.agent.tools import TOOLS, TOOL_MAP

load_dotenv()

from tianshu.agent._ctx import _step_ctx

_DIM   = "\033[2m"
_RESET = "\033[0m"

_KEY_ARG: dict[str, str] = {
    "bash":             "command",
    "read_file":        "path",
    "write_file":       "path",
    "edit_file":        "path",
    "create_directory": "path",
    "get_outline":      "path",
    "find_symbol":      "name",
    "grep_files":       "pattern",
    "list_files":       "path",
    "web_search":       "query",
    "web_fetch":        "url",
    "save_memory":      "slug",
    "delete_memory":    "slug",
    "read_memory":      "slug",
}


def _format_tool_call(name: str, inp: dict) -> str:
    key = _KEY_ARG.get(name)
    arg = str(inp.get(key, "")) if key else str(inp)
    if len(arg) > 60:
        arg = arg[:57] + "..."
    return f"{name}  {arg}"


_MAX_ITERATIONS = 20
_FINAL_STOPS = {"end_turn", "stop_sequence", "max_tokens", "pause_turn", "refusal"}

def _build_system_prompt(cwd: str) -> str:
    lines = [
        "You are an expert coding agent. You help users read, write, edit, and reason about code.",
        "You have access to tools for reading/writing files, running shell commands, searching code, and fetching web content.",
        "Always prefer targeted edits over rewriting entire files. Verify your changes work before reporting completion.",
        "To explore code: use get_outline(path) to see a file's symbols before reading it, and find_symbol(name) to locate definitions.",
        "When browsing the project, skip these directories entirely — they are not source code: "
        ".venv, venv, node_modules, dist, build, __pycache__, .git, .tianshu, vendor, site-packages.",
        "",
        f"Working directory: {cwd}",
    ]

    _SKIP_DIRS = {".venv", "venv", "__pycache__", "dist", "build", "node_modules", ".git", ".tianshu", "vendor", "site-packages"}
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
        model: str | None = None,
        cwd: str | None = None,
        # plan-mode steps reuse the parent Agent's system prompt to avoid
        # re-running the rglob + git status scan for every step
        _system_prompt: str | None = None,
        _agent_id: str = "main",
        _agent_type: str = "main",
        _emit: Callable[[dict], None] | None = None,
        _max_iterations: int = _MAX_ITERATIONS,
    ):
        self.model = model or os.environ.get("AGENT_MODEL", "gpt-5")
        self.provider = make_provider(self.model)
        self.client = self.provider.create_client()
        self._tool_schemas = self.provider.to_tool_schemas(TOOLS)
        self._summarize_fn = lambda msgs: self.provider.summarize(self.client, self.model, msgs)
        self.cwd = cwd or os.getcwd()
        self.history = []
        self.context = ContextManager(cwd=self.cwd)
        self.longterm = LongTermMemory(self.cwd)
        self._system_prompt = _system_prompt or _build_system_prompt(self.cwd)
        self._agent_id = _agent_id
        self._agent_type = _agent_type
        self._emit = _emit
        self._max_iterations = _max_iterations
        if self._emit:
            self._emit({"type": "agent_created", "agentId": _agent_id, "agentType": _agent_type})
            self._emit({"type": "agent_started", "agentId": _agent_id})

    def chat(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        _reactive_retries = 0

        for i in range(self._max_iterations):
            self.history = self.context.prepare(
                self.history, user_input, self._summarize_fn)
            system = self._system_prompt + self.longterm.to_system_prompt() + self.context.to_system_prompt()

            try:
                response = self.provider.call(
                    self.client, self.model, system, self.history, self._tool_schemas)
                _reactive_retries = 0
            except Exception as err:
                _is_too_long = any(
                    t in str(err).lower()
                    for t in ("prompt_too_long", "prompt is too long", "too many tokens")
                )
                if _is_too_long and _reactive_retries < 1:
                    print("[reactive compact]")
                    self.history = self.context.reactive_compact(
                        self.history, user_input, self._summarize_fn)
                    _reactive_retries += 1
                    continue
                raise

            if response.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "input": tc.input}
                        for tc in response.tool_calls
                    ],
                }
            else:
                assistant_msg = {"role": "assistant", "content": response.text}
            self.history.append(assistant_msg)
            print(f"  {_DIM}[{self._agent_id}] iter={i+1} stop={response.stop_reason}{_RESET}")

            if self._emit and response.stop_reason in _FINAL_STOPS:
                self._emit({
                    "type": "prompt_updated",
                    "agentId": self._agent_id,
                    "prompt": self.history,
                    "context": self.context.stats(self.history, system),
                    "isFinal": True,
                })

            match response.stop_reason:
                case "end_turn" | "stop_sequence":
                    return response.text
                case "max_tokens":
                    return response.text + "\n[response truncated: max_tokens reached]"
                case "pause_turn":
                    return response.text or "[paused]"
                case "refusal":
                    return "[model refused to respond]"
                case "tool_use":
                    pass
                case _:
                    return response.text if response.text else f"[stopped: {response.stop_reason}]"

            tool_results = []
            for tc in response.tool_calls:
                tool = TOOL_MAP.get(tc.name)
                if self._emit:
                    self._emit({"type": "tool_call", "id": tc.id, "name": tc.name, "input": tc.input})
                result = tool.func(**tc.input) if tool else f"Unknown tool: {tc.name}"
                if self._emit:
                    self._emit({"type": "tool_result", "id": tc.id, "result": str(result)[:2000]})
                label = getattr(_step_ctx, "label", "")
                prefix = f"{label} " if label else ""
                print(f"  {_DIM}{prefix}· {_format_tool_call(tc.name, tc.input)}{_RESET}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })

            self.history.append({"role": "user", "content": tool_results})
            if self._emit:
                self._emit({
                    "type": "prompt_updated",
                    "agentId": self._agent_id,
                    "prompt": self.history,
                    "context": self.context.stats(self.history, system),
                    "isFinal": False,
                })

        return "Maximum iterations reached without completing the task."

    def execute(self, goal: str) -> str:
        if self._emit:
            self._emit({"type": "prompt_updated", "agentId": self._agent_id, "prompt": goal})
        skill = SkillLoader().match(goal, self.provider, self.client, self.model)
        if skill:
            print(f"  [skill] matched: {skill.name}")
            result = self.execute_skill(skill)
        else:
            plan = Planner(self.provider, self.client, self.model).decompose(goal)
            if plan is None:
                result = self.chat(goal)
            else:
                steps_summary = PlanExecutor(self).execute(plan)
                synthesis_prompt = (
                    f"All subtasks have been completed. Here is a summary of what was done:\n\n"
                    f"{steps_summary}\n\n"
                    f"Based on the original goal and the completed work above, provide a comprehensive final response."
                )
                result = self.chat(synthesis_prompt)
        if self._emit:
            self._emit({"type": "agent_done", "agentId": self._agent_id, "status": "done"})
        return result

    def execute_skill(self, skill) -> str:
        steps = [Step(index=i, description=d) for i, d in enumerate(skill.steps)]
        plan = Plan(goal=skill.description, steps=steps)
        steps_summary = PlanExecutor(self).execute(plan)
        synthesis_prompt = (
            f"All subtasks have been completed. Here is a summary of what was done:\n\n"
            f"{steps_summary}\n\n"
            f"Based on the original goal and the completed work above, provide a comprehensive final response."
        )
        return self.chat(synthesis_prompt)
