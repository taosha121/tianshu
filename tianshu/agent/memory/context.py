import json
import re
import uuid
from pathlib import Path
from typing import Callable


def _estimate_chars(messages: list) -> int:
    return len(json.dumps(messages, default=str, ensure_ascii=False))


class ContextManager:
    CONTEXT_CHAR_LIMIT = 400_000
    TOOL_RESULT_BATCH_CHAR_LIMIT = 100_000
    LARGE_RESULT_CHAR_LIMIT = 20_000
    KEEP_RECENT_RESULTS = 3
    KEEP_RECENT_MESSAGES = 5
    SNIP_TRIGGER = 50
    SNIP_TARGET = 30

    def __init__(self, cwd: str = "."):
        self._transcript_dir = Path(cwd) / ".tianshu" / "transcripts"
        self._tool_results_dir = Path(cwd) / ".tianshu" / "tool-results"

    # --- helpers ---

    @staticmethod
    def _block_type(block) -> str | None:
        return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

    @classmethod
    def _has_tool_use(cls, message: dict) -> bool:
        if message.get("role") != "assistant":
            return False
        if message.get("tool_calls"):
            return True
        content = message.get("content")
        return isinstance(content, list) and any(cls._block_type(b) == "tool_use" for b in content)

    @classmethod
    def _is_tool_result(cls, message: dict) -> bool:
        content = message.get("content")
        return (
            message.get("role") == "user"
            and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        )

    @staticmethod
    def _unseen_positions(messages: list) -> set[tuple[int, int]]:
        last_assistant = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if messages[i].get("role") == "assistant"),
            -1,
        )
        return {
            (mi, bi)
            for mi in range(last_assistant + 1, len(messages))
            if messages[mi].get("role") == "user"
            and isinstance(messages[mi].get("content"), list)
            for bi, b in enumerate(messages[mi]["content"])
            if isinstance(b, dict) and b.get("type") == "tool_result"
        }

    # --- disk I/O ---

    def _write_transcript(self, messages: list) -> Path:
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        path = self._transcript_dir / f"transcript_{uuid.uuid4().hex}.jsonl"
        with path.open("x", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")
        return path

    def _save_output(self, tool_use_id: str, output: str) -> Path:
        self._tool_results_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(tool_use_id))[:120] or "unknown"
        path = self._tool_results_dir / f"{safe_id}.txt"
        path.write_text(output, encoding="utf-8")
        return path

    def _persisted_path(self, output: str) -> str | None:
        prefix = "[Earlier tool result saved at "
        if output.startswith(prefix) and output.endswith("]"):
            candidate = output.removeprefix(prefix).removesuffix("]")
            path = Path(candidate)
            if path.resolve().is_relative_to(self._tool_results_dir.resolve()) and path.is_file():
                return str(path)
        return None

    def _persist_if_large(self, tool_use_id: str, output: str) -> str:
        if len(output) <= self.LARGE_RESULT_CHAR_LIMIT:
            return output
        path = self._save_output(tool_use_id, output)
        return f"[Earlier tool result saved at {path}]\nPreview:\n{output[:2000]}"

    # --- step 1: tool_result_budget ---
    # Persist oversized results from the latest tool batch before they enter context.

    def _tool_result_budget(self, messages: list) -> list:
        if not messages:
            return messages
        last = messages[-1]
        if last.get("role") != "user" or not isinstance(last.get("content"), list):
            return messages
        blocks = [b for b in last["content"]
                  if isinstance(b, dict) and b.get("type") == "tool_result"]
        total = sum(len(str(b.get("content", ""))) for b in blocks)
        if total <= self.TOOL_RESULT_BATCH_CHAR_LIMIT:
            return messages
        for block in sorted(blocks, key=lambda b: len(str(b.get("content", ""))), reverse=True):
            if total <= self.TOOL_RESULT_BATCH_CHAR_LIMIT:
                break
            output = str(block.get("content", ""))
            if len(output) <= self.LARGE_RESULT_CHAR_LIMIT:
                continue
            block["content"] = self._persist_if_large(block.get("tool_use_id", "unknown"), output)
            total = sum(len(str(b.get("content", ""))) for b in blocks)
        return messages

    # --- step 2: snip_compact ---
    # Archive the middle of the conversation once message count exceeds the trigger.

    def _is_archive_marker(self, message: dict) -> bool:
        content = message.get("content")
        if not isinstance(content, str):
            return False
        m = re.fullmatch(r"\[\d+ messages archived at (.+)\]", content)
        if not m:
            return False
        path = Path(m.group(1))
        return path.resolve().is_relative_to(self._transcript_dir.resolve()) and path.is_file()

    def _snip_compact(self, messages: list) -> list:
        if len(messages) < self.SNIP_TRIGGER:
            return messages
        head_end = 3
        tail_start = len(messages) - (self.SNIP_TARGET - head_end - 1)
        if self._has_tool_use(messages[head_end - 1]):
            while head_end < tail_start and self._is_tool_result(messages[head_end]):
                head_end += 1
        if (tail_start > 0
                and self._is_tool_result(messages[tail_start])
                and self._has_tool_use(messages[tail_start - 1])):
            tail_start -= 1
        if head_end >= tail_start:
            return messages
        middle = messages[head_end:tail_start]
        if len(middle) == 1 and self._is_archive_marker(middle[0]):
            return messages
        transcript_path = self._write_transcript(messages)
        marker = {"role": "user",
                  "content": f"[{tail_start - head_end} messages archived at {transcript_path}]"}
        return [*messages[:head_end], marker, *messages[tail_start:]]

    # --- step 3: micro_compact + fit_tool_results ---
    # Replace seen tool results with disk references; keep the most recent few intact.

    def _micro_compact(self, messages: list, target_chars: int | None = None) -> list:
        results = [
            (mi, bi, b)
            for mi, msg in enumerate(messages)
            if msg.get("role") == "user" and isinstance(msg.get("content"), list)
            for bi, b in enumerate(msg["content"])
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        unseen = self._unseen_positions(messages)
        consumed = [e for e in results if e[:2] not in unseen]
        for _, _, block in consumed[:-self.KEEP_RECENT_RESULTS]:
            if target_chars is not None and _estimate_chars(messages) <= target_chars:
                break
            content = str(block.get("content", ""))
            if len(content) <= 120:
                continue
            saved = self._persisted_path(content) or str(
                self._save_output(block.get("tool_use_id", "unknown"), content))
            block["content"] = f"[Earlier tool result saved at {saved}]"
        return messages

    def _fit_tool_results(self, messages: list, target_chars: int) -> list:
        results = [
            b
            for msg in messages
            if msg.get("role") == "user" and isinstance(msg.get("content"), list)
            for b in msg["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        for block in sorted(results, key=lambda b: len(str(b.get("content", ""))), reverse=True):
            if _estimate_chars(messages) <= target_chars:
                break
            output = str(block.get("content", ""))
            saved = self._persisted_path(output) or str(
                self._save_output(block.get("tool_use_id", "unknown"), output))
            replacement = f"[Earlier tool result saved at {saved}]\nPreview:\n{output[:1000]}"
            if len(replacement) < len(output):
                block["content"] = replacement
        return messages

    # --- step 4: compact_history ---
    # LLM summarization as last resort; replaces entire history with a summary message.

    def _summarize(self, messages: list, summarize_fn: Callable[[list], str]) -> str:
        return summarize_fn(messages)

    def _compact_history(self, messages: list, active_request: str,
                         summarize_fn: Callable[[list], str]) -> list:
        transcript = self._write_transcript(messages)
        print(f"[compact: transcript saved at {transcript}]")
        summary = self._summarize(messages, summarize_fn)
        return [{"role": "user", "content": (
            f"[Compacted]\n\nCurrent user request:\n{active_request}\n\n"
            f"Conversation summary (reference only):\n{summary}\n\n"
            f"Full transcript: {transcript}"
        )}]

    # --- reactive compact (API returned prompt_too_long) ---

    def reactive_compact(self, messages: list, active_request: str,
                         summarize_fn: Callable[[list], str]) -> list:
        transcript = self._write_transcript(messages)
        tail_start = max(0, len(messages) - self.KEEP_RECENT_MESSAGES)
        if (tail_start > 0
                and self._is_tool_result(messages[tail_start])
                and self._has_tool_use(messages[tail_start - 1])):
            tail_start -= 1
        old = messages[:tail_start] if tail_start else messages
        summary = self._summarize(old, summarize_fn)
        msg = {"role": "user", "content": (
            f"[Reactive compact]\n\nCurrent user request:\n{active_request}\n\n"
            f"Conversation summary (reference only):\n{summary}\n\n"
            f"Full transcript: {transcript}"
        )}
        return [msg, *messages[tail_start:]] if tail_start else [msg]

    # --- main entry point ---

    def prepare(self, messages: list, active_request: str,
                summarize_fn: Callable[[list], str]) -> list:
        messages = self._tool_result_budget(messages)
        before_snip = messages
        messages = self._snip_compact(messages)
        if messages is not before_snip:
            active_marker = f"Current user request:\n{active_request}"
            if not any(
                msg.get("role") == "user"
                and isinstance(msg.get("content"), str)
                and (msg["content"] == active_request or active_marker in msg["content"])
                for msg in messages
            ):
                messages.append({"role": "user", "content": active_request})
        if _estimate_chars(messages) > self.CONTEXT_CHAR_LIMIT:
            target = int(self.CONTEXT_CHAR_LIMIT * 0.8)
            messages = self._micro_compact(messages, target)
            if _estimate_chars(messages) > self.CONTEXT_CHAR_LIMIT:
                messages = self._fit_tool_results(messages, target)
            if _estimate_chars(messages) > self.CONTEXT_CHAR_LIMIT:
                print("[auto compact]")
                messages = self._compact_history(messages, active_request, summarize_fn)
        return messages

    # --- kept for compatibility with server.py emit calls ---

    def stats(self, history: list, system: str = "") -> dict:
        chars = _estimate_chars(history) + len(system)
        return {
            "historyLen": len(history),
            "estimatedChars": chars,
            "contextCharLimit": self.CONTEXT_CHAR_LIMIT,
            "willCompress": chars >= self.CONTEXT_CHAR_LIMIT,
        }

    def to_system_prompt(self) -> str:
        return ""
