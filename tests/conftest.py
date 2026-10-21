from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

NOW = "2026-10-21T12:00:00+00:00"

# path -> JSON body. Dates are relative to NOW (2026-10-21T12:00Z).
ROUTES: dict[str, object] = {
    "/npm/evil-pkg": {
        "time": {"1.0.0": "2026-09-01T00:00:00.000Z", "1.1.0": "2026-10-21T10:00:00.000Z"},
        "versions": {
            "1.0.0": {"dist": {"attestations": {"url": "x"}}},
            "1.1.0": {"dist": {}},
        },
    },
    "/npm/@scope/old": {
        "time": {"2.0.0": "2025-01-01T00:00:00.000Z"},
        "versions": {"2.0.0": {"dist": {}, "deprecated": "use new"}},
    },
    "/pypi/litellm-like/": {
        "files": [
            {
                "filename": "litellm_like-1.106.2-py3-none-any.whl",
                "upload-time": "2026-10-01T00:00:00Z",
                "provenance": "https://p/1",
            },
            {"filename": "litellm_like-1.106.2.tar.gz", "upload-time": "2026-10-01T00:01:00Z"},
            {
                "filename": "litellm_like-1.107.0-py3-none-any.whl",
                "upload-time": "2026-10-21T11:39:00Z",
            },
            {"filename": "litellm_like-1.107.0.tar.gz", "upload-time": "2026-10-21T11:40:00Z"},
        ]
    },
    "/crates/serde-ish": {
        "versions": [
            {"num": "1.0.0", "created_at": "2024-01-01T00:00:00Z", "yanked": False},
            {"num": "1.0.1", "created_at": "2024-02-01T00:00:00Z", "yanked": True},
        ]
    },
    "/go/github.com/!burnt!sushi/toml/@v/v1.4.0.info": {
        "Version": "v1.4.0",
        "Time": "2026-10-21T08:00:00Z",
    },
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = ROUTES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def registry_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("STEEP_NPM_URL", f"{base}/npm")
    monkeypatch.setenv("STEEP_PYPI_URL", f"{base}/pypi")
    monkeypatch.setenv("STEEP_CRATES_URL", f"{base}/crates")
    monkeypatch.setenv("STEEP_GO_PROXY", f"{base}/go")
    yield base
    server.shutdown()
