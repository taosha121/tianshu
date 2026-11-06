import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]

    def to_api_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if start_line or end_line:
            s = max(0, start_line - 1)
            e = end_line if end_line else len(lines)
            lines = lines[s:e]
            prefix = f"[lines {start_line}-{end_line or len(lines) + s}]\n"
            return prefix + "".join(lines)
        return "".join(lines)
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Read failed: {e}"


def get_outline(path: str) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Read failed: {e}"

    ext = Path(path).suffix.lower()
    result = []

    if ext == ".py":
        for i, line in enumerate(lines, 1):
            s = line.lstrip()
            if s.startswith(("def ", "async def ", "class ")):
                result.append(f"{i:4d}  {line.rstrip()}")
    elif ext in (".js", ".ts", ".mjs", ".cjs"):
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
        for i, line in enumerate(lines, 1):
            if _JS_SYMBOL.match(line):
                result.append(f"{i:4d}  {line.rstrip()}")

    return "\n".join(result) if result else "(no symbols found)"


def find_symbol(name: str, directory: str = ".") -> str:
    try:
        py_cmd = [
            "grep", "-rn", "--include=*.py",
            "-E", rf"^\s*(def|class|async def)\s+{name}\s*[\(:]",
            directory,
        ]
        js_cmd = [
            "grep", "-rn",
            "--include=*.js", "--include=*.ts", "--include=*.mjs",
            "-E", rf"(function\s+{name}|class\s+{name}|const\s+{name}\s*=)",
            directory,
        ]
        out = ""
        for cmd in (py_cmd, js_cmd):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                out += r.stdout.strip() + "\n"
        return out.strip() if out.strip() else f"Symbol not found: {name}"
    except subprocess.TimeoutExpired:
        return "Search timed out"
    except Exception as e:
        return f"Search failed: {e}"


def write_file(path: str, content: str) -> str:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written: {path}"
    except Exception as e:
        return f"Write failed: {e}"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
        if old_string not in text:
            return "Target string not found, cannot replace"
        count = text.count(old_string)
        if count > 1:
            return f"Target string appears {count} times, provide more context to make it unique"
        Path(path).write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited: {path}"
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Edit failed: {e}"


def create_directory(path: str) -> str:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"Directory created: {path}"
    except Exception as e:
        return f"Create failed: {e}"


def list_files(directory: str = ".", pattern: str = "**/*") -> str:
    try:
        root = Path(directory).resolve()
        matches = [
            str(p.relative_to(root))
            for p in root.glob(pattern)
            if p.is_file() and not any(part.startswith(".") for part in p.parts)
        ]
        if not matches:
            return "No matching files found"
        return "\n".join(sorted(matches))
    except Exception as e:
        return f"List files failed: {e}"


def grep_files(pattern: str, directory: str = ".", file_glob: str = "") -> str:
    try:
        cmd = ["grep", "-rn", "--include", file_glob or "*", pattern, directory]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        return output if output else "No matches found"
    except subprocess.TimeoutExpired:
        return "Search timed out"
    except Exception as e:
        return f"Search failed: {e}"


def bash(command: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out ({timeout}s)"
    except Exception as e:
        return f"Execution failed: {e}"


def web_search(query: str) -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "TAVILY_API_KEY not configured"
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": 5},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return "\n\n".join(
            f"[{r['title']}]({r['url']})\n{r.get('content', '')}" for r in results
        )
    except Exception as e:
        return f"Search failed: {e}"


def web_fetch(url: str) -> str:
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"Fetch failed: {e}"


def save_memory(slug: str, memory_type: str, description: str, content: str,
                scope: str = "project") -> str:
    from tianshu.agent.memory.longterm import LongTermMemory
    return LongTermMemory(os.getcwd()).save(slug, memory_type, description, content, scope)


def delete_memory(slug: str, scope: str = "project") -> str:
    from tianshu.agent.memory.longterm import LongTermMemory
    return LongTermMemory(os.getcwd()).delete(slug, scope)


def read_memory(slug: str, scope: str = "project") -> str:
    from tianshu.agent.memory.longterm import LongTermMemory
    return LongTermMemory(os.getcwd()).load_entry(slug, scope)


_TODO_STATUSES = {"pending", "in_progress", "completed"}


def todo_list_write(todos: list) -> list:
    # Pure validation/normalization; the agent runtime stores the result and
    # emits the UI event (it needs the agent instance, which a tool func lacks).
    normalized = []
    for t in todos or []:
        content = str(t.get("content", "")).strip()
        status = t.get("status", "pending")
        if status not in _TODO_STATUSES:
            status = "pending"
        if content:
            normalized.append({"content": content, "status": status})
    return normalized


def invoke_subagent(goal: str, tools: list | None = None) -> str:
    # Placeholder: real execution happens in Agent._dispatch_tool, which owns
    # the parent agent (provider, cwd, hooks, permission, emit) a func can't see.
    return "invoke_subagent must be handled by the agent runtime"


