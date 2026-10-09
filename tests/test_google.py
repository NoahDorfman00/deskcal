import unittest

from deskcal.google_source import parse_items

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


class GoogleParseTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
