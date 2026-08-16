import os

import pyfiglet

from tianshu.agent import Agent
from tianshu.agent.skills import SkillLoader

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_YELLOW = "\033[33m"


def _cjk_len(s):
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _cjk_center(s, width):
    pad = max(0, width - _cjk_len(s))
    return " " * (pad // 2) + s + " " * (pad - pad // 2)


def _print_banner():
    W = 80
    raw_lines = pyfiglet.figlet_format("TIANSHU", font="banner3", width=W).splitlines()
    stripped   = [line.rstrip() for line in raw_lines]
    max_w      = max(len(line) for line in stripped)
    pad        = " " * max(0, (W - max_w) // 2)
    logo       = "\n".join(_CYAN + pad + line + _RESET for line in stripped)
    rule   = _DIM + "=" * W + _RESET
    slogan = _BOLD + _YELLOW + _cjk_center("枢   运   北   斗   ，   御   动   九   天", W) + _RESET
    info   = _DIM + "Tianshu  v0.3.0".center(W) + _RESET
    print(f"\n{rule}\n{slogan}\n{rule}\n{logo}\n{rule}\n{info}\n{rule}\n")


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
