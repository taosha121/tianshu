import asyncio
import json
import queue
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
# permission request_id -> thread-safe queue holding one Allow/Deny response.
# stdlib queue.Queue: the agent blocks on get() in its worker thread while the
# HTTP endpoint puts the response from the event loop.
_permission_queues: dict[str, queue.Queue] = {}

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
    run_queue: asyncio.Queue = asyncio.Queue()
    _run_queues[run_id] = run_queue

    loop = asyncio.get_event_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(run_queue.put_nowait, event)

    def request_permission(tool: str, inp: dict, reason: str) -> bool:
        """Emit a permission_request and block the worker thread until the user responds."""
        request_id = uuid.uuid4().hex[:8]
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        _permission_queues[request_id] = resp_q
        emit({
            "type": "permission_request",
            "requestId": request_id,
            "tool": tool,
            "input": inp,
            "reason": reason,
        })
        try:
            return bool(resp_q.get())
        finally:
            _permission_queues.pop(request_id, None)

    is_new_session = req.sessionId is None or req.sessionId not in _sessions
    session_id = req.sessionId if not is_new_session else uuid.uuid4().hex[:8]

    if is_new_session:
        agent = Agent(cwd=_SERVER_CWD, _emit=emit, _permission_cb=request_permission)
        _sessions[session_id] = agent
    else:
        agent = _sessions[session_id]
        agent._emit = emit
        agent._permission_cb = request_permission

    async def _run():
        result = await asyncio.to_thread(agent.execute, req.command)
        loop.call_soon_threadsafe(run_queue.put_nowait, {"type": "result", "text": result})
        loop.call_soon_threadsafe(run_queue.put_nowait, None)

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
    q.put_nowait(body.allow)
    return {"ok": True}


_STATIC_DIR = Path(__file__).parent.parent / "ui" / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
