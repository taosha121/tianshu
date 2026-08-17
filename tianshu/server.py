import asyncio
import json
import os
import uuid

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


class RunRequest(BaseModel):
    command: str


@app.post("/run")
async def start_run(req: RunRequest):
    run_id = uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    _run_queues[run_id] = queue

    loop = asyncio.get_event_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def _run():
        agent = Agent(
            cwd=os.getcwd(),
            _agent_id="main",
            _agent_type="main",
            _emit=emit,
        )
        await asyncio.to_thread(agent.execute, req.command)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(_run())
    return {"runId": run_id}


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
    import uvicorn
    uvicorn.run("tianshu.server:app", host="0.0.0.0", port=8000, reload=False)
