from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SEVERITIES = ("low", "medium", "high")


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


@dataclass(frozen=True)
class Package:
    ecosystem: str  # npm | pypi | crates | go
    name: str
    version: str
    source: str  # lockfile the package was read from

    @property
    def label(self) -> str:
        return f"{self.ecosystem}:{self.name}@{self.version}"


@dataclass(frozen=True)
class VersionInfo:
    published: datetime | None
    # True/False when the registry exposes attestations, None when it cannot tell.
    provenance: bool | None = None
    yanked: bool = False
    deprecated: bool = False


@dataclass(frozen=True)
class Finding:
    package: Package
    rule: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "package": self.package.label,
            "lockfile": self.package.source,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }
