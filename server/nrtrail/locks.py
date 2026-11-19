"""장비마다 하나씩 거는 잠금. 한 장비는 한 번에 한 가지 일만 하지만, 서로 다른 장비는 동시에 일할 수 있다.

    locks = DeviceLocks()
    if locks.busy(device): 409 로 거절한다(기다리지 않는다. 화면이 다음 차례에 다시 묻는다)
    async with locks.hold(device): 그 장비로 받거나 보낸다

두 장비를 함께 쓰는 일(보내면서 다른 장비로 받기)은 hold(a, b) 로 둘 다 잡는다. 잡는 순서는 이름순이라 서로 물리지 않는다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class DeviceLocks:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def of(self, device: str) -> asyncio.Lock:
        return self._locks.setdefault(device, asyncio.Lock())

    def busy(self, *devices: str) -> bool:
        """이 장비들 가운데 하나라도 지금 쓰이고 있는가."""
        return any(self.of(d).locked() for d in devices if d)

    @asynccontextmanager
    async def hold(self, *devices: str) -> AsyncIterator[None]:
        names = sorted({d for d in devices if d})
        held: list[asyncio.Lock] = []
        try:
            for name in names:
                lock = self.of(name)
                await lock.acquire()
                held.append(lock)
            yield
        finally:
            for lock in reversed(held):
                lock.release()

    def in_use(self) -> list[str]:
        return sorted(d for d, lock in self._locks.items() if lock.locked())
