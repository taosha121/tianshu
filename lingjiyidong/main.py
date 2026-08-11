import os

from lingjiyidong.agent import Agent
from lingjiyidong.agent.skills import SkillLoader

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
    W = 58          # 外层 │ 之间的内容显示宽度
    MW = W - 4      # 中层 ┆ 之间的内容显示宽度（左右各 " ┆" = 2 字符，共 -4）
    IW = W - 8      # 内层 · 之间的内容显示宽度（左右各 " ┆ ·" = 4 字符，共 -8）

    def outer(s):
        # 外层青色实线边框
        return f"  {_CYAN}│{_RESET}{s}{_CYAN}│{_RESET}"

    def mid(s):
        # 中层黄色虚线边框
        return f"  {_CYAN}│{_RESET} {_YELLOW}┆{_RESET}{s}{_YELLOW}┆{_RESET} {_CYAN}│{_RESET}"

    def inner(s):
        # 内层品红色点线边框
        return f"  {_CYAN}│{_RESET} {_YELLOW}┆{_RESET} {_MAGENTA}·{_RESET}{s}{_MAGENTA}·{_RESET} {_YELLOW}┆{_RESET} {_CYAN}│{_RESET}"

    def fill(plain, colored, width):
        # 用空格把 colored 右填充到 width 显示字符
        return colored + " " * max(0, width - _cjk_len(plain))

    def content(lp, lc, rp="", rc=""):
        # 双列内容行：左列机器人固定 12 显示字符，右列文字填满剩余
        # 传入 inner()，所以总显示宽度须等于 IW
        left = fill(lp, lc, 12)                     # 左列 12 字符
        right = fill(rp, rc, IW - 12 - 2)           # 右列：IW - 左列 - 两侧各1空格
        return inner(f" {left} {right}")

    def cmd(plain, colored):
        # 命令提示行，同样进 inner()，总显示宽度 = IW
        return inner(f" {fill(plain, colored, IW - 2)} ")

    print()
    print(f"  {_CYAN}╭{'─' * W}╮{_RESET}")
    print(outer(" " * W))
    # 中层边框顶，内容宽 W，虚线部分 = W - 4（两端各 " ╭" " ╮" 共4字符）
    print(outer(f" {_YELLOW}╭{'╌' * (W - 4)}╮{_RESET} "))
    print(mid(" " * MW))
    # 内层边框顶，内容宽 MW，点线部分 = MW - 4 = IW
    print(mid(f" {_MAGENTA}╭{'·' * IW}╮{_RESET} "))
    print(inner(" " * IW))

    # 机器人 + 文字
    print(content("╭────────╮",  f"{_CYAN}╭────────╮{_RESET}",
                  "灵机一动  v0.3.0", f"{_BOLD}{_GREEN}灵机一动{_RESET}  {_DIM}v0.3.0{_RESET}"))
    print(content("│ ◉    ◉ │",  f"{_CYAN}│{_RESET} {_YELLOW}◉{_RESET}    {_YELLOW}◉{_RESET} {_CYAN}│{_RESET}",
                  "灵光乍现，代码自成", f"{_DIM}灵光乍现，代码自成{_RESET}"))
    print(content("│   ──   │",  f"{_CYAN}│{_RESET}   {_MAGENTA}──{_RESET}   {_CYAN}│{_RESET}",
                  "Spark once. Code forever.", f"{_MAGENTA}Spark once. Code forever.{_RESET}"))
    print(content("╰───┬────╯",  f"{_CYAN}╰───┬────╯{_RESET}"))
    print(content("    │",       f"    {_CYAN}│{_RESET}"))

    print(inner(" " * IW))
    print(cmd("/<skill>       直接执行预定义 skill",
              f"{_YELLOW}/<skill>{_RESET}       直接执行预定义 skill"))
    print(cmd("exit           退出",
              f"{_YELLOW}exit{_RESET}           退出"))
    print(inner(" " * IW))

    # 内层边框底
    print(mid(f" {_MAGENTA}╰{'·' * IW}╯{_RESET} "))
    print(mid(" " * MW))
    # 中层边框底
    print(outer(f" {_YELLOW}╰{'╌' * (W - 4)}╯{_RESET} "))
    print(outer(" " * W))
    print(f"  {_CYAN}╰{'─' * W}╯{_RESET}")
    print()


def main():
    agent = Agent(cwd=os.getcwd())
    loader = SkillLoader()
    _print_banner()
    print(f"  {_DIM}工作目录: {os.getcwd()}{_RESET}")
    print()
    while True:
        user_input = input("\nYou: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.startswith("/"):
            # skill 手动触发，跳过路由直接执行预定义步骤
            skill_name = user_input[1:].strip()
            skill = loader.find(skill_name)
            if skill:
                result = agent.execute_skill(skill)
                print(f"\nAgent: {result}")
            else:
                available = ", ".join(f"/{s.name}" for s in loader.all())
                print(f"  未知命令: /{skill_name}" + (f"  可用: {available}" if available else ""))
        else:
            # 普通输入，模型自己判断是否需要 plan
            result = agent.execute(user_input)
            print(f"\nAgent: {result}")


if __name__ == "__main__":
    main()
