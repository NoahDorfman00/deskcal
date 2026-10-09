"""Pure scheduling logic: what's on now, what's next, which alerts are due."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .calendar_source import Event

# An alert that should have fired more than this long ago is skipped
# (e.g. the app was restarted mid-meeting) rather than going off late.
ALERT_GRACE = timedelta(seconds=90)


@dataclass(frozen=True)
class Alert:
    events: tuple[Event, ...]
    minutes_before: int  # 0 = starting now
    key: tuple


def timed(events: list[Event]) -> list[Event]:
    return [e for e in events if not e.all_day]


def current_events(events: list[Event], now: datetime) -> list[Event]:
    return [e for e in timed(events) if e.start <= now < e.end]


def upcoming_events(events: list[Event], now: datetime) -> list[Event]:
    return [e for e in timed(events) if e.start > now]


def due_alert(
    events: list[Event], now: datetime, offsets: list[int], fired: set
) -> Alert | None:
    """Return the alert that should go off right now, if any.

    Events starting at the same moment are grouped into one alert. Keys of
    alerts returned are added to `fired` so each only goes off once.
    """
    due: list[tuple[int, Event]] = []
    for e in timed(events):
        # Only the most recently passed trigger point matters; older ones are
        # stale (e.g. after a restart we shouldn't say "in 5 min" at start time).
        for minutes in sorted(set(offsets)):
            since = now - (e.start - timedelta(minutes=minutes))
            if since < timedelta(0):
                continue
            if since < ALERT_GRACE and (e.key, minutes) not in fired:
                due.append((minutes, e))
            break
    if not due:
        return None
    start = min(e.start for _, e in due)
    group = [(m, e) for m, e in due if e.start == start]
    minutes = min(m for m, _ in group)
    keys = tuple((e.key, m) for m, e in group)
    fired.update(keys)
    return Alert(tuple(e for _, e in group), minutes, keys)


def humanize_until(target: datetime, now: datetime, clock_24h: bool = False) -> str:
    """'in 5 min', 'in 1 hr 20 min', 'tomorrow 9:00 AM', 'Mon 9:00 AM'."""
    delta = target - now
    total_min = int((delta.total_seconds() + 59) // 60)  # round up
    if total_min <= 0:
        return "now"
    if total_min < 60:
        return f"in {total_min} min"
    if target.date() == now.date():
        hours, mins = divmod(total_min, 60)
        return f"in {hours} hr" + (f" {mins} min" if mins else "")
    days = (target.date() - now.date()).days
    when = fmt_time(target, clock_24h)
    if days == 1:
        return f"tomorrow {when}"
    if days < 7:
        return f"{target:%a} {when}"
    return f"{target:%b} {target.day} {when}"


def fmt_time(dt: datetime, clock_24h: bool = False) -> str:
    if clock_24h:
        return f"{dt:%H:%M}"
    # Not %p: it's locale-dependent ("pm" vs "PM") once Qt applies the locale.
    return f"{dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_range(e: Event, clock_24h: bool = False) -> str:
    start, end = fmt_time(e.start, clock_24h), fmt_time(e.end, clock_24h)
    if not clock_24h and start[-2:] == end[-2:]:
        start = start[:-3]  # "3:00 – 3:30 PM"
    return f"{start} – {end}"
