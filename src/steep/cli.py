from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from steep import __version__
from steep.analyze import Policy, audit
from steep.config import ConfigError, load_config
from steep.http import Fetcher
from steep.lockfiles import LockfileError, discover, parse_lockfile
from steep.models import Package, severity_rank
from steep.registries import build_registries
from steep.report import render_json, render_markdown, render_text

DEFAULT_CACHE = Path.home() / ".cache" / "steep"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="steep",
        description="Audit lockfiles for too-new dependency versions and lost build provenance.",
    )
    p.add_argument("paths", nargs="*", type=Path, help="lockfiles or directories (default: .)")
    p.add_argument("--min-age-days", type=float, help="cooldown window (default 7)")
    p.add_argument(
        "--fail-on",
        choices=["low", "medium", "high", "never"],
        help="exit 1 when a finding of this severity or higher exists (default medium)",
    )
    p.add_argument("--base", metavar="REF", help="only check versions added/changed since git REF")
    p.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    p.add_argument("--config", type=Path, help="path to steep.toml")
    p.add_argument("--allow", action="append", default=[], metavar="ECO:NAME[@VER]")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    p.add_argument("--offline", action="store_true", help="use cached registry data only")
    p.add_argument("--version", action="version", version=f"steep {__version__}")
    return p


def _base_packages(path: Path, ref: str) -> set[tuple[str, str, str]]:
    """Packages present in `path` at git `ref`; empty when the file did not exist there."""
    proc = subprocess.run(  # noqa: S603
        ["git", "show", f"{ref}:./{path.name}"],  # noqa: S607
        cwd=path.resolve().parent,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if "does not exist" in proc.stderr or "exists on disk, but not in" in proc.stderr:
            return set()
        raise LockfileError(f"git show {ref}:{path.name} failed: {proc.stderr.strip()}")
    return {(p.ecosystem, p.name, p.version) for p in parse_lockfile(path, proc.stdout)}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.min_age_days is not None and args.min_age_days < 0:
            raise ConfigError("--min-age-days must be non-negative")
        policy = Policy(
            cfg.min_age_days if args.min_age_days is None else args.min_age_days,
            cfg.allow + args.allow,
        )
        fail_on = args.fail_on or cfg.fail_on
        packages: dict[tuple[str, str, str, str], Package] = {}
        files = list(discover(args.paths or [Path(".")]))
        if not files:
            print("steep: no supported lockfiles found", file=sys.stderr)
            return 2
        for path in files:
            skip = _base_packages(path, args.base) if args.base else set()
            for pkg in parse_lockfile(path, path.read_text()):
                if (pkg.ecosystem, pkg.name, pkg.version) not in skip:
                    packages.setdefault((pkg.ecosystem, pkg.name, pkg.version, pkg.source), pkg)
    except (LockfileError, ConfigError, OSError) as exc:
        print(f"steep: {exc}", file=sys.stderr)
        return 2

    fetcher = Fetcher(
        cache_dir=None if args.no_cache else args.cache_dir,
        offline=args.offline,
    )
    findings, checked = audit(packages.values(), build_registries(fetcher), policy)

    if args.format == "json":
        print(render_json(findings, checked))
    elif args.format == "markdown":
        print(render_markdown(findings, checked))
    else:
        print(render_text(findings, checked, color=sys.stdout.isatty()))
    if fail_on == "never":
        return 0
    return 1 if any(severity_rank(f.severity) >= severity_rank(fail_on) for f in findings) else 0
