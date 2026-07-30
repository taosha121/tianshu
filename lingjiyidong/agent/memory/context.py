import json
from typing import Any

_CHARS_PER_TOKEN = 1.5


def _estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) / _CHARS_PER_TOKEN
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(json.dumps(block)) / _CHARS_PER_TOKEN
                else:
                    total += len(str(block)) / _CHARS_PER_TOKEN
    return int(total)


class ContextManager:
    def __init__(
        self,
        max_tokens: int = 80_000,
        compress_threshold: float = 0.75,
        min_window: int = 4,
    ):
        self.max_tokens = max_tokens
        self.compress_threshold = compress_threshold
        self.min_window = min_window  # 压缩后至少保留最近 N 条消息
        self._summary: str = ""

    @property
    def system_addendum(self) -> str:
        if self._summary:
            return f"\n\n--- 早期对话摘要 ---\n{self._summary}\n--- 摘要结束 ---"
        return ""

    def maybe_compress(self, history: list[dict], client: Any, model: str) -> list[dict]:
        """检查 token 用量，超过阈值时压缩旧消息，返回新 history。"""
        estimated = _estimate_tokens(history)
        threshold = int(self.max_tokens * self.compress_threshold)
        if estimated < threshold:
            return history

        keep = self.min_window
        to_compress = history[:-keep] if len(history) > keep else []
        if not to_compress:
            return history

        new_summary = self._do_compress(to_compress, client, model)
        self._summary = new_summary
        return history[-keep:]

    def _do_compress(self, messages: list[dict], client: Any, model: str) -> str:
        serialized = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            parts.append(block["text"])
                        elif btype == "tool_use":
                            parts.append(f"[工具调用: {block['name']}({block.get('input', {})})]")
                        elif btype == "tool_result":
                            parts.append(f"[工具结果: {block.get('content', '')}]")
                    else:
                        parts.append(str(block))
                text = " ".join(parts)
            else:
                text = str(content)
            serialized.append(f"{role}: {text}")

        conversation_text = "\n".join(serialized)

        existing = f"已有摘要：\n{self._summary}\n\n" if self._summary else ""
        prompt = (
            f"{existing}"
            f"请将以下对话压缩为简洁的摘要，保留关键信息、决策和结论，去除冗余内容：\n\n"
            f"{conversation_text}"
        )

        response = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
