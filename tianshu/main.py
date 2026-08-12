import os

from tianshu.agent import Agent
from tianshu.agent.skills import SkillLoader

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"


def _cjk_len(s):
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _print_banner():
    W = 58
    MW = W - 4
    IW = W - 8

    def outer(s):
        return f"  {_CYAN}│{_RESET}{s}{_CYAN}│{_RESET}"

    def mid(s):
        return f"  {_CYAN}│{_RESET} {_YELLOW}┆{_RESET}{s}{_YELLOW}┆{_RESET} {_CYAN}│{_RESET}"

    def inner(s):
        return f"  {_CYAN}│{_RESET} {_YELLOW}┆{_RESET} {_MAGENTA}·{_RESET}{s}{_MAGENTA}·{_RESET} {_YELLOW}┆{_RESET} {_CYAN}│{_RESET}"

    def fill(plain, colored, width):
        return colored + " " * max(0, width - _cjk_len(plain))

    def content(lp, lc, rp="", rc=""):
        left = fill(lp, lc, 12)
        right = fill(rp, rc, IW - 12 - 2)
        return inner(f" {left} {right}")

    def cmd(plain, colored):
        return inner(f" {fill(plain, colored, IW - 2)} ")

    print()
    print(f"  {_CYAN}╭{'─' * W}╮{_RESET}")
    print(outer(" " * W))
    print(outer(f" {_YELLOW}╭{'╌' * (W - 4)}╮{_RESET} "))
    print(mid(" " * MW))
    print(mid(f" {_MAGENTA}╭{'·' * IW}╮{_RESET} "))
    print(inner(" " * IW))

    print(content("·──◆",  f"{_DIM}·──{_RESET}{_YELLOW}◆{_RESET}",
                  "天枢  v0.3.0", f"{_BOLD}{_GREEN}天枢{_RESET}  {_DIM}v0.3.0{_RESET}"))
    print(content("│  │",   f"{_DIM}│  │{_RESET}",
                  "执枢御变", f"{_DIM}执枢御变{_RESET}"))
    print(content("·──·",   f"{_DIM}·──·{_RESET}"))
    print(content("    ·",  f"    {_DIM}·{_RESET}"))
    print(content("     ·─·", f"     {_DIM}·─·{_RESET}"))

    print(inner(" " * IW))
    print(cmd("/<skill>       run a predefined skill directly",
              f"{_YELLOW}/<skill>{_RESET}       run a predefined skill directly"))
    print(cmd("exit           quit",
              f"{_YELLOW}exit{_RESET}           quit"))
    print(inner(" " * IW))

    print(mid(f" {_MAGENTA}╰{'·' * IW}╯{_RESET} "))
    print(mid(" " * MW))
    print(outer(f" {_YELLOW}╰{'╌' * (W - 4)}╯{_RESET} "))
    print(outer(" " * W))
    print(f"  {_CYAN}╰{'─' * W}╯{_RESET}")
    print()


def main():
    agent = Agent(cwd=os.getcwd())
    loader = SkillLoader()
    _print_banner()
    print(f"  {_DIM}Working directory: {os.getcwd()}{_RESET}")
    print()
    while True:
        user_input = input("\nYou: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.startswith("/"):
            skill_name = user_input[1:].strip()
            skill = loader.find(skill_name)
            if skill:
                result = agent.execute_skill(skill)
                print(f"\nAgent: {result}")
            else:
                available = ", ".join(f"/{s.name}" for s in loader.all())
                print(f"  Unknown command: /{skill_name}" + (f"  Available: {available}" if available else ""))
        else:
            result = agent.execute(user_input)
            print(f"\nAgent: {result}")


if __name__ == "__main__":
    main()
