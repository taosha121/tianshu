from conftest import FakeProvider, ProviderResponse, ToolCall, build_agent

from tianshu.agent.hooks import HookOutcome, HookRegistry


def _tool_use_then_end(tool_name, tool_input, final="done"):
    return FakeProvider(responses=[
        ProviderResponse(stop_reason="tool_use", text="",
                         tool_calls=[ToolCall(id="c1", name=tool_name, input=tool_input)]),
        ProviderResponse(stop_reason="end_turn", text=final),
    ])


def _result_blocks(agent):
    blocks = []
    for msg in agent.history:
        content = msg.get("content")
        if isinstance(content, list):
            blocks += [b for b in content if isinstance(b, dict)
                       and b.get("type") == "tool_result"]
    return blocks


# --- basic control flow ---

def test_end_turn_returns_text(tmp_path):
    agent = build_agent(FakeProvider(responses=[
        ProviderResponse(stop_reason="end_turn", text="hello")]), tmp_path)
    assert agent.chat("hi") == "hello"
    assert agent.history[0] == {"role": "user", "content": "hi"}


def test_tool_use_feeds_result_and_continues(tmp_path):
    provider = _tool_use_then_end("nope_tool", {"x": 1})
    agent = build_agent(provider, tmp_path)
    out = agent.chat("do it")
    assert out == "done"
    assert provider.call_count == 2
    blocks = _result_blocks(agent)
    assert len(blocks) == 1
    assert "Unknown tool: nope_tool" in blocks[0]["content"]


def test_max_tokens_appends_notice(tmp_path):
    agent = build_agent(FakeProvider(responses=[
        ProviderResponse(stop_reason="max_tokens", text="partial")]), tmp_path)
    assert agent.chat("x").endswith("[response truncated: max_tokens reached]")


def test_refusal(tmp_path):
    agent = build_agent(FakeProvider(responses=[
        ProviderResponse(stop_reason="refusal", text="")]), tmp_path)
    assert agent.chat("x") == "[model refused to respond]"


def test_max_iterations_guard(tmp_path):
    # provider always wants another tool call -> loop must bail out
    provider = FakeProvider(responses=[
        ProviderResponse(stop_reason="tool_use", text="",
                         tool_calls=[ToolCall(id="c", name="nope", input={})])])
    agent = build_agent(provider, tmp_path, max_iterations=3)
    out = agent.chat("loop")
    assert out == "Maximum iterations reached without completing the task."
    assert provider.call_count == 3


# --- permission integration ---

def test_denied_command_surfaces_in_tool_result(tmp_path):
    provider = _tool_use_then_end("bash", {"command": "rm -rf /"})
    agent = build_agent(provider, tmp_path)
    agent.chat("wipe")
    blocks = _result_blocks(agent)
    assert "[Permission denied]" in blocks[0]["content"]


def test_permission_cb_decline_surfaces(tmp_path):
    provider = _tool_use_then_end("write_file", {"path": "a.py", "content": "x"})
    agent = build_agent(provider, tmp_path, permission_cb=lambda n, i, r: False)
    agent.chat("write")
    blocks = _result_blocks(agent)
    assert "declined" in blocks[0]["content"]


# --- hook integration ---

def test_pre_hook_block_surfaces_in_tool_result(tmp_path):
    hooks = HookRegistry()
    hooks.register("PreToolUse", "bash",
                   lambda n, i: HookOutcome(block=True, reason="no shell here"))
    provider = _tool_use_then_end("bash", {"command": "ls"})
    agent = build_agent(provider, tmp_path, hooks=hooks)
    agent.chat("run")
    blocks = _result_blocks(agent)
    assert "[Blocked by hook] no shell here" in blocks[0]["content"]
