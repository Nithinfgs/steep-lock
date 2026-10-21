from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "steep.toml"


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    min_age_days: float = 7.0
    fail_on: str = "medium"
    allow: list[str] = field(default_factory=list)


def load_config(path: Path | None) -> Config:
    """Load steep.toml. A missing default file is fine; an explicit missing path is not."""
    explicit = path is not None
    target = path or Path(CONFIG_NAME)
    if not target.is_file():
        if explicit:
            raise ConfigError(f"{target}: config file not found")
        return Config()
    try:
        data = tomllib.loads(target.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{target}: {exc}") from exc
    cfg = Config()
    unknown = set(data) - {"min_age_days", "fail_on", "allow"}
    if unknown:
        raise ConfigError(f"{target}: unknown keys: {', '.join(sorted(unknown))}")
    if "min_age_days" in data:
        value = data["min_age_days"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ConfigError(f"{target}: min_age_days must be a non-negative number")
        cfg.min_age_days = float(value)
    if "fail_on" in data:
        if data["fail_on"] not in ("low", "medium", "high", "never"):
            raise ConfigError(f"{target}: fail_on must be low, medium, high or never")
        cfg.fail_on = data["fail_on"]
    if "allow" in data:
        allow = data["allow"]
        if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
            raise ConfigError(f"{target}: allow must be a list of strings")
        cfg.allow = allow
    return cfg
