import asyncio


class EventBus:
    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, task_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(q)
        return q

    def unsubscribe(self, task_id: int, q: asyncio.Queue):
        queues = self._subscribers.get(task_id)
        if queues is None:
            return
        queues.discard(q)
        if not queues:  # 清理空集合，避免 task_id 无限累积导致内存泄漏
            self._subscribers.pop(task_id, None)

    def emit(self, task_id: int, event: dict):
        for q in self._subscribers.get(task_id, set()):
            q.put_nowait(event)


event_bus = EventBus()
