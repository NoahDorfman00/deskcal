import unittest
from datetime import datetime, timedelta, timezone

from deskcal import schedule
from deskcal.calendar_source import Event, parse_ics

UTC = timezone.utc

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:standup
SUMMARY:Standup
DTSTART:20261012T140000Z
DTEND:20261012T141500Z
RRULE:FREQ=DAILY;COUNT=5
LOCATION:https://acme.zoom.us/j/123
END:VEVENT
BEGIN:VEVENT
UID:declined
SUMMARY:Declined thing
DTSTART:20261012T150000Z
DTEND:20261012T160000Z
ATTENDEE;PARTSTAT=DECLINED:mailto:me@example.com
END:VEVENT
BEGIN:VEVENT
UID:cancelled
SUMMARY:Cancelled thing
STATUS:CANCELLED
DTSTART:20261012T160000Z
DTEND:20261012T170000Z
END:VEVENT
BEGIN:VEVENT
UID:allday
SUMMARY:Holiday
DTSTART;VALUE=DATE:20261013
DTEND;VALUE=DATE:20261014
END:VEVENT
BEGIN:VEVENT
UID:review
SUMMARY:Review
DTSTART:20261012T180000Z
DURATION:PT30M
DESCRIPTION:Join https://meet.google.com/abc-defg-hij
END:VEVENT
END:VCALENDAR
"""


def ev(uid, start, minutes=30, **kw):
    return Event(uid, uid, start, start + timedelta(minutes=minutes), **kw)


class ParseTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 10, 12, tzinfo=UTC)
        self.events = parse_ics(ICS, "Work", start, start + timedelta(days=7), {"me@example.com"})

    def test_expands_recurrences_and_filters(self):
        titles = [e.title for e in self.events]
        self.assertEqual(titles.count("Standup"), 5)
        self.assertNotIn("Declined thing", titles)
        self.assertNotIn("Cancelled thing", titles)

    def test_video_and_location(self):
        standup = next(e for e in self.events if e.title == "Standup")
        self.assertEqual(standup.video, "Zoom")
        self.assertEqual(standup.location, "")  # raw URL hidden
        review = next(e for e in self.events if e.title == "Review")
        self.assertEqual(review.video, "Meet")
        self.assertEqual(review.end - review.start, timedelta(minutes=30))

    def test_all_day(self):
        holiday = next(e for e in self.events if e.title == "Holiday")
        self.assertTrue(holiday.all_day)
        self.assertIsNotNone(holiday.start.tzinfo)

    def test_recurrences_have_distinct_keys(self):
        keys = {e.key for e in self.events if e.title == "Standup"}
        self.assertEqual(len(keys), 5)


class AlertTests(unittest.TestCase):
    start = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)

    def test_fires_once_at_each_offset(self):
        events, fired = [ev("a", self.start)], set()
        at = lambda m, s=0: self.start - timedelta(minutes=m) + timedelta(seconds=s)  # noqa: E731
        self.assertIsNone(schedule.due_alert(events, at(5, -1), [5, 0], fired))
        alert = schedule.due_alert(events, at(5), [5, 0], fired)
        self.assertEqual(alert.minutes_before, 5)
        self.assertIsNone(schedule.due_alert(events, at(5, 1), [5, 0], fired))
        self.assertEqual(schedule.due_alert(events, at(0), [5, 0], fired).minutes_before, 0)
        self.assertIsNone(schedule.due_alert(events, at(0, 30), [5, 0], fired))

    def test_restart_near_start_skips_stale_heads_up(self):
        events, fired = [ev("a", self.start)], set()
        now = self.start + timedelta(seconds=10)
        self.assertEqual(schedule.due_alert(events, now, [1, 0], fired).minutes_before, 0)
        self.assertIsNone(schedule.due_alert(events, now, [1, 0], fired))

    def test_no_alert_long_after_trigger(self):
        events = [ev("a", self.start)]
        late = self.start - timedelta(minutes=2)  # 3 min past the 5-min trigger
        self.assertIsNone(schedule.due_alert(events, late, [5], set()))

    def test_simultaneous_meetings_grouped(self):
        events = [ev("a", self.start), ev("b", self.start), ev("c", self.start + timedelta(hours=1))]
        alert = schedule.due_alert(events, self.start, [0], set())
        self.assertEqual({e.uid for e in alert.events}, {"a", "b"})

    def test_all_day_never_alerts(self):
        events = [ev("h", self.start, all_day=True)]
        self.assertIsNone(schedule.due_alert(events, self.start, [0], set()))


class FormatTests(unittest.TestCase):
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

    def test_humanize(self):
        h = lambda **kw: schedule.humanize_until(self.now + timedelta(**kw), self.now)  # noqa: E731
        self.assertEqual(h(seconds=30), "in 1 min")
        self.assertEqual(h(minutes=45), "in 45 min")
        self.assertEqual(h(minutes=80), "in 1 hr 20 min")
        self.assertEqual(h(hours=2), "in 2 hr")
        self.assertEqual(h(days=1), "tomorrow 9:00 AM")
        self.assertEqual(h(days=3), "Thu 9:00 AM")

    def test_range(self):
        e = ev("x", datetime(2026, 10, 12, 15, 0, tzinfo=UTC))
        self.assertEqual(schedule.fmt_range(e), "3:00 – 3:30 PM")
        e2 = Event("y", "y", datetime(2026, 10, 12, 11, 30, tzinfo=UTC), datetime(2026, 10, 12, 12, 30, tzinfo=UTC))
        self.assertEqual(schedule.fmt_range(e2), "11:30 AM – 12:30 PM")
        self.assertEqual(schedule.fmt_range(e2, clock_24h=True), "11:30 – 12:30")


if __name__ == "__main__":
    unittest.main()
