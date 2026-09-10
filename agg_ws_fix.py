from __future__ import annotations
import asyncio
import time

class KeepAliveWS:
    def __init__(self, ws, ping_interval=15, ping_timeout=10):
        self.ws = ws
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self._last_pong = time.time()

    async def run(self):
        async def pinger():
            while True:
                await asyncio.sleep(self.ping_interval)
                try:
                    pong = await self.ws.ping()
                    await asyncio.wait_for(pong, timeout=self.ping_timeout)
                    self._last_pong = time.time()
                except Exception:
                    await self.ws.close()
                    return
        return asyncio.create_task(pinger())
