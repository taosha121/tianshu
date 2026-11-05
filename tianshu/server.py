import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tianshu.agent import Agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# run_id -> asyncio.Queue; None = sentinel (run finished)
_run_queues: dict[str, asyncio.Queue] = {}
# session_id -> Agent
_sessions: dict[str, Agent] = {}
# permission request_id -> asyncio.Queue (holds one Allow/Deny response)
_permission_queues: dict[str, asyncio.Queue] = {}

_SERVER_CWD: str = str(Path(__file__).parents[1])


class RunRequest(BaseModel):
    command: str
    sessionId: str | None = None


class PermissionResponse(BaseModel):
    allow: bool


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
        agent = Agent(cwd=_SERVER_CWD, _emit=emit)
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
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            _run_queues.pop(run_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/permission/{request_id}")
async def respond_permission(request_id: str, body: PermissionResponse):
    q = _permission_queues.get(request_id)
    if q is None:
        raise HTTPException(status_code=404, detail="permission request not found")
    await q.put(body.allow)
    return {"ok": True}


_STATIC_DIR = Path(__file__).parent.parent / "ui" / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


def serve():
    import argparse
    import uvicorn

    global _SERVER_CWD
    parser = argparse.ArgumentParser(description="tianshu web server")
    parser.add_argument("project", nargs="?", default=None)
    args = parser.parse_args()

    if args.project:
        base = Path(__file__).parents[2]
        candidate = base / args.project
        if candidate.is_dir():
            _SERVER_CWD = str(candidate)
        else:
            for d in base.iterdir():
                if d.is_dir() and d.name.lower() == args.project.lower():
                    _SERVER_CWD = str(d)
                    break

    print(f"[tianshu] cwd: {_SERVER_CWD}")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
