from tianshu.agent.hooks.core import (
    POST,
    PRE,
    HookOutcome,
    HookRegistry,
    load_shell_hooks,
    _make_post_shell_hook,
    _make_pre_shell_hook,
    _parse_stdout,
)


# --- in-process hook dispatch ---

def test_pre_hook_blocks_and_skips():
    reg = HookRegistry()

    @reg.pre("bash")
    def deny(name, inp):
        return HookOutcome(block=True, reason="nope")

    inp, blocked = reg.run_pre("bash", {"command": "ls"})
    assert blocked == "nope"


def test_pre_hook_matcher_scopes_by_tool():
    reg = HookRegistry()

    @reg.pre("bash")
    def deny(name, inp):
        return HookOutcome(block=True, reason="nope")

    _, blocked = reg.run_pre("write_file", {"path": "a"})
    assert blocked is None


def test_pre_hook_input_rewrite_chains():
    reg = HookRegistry()

    @reg.pre("*")
    def first(name, inp):
        return HookOutcome(input={**inp, "a": 1})

    @reg.pre("*")
    def second(name, inp):
        assert inp["a"] == 1  # sees the first hook's rewrite
        return HookOutcome(input={**inp, "b": 2})

    inp, blocked = reg.run_pre("bash", {"command": "ls"})
    assert blocked is None
    assert inp["a"] == 1 and inp["b"] == 2


def test_post_hook_result_rewrite_chains():
    reg = HookRegistry()

    @reg.post("*")
    def up(name, inp, result):
        return HookOutcome(result=result.upper())

    @reg.post("*")
    def bang(name, inp, result):
        return HookOutcome(result=result + "!")

    assert reg.run_post("bash", {}, "hi") == "HI!"


def test_failing_hook_is_isolated():
    reg = HookRegistry()

    @reg.pre("*")
    def boom(name, inp):
        raise RuntimeError("bad hook")

    @reg.pre("*")
    def ok(name, inp):
        return HookOutcome(input={**inp, "survived": True})

    inp, blocked = reg.run_pre("bash", {"command": "ls"})
    assert blocked is None
    assert inp["survived"] is True


# --- stdout parsing ---

def test_parse_stdout_variants():
    assert _parse_stdout("") == {}
    assert _parse_stdout("not json") == {}
    assert _parse_stdout("[1, 2]") == {}          # valid json, not a dict
    assert _parse_stdout('{"input": {"x": 1}}') == {"input": {"x": 1}}


# --- shell hooks (real subprocess) ---

def test_shell_pre_hook_blocks_on_exit_2():
    reg = HookRegistry()
    reg.register(PRE, "*", _make_pre_shell_hook(">&2 echo denied-by-shell; exit 2"))
    _, blocked = reg.run_pre("bash", {"command": "ls"})
    assert blocked == "denied-by-shell"


def test_shell_pre_hook_rewrites_input():
    reg = HookRegistry()
    reg.register(PRE, "*", _make_pre_shell_hook(
        "echo '{\"input\": {\"command\": \"safe\"}}'"))
    inp, blocked = reg.run_pre("bash", {"command": "danger"})
    assert blocked is None
    assert inp == {"command": "safe"}


def test_shell_post_hook_rewrites_result():
    reg = HookRegistry()
    reg.register(POST, "*", _make_post_shell_hook(
        "echo '{\"result\": \"rewritten\"}'"))
    assert reg.run_post("bash", {}, "original") == "rewritten"


def test_load_shell_hooks_from_config(tmp_path):
    cfg_dir = tmp_path / ".tianshu"
    cfg_dir.mkdir()
    (cfg_dir / "hooks.json").write_text(
        '{"PreToolUse": [{"matcher": "bash", "command": '
        '"echo \'{\\"input\\": {\\"command\\": \\"patched\\"}}\'"}]}',
        encoding="utf-8",
    )
    reg = HookRegistry()
    load_shell_hooks(reg, str(tmp_path))
    inp, _ = reg.run_pre("bash", {"command": "raw"})
    assert inp == {"command": "patched"}
    # matcher scoping still applies to loaded hooks
    other, _ = reg.run_pre("write_file", {"path": "x"})
    assert other == {"path": "x"}
