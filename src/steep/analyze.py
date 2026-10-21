"""Turn lockfile packages plus registry metadata into findings."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from steep.http import FetchError
from steep.models import Finding, Package, VersionInfo
from steep.registries import Registry

PROVENANCE_LOOKBACK = 3


@dataclass
class Policy:
    min_age_days: float = 7.0
    allow: list[str] = field(default_factory=list)

    def is_allowed(self, pkg: Package) -> bool:
        return pkg.label in self.allow or f"{pkg.ecosystem}:{pkg.name}" in self.allow


def evaluate(
    pkg: Package,
    info: VersionInfo | None,
    earlier: list[VersionInfo],
    policy: Policy,
    now: datetime,
) -> list[Finding]:
    if info is None:
        return [
            Finding(
                pkg,
                "not-found",
                "low",
                "version not found in the public registry (private mirror or removed release?)",
            )
        ]
    findings: list[Finding] = []
    if info.published is not None:
        published = info.published if info.published.tzinfo else info.published.replace(tzinfo=UTC)
        age = now - published
        if age < timedelta(days=policy.min_age_days):
            severity = "high" if age < timedelta(days=policy.min_age_days / 3) else "medium"
            findings.append(
                Finding(
                    pkg,
                    "too-new",
                    severity,
                    f"published {_fmt_age(age)} ago, inside the "
                    f"{policy.min_age_days:g}-day cooldown",
                )
            )
    if info.provenance is False and any(e.provenance for e in earlier[:PROVENANCE_LOOKBACK]):
        findings.append(
            Finding(
                pkg,
                "provenance-regression",
                "high",
                "this release has no build provenance although a recent earlier release did",
            )
        )
    if info.yanked:
        findings.append(Finding(pkg, "yanked", "high", "release is yanked in the registry"))
    if info.deprecated:
        findings.append(Finding(pkg, "deprecated", "medium", "release is marked deprecated"))
    return findings


def _fmt_age(age: timedelta) -> str:
    hours = age.total_seconds() / 3600
    return f"{hours:.0f}h" if hours < 48 else f"{age.days}d"


def audit(
    packages: Iterable[Package],
    registries: dict[str, Registry],
    policy: Policy,
    now: datetime | None = None,
    workers: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Finding], int]:
    """Return (findings, number of packages checked)."""
    now = now or datetime.now(UTC)
    pkgs = [p for p in packages if not policy.is_allowed(p)]

    def check(pkg: Package) -> list[Finding]:
        registry = registries.get(pkg.ecosystem)
        if registry is None:
            return []
        try:
            info, earlier = registry.lookup(pkg.name, pkg.version)
        except FetchError as exc:
            return [Finding(pkg, "lookup-failed", "low", str(exc))]
        return evaluate(pkg, info, earlier, policy, now)

    findings: list[Finding] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, result in enumerate(pool.map(check, pkgs), start=1):
            findings.extend(result)
            if progress:
                progress(done, len(pkgs))
    return findings, len(pkgs)
