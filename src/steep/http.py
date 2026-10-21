"""Small HTTP layer: https-only (loopback http allowed for tests), retries, JSON disk cache."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from steep import __version__

USER_AGENT = f"steep-lock/{__version__} (+https://github.com/Nithinfgs/steep-lock)"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in LOOPBACK):
        return url
    raise FetchError(f"refusing non-https registry URL: {url}")


class Fetcher:
    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_seconds: int = 3600,
        offline: bool = False,
        timeout: float = 20.0,
        retries: int = 2,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl = ttl_seconds
        self.offline = offline
        self.timeout = timeout
        self.retries = retries

    def _cache_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:40] + ".json")

    def get_cached(self, key: str) -> Any | None:
        path = self._cache_path(key)
        if path is None or not path.is_file():
            return None
        if not self.offline and time.time() - path.stat().st_mtime > self.ttl:
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def put_cached(self, key: str, value: Any) -> None:
        path = self._cache_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
            tmp.write_text(json.dumps(value))
            tmp.replace(path)
        except OSError:
            pass  # cache is best-effort

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        check_url(url)
        if self.offline:
            raise FetchError(f"offline mode and no cached data for {url}")
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        )
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504):
                    raise FetchError(f"HTTP {exc.code} for {url}", exc.code) from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
            time.sleep(0.5 * (2**attempt))
        raise FetchError(f"request failed for {url}: {last}")
