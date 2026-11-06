from tianshu.agent.provider.base import Provider, ProviderResponse, ToolCall


class FakeProvider(Provider):
    """Scriptable provider for deterministic tests.

    - `call` returns queued ProviderResponses in order (last one repeats).
    - `complete` / `summarize` return canned strings.
    """

    def __init__(self, responses=None, complete_text="", summary="summary"):
        self._responses = list(responses or [])
        self._complete_text = complete_text
        self._summary = summary
        self.call_count = 0
        self.complete_prompts = []

    def create_client(self):
        return object()

    def to_tool_schemas(self, tools):
        return [{"name": getattr(t, "name", str(t))} for t in tools]

    def call(self, client, model, system, messages, tool_schemas):
        self.call_count += 1
        if not self._responses:
            return ProviderResponse(stop_reason="end_turn", text="")
        idx = min(self.call_count - 1, len(self._responses) - 1)
        return self._responses[idx]

    def summarize(self, client, model, messages):
        return self._summary

    def complete(self, client, model, user_message, system=""):
        self.complete_prompts.append(user_message)
        return self._complete_text


__all__ = ["FakeProvider", "ProviderResponse", "ToolCall", "build_agent"]


def build_agent(provider, cwd, *, max_iterations=20, permission_cb=None, hooks=None):
    """Assemble a minimal Agent without touching network/API-key-dependent __init__.

    Wires exactly the attributes chat() / _dispatch_tool() read, so the agent
    loop can be driven by a scripted FakeProvider.
    """
    from tianshu.agent.core import Agent
    from tianshu.agent.hooks import HookRegistry
    from tianshu.agent.memory import ContextManager, LongTermMemory
    from tianshu.agent.permission import PermissionEngine
    from tianshu.agent.tools import TOOLS

    agent = Agent.__new__(Agent)
    agent.provider = provider
    agent.client = None
    agent.model = "fake"
    agent._tool_schemas = []
    agent._tool_map = {t.name: t for t in TOOLS}
    agent.cwd = str(cwd)
    agent.history = []
    agent.todos = []
    agent.context = ContextManager(cwd=str(cwd))
    agent.longterm = LongTermMemory(str(cwd))
    agent.permission = PermissionEngine()
    agent.hooks = hooks if hooks is not None else HookRegistry()
    agent._system_prompt = "SYSTEM"
    agent._summarize_fn = lambda msgs: "summary"
    agent._agent_id = "test"
    agent._agent_type = "main"
    agent._emit = None
    agent._permission_cb = permission_cb
    agent._max_iterations = max_iterations
    return agent
