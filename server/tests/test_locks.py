"""장비마다의 잠금: 같은 장비는 한 번에 하나, 다른 장비는 동시에."""
import asyncio

from nrtrail.locks import DeviceLocks


def test_different_devices_run_at_the_same_time_and_the_same_device_waits() -> None:
    async def main() -> list[str]:
        locks, order = DeviceLocks(), []

        async def use(device: str, name: str, seconds: float) -> None:
            async with locks.hold(device):
                order.append(f"{name} start")
                await asyncio.sleep(seconds)
                order.append(f"{name} end")

        await asyncio.gather(use("a", "a1", 0.05), use("b", "b1", 0.01), use("a", "a2", 0.01))
        return order

    order = asyncio.run(main())
    assert order.index("b1 end") < order.index("a1 end")              # b 는 a 를 기다리지 않는다
    assert order.index("a1 end") < order.index("a2 start")            # 같은 장비는 차례를 기다린다


def test_busy_is_per_device_and_a_pair_is_held_together() -> None:
    async def main() -> None:
        locks = DeviceLocks()
        assert not locks.busy("a", "b") and locks.in_use() == []
        async with locks.hold("b", "a", ""):                          # 보내면서 받기: 두 장비를 함께 잡는다(빈 이름은 건너뛴다)
            assert locks.busy("a") and locks.busy("b") and not locks.busy("c")
            assert locks.busy("c", "a") and locks.in_use() == ["a", "b"]
        assert not locks.busy("a", "b")

    asyncio.run(main())


def test_two_pairs_in_opposite_order_do_not_deadlock() -> None:
    async def main() -> None:
        locks = DeviceLocks()

        async def use(*devices: str) -> None:
            async with locks.hold(*devices):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(asyncio.gather(use("a", "b"), use("b", "a"), use("a", "b")), timeout=2)

    asyncio.run(main())
