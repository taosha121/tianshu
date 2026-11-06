import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

PRE = "PreToolUse"
POST = "PostToolUse"

_SHELL_TIMEOUT = 10


@dataclass
class HookOutcome:
    block: bool = False           # pre: block the call and skip execution
    reason: str = ""              # explanation fed back to the model when blocking
    input: dict | None = None     # pre: rewritten input (None = unchanged)
    result: str | None = None     # post: rewritten result (None = unchanged)


# pre  hook: fn(name, inp)         -> HookOutcome | None
# post hook: fn(name, inp, result) -> HookOutcome | None
PreHook = Callable[[str, dict], "HookOutcome | None"]
PostHook = Callable[[str, dict, str], "HookOutcome | None"]


def _match(matcher: str, name: str) -> bool:
    return matcher == "*" or matcher == name


class HookRegistry:
    """Holds pre/post tool-use hooks and runs the ones matching a tool name."""

    def __init__(self):
        self._pre: list[tuple[str, PreHook]] = []
        self._post: list[tuple[str, PostHook]] = []

    def register(self, event: str, matcher: str, fn: Callable) -> None:
        if event == PRE:
            self._pre.append((matcher, fn))
        elif event == POST:
            self._post.append((matcher, fn))
        else:
            raise ValueError(f"Unknown hook event: {event}")

    def pre(self, matcher: str = "*"):
        def deco(fn: PreHook) -> PreHook:
            self.register(PRE, matcher, fn)
            return fn
        return deco

    def post(self, matcher: str = "*"):
        def deco(fn: PostHook) -> PostHook:
            self.register(POST, matcher, fn)
            return fn
        return deco

    def run_pre(self, name: str, inp: dict) -> tuple[dict, str | None]:
        """Run matching pre hooks. Returns (final_input, block_reason_or_None)."""
        for matcher, fn in self._pre:
            if not _match(matcher, name):
                continue
            try:
                outcome = fn(name, inp)
            except Exception as e:
                print(f"[hook warning] pre hook for {name} failed: {e}")
                continue
            if outcome is None:
                continue
            if outcome.input is not None:
                inp = outcome.input
            if outcome.block:
                return inp, (outcome.reason or f"blocked by a PreToolUse hook on {name}")
        return inp, None

    def run_post(self, name: str, inp: dict, result: str) -> str:
        """Run matching post hooks, chaining result rewrites."""
        for matcher, fn in self._post:
            if not _match(matcher, name):
                continue
            try:
                outcome = fn(name, inp, result)
            except Exception as e:
                print(f"[hook warning] post hook for {name} failed: {e}")
                continue
            if outcome is not None and outcome.result is not None:
                result = outcome.result
        return result


def _run_shell(command: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        shell=True,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=_SHELL_TIMEOUT,
    )


def _parse_stdout(stdout: str) -> dict:
    stdout = stdout.strip()
    if not stdout:
        return {}
    try:
        data = json.loads(stdout)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _make_pre_shell_hook(command: str) -> PreHook:
    def hook(name: str, inp: dict) -> HookOutcome | None:
        try:
            proc = _run_shell(command, {"event": PRE, "tool": name, "input": inp})
        except subprocess.TimeoutExpired:
            print(f"[hook warning] pre shell hook timed out, allowing: {command}")
            return None
        if proc.returncode == 2:
            reason = (proc.stderr or proc.stdout or "").strip()
            return HookOutcome(block=True, reason=reason)
        if proc.returncode != 0:
            print(f"[hook warning] pre shell hook exited {proc.returncode}, allowing: {command}")
            return None
        data = _parse_stdout(proc.stdout)
        new_input = data.get("input")
        return HookOutcome(input=new_input) if isinstance(new_input, dict) else None
    return hook


def _make_post_shell_hook(command: str) -> PostHook:
    def hook(name: str, inp: dict, result: str) -> HookOutcome | None:
        try:
            proc = _run_shell(command, {"event": POST, "tool": name, "input": inp, "result": result})
        except subprocess.TimeoutExpired:
            print(f"[hook warning] post shell hook timed out: {command}")
            return None
        if proc.returncode != 0:
            print(f"[hook warning] post shell hook exited {proc.returncode}: {command}")
            return None
        data = _parse_stdout(proc.stdout)
        new_result = data.get("result")
        return HookOutcome(result=new_result) if isinstance(new_result, str) else None
    return hook


def _config_paths(cwd: str) -> list[Path]:
    # global first, then project — project entries run after global ones
    return [
        Path.home() / ".tianshu" / "hooks.json",
        Path(cwd) / ".tianshu" / "hooks.json",
    ]


def load_shell_hooks(registry: HookRegistry, cwd: str) -> None:
    """Load shell-command hooks declared in global and project .tianshu/hooks.json."""
    for path in _config_paths(cwd):
        if not path.exists():
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[hook warning] failed to load {path}: {e}")
            continue
        for event, maker in ((PRE, _make_pre_shell_hook), (POST, _make_post_shell_hook)):
            for entry in config.get(event, []):
                command = entry.get("command")
                if not command:
                    continue
                registry.register(event, entry.get("matcher", "*"), maker(command))
