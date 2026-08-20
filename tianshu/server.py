import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tianshu.agent import Agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# run_id -> asyncio.Queue; entries are event dicts, None = sentinel (run finished)
_run_queues: dict[str, asyncio.Queue] = {}
# session_id -> Agent; persists across multiple runs
_sessions: dict[str, Agent] = {}

# working directory resolved at startup
_SERVER_CWD: str = str(Path(__file__).parents[1])


def _resolve_cwd(project_name: str | None) -> str:
    default = Path(__file__).parents[1]
    if not project_name:
        return str(default)

    base = default.parent
    # exact match first
    candidate = base / project_name
    if candidate.is_dir():
        return str(candidate)

    # case-insensitive fallback
    try:
        for d in base.iterdir():
            if d.is_dir() and d.name.lower() == project_name.lower():
                return str(d)
    except PermissionError:
        pass

    print(f"[tianshu] Project '{project_name}' not found in {base}, using default: {default.name}")
    return str(default)


class RunRequest(BaseModel):
    command: str
    sessionId: str | None = None


@app.get("/info")
async def info():
    return {"cwd": _SERVER_CWD, "project": Path(_SERVER_CWD).name}

@app.post("/run")
async def start_run(req: RunRequest):
    run_id = uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    _run_queues[run_id] = queue

    loop = asyncio.get_event_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    is_new_session = req.sessionId is None or req.sessionId not in _sessions
    session_id = req.sessionId if not is_new_session else uuid.uuid4().hex[:8]

    if is_new_session:
        agent = Agent(
            cwd=_SERVER_CWD,
            _agent_id="main",
            _agent_type="main",
            _emit=emit,
        )
        _sessions[session_id] = agent
    else:
        agent = _sessions[session_id]
        agent._emit = emit

    async def _run():
        result = await asyncio.to_thread(agent.execute, req.command)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "result", "text": result})
        loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(_run())
    return {"runId": run_id, "sessionId": session_id, "isNewSession": is_new_session}


@app.get("/stream/{run_id}")
async def stream(run_id: str):
    queue = _run_queues.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield 'data: {"type":"done"}\n\n'
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            _run_queues.pop(run_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def serve():
    global _SERVER_CWD
    parser = argparse.ArgumentParser(description="tianshu dashboard server")
    parser.add_argument("project", nargs="?", default=None,
                        help="Project name to work in (sibling directory of tianshu)")
    args = parser.parse_args()
    _SERVER_CWD = _resolve_cwd(args.project)
    print(f"[tianshu] Working directory: {_SERVER_CWD}")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
