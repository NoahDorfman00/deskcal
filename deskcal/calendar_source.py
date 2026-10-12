"""Fetch iCal feeds and turn them into a flat, sorted list of events."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import icalendar
import recurring_ical_events
import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "deskcal"

VIDEO_PATTERNS = [
    ("Zoom", re.compile(r"https://[\w.-]*zoom\.us/[^\s<>\"']+")),
    ("Meet", re.compile(r"https://meet\.google\.com/[^\s<>\"']+")),
    ("Teams", re.compile(r"https://teams\.microsoft\.com/[^\s<>\"']+")),
    ("Webex", re.compile(r"https://[\w.-]*webex\.com/[^\s<>\"']+")),
]


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


def _to_local(value: date | datetime) -> tuple[datetime, bool]:
    """Return (aware local datetime, is_all_day)."""
    if not isinstance(value, datetime):
        return datetime.combine(value, time()).astimezone(), True
    if value.tzinfo is None:  # "floating" time: treat as local
        return value.astimezone(), False
    return value.astimezone(), False


def _declined(component, my_emails: set[str]) -> bool:
    if not my_emails:
        return False
    attendees = component.get("ATTENDEE", [])
    if not isinstance(attendees, list):
        attendees = [attendees]
    for att in attendees:
        email = str(att).lower().removeprefix("mailto:")
        if email in my_emails and str(att.params.get("PARTSTAT", "")).upper() == "DECLINED":
            return True
    return False


def _detect_video(component) -> str:
    text = " ".join(
        str(component.get(field, ""))
        for field in ("LOCATION", "DESCRIPTION", "URL", "X-GOOGLE-CONFERENCE")
    )
    for name, pattern in VIDEO_PATTERNS:
        if pattern.search(text):
            return name
    return ""


def parse_ics(
    data: bytes | str,
    calendar_name: str,
    window_start: datetime,
    window_end: datetime,
    my_emails: set[str] = frozenset(),
) -> list[Event]:
    cal = icalendar.Calendar.from_ical(data)
    events = []
    for comp in recurring_ical_events.of(cal).between(window_start, window_end):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if _declined(comp, my_emails):
            continue
        start, all_day = _to_local(comp.decoded("DTSTART"))
        if "DTEND" in comp:
            end, _ = _to_local(comp.decoded("DTEND"))
        elif "DURATION" in comp:
            end = start + comp.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        location = str(comp.get("LOCATION", "")).strip()
        events.append(
            Event(
                uid=str(comp.get("UID", "")),
                title=str(comp.get("SUMMARY", "")).strip() or "(No title)",
                start=start,
                end=end,
                all_day=all_day,
                # Hide raw meeting URLs in the location; the video badge covers it.
                location="" if location.startswith("http") else location,
                calendar=calendar_name,
                video=_detect_video(comp),
            )
        )
    return events


def _cache_path(url: str, suffix: str = ".ics") -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:16] + suffix)


def _download(url: str) -> bytes:
    # Google/Outlook hand out webcal:// links; they're plain https underneath.
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.content


def fetch_events(
    calendars: list[dict],
    my_emails: set[str],
    google_calendars: list[str] = (),
    script_calendars: list[dict] = (),
    now: datetime | None = None,
) -> tuple[list[Event], list[str]]:
    """Fetch all iCal feeds, Apps Script feeds and Google calendars.

    Returns (events, error messages).

    If a download fails, the last successful copy from disk is used instead,
    so a network blip (or booting before Wi-Fi is up) doesn't blank the screen.
    """
    now = now or datetime.now().astimezone()
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=8)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    events: list[Event] = []
    errors: list[str] = []
    for cal in calendars:
        name, url = cal.get("name", "Calendar"), cal["url"]
        cache = _cache_path(url)
        try:
            data = _download(url)
            cache.write_bytes(data)
        except Exception as exc:
            log.warning("Fetching %s failed: %s", name, exc)
            errors.append(f"{name}: {exc.__class__.__name__}")
            if not cache.exists():
                continue
            data = cache.read_bytes()
        try:
            events.extend(parse_ics(data, name, window_start, window_end, my_emails))
        except Exception as exc:
            log.exception("Parsing %s failed", name)
            errors.append(f"{name}: parse error ({exc.__class__.__name__})")

    if script_calendars:
        from .google_source import parse_items

    for cal in script_calendars:
        name, url = cal.get("name", "Calendar"), cal["url"]
        cache = _cache_path(url, ".json")
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

    if google_calendars:
        from . import google_source

        g_events, g_errors = google_source.fetch(list(google_calendars), window_start, window_end)
        events.extend(g_events)
        errors.extend(g_errors)

    # Dedupe: the same meeting can appear on several subscribed calendars.
    unique = {(e.title, e.start, e.end): e for e in events}
    return sorted(unique.values(), key=lambda e: (e.start, e.end)), errors


def demo_events(now: datetime | None = None) -> list[Event]:
    """Fake schedule for trying the display without a real calendar."""
    now = (now or datetime.now().astimezone()).replace(second=0, microsecond=0)
    m = lambda minutes: now + timedelta(minutes=minutes)  # noqa: E731
    return [
        Event("d1", "Daily standup", m(-10), m(5), video="Zoom"),
        Event("d2", "Design review: calendar display", m(1), m(31), location="Room 4B", video="Meet"),
        Event("d3", "1:1 with Sam", m(90), m(120)),
        Event("d4", "Sprint planning", m(180), m(240), video="Teams"),
        Event("d5", "Company all-hands", m(60 * 22), m(60 * 23)),
    ]
