import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Decision(Enum):
    ALLOW = "allow"   # run automatically
    ASK = "ask"       # require user confirmation
    DENY = "deny"     # never run


@dataclass
class PermissionRule:
    decision: Decision
    tool: str = "*"                                   # tool name, "*" matches any
    arg: str | None = None                            # which input field to match; None = whole input
    pattern: str | None = None                        # regex matched against the target
    predicate: Callable[[str, dict], bool] | None = None  # custom matcher, takes precedence over pattern
    reason: str = ""
    _rx: "re.Pattern | None" = field(init=False, default=None, repr=False)

    def __post_init__(self):
        self._rx = re.compile(self.pattern) if self.pattern else None

    def matches(self, tool_name: str, inp: dict) -> bool:
        if self.tool != "*" and self.tool != tool_name:
            return False
        if self.predicate is not None:
            return self.predicate(tool_name, inp)
        if self._rx is None:
            return True
        target = str(inp.get(self.arg, "")) if self.arg else str(inp)
        return self._rx.search(target) is not None


_READONLY_TOOLS = {
    "read_file", "get_outline", "find_symbol", "grep_files",
    "list_files", "read_memory", "web_search", "web_fetch",
}

# Read-only commands: auto-allowed when the leading word is whitelisted
# and there are no chaining/redirection operators.
_SAFE_BASH_LEAD = re.compile(
    r"^\s*(?:ls|pwd|cat|echo|head|tail|wc|which|whoami|date|env|tree|file|stat|"
    r"du|df|uname|rg|grep|find|git\s+(?:status|diff|log|show|branch|remote))\b"
)
_BASH_CHAIN = re.compile(r"[;&|`]|\$\(|>>|>")


def _bash_cmd(inp: dict) -> str:
    return str(inp.get("command", ""))


def _is_safe_bash(_tool: str, inp: dict) -> bool:
    cmd = _bash_cmd(inp)
    return bool(_SAFE_BASH_LEAD.match(cmd)) and not _BASH_CHAIN.search(cmd)


_CATASTROPHIC = [
    (re.compile(r":\(\)\s*\{.*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\bmkfs\b"), "formats a filesystem"),
    (re.compile(r"\bdd\b[^;&|]*\bof=/dev/"), "writes directly to a block device"),
    (re.compile(r">\s*/dev/sd[a-z]"), "overwrites a disk device"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "shuts down or reboots the machine"),
]


def _is_catastrophic_bash(_tool: str, inp: dict) -> tuple[bool, str]:
    cmd = _bash_cmd(inp)
    for rx, why in _CATASTROPHIC:
        if rx.search(cmd):
            return True, why
    # rm carrying both -r and -f and targeting root / home / a bare wildcard
    if re.search(r"\brm\b", cmd):
        has_r = re.search(r"\brm\b[^;&|]*\s-[a-zA-Z]*r", cmd) is not None
        has_f = re.search(r"\brm\b[^;&|]*\s-[a-zA-Z]*f", cmd) is not None
        if has_r and has_f and re.search(r"\s(/|~|/\*|\$HOME|\*)(\s|$)", cmd):
            return True, "recursively deletes root or home directory"
    return False, ""


def _catastrophic_rule(_tool: str, inp: dict) -> bool:
    return _is_catastrophic_bash(_tool, inp)[0]


def _default_rules() -> list[PermissionRule]:
    return [
        # -- DENY: catastrophic operations, never run --
        PermissionRule(Decision.DENY, tool="bash", predicate=_catastrophic_rule,
                       reason="catastrophic shell command"),

        # -- ALLOW: read-only tools pass through unconditionally --
        PermissionRule(Decision.ALLOW,
                       predicate=lambda t, i: t in _READONLY_TOOLS),
        PermissionRule(Decision.ALLOW, tool="save_memory"),
        PermissionRule(Decision.ALLOW, tool="delete_memory"),
        # read-only shell commands
        PermissionRule(Decision.ALLOW, tool="bash", predicate=_is_safe_bash),

        # -- ASK: writes / command execution need confirmation --
        PermissionRule(Decision.ASK, tool="write_file", arg="path", pattern=r"(^|/)\.env",
                       reason="writes to a sensitive .env file"),
        PermissionRule(Decision.ASK, tool="bash", reason="runs a shell command"),
        PermissionRule(Decision.ASK, tool="write_file", reason="writes a file"),
        PermissionRule(Decision.ASK, tool="edit_file", reason="modifies a file"),
        PermissionRule(Decision.ASK, tool="create_directory", reason="creates a directory"),
    ]


class PermissionEngine:
    """Decides the permission policy for a tool call; the first matching rule wins."""

    def __init__(self, extra_rules: list[PermissionRule] | None = None):
        self.rules = list(extra_rules or []) + _default_rules()

    def check(self, tool_name: str, tool_input: dict) -> tuple[Decision, str]:
        # Catastrophic bash returns a DENY with its specific reason first.
        if tool_name == "bash":
            bad, why = _is_catastrophic_bash(tool_name, tool_input)
            if bad:
                return Decision.DENY, why
        for rule in self.rules:
            if rule.matches(tool_name, tool_input):
                return rule.decision, rule.reason
        return Decision.ALLOW, ""
