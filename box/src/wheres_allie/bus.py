import asyncio


class Subscription:
    """Async iterator of (topic, data) for one subscriber; a context manager unsubscribes."""

    def __init__(self, bus: "Bus", prefix: str):
        self.prefix = prefix
        self.queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=1000)
        self._bus = bus

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> tuple[str, dict]:
        return await self.queue.get()

    def close(self) -> None:
        if self in self._bus._subs:
            self._bus._subs.remove(self)

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Bus:
    """In-process pub/sub. publish() must be called from the event loop thread."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []

    def publish(self, topic: str, data: dict) -> None:
        for sub in list(self._subs):
            if topic.startswith(sub.prefix):
                try:
                    sub.queue.put_nowait((topic, data))
                except asyncio.QueueFull:
                    pass  # ponytail: a slow subscriber drops events; add backpressure if needed

    def subscribe(self, topic_prefix: str = "") -> Subscription:
        sub = Subscription(self, topic_prefix)
        self._subs.append(sub)
        return sub
