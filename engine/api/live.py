"""Live updates to the screens over a WebSocket.

Every screen keeps one WebSocket open. The engine sends it messages from the
bus: prices, candles, orders, fills, account numbers, alerts, feed health.
Prices are bundled and sent ten times a second (well inside the bible's
quarter-second target), so a busy market can't flood a screen.
"""

import asyncio
import json
import logging

from engine.core.bus import MessageBus

log = logging.getLogger(__name__)

FLUSH_EVERY = 0.1
# Messages where only the newest one matters (older ones can be dropped).
LATEST_ONLY = {"tick", "candle", "account"}


class LiveHub:
    def __init__(self, bus: MessageBus):
        self.clients: set["Client"] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        bus.subscribe("*", self._on_message)

    def _on_message(self, topic: str, message) -> None:
        if self.loop is None or not self.clients:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._deliver(topic, message)
        else:
            self.loop.call_soon_threadsafe(self._deliver, topic, message)

    def _deliver(self, topic: str, message) -> None:
        for client in list(self.clients):
            client.add(topic, message)


class Client:
    def __init__(self, websocket):
        self.websocket = websocket
        self.latest: dict[str, dict] = {}
        self.queue: list[dict] = []
        self.wake = asyncio.Event()

    def add(self, topic: str, message) -> None:
        if topic in LATEST_ONLY and isinstance(message, dict):
            key = f"{topic}|{message.get('symbol', '')}|{message.get('timeframe', '')}|{message.get('account_id', '')}"
            if topic == "candle" and message.get("finished"):
                self.queue.append({"type": topic, "data": message})      # finished candles are never dropped
            else:
                self.latest[key] = {"type": topic, "data": message}
        else:
            self.queue.append({"type": topic, "data": message})
        self.wake.set()

    async def pump(self) -> None:
        while True:
            await self.wake.wait()
            self.wake.clear()
            batch = self.queue + list(self.latest.values())
            self.queue, self.latest = [], {}
            if batch:
                await self.websocket.send_text(json.dumps(batch, default=str))
            await asyncio.sleep(FLUSH_EVERY)