TOOLS: list[Tool] = [
    Tool(
        name="read_file",
        description="Read the contents of a local file. Use start_line/end_line to read only a range and avoid loading large files entirely.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file"},
                "start_line": {"type": "integer", "description": "First line to read (1-indexed); omit to read from the beginning"},
                "end_line": {"type": "integer", "description": "Last line to read (inclusive); omit to read to end of file"},
            },
            "required": ["path"],
        },
        func=read_file,
    ),
    Tool(
        name="write_file",
        description="Create or overwrite a file. Parent directories are created automatically.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Full content to write"},
            },
            "required": ["path", "content"],
        },
        func=write_file,
    ),
    Tool(
        name="edit_file",
        description="Replace a unique string in a file. old_string must appear exactly once.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact string to replace; must be unique in the file"},
                "new_string": {"type": "string", "description": "Replacement string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        func=edit_file,
    ),
    Tool(
        name="create_directory",
        description="Create a directory, including any missing parent directories.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to create"},
            },
            "required": ["path"],
        },
        func=create_directory,
    ),
    Tool(
        name="list_files",
        description="List files in a directory, optionally filtered by a glob pattern.",
        input_schema={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to list; defaults to current directory"},
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'; defaults to all files"},
            },
            "required": [],
        },
        func=list_files,
    ),
    Tool(
        name="grep_files",
        description="Search for a pattern across files in a directory; returns matching file names and line numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regex to search for"},
                "directory": {"type": "string", "description": "Directory to search; defaults to current directory"},
                "file_glob": {"type": "string", "description": "Restrict search to files matching this glob, e.g. '*.py'"},
            },
            "required": ["pattern"],
        },
        func=grep_files,
    ),
    Tool(
        name="bash",
        description="Execute a shell command and return stdout and stderr. Useful for running tests, git operations, installing dependencies, etc.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds; defaults to 30"},
            },
            "required": ["command"],
        },
        func=bash,
    ),
    Tool(
        name="web_search",
        description="Search the web and return result summaries.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or question"},
            },
            "required": ["query"],
        },
        func=web_search,
    ),
    Tool(
        name="web_fetch",
        description="Fetch the content of a URL; useful for reading documentation or issues.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        func=web_fetch,
    ),
    Tool(
        name="save_memory",
        description=(
            "Save important information to long-term memory (persisted across sessions). "
            "Use scope='global' for cross-project preferences, scope='project' (default) for project-specific facts. "
            "type must be one of: fact, decision, preference, error. "
            "slug is a short kebab-case identifier, e.g. 'user-prefers-tabs'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Short kebab-case identifier"},
                "memory_type": {"type": "string", "enum": ["fact", "decision", "preference", "error"]},
                "description": {"type": "string", "description": "One-line summary shown in the memory index"},
                "content": {"type": "string", "description": "Full content of the memory"},
                "scope": {"type": "string", "enum": ["global", "project"], "description": "global = ~/.tianshu/memory, project = <cwd>/.tianshu/memory; defaults to project"},
            },
            "required": ["slug", "memory_type", "description", "content"],
        },
        func=save_memory,
    ),
    Tool(
        name="delete_memory",
        description="Delete a memory entry by slug.",
        input_schema={
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "scope": {"type": "string", "enum": ["global", "project"], "description": "Defaults to project"},
            },
            "required": ["slug"],
        },
        func=delete_memory,
    ),
    Tool(
        name="read_memory",
        description="Read the full content of a memory entry by slug.",
        input_schema={
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "scope": {"type": "string", "enum": ["global", "project"], "description": "Defaults to project"},
            },
            "required": ["slug"],
        },
        func=read_memory,
    ),
    Tool(
        name="get_outline",
        description="Return all def/class signatures and line numbers in a Python file without the function bodies. Faster than read_file for understanding file structure.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the Python file"},
            },
            "required": ["path"],
        },
        func=get_outline,
    ),
    Tool(
        name="find_symbol",
        description="Find where a function or class is defined in the repo; returns file name and line number. Equivalent to 'go to definition'.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Function or class name"},
                "directory": {"type": "string", "description": "Root directory to search; defaults to current directory"},
            },
            "required": ["name"],
        },
        func=find_symbol,
    ),
    Tool(
        name="todo_list_write",
        description=(
            "Write or update your task list for a multi-step task. Pass the FULL list every time — "
            "it replaces the previous list entirely. Use this to plan complex work and keep the user "
            "informed of progress: add items when you start, flip one to in_progress as you work on it, "
            "and mark it completed the moment it's done. Keep exactly one item in_progress at a time. "
            "Skip this for simple single-step requests — just answer directly."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete task list, in order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "What the task is"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
        func=todo_list_write,
    ),
    Tool(
        name="invoke_subagent",
        description=(
            "Delegate a self-contained subtask to a fresh subagent that runs in its own isolated "
            "context and returns only its final answer. Use this ONLY when a chunk of work would flood "
            "your own context with noise you don't need to keep (e.g. searching across many files for a "
            "single answer), or when a task is genuinely independent. For ordinary sequential steps, do "
            "NOT use this — just do the work yourself and track it with todo_list_write."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "A clear, self-contained description of the subtask and what to return"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional allowlist of tool names the subagent may use; omit to allow all tools",
                },
            },
            "required": ["goal"],
        },
        func=invoke_subagent,
    ),
]

TOOL_MAP: dict[str, Tool] = {t.name: t for t in TOOLS}
