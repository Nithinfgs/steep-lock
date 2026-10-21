"""Lockfile parsers. Each takes the file text and returns registry-hosted packages only."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path

from steep.models import Package

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "target", "vendor", "__pycache__", ".tox"}
NPM_HOST = "registry.npmjs.org"
CRATES_SOURCES = (
    "registry+https://github.com/rust-lang/crates.io-index",
    "sparse+https://index.crates.io/",
)


class LockfileError(ValueError):
    pass


def _norm_pypi(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_package_lock(text: str, source: str) -> list[Package]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LockfileError(f"{source}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise LockfileError(f"{source}: unexpected top-level structure")
    found: dict[tuple[str, str], Package] = {}

    def add(name: str, entry: dict[str, object]) -> None:
        version = entry.get("version")
        resolved = entry.get("resolved")
        if not isinstance(version, str) or entry.get("link"):
            return
        if not isinstance(resolved, str) or f"//{NPM_HOST}/" not in resolved:
            return  # git, file, tarball URL or private registry
        found[(name, version)] = Package("npm", name, version, source)

    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, entry in packages.items():
            if not key or not isinstance(entry, dict):
                continue
            name = key.rsplit("node_modules/", 1)[-1]
            add(name, entry)
    else:  # lockfileVersion 1

        def walk(deps: object) -> None:
            if not isinstance(deps, dict):
                return
            for name, entry in deps.items():
                if isinstance(entry, dict):
                    add(name, entry)
                    walk(entry.get("dependencies"))

        walk(data.get("dependencies"))
    return sorted(found.values(), key=lambda p: (p.name, p.version))


_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9._!+*-]+)")


def parse_requirements(text: str, source: str) -> list[Package]:
    found: dict[tuple[str, str], Package] = {}
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("-", "#", "http", "git+")):
            continue
        match = _REQ.match(line)
        if match and "*" not in match.group(2):
            name = _norm_pypi(match.group(1))
            found[(name, match.group(2))] = Package("pypi", name, match.group(2), source)
    return sorted(found.values(), key=lambda p: (p.name, p.version))


def _toml(text: str, source: str) -> dict[str, object]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LockfileError(f"{source}: invalid TOML ({exc})") from exc


def _toml_packages(text: str, source: str) -> list[dict[str, object]]:
    pkgs = _toml(text, source).get("package", [])
    return [p for p in pkgs if isinstance(p, dict)] if isinstance(pkgs, list) else []


def parse_uv_lock(text: str, source: str) -> list[Package]:
    out = []
    for pkg in _toml_packages(text, source):
        src = pkg.get("source")
        registry = src.get("registry") if isinstance(src, dict) else None
        name, version = pkg.get("name"), pkg.get("version")
        if (
            isinstance(registry, str)
            and "pypi.org" in registry
            and isinstance(name, str)
            and isinstance(version, str)
        ):
            out.append(Package("pypi", _norm_pypi(name), version, source))
    return out


def parse_poetry_lock(text: str, source: str) -> list[Package]:
    out = []
    for pkg in _toml_packages(text, source):
        name, version = pkg.get("name"), pkg.get("version")
        if "source" in pkg:  # git/directory/custom index
            continue
        if isinstance(name, str) and isinstance(version, str):
            out.append(Package("pypi", _norm_pypi(name), version, source))
    return out


def parse_cargo_lock(text: str, source: str) -> list[Package]:
    out = []
    for pkg in _toml_packages(text, source):
        name, version, src = pkg.get("name"), pkg.get("version"), pkg.get("source")
        if (
            isinstance(name, str)
            and isinstance(version, str)
            and isinstance(src, str)
            and src.startswith(CRATES_SOURCES)
        ):
            out.append(Package("crates", name, version, source))
    return out


def parse_go_sum(text: str, source: str) -> list[Package]:
    found: dict[tuple[str, str], Package] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1].endswith("/go.mod"):
            continue
        found[(parts[0], parts[1])] = Package("go", parts[0], parts[1], source)
    return sorted(found.values(), key=lambda p: (p.name, p.version))


PARSERS: dict[str, Callable[[str, str], list[Package]]] = {
    "package-lock.json": parse_package_lock,
    "npm-shrinkwrap.json": parse_package_lock,
    "requirements.txt": parse_requirements,
    "uv.lock": parse_uv_lock,
    "poetry.lock": parse_poetry_lock,
    "Cargo.lock": parse_cargo_lock,
    "go.sum": parse_go_sum,
}


def parse_lockfile(path: Path, text: str) -> list[Package]:
    parser = PARSERS.get(path.name)
    if parser is None:
        raise LockfileError(f"{path}: unsupported lockfile (supported: {', '.join(PARSERS)})")
    return parser(text, str(path))


def discover(paths: list[Path]) -> Iterator[Path]:
    """Yield lockfiles: explicit files as given, directories searched recursively."""
    for root in paths:
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            raise LockfileError(f"{root}: no such file or directory")
        for candidate in sorted(root.rglob("*")):
            skipped = SKIP_DIRS.intersection(candidate.relative_to(root).parts[:-1])
            if candidate.name in PARSERS and candidate.is_file() and not skipped:
                yield candidate
