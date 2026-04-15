"""Static file server for benchmark mock site assets."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

SERVER_HOST = "127.0.0.1"
THREAD_JOIN_TIMEOUT_SECONDS = 5.0


class _SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return None


class MockSiteServer:
    """Serve the benchmark mock site from a single root directory."""

    def __init__(self, root_dir: Path | None = None, port: int = 0) -> None:
        self.root_dir = (root_dir or Path(__file__).resolve().parent).resolve()
        self._requested_port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("Mock site server is not started.")
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Mock site server is already started.")
        handler = partial(_SilentHandler, directory=str(self.root_dir))
        self._server = ThreadingHTTPServer((SERVER_HOST, self._requested_port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT_SECONDS)
        self._server = None
        self._thread = None
