from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "deskcal" / "config.toml"


@dataclass
class Config:
    calendars: list[dict] = field(default_factory=list)
    refresh_minutes: float = 5
    alert_minutes_before: list[int] = field(default_factory=lambda: [5])
    alert_at_start: bool = True
    volume: float = 0.8
    clock_24h: bool = False

    @property
    def alert_offsets(self) -> list[int]:
        return sorted(set(self.alert_minutes_before) | ({0} if self.alert_at_start else set()))


def _load_env(path: Path) -> None:
    """Read KEY=value lines into the environment; variables already set win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _expand(url: str, path: Path) -> str:
    def lookup(match: re.Match) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"{path} uses ${{{name}}}, but it isn't set in {path.with_name('.env')}")
        return os.environ[name]

    return re.sub(r"\$\{(\w+)\}", lookup, url)


def load(path: Path = DEFAULT_PATH) -> Config:
    if not path.exists():
        return Config()
    # Secrets (feed URLs) live in a .env file next to the config.
    _load_env(path.with_name(".env"))
    raw = tomllib.loads(path.read_text())
    cfg = Config()
    for key, value in raw.items():
        if not hasattr(cfg, key):
            raise ValueError(f"Unknown setting {key!r} in {path}")
        setattr(cfg, key, value)
    for cal in cfg.calendars:
        cal["url"] = _expand(cal["url"], path)
    return cfg
