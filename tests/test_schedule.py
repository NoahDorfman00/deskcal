import unittest
from datetime import datetime, timedelta, timezone

from deskcal import schedule
from deskcal.calendar_source import Event

UTC = timezone.utc

def ev(uid, start, minutes=30, **kw):
    return Event(uid, uid, start, start + timedelta(minutes=minutes), **kw)


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
