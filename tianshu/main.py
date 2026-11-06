import argparse
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _resolve_cwd(project: str | None) -> str | None:
    """Resolve a project argument to a working directory.

    Accepts an absolute/relative path, or a bare name matched against
    sibling directories under projects/. Returns None to keep the default.
    """
    if not project:
        return None
    p = Path(project).expanduser()
    if p.is_dir():
        return str(p.resolve())
    base = Path(__file__).parents[2]
    candidate = base / project
    if candidate.is_dir():
        return str(candidate)
    for d in base.iterdir():
        if d.is_dir() and d.name.lower() == project.lower():
            return str(d)
    print(f"[tianshu] project not found: {project!r}; using default")
    return None


def main():
    parser = argparse.ArgumentParser(description="tianshu web server")
    parser.add_argument(
        "project", nargs="?", default=None,
        help="working directory: an absolute/relative path, or a name under projects/",
    )
    args = parser.parse_args()

    import tianshu.server as server
    cwd = _resolve_cwd(args.project)
    if cwd:
        server._SERVER_CWD = cwd
    print(f"[tianshu] cwd: {server._SERVER_CWD}")

    def _open():
        time.sleep(0.8)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run("tianshu.server:app", host="127.0.0.1", port=8000, reload=False,
                access_log=False, log_level="error")


if __name__ == "__main__":
    main()
