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


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except Exception as e:
        return f"读取失败: {e}"


def write_file(path: str, content: str) -> str:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入: {path}"
    except Exception as e:
        return f"写入失败: {e}"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
        if old_string not in text:
            return f"未找到目标内容，无法替换"
        count = text.count(old_string)
        if count > 1:
            return f"目标内容出现 {count} 次，请提供更多上下文使其唯一"
        Path(path).write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return f"已替换: {path}"
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except Exception as e:
        return f"编辑失败: {e}"


def create_directory(path: str) -> str:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"已创建目录: {path}"
    except Exception as e:
        return f"创建失败: {e}"


def list_files(directory: str = ".", pattern: str = "**/*") -> str:
    try:
        root = Path(directory).resolve()
        matches = [
            str(p.relative_to(root))
            for p in root.glob(pattern)
            if p.is_file() and not any(part.startswith(".") for part in p.parts)
        ]
        if not matches:
            return "没有找到匹配的文件"
        return "\n".join(sorted(matches))
    except Exception as e:
        return f"列举文件失败: {e}"


def grep_files(pattern: str, directory: str = ".", file_glob: str = "") -> str:
    try:
        cmd = ["grep", "-rn", "--include", file_glob or "*", pattern, directory]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        return output if output else "没有找到匹配内容"
    except subprocess.TimeoutExpired:
        return "搜索超时"
    except Exception as e:
        return f"搜索失败: {e}"


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
        return f"命令超时（{timeout}s）"
    except Exception as e:
        return f"执行失败: {e}"


def web_search(query: str) -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "未配置 TAVILY_API_KEY"
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
        return f"搜索失败: {e}"


def web_fetch(url: str) -> str:
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"抓取失败: {e}"


def save_memory(note: str, workspace: str = ".") -> str:
    from lingjiyidong.agent.memory.longterm import LongTermMemory
    mem = LongTermMemory(workspace)
    mem.append(note)
    return f"已保存到记忆: {note}"


TOOLS: list[Tool] = [
    Tool(
        name="read_file",
        description="读取本地文件内容并返回。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件的绝对路径或相对路径"},
            },
            "required": ["path"],
        },
        func=read_file,
    ),
    Tool(
        name="write_file",
        description="创建或覆盖写入一个文件。父目录不存在时自动创建。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入的完整内容"},
            },
            "required": ["path", "content"],
        },
        func=write_file,
    ),
    Tool(
        name="edit_file",
        description="精准替换文件中的一段内容。old_string 必须在文件中唯一存在。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_string": {"type": "string", "description": "要被替换的原始内容，必须完整匹配"},
                "new_string": {"type": "string", "description": "替换后的新内容"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        func=edit_file,
    ),
    Tool(
        name="create_directory",
        description="创建目录，支持递归创建多级目录。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要创建的目录路径"},
            },
            "required": ["path"],
        },
        func=create_directory,
    ),
    Tool(
        name="list_files",
        description="列举目录下的文件，支持 glob 模式过滤。",
        input_schema={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "要列举的目录路径，默认为当前目录"},
                "pattern": {"type": "string", "description": "glob 模式，例如 '**/*.py'，默认列举所有文件"},
            },
            "required": [],
        },
        func=list_files,
    ),
    Tool(
        name="grep_files",
        description="在目录中搜索匹配指定模式的文本，返回文件名和行号。",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的文本或正则表达式"},
                "directory": {"type": "string", "description": "搜索的目录，默认为当前目录"},
                "file_glob": {"type": "string", "description": "限定搜索的文件类型，例如 '*.py'"},
            },
            "required": ["pattern"],
        },
        func=grep_files,
    ),
    Tool(
        name="bash",
        description="在 shell 中执行命令，返回 stdout 和 stderr。可用于运行测试、git 操作、安装依赖等。",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 30"},
            },
            "required": ["command"],
        },
        func=bash,
    ),
    Tool(
        name="web_search",
        description="在网络上搜索信息，返回搜索结果摘要。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
            },
            "required": ["query"],
        },
        func=web_search,
    ),
    Tool(
        name="web_fetch",
        description="抓取指定 URL 的网页内容，用于阅读文档或 issue。",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的 URL"},
            },
            "required": ["url"],
        },
        func=web_fetch,
    ),
    Tool(
        name="save_memory",
        description="将重要信息保存到长期记忆，下次启动时自动加载。",
        input_schema={
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "要记住的信息"},
                "workspace": {"type": "string", "description": "工作目录路径，默认为当前目录"},
            },
            "required": ["note"],
        },
        func=save_memory,
    ),
]

TOOL_MAP: dict[str, Tool] = {t.name: t for t in TOOLS}
