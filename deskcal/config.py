from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "deskcal" / "config.toml"


@dataclass
class Config:
    calendars: list[dict] = field(default_factory=list)
    google_calendars: list[str] = field(default_factory=list)
    my_emails: set[str] = field(default_factory=set)
    refresh_minutes: float = 5
    alert_minutes_before: list[int] = field(default_factory=lambda: [5])
    alert_at_start: bool = True
    volume: float = 0.8
    clock_24h: bool = False

    @property
    def has_sources(self) -> bool:
        return bool(self.calendars or self.google_calendars)

    @property
    def alert_offsets(self) -> list[int]:
        return sorted(set(self.alert_minutes_before) | ({0} if self.alert_at_start else set()))


def load(path: Path = DEFAULT_PATH) -> Config:
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text())
    cfg = Config()
    for key, value in raw.items():
        if not hasattr(cfg, key):
            raise ValueError(f"Unknown setting {key!r} in {path}")
        setattr(cfg, key, value)
    cfg.my_emails = {e.lower() for e in cfg.my_emails}
    return cfg
