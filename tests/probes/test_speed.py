# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wls.cli import main
from wls.core.storage import read_run, verify_run
from wls.probes.speed import SpeedProbe, check_url


class Handler(BaseHTTPRequestHandler):
    uploaded = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/fail"):
            self.send_error(503)
            return
        if self.path.startswith("/empty"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(4_000_000))
        self.end_headers()
        block = b"x" * 65536
        try:
            for _ in range(4_000_000 // 65536 + 1):
                self.wfile.write(block[: min(65536, 4_000_000)])
        except OSError:
            pass  # client stopped early

    def do_POST(self):
        remaining = int(self.headers["Content-Length"])
        try:
            while remaining > 0:
                data = self.rfile.read(min(65536, remaining))
                if not data:
                    return
                remaining -= len(data)
                type(self).uploaded += len(data)
        except OSError:
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    Handler.uploaded = 0
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


async def one_cycle(probe: SpeedProbe) -> list[dict]:
    got: list[dict] = []
    done = asyncio.Event()
    probe.on_cycle = done.set
    task = asyncio.create_task(probe.run(lambda values: got.append(dict(values))))
    try:
        async with asyncio.timeout(10):
            waiter = asyncio.ensure_future(done.wait())
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if task.done():
                task.result()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return got


async def test_download_then_upload_rates_are_reported(server):
    probe = SpeedProbe(f"{server}/down", f"{server}/up", phase_seconds=0.4, interval=0.1,
                       upload_bytes=500_000)  # fmt: skip
    got = await one_cycle(probe)
    down = [v["down_mbps"] for v in got if "down_mbps" in v]
    up = [v["up_mbps"] for v in got if "up_mbps" in v]
    assert len(down) >= 3 and len(up) >= 3
    assert max(down) > 1 and max(up) > 1  # loopback is far faster than 1 Mbps
    assert got.index({"up_mbps": up[0]}) > got.index({"down_mbps": down[-1]})  # phases in order
    assert Handler.uploaded > 0


async def test_server_error_fails_the_probe_with_the_status(server):
    probe = SpeedProbe(f"{server}/fail", f"{server}/up", phase_seconds=0.3, interval=0.1)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await one_cycle(probe)


async def test_server_that_sends_nothing_fails_instead_of_spinning(server):
    probe = SpeedProbe(f"{server}/empty", f"{server}/up", phase_seconds=0.3, interval=0.1)
    with pytest.raises(RuntimeError, match="no data"):
        await one_cycle(probe)


async def test_unreachable_server_fails_the_probe():
    probe = SpeedProbe("http://127.0.0.1:9/down", "http://127.0.0.1:9/up",
                       phase_seconds=0.3, interval=0.1)  # fmt: skip
    with pytest.raises(OSError):
        await one_cycle(probe)


@pytest.mark.parametrize("url", ["ftp://example.com/x", "example.com/x", "file:///etc/passwd", ""])
def test_only_http_urls_are_accepted(url):
    with pytest.raises(ValueError):
        check_url(url)


def test_speed_command_measures_saves_and_ends_by_itself(server, tmp_path, capsys):
    code = main(["speed", "--seconds", "0.4", "--down-url", f"{server}/down",
                 "--up-url", f"{server}/up", "--out", str(tmp_path)])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert "download" in out and "upload" in out and "Mbps" in out
    (run,) = tmp_path.glob("*-speed.sqlite")
    assert verify_run(run).intact
    metrics = {metric for _, _, metric, _ in read_run(run)[1]}
    assert metrics == {"down_mbps", "up_mbps"}


def test_speed_command_reports_a_failing_server(server, tmp_path, capsys):
    code = main(["speed", "--seconds", "0.3", "--down-url", f"{server}/fail",
                 "--up-url", f"{server}/up", "--out", str(tmp_path)])  # fmt: skip
    assert code == 1
    assert "HTTP 503" in capsys.readouterr().err


def test_speed_command_refuses_a_non_http_url(tmp_path, capsys):
    assert main(["speed", "--down-url", "file:///etc/passwd", "--out", str(tmp_path)]) == 2
    assert not list(tmp_path.iterdir())
