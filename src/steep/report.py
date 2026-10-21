from __future__ import annotations

import json

from steep.models import Finding, severity_rank

COLORS = {"high": "31", "medium": "33", "low": "36"}


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-severity_rank(f.severity), f.package.label, f.rule))


def render_text(findings: list[Finding], checked: int, color: bool) -> str:
    def paint(text: str, sev: str) -> str:
        return f"\033[{COLORS[sev]}m{text}\033[0m" if color else text

    lines = []
    for f in _sorted(findings):
        lines.append(
            f"{paint(f.severity.upper().ljust(6), f.severity)} {f.package.label}  [{f.rule}]\n"
            f"       {f.message}\n       in {f.package.source}"
        )
    counts = {s: sum(1 for f in findings if f.severity == s) for s in ("high", "medium", "low")}
    lines.append(
        f"checked {checked} package version(s): "
        f"{counts['high']} high, {counts['medium']} medium, {counts['low']} low"
    )
    return "\n".join(lines)


def render_json(findings: list[Finding], checked: int) -> str:
    return json.dumps(
        {"checked": checked, "findings": [f.to_dict() for f in _sorted(findings)]}, indent=2
    )


def render_markdown(findings: list[Finding], checked: int) -> str:
    if not findings:
        return f"### steep: no issues\n\nChecked {checked} package version(s).\n"
    rows = "\n".join(
        f"| {f.severity} | `{f.package.label}` | {f.rule} | {f.message} |"
        for f in _sorted(findings)
    )
    return (
        f"### steep: {len(findings)} finding(s)\n\n"
        "| Severity | Package | Rule | Detail |\n|---|---|---|---|\n"
        f"{rows}\n\nChecked {checked} package version(s).\n"
    )
