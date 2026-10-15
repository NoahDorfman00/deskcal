"""Fetch Apps Script calendar feeds and turn them into a flat, sorted list of events.

A feed is the web app in apps_script/Code.gs: it returns {"items": [...]},
where each item is a Google Calendar API event resource.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "deskcal"

VIDEO_PATTERNS = [
    ("Zoom", re.compile(r"https://[\w.-]*zoom\.us/[^\s<>\"']+")),
    ("Meet", re.compile(r"https://meet\.google\.com/[^\s<>\"']+")),
    ("Teams", re.compile(r"https://teams\.microsoft\.com/[^\s<>\"']+")),
    ("Webex", re.compile(r"https://[\w.-]*webex\.com/[^\s<>\"']+")),
]

# Calendar entries that aren't meetings.
SKIP_TYPES = {"workingLocation", "outOfOffice"}


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    start: datetime  # timezone-aware, local time
    end: datetime
    all_day: bool = False
    location: str = ""
    calendar: str = ""
    video: str = ""  # "Zoom", "Meet", ... or ""

    @property
    def key(self) -> str:
        """Unique per occurrence (recurring events share a UID)."""
        return f"{self.uid}@{self.start.isoformat()}"


def _when(field: dict) -> tuple[datetime, bool]:
    """Return (aware local datetime, is_all_day)."""
    if "dateTime" in field:
        return datetime.fromisoformat(field["dateTime"]).astimezone(), False
    return datetime.combine(date.fromisoformat(field["date"]), time()).astimezone(), True


def _video(item: dict) -> str:
    if item.get("hangoutLink"):
        return "Meet"
    solution = item.get("conferenceData", {}).get("conferenceSolution", {}).get("name", "")
    for name, _ in VIDEO_PATTERNS:
        if name.lower() in solution.lower():
            return name
    text = " ".join(str(item.get(k, "")) for k in ("location", "description"))
    for name, pattern in VIDEO_PATTERNS:
        if pattern.search(text):
            return name
    return ""


def parse_items(items: list[dict], calendar_name: str) -> list[Event]:
    events = []
    for item in items:
        if item.get("status") == "cancelled" or item.get("eventType") in SKIP_TYPES:
            continue
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in item.get("attendees", [])):
            continue
        start, all_day = _when(item["start"])
        end, _ = _when(item["end"])
        location = item.get("location", "").strip()
        events.append(
            Event(
                uid=item.get("iCalUID") or item.get("id", ""),
                title=item.get("summary", "").strip() or "(No title)",
                start=start,
                end=end,
                all_day=all_day,
                # Hide raw meeting URLs in the location; the video badge covers it.
                location="" if re.match(r"https?://", location) else location,
                calendar=calendar_name,
                video=_video(item),
            )
        )
    return events


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".json")


def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.content


def fetch_events(calendars: list[dict]) -> tuple[list[Event], list[str]]:
    """Fetch all feeds. Returns (events, error messages).

    If a download fails, the last successful copy from disk is used instead,
    so a network blip (or booting before Wi-Fi is up) doesn't blank the screen.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    events: list[Event] = []
    errors: list[str] = []
    for cal in calendars:
        name, url = cal.get("name", "Calendar"), cal["url"]
        cache = _cache_path(url)
        items = None
        try:
            # A broken deployment answers with an HTML page, not JSON, so
            # parse before overwriting the cache.
            items = json.loads(_download(url))["items"]
            cache.write_text(json.dumps(items))
        except Exception as exc:
            log.warning("Fetching %s failed: %s", name, exc)
            errors.append(f"{name}: {exc.__class__.__name__}")
            if cache.exists():
                items = json.loads(cache.read_text())
        if items is not None:
            events.extend(parse_items(items, name))

    # Dedupe: the same meeting can appear on several calendars.
    unique = {(e.title, e.start, e.end): e for e in events}
    return sorted(unique.values(), key=lambda e: (e.start, e.end)), errors


# Demo scenes, cycled by tapping the screen in --demo mode.
DEMO_SCENES = [
    "Busy day",
    "Double-booked",
    "Triple-booked",
    "Four at once",
    "Back-to-back",
    "Screensaver",
    "Alert",
]


def demo_events(now: datetime | None = None, scene: int = 0) -> list[Event]:
    """Fake schedule for trying the display without a real calendar."""
    now = (now or datetime.now().astimezone()).replace(second=0, microsecond=0)
    m = lambda minutes: now + timedelta(minutes=minutes)  # noqa: E731
    later = [
        Event("d4", "Sprint planning", m(180), m(240), video="Teams"),
        Event("d5", "Company all-hands", m(60 * 22), m(60 * 23)),
    ]
    name = DEMO_SCENES[scene % len(DEMO_SCENES)]
    if name == "Double-booked":
        return [
            Event("c1", "1:1 with Sam", m(12), m(42)),
            Event("c2", "Vendor sync", m(12), m(57), video="Zoom"),
        ] + later
    if name == "Triple-booked":
        return [
            Event("c1", "Design review", m(15), m(75), video="Meet"),
            Event("c2", "1:1 with Sam", m(15), m(45)),
            Event("c3", "Hiring panel", m(30), m(60), video="Meet"),
        ] + later
    if name == "Four at once":
        return [
            Event("c1", "Design review", m(10), m(70), video="Meet"),
            Event("c2", "1:1 with Sam", m(10), m(40)),
            Event("c3", "Hiring panel", m(25), m(55), video="Meet"),
            Event("c4", "Vendor sync", m(30), m(50), video="Zoom"),
        ] + later
    if name == "Back-to-back":
        return [
            Event("b1", "Customer call", m(-20), m(10), video="Zoom"),
            Event("b2", "Roadmap review", m(10), m(40), video="Meet"),
            Event("b3", "Interview", m(40), m(85)),
            Event("b4", "Team lunch", m(85), m(145), location="Kitchen"),
        ]
    if name == "Screensaver":
        return [Event("s1", "Morning sync", m(60 * 7), m(60 * 7 + 30))]
    if name == "Alert":
        return [Event("a1", "Design review", m(5), m(35), video="Meet")] + later
    return [
        Event("d1", "Daily standup", m(-10), m(8), video="Zoom"),
        Event("d2", "Design review", m(8), m(38), video="Meet"),
        Event("d3", "1:1 with Sam", m(90), m(120)),
        Event("d3b", "Vendor sync", m(90), m(135), video="Zoom"),
    ] + later
