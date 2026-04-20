from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator
from urllib.request import urlopen

from autospider.contexts.collection.infrastructure.channel.base import URLChannel
from autospider.legacy.domain.fields import FieldDefinition

MOCK_HTML = (
    "<html><body><article data-kind='product'>"
    "<h1>Contract Fixture Product</h1>"
    "<span class='price'>$10</span>"
    "</article></body></html>\n"
)


@dataclass(slots=True)
class CollectorResult:
    collected_urls: list[str]


@dataclass(slots=True)
class FieldResult:
    field_name: str
    value: str
    error: str = ""


@dataclass(slots=True)
class Record:
    url: str
    success: bool
    fields: list[FieldResult]


@dataclass(slots=True)
class WorkerResult:
    record: Record
    extraction_config: dict[str, Any]


class FakeBrowserRuntimeSession:
    def __init__(self, **_: Any) -> None:
        self.page = object()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class FakeSkillRuntime:
    def __init__(self, *_: Any, **__: Any) -> None:
        return None


class FakeURLCollector:
    def __init__(self, *, list_url: str, url_channel: URLChannel, **_: Any) -> None:
        self._list_url = list_url
        self._channel = url_channel
        self.nav_steps = [{"action": "open", "url": list_url}]
        self.common_detail_xpath = "//article[@data-kind='product']"
        self.pagination_handler = type(
            "PaginationHandler", (), {"pagination_xpath": None, "jump_widget_xpath": None}
        )()

    async def run(self) -> CollectorResult:
        await self._channel.publish(self._list_url)
        return CollectorResult(collected_urls=[self._list_url])


class FakeDetailPageWorker:
    def __init__(self, *, fields: list[FieldDefinition], **_: Any) -> None:
        self._fields = list(fields)

    async def extract(self, url: str) -> WorkerResult:
        title = _extract_title(_fetch_text(url))
        field_results = [FieldResult(field_name=field.name, value=title) for field in self._fields]
        config = {"fields": [field.model_dump(mode="python") for field in self._fields]}
        return WorkerResult(
            record=Record(url=url, success=True, fields=field_results), extraction_config=config
        )


@contextmanager
def serve_site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _site_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _site_handler() -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            _ = format, args

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(MOCK_HTML.encode("utf-8"))

    return Handler


def _fetch_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _extract_title(html: str) -> str:
    match = re.search(r"<h1>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise AssertionError("fake_worker_failed_to_extract_title")
    return re.sub(r"\s+", " ", match.group(1)).strip()
