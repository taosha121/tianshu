import os
import traceback

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog
from textual import work

from tianshu.agent import Agent
from tianshu.agent.core import _format_tool_call


class TianshuApp(App):
    CSS = """
    RichLog {
        height: 1fr;
        padding: 1 2;
        scrollbar-gutter: stable;
    }
    Input {
        dock: bottom;
        margin: 0 2 1 2;
    }
    """

    TITLE = "天枢"
    SUB_TITLE = "枢运北斗，御动九天"
    BINDINGS = [Binding("ctrl+c", "quit", "退出")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(highlight=True, markup=True, wrap=True)
        yield Input(placeholder="输入指令...")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)

        def emit(event: dict) -> None:
            if event.get("type") == "tool_call":
                label = _format_tool_call(event["name"], event["input"])
                self.call_from_thread(log.write, f"  [dim]· {label}[/dim]")

        self._agent = Agent(cwd=os.getcwd(), _emit=emit)
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]▶[/bold cyan] {escape(user_input)}")
        event.input.clear()
        self._run(user_input)

    @work(thread=True)
    def _run(self, user_input: str) -> None:
        log = self.query_one(RichLog)
        try:
            result = self._agent.execute(user_input)
            self.call_from_thread(log.write, f"[bold green]◆[/bold green] {escape(result)}\n")
        except Exception:
            tb = escape(traceback.format_exc())
            self.call_from_thread(log.write, f"[bold red]✗ Error:[/bold red]\n{tb}\n")
        self.call_from_thread(self.query_one(Input).focus)


def main():
    TianshuApp().run()


if __name__ == "__main__":
    main()
