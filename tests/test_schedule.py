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


class CollisionTests(unittest.TestCase):
    now = datetime(2026, 10, 12, 13, 52, tzinfo=UTC)

    def at(self, uid, hour, minute, minutes=30):
        return ev(uid, datetime(2026, 10, 12, hour, minute, tzinfo=UTC), minutes)

    def test_single_next_meeting_is_not_a_collision(self):
        events = [self.at("a", 14, 0), self.at("b", 14, 30)]  # back to back
        self.assertEqual([e.uid for e in schedule.next_group(events, self.now)], ["a"])

    def test_overlapping_meetings_grouped_with_next(self):
        events = [self.at("a", 14, 0), self.at("b", 14, 0, 45), self.at("c", 15, 0)]
        self.assertEqual([e.uid for e in schedule.next_group(events, self.now)], ["a", "b"])

    def test_meeting_in_progress_that_runs_into_next_counts(self):
        events = [self.at("long", 13, 0, 90), self.at("a", 14, 0)]
        self.assertEqual([e.uid for e in schedule.next_group(events, self.now)], ["a", "long"])

    def test_nothing_upcoming(self):
        self.assertEqual(schedule.next_group([self.at("old", 9, 0)], self.now), [])


class FormatTests(unittest.TestCase):
    def test_countdown(self):
        now = datetime(2026, 10, 12, 13, 52, tzinfo=UTC)
        self.assertEqual(schedule.fmt_countdown(now + timedelta(minutes=8), now), "00:08:00")
        self.assertEqual(schedule.fmt_countdown(now + timedelta(hours=26, seconds=0.2), now), "26:00:01")
        self.assertEqual(schedule.fmt_countdown(now - timedelta(seconds=5), now), "00:00:00")

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


class IdleTests(unittest.TestCase):
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    horizon = timedelta(hours=6)

    def test_idle_with_no_meetings(self):
        self.assertTrue(schedule.is_idle([], self.now, self.horizon))

    def test_idle_until_next_meeting_is_within_horizon(self):
        events = [ev("a", self.now + timedelta(hours=6, minutes=1))]
        self.assertTrue(schedule.is_idle(events, self.now, self.horizon))
        self.assertFalse(schedule.is_idle(events, self.now + timedelta(minutes=1), self.horizon))

    def test_not_idle_during_a_meeting(self):
        events = [ev("a", self.now - timedelta(minutes=10))]
        self.assertFalse(schedule.is_idle(events, self.now, self.horizon))

    def test_all_day_events_ignored(self):
        events = [ev("a", self.now, minutes=24 * 60, all_day=True)]
        self.assertTrue(schedule.is_idle(events, self.now, self.horizon))


class ConcurrencyTests(unittest.TestCase):
    def test_overlap_counts_two(self):
        runs = schedule.concurrency([(0, 10), (5, 15)])
        self.assertEqual(runs, [(0, 5, 1), (5, 10, 2), (10, 15, 1)])

    def test_gap_between_meetings(self):
        self.assertEqual(schedule.concurrency([(0, 4), (6, 8)]), [(0, 4, 1), (6, 8, 1)])

    def test_contained_meeting(self):
        runs = schedule.concurrency([(0, 20), (5, 10), (5, 10)])
        self.assertEqual(runs, [(0, 5, 1), (5, 10, 3), (10, 20, 1)])
