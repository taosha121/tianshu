from lingjiyidong.agent import Agent

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _cjk_len(s):
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _print_banner():
    W = 36

    def row(plain="", colored=None, pad=2):
        if colored is None:
            colored = plain
        prefix = " " * pad
        fill = W - _cjk_len(prefix + plain)
        return f"  {_CYAN}│{_RESET}{prefix}{colored}{' ' * max(0, fill)}{_CYAN}│{_RESET}"

    print()
    print(f"  {_CYAN}╭{'─' * W}╮{_RESET}")
    print(row())
    print(row("   ╭────────╮",              f"   {_CYAN}╭────────╮{_RESET}"))
    print(row("   │ ◉    ◉ │",              f"   {_CYAN}│{_RESET} ◉    ◉ {_CYAN}│{_RESET}"))
    print(row("   │   ──   │",              f"   {_CYAN}│{_RESET}   ──   {_CYAN}│{_RESET}"))
    print(row("   ╰───┬────╯",              f"   {_CYAN}╰───┬────╯{_RESET}"))
    print(row("       │",                   f"       {_CYAN}│{_RESET}"))
    print(row())
    print(row("灵机一动  v0.1.0",           f"{_BOLD}{_GREEN}灵机一动{_RESET}  {_DIM}v0.1.0{_RESET}"))
    print(row("灵光乍现，代码自成",         f"{_DIM}灵光乍现，代码自成{_RESET}"))
    print(row())
    print(row("/plan <goal>   启用任务规划模式", f"{_DIM}/plan <goal>{_RESET}   启用任务规划模式"))
    print(row("exit           退出",         f"{_DIM}exit{_RESET}           退出"))
    print(row())
    print(f"  {_CYAN}╰{'─' * W}╯{_RESET}")
    print()


def main():
    agent = Agent()
    _print_banner()
    while True:
        user_input = input("\nYou: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input.startswith("/plan "):
            goal = user_input[6:].strip()
            result = agent.execute(goal)
            print(f"\nAgent: {result}")
        else:
            response = agent.chat(user_input)
            print(f"Agent: {response}")


if __name__ == "__main__":
    main()
