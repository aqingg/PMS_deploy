# api/sse.py
import asyncio
from typing import Dict, List, Any, Callable
from fastapi import Request
from starlette.responses import StreamingResponse
from dataclasses import dataclass

@dataclass
class Listener:
    queue: asyncio.Queue
    active: bool = True

class EventBus:
    def __init__(self):
        self.listeners: List[Listener] = []

    async def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        listener = Listener(queue=queue)
        self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener: Listener):
        listener.active = False
        try:
            self.listeners.remove(listener)
        except ValueError:
            pass

    async def publish(self, message: Dict[str, Any]):
        dead: List[Listener] = []

        for listener in list(self.listeners):
            if not listener.active:
                dead.append(listener)
                continue

            try:
                listener.queue.put_nowait(message)
            except asyncio.QueueFull:
                # 慢消费者，直接标记为失效
                listener.active = False
                dead.append(listener)

        for listener in dead:
            self.unsubscribe(listener)

event_bus = EventBus()
