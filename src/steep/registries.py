"""Registry clients. Each returns release metadata (publish time, provenance, yanked)."""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Any
from urllib.parse import quote

from steep.http import Fetcher, FetchError
from steep.models import VersionInfo

History = dict[str, VersionInfo]

_PY_EXT = re.compile(r"\.(tar\.gz|zip|tar\.bz2|tar\.xz|whl|egg)$")


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _from_cache(raw: dict[str, Any]) -> History:
    return {
        ver: VersionInfo(parse_time(d["published"]), d["provenance"], d["yanked"], d["deprecated"])
        for ver, d in raw.items()
    }


def _to_cache(history: History) -> dict[str, Any]:
    return {
        ver: {
            "published": i.published.isoformat() if i.published else None,
            "provenance": i.provenance,
            "yanked": i.yanked,
            "deprecated": i.deprecated,
        }
        for ver, i in history.items()
    }


class Registry:
    """Base class: `history(name)` returns every known version of a package."""

    ecosystem = ""
    env_var = ""
    default_url = ""

    def __init__(self, fetcher: Fetcher, base_url: str | None = None) -> None:
        self.fetcher = fetcher
        self.base_url = (base_url or os.environ.get(self.env_var) or self.default_url).rstrip("/")
        self._memo: dict[str, History] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def history(self, name: str) -> History:
        with self._guard:
            lock = self._locks.setdefault(name, threading.Lock())
        with lock:  # one network fetch per package even when many versions are locked
            if name in self._memo:
                return self._memo[name]
            key = f"{self.ecosystem}|{self.base_url}|{name}"
            cached = self.fetcher.get_cached(key)
            if cached is not None:
                result = _from_cache(cached)
            else:
                result = self._fetch(name)
                self.fetcher.put_cached(key, _to_cache(result))
            self._memo[name] = result
            return result

    def _fetch(self, name: str) -> History:
        raise NotImplementedError

    def lookup(self, name: str, version: str) -> tuple[VersionInfo | None, list[VersionInfo]]:
        """Return (info for version, infos for earlier releases, newest first)."""
        history = self.history(name)
        current = history.get(version)
        if current is None:
            return None, []
        dated = [
            (i.published, i)
            for v, i in history.items()
            if v != version
            and i.published
            and current.published
            and i.published < current.published
        ]
        dated.sort(key=lambda pair: pair[0], reverse=True)
        return current, [i for _, i in dated]


class NpmRegistry(Registry):
    ecosystem = "npm"
    env_var = "STEEP_NPM_URL"
    default_url = "https://registry.npmjs.org"

    def _fetch(self, name: str) -> History:
        doc = self.fetcher.get_json(f"{self.base_url}/{quote(name, safe='@/')}")
        times = doc.get("time", {})
        out: History = {}
        for version, meta in doc.get("versions", {}).items():
            dist = meta.get("dist", {}) if isinstance(meta, dict) else {}
            out[version] = VersionInfo(
                published=parse_time(times.get(version)),
                provenance=bool(dist.get("attestations")),
                deprecated=bool(meta.get("deprecated")),
            )
        return out


class PypiRegistry(Registry):
    ecosystem = "pypi"
    env_var = "STEEP_PYPI_URL"
    default_url = "https://pypi.org/simple"

    def _fetch(self, name: str) -> History:
        doc = self.fetcher.get_json(
            f"{self.base_url}/{quote(name)}/",
            {"Accept": "application/vnd.pypi.simple.v1+json"},
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for f in doc.get("files", []):
            version = self._version_of(f.get("filename", ""), name)
            if version:
                grouped.setdefault(version, []).append(f)
        out: History = {}
        for version, files in grouped.items():
            times = [t for t in (parse_time(f.get("upload-time")) for f in files) if t]
            out[version] = VersionInfo(
                published=min(times) if times else None,  # earliest file = release time
                provenance=any(bool(f.get("provenance")) for f in files),
                yanked=all(bool(f.get("yanked")) for f in files),
            )
        return out

    @staticmethod
    def _version_of(filename: str, project: str) -> str | None:
        stem = _PY_EXT.sub("", filename)
        if filename.endswith(".whl"):
            parts = stem.split("-")
            return parts[1] if len(parts) >= 5 else None
        head, _, version = stem.rpartition("-")
        return version if head and version else None


class CratesRegistry(Registry):
    ecosystem = "crates"
    env_var = "STEEP_CRATES_URL"
    default_url = "https://crates.io/api/v1/crates"

    def _fetch(self, name: str) -> History:
        doc = self.fetcher.get_json(f"{self.base_url}/{quote(name)}")
        return {
            v["num"]: VersionInfo(
                published=parse_time(v.get("created_at")),
                provenance=None,
                yanked=bool(v.get("yanked")),
            )
            for v in doc.get("versions", [])
        }


class GoRegistry(Registry):
    """The Go proxy only answers per-version, so history holds just the requested versions."""

    ecosystem = "go"
    env_var = "STEEP_GO_PROXY"
    default_url = "https://proxy.golang.org"

    @staticmethod
    def escape(path: str) -> str:
        return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), path)

    def _fetch(self, name: str) -> History:  # pragma: no cover - not used
        raise NotImplementedError

    def lookup(self, name: str, version: str) -> tuple[VersionInfo | None, list[VersionInfo]]:
        key = f"go|{self.base_url}|{name}@{version}"
        cached = self.fetcher.get_cached(key)
        if cached is None:
            try:
                doc = self.fetcher.get_json(
                    f"{self.base_url}/{self.escape(name)}/@v/{self.escape(version)}.info"
                )
            except FetchError as exc:
                if exc.status in (404, 410):
                    return None, []
                raise
            cached = {"published": doc.get("Time")}
            self.fetcher.put_cached(key, cached)
        return VersionInfo(published=parse_time(cached.get("published"))), []


def build_registries(fetcher: Fetcher) -> dict[str, Registry]:
    return {
        r.ecosystem: r
        for r in (
            NpmRegistry(fetcher),
            PypiRegistry(fetcher),
            CratesRegistry(fetcher),
            GoRegistry(fetcher),
        )
    }
