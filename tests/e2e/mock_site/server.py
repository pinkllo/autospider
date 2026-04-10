from __future__ import annotations

from contextlib import AbstractContextManager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import TracebackType
from typing import Any
from urllib.parse import parse_qs, urlparse

from .data import get_record
from .pages import (
    render_announcements_page,
    render_deals_payload,
    render_detail_page,
    render_download,
    render_home_page,
)


class _ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class MockSiteServer(AbstractContextManager["MockSiteServer"]):
    def __init__(self, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self._port = port
        self._server: _ReusableHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Mock site server is not running.")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "MockSiteServer":
        if self._server is not None:
            return self
        handler = self._build_handler()
        self._server = _ReusableHTTPServer((self._host, self._port), handler)
        self._thread = Thread(target=self._server.serve_forever, name="mock-site-server")
        self._thread.daemon = True
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class MockSiteRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                page = _read_page(query)
                if parsed.path == "/":
                    self._write_html(render_home_page(base_url=owner.base_url))
                    return
                if parsed.path == "/announcements":
                    self._write_html(
                        render_announcements_page(base_url=owner.base_url, page=page)
                    )
                    return
                if parsed.path == "/api/deals":
                    self._write_bytes(
                        body=render_deals_payload(base_url=owner.base_url, page=page),
                        content_type="application/json; charset=utf-8",
                    )
                    return
                if parsed.path.startswith("/details/"):
                    self._write_detail(parsed.path)
                    return
                if parsed.path.startswith("/downloads/"):
                    self._write_download(parsed.path)
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _write_detail(self, path: str) -> None:
                parts = [part for part in path.split("/") if part]
                if len(parts) != 3:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
                _, category, slug = parts
                record = get_record(category=category, slug=slug)
                if record is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
                self._write_html(
                    render_detail_page(
                        base_url=owner.base_url,
                        category=category,
                        record=record,
                    )
                )

            def _write_download(self, path: str) -> None:
                parts = [part for part in path.split("/") if part]
                if len(parts) != 3:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
                _, category, filename = parts
                slug = filename.removesuffix(".pdf")
                record = get_record(category=category, slug=slug)
                if record is None or not filename.endswith(".pdf"):
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
                self._write_bytes(
                    body=render_download(category=category, slug=slug),
                    content_type="application/pdf",
                )

            def _write_html(self, body: str) -> None:
                self._write_bytes(
                    body=body.encode("utf-8"),
                    content_type="text/html; charset=utf-8",
                )

            def _write_bytes(self, *, body: bytes, content_type: str) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return MockSiteRequestHandler


def _read_page(query: dict[str, list[str]]) -> int:
    value = query.get("page", ["1"])[0]
    try:
        page = int(value)
    except ValueError:
        return 1
    return max(1, page)
