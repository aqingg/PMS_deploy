from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import asyncio
from api.sse import event_bus
import json
import time

router = APIRouter()

@router.get("/events/stream")
async def sse_stream(request: Request, username: str):
    
    listener = await event_bus.subscribe()
    queue = listener.queue

    async def event_generator():
        # 心跳定时器
        last_heartbeat = time.time()

        try:
            while True:
                # 客户端断开
                if await request.is_disconnected():
                    break

                # 心跳（每 20 秒）
                if time.time() - last_heartbeat > 20:
                    yield "data: {\"event\":\"heartbeat\"}\n\n"
                    last_heartbeat = time.time()

                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # 推送事件
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            # 确保断连后释放 listener
            event_bus.unsubscribe(listener)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
