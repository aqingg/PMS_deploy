from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse
from .sse import event_bus
import json
import asyncio

router = APIRouter()

@router.get("/stream")
async def sse_stream(request: Request):

    listener = await event_bus.subscribe()
    queue = listener.queue

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await queue.get()
                    data = json.dumps(message)
                    yield f"data: {data}\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            # 确保断连后清理 listener
            event_bus.unsubscribe(listener)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
