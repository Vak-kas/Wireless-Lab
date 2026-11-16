# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import shutil

import pytest

from wls.core.devices import Capability
from wls.probes.ping import PingProbe, parse_rtt_ms, ping_command
from wls.providers.host import LocalHostProvider

LINUX = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.2 ms

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 11.200/11.200/11.200/0.000 ms
"""
MACOS = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=8.431 ms

--- 1.1.1.1 ping statistics ---
1 packets transmitted, 1 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 8.431/8.431/8.431/0.000 ms
"""
WINDOWS = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=12ms TTL=57

Ping statistics for 1.1.1.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 12ms, Maximum = 12ms, Average = 12ms
"""
WINDOWS_KOREAN = """
Ping 1.1.1.1 32바이트 데이터 사용:
1.1.1.1의 응답: 바이트=32 시간=7ms TTL=57
"""
WINDOWS_FAST = "Reply from 127.0.0.1: bytes=32 time<1ms TTL=128"
LINUX_LOST = """PING 10.255.255.1 (10.255.255.1) 56(84) bytes of data.

--- 10.255.255.1 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""
WINDOWS_LOST = """
Pinging 10.255.255.1 with 32 bytes of data:
Request timed out.

Ping statistics for 10.255.255.1:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""
WINDOWS_UNREACHABLE = "Reply from 192.168.0.10: Destination host unreachable."


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (LINUX, 11.2),
        (MACOS, 8.431),
        (WINDOWS, 12.0),
        (WINDOWS_KOREAN, 7.0),
        (WINDOWS_FAST, 1.0),
        (LINUX_LOST, None),
        (WINDOWS_LOST, None),
        (WINDOWS_UNREACHABLE, None),
        ("", None),
    ],
)
def test_reply_time_is_parsed_on_every_os(output, expected):
    assert parse_rtt_ms(output) == expected


def test_command_matches_each_operating_system():
    assert ping_command("1.1.1.1", 1.5, "Windows") == ["ping", "-n", "1", "-w", "1500", "1.1.1.1"]
    assert ping_command("1.1.1.1", 1.5, "Darwin") == [
        "ping", "-n", "-c", "1", "-W", "1500", "1.1.1.1",
    ]  # fmt: skip
    assert ping_command("1.1.1.1", 1.5, "Linux") == ["ping", "-n", "-c", "1", "-W", "2", "1.1.1.1"]


@pytest.mark.parametrize("host", ["", "-f", "1.1.1.1 -f", "a\tb"])
def test_hosts_that_could_be_read_as_options_are_refused(host):
    with pytest.raises(ValueError):
        ping_command(host, 1.0)


async def collect(probe: PingProbe, count: int) -> list[dict]:
    got: list[dict] = []
    done = asyncio.Event()

    def emit(values):
        got.append(dict(values))
        if len(got) >= count:
            done.set()

    task = asyncio.create_task(probe.run(emit))
    try:
        async with asyncio.timeout(5):
            await done.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return got[:count]


async def test_probe_reports_replies_and_losses():
    outputs = iter([LINUX, LINUX_LOST, MACOS])

    async def fake_runner(command, timeout):
        return next(outputs)

    probe = PingProbe("1.1.1.1", interval=0.001, runner=fake_runner)
    assert await collect(probe, 3) == [
        {"rtt_ms": 11.2, "lost": 0.0},
        {"lost": 1.0},
        {"rtt_ms": 8.431, "lost": 0.0},
    ]


async def test_missing_ping_command_surfaces_as_an_error():
    async def missing(command, timeout):
        raise FileNotFoundError("ping")

    with pytest.raises(FileNotFoundError):
        await PingProbe("1.1.1.1", runner=missing).run(lambda values: None)


async def test_this_computer_is_discovered_with_net_probe_support():
    (host,) = await LocalHostProvider().discover()
    assert host.id == "host"
    assert host.support(Capability.NET_PROBE).supported == (shutil.which("ping") is not None)


@pytest.mark.skipif(shutil.which("ping") is None, reason="no system ping")
async def test_real_ping_to_this_computer():
    samples = await collect(PingProbe("127.0.0.1", interval=0.05), 2)
    assert all(s["lost"] == 0.0 and s["rtt_ms"] >= 0 for s in samples), samples
