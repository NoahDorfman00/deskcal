import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deskcal import calendar_source
from deskcal.calendar_source import parse_items

ITEMS = [
    {
        "id": "a", "iCalUID": "a@google.com", "summary": "Standup", "hangoutLink": "https://meet.google.com/x",
        "start": {"dateTime": "2026-10-12T10:00:00-04:00"}, "end": {"dateTime": "2026-10-12T10:15:00-04:00"},
    },
    {
        "id": "b", "summary": "Declined", "attendees": [{"email": "me@x.com", "self": True, "responseStatus": "declined"}],
        "start": {"dateTime": "2026-10-12T11:00:00-04:00"}, "end": {"dateTime": "2026-10-12T12:00:00-04:00"},
    },
    {
        "id": "c", "summary": "Home", "eventType": "workingLocation",
        "start": {"date": "2026-10-12"}, "end": {"date": "2026-10-13"},
    },
    {"id": "d", "status": "cancelled", "start": {"dateTime": "2026-10-12T13:00:00Z"}, "end": {"dateTime": "2026-10-12T14:00:00Z"}},
    {
        "id": "e", "summary": "Vendor call", "location": "https://acme.zoom.us/j/1",
        "conferenceData": {"conferenceSolution": {"name": "Zoom Meeting"}},
        "start": {"dateTime": "2026-10-12T15:00:00Z"}, "end": {"dateTime": "2026-10-12T15:30:00Z"},
    },
    {"id": "f", "summary": "Offsite", "start": {"date": "2026-10-14"}, "end": {"date": "2026-10-15"}},
]


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.events = {e.title: e for e in parse_items(ITEMS, "primary")}

    def test_filters(self):
        self.assertEqual(set(self.events), {"Standup", "Vendor call", "Offsite"})

    def test_fields(self):
        standup = self.events["Standup"]
        self.assertEqual(standup.video, "Meet")
        self.assertEqual(standup.uid, "a@google.com")
        self.assertEqual((standup.end - standup.start).total_seconds(), 15 * 60)
        self.assertEqual(self.events["Vendor call"].video, "Zoom")
        self.assertEqual(self.events["Vendor call"].location, "")
        self.assertTrue(self.events["Offsite"].all_day)
        self.assertIsNotNone(self.events["Offsite"].start.tzinfo)

    def test_video_link_in_description(self):
        item = dict(ITEMS[5], description="https://teams.microsoft.com/l/meetup-join/1")
        self.assertEqual(parse_items([item], "Work")[0].video, "Teams")

    def test_recurrences_have_distinct_keys(self):
        days = [dict(ITEMS[0], start={"dateTime": f"2026-10-{d}T10:00:00-04:00"}) for d in (12, 13, 14)]
        self.assertEqual(len({e.key for e in parse_items(days, "Work")}), 3)


class ScriptFeedTests(unittest.TestCase):
    CALS = [{"name": "Work", "url": "https://script.google.com/macros/s/x/exec"}]

    def fetch(self, body):
        with mock.patch.object(calendar_source, "_download", return_value=body):
            return calendar_source.fetch_events(self.CALS)

    def test_fetch_and_cache_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(calendar_source, "CACHE_DIR", Path(tmp)):
            events, errors = self.fetch(json.dumps({"items": ITEMS}).encode())
            self.assertEqual({e.title for e in events}, {"Standup", "Vendor call", "Offsite"})
            self.assertEqual(errors, [])
            self.assertEqual(events[0].calendar, "Work")

            # A sign-in page instead of JSON: keep showing the last good copy.
            events, errors = self.fetch(b"<html>Sign in</html>")
            self.assertEqual(len(events), 3)
            self.assertEqual(errors, ["Work: JSONDecodeError"])


if __name__ == "__main__":
    unittest.main()
