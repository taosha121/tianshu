from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResponse:
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "pause_turn" | "refusal"
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(ABC):
    @abstractmethod
    def create_client(self): ...

    @abstractmethod
    def to_tool_schemas(self, tools: list) -> list: ...

    @abstractmethod
    def call(
        self,
        client,
        model: str,
        system: str,
        messages: list,
        tool_schemas: list,
    ) -> ProviderResponse: ...

    @abstractmethod
    def summarize(self, client, model: str, messages: list) -> str: ...

    @abstractmethod
    def complete(self, client, model: str, user_message: str, system: str = "") -> str: ...
