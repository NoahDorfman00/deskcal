"""Google Calendar API source (read-only), for calendars without an iCal link.

One-time setup: put an OAuth "Desktop app" client JSON at CLIENT_FILE and run
`python3 -m deskcal --login`. The resulting refresh token is kept in TOKEN_FILE.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from .calendar_source import CACHE_DIR, VIDEO_PATTERNS, Event, _to_local

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "deskcal"
CLIENT_FILE = CONFIG_DIR / "google_client.json"
TOKEN_FILE = CONFIG_DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
API = "https://www.googleapis.com/calendar/v3"
LOGIN_PORT = 8085

# Calendar entries that aren't meetings.
SKIP_TYPES = {"workingLocation", "outOfOffice"}


class NotSignedIn(Exception):
    pass


def _save_token(creds) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())


def load_credentials():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_FILE.exists():
        raise NotSignedIn("not signed in")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise NotSignedIn("sign-in expired")
        try:
            creds.refresh(Request())
        except RefreshError as exc:  # revoked, expired, or blocked by admin
            raise NotSignedIn(f"sign-in expired ({exc.args[0] if exc.args else exc})") from exc
        _save_token(creds)
    return creds


def login() -> None:
    """Interactive one-time sign-in using a loopback redirect on LOGIN_PORT."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_FILE.exists():
        raise SystemExit(f"Missing {CLIENT_FILE}: download your OAuth client JSON there first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=LOGIN_PORT,
        open_browser=False,
        prompt="consent",  # always hand back a refresh token
        authorization_prompt_message=(
            "\nOpen this link in a browser (on your laptop, through the SSH tunnel\n"
            f"`ssh -L {LOGIN_PORT}:localhost:{LOGIN_PORT} <pi>`, or on the Pi itself):\n\n{{url}}\n"
        ),
        success_message="Desk Calendar is signed in. You can close this tab.",
    )
    _save_token(creds)
    print(f"Signed in. Token saved to {TOKEN_FILE}")


def _when(field: dict) -> tuple[datetime, bool]:
    if "dateTime" in field:
        return _to_local(datetime.fromisoformat(field["dateTime"]))
    return _to_local(date.fromisoformat(field["date"]))


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
                location="" if re.match(r"https?://", location) else location,
                calendar=calendar_name,
                video=_video(item),
            )
        )
    return events


def _download(session, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
    url = f"{API}/calendars/{quote(calendar_id, safe='')}/events"
    params = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",  # expand recurring events
        "orderBy": "startTime",
        "maxResults": "250",
    }
    items: list[dict] = []
    while True:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("items", []))
        if not body.get("nextPageToken"):
            return items
        params["pageToken"] = body["nextPageToken"]


def fetch(calendar_ids: list[str], start: datetime, end: datetime) -> tuple[list[Event], list[str]]:
    """Fetch events; falls back to the last good copy on disk per calendar."""
    from google.auth.transport.requests import AuthorizedSession

    events: list[Event] = []
    errors: list[str] = []
    session = None
    try:
        session = AuthorizedSession(load_credentials())
    except NotSignedIn as exc:
        errors.append(f"Google: {exc}: run `python3 -m deskcal --login`")
    except Exception as exc:
        log.warning("Google auth failed: %s", exc)
        errors.append(f"Google: {exc.__class__.__name__}")

    for cal_id in calendar_ids:
        cache = CACHE_DIR / f"google-{quote(cal_id, safe='')}.json"
        items = None
        if session is not None:
            try:
                items = _download(session, cal_id, start, end)
                cache.write_text(json.dumps(items))
            except Exception as exc:
                log.warning("Google fetch of %s failed: %s", cal_id, exc)
                errors.append(f"Google: {exc.__class__.__name__}")
        if items is None and cache.exists():
            items = json.loads(cache.read_text())
        if items is not None:
            events.extend(parse_items(items, cal_id))
    return events, errors
