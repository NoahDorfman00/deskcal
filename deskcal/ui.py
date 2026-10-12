"""Fullscreen PyQt5 display: clock, current/next meeting, later today, alerts."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import schedule, sound
from .calendar_source import Event, demo_events, fetch_events
from .config import Config

log = logging.getLogger(__name__)

FONT = "Nunito Sans"
BG = "#0f1115"
CARD = "#1a1d24"
TEXT = "#f2f3f5"
MUTED = "#8b919c"
CALM = "#5aa9e6"  # > 15 min away
SOON = "#f4b942"  # <= 15 min
URGENT = "#ff5c5c"  # <= 5 min
NOW = "#4cc38a"  # in progress

RETRY_SECONDS = 30  # retry interval after a failed fetch


def urgency_color(minutes_away: float) -> str:
    if minutes_away <= 5:
        return URGENT
    if minutes_away <= 15:
        return SOON
    return CALM


def label(text: str = "", size: int = 16, color: str = TEXT, weight: int = 400) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; font-family: '{FONT}'; font-size: {size}px; font-weight: {weight};"
        " background: transparent;"
    )
    return lbl


def restyle(lbl: QLabel, color: str) -> None:
    css = lbl.styleSheet()
    start = css.index("color:")
    lbl.setStyleSheet(css[:start] + f"color: {color};" + css[css.index(";", start) + 1 :])


def describe(e: Event, clock_24h: bool) -> str:
    parts = [schedule.fmt_range(e, clock_24h)]
    if e.video:
        parts.append(e.video)
    if e.location:
        parts.append(e.location)
    return "  ·  ".join(parts)


class Fetcher(QObject):
    """Runs calendar downloads off the UI thread."""

    done = pyqtSignal(list, list)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self._busy = False

    def start(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            events, errors = fetch_events(
                self.cfg.calendars,
                self.cfg.my_emails,
                self.cfg.google_calendars,
                self.cfg.script_calendars,
            )
        except Exception as exc:  # never let the thread die silently
            log.exception("Fetch failed")
            events, errors = None, [str(exc)]
        self._busy = False
        self.done.emit(events if events is not None else [], errors)


class AlertOverlay(QFrame):
    """Full-screen, pulsing banner. Tap anywhere to dismiss."""

    AUTO_DISMISS = timedelta(minutes=3)

    def __init__(self, parent: QWidget, clock_24h: bool):
        super().__init__(parent)
        self.clock_24h = clock_24h
        self.shown_at: datetime | None = None
        self.color = URGENT
        self._pulse_on = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.addStretch()
        self.heading = label("", 54, TEXT, 800)
        self.title = label("", 34, TEXT, 700)
        self.title.setWordWrap(True)
        self.detail = label("", 22, TEXT, 400)
        self.hint = label("tap to dismiss", 16, TEXT, 400)
        for w in (self.heading, self.title, self.detail):
            w.setAlignment(Qt.AlignCenter)
            layout.addWidget(w)
            layout.addSpacing(8)
        layout.addStretch()
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

        self.pulse = QTimer(self, interval=700, timeout=self._toggle)
        self.hide()

    def show_alert(self, alert: schedule.Alert, volume: float) -> None:
        first = alert.events[0]
        if alert.minutes_before == 0:
            self.heading.setText("Starting now")
            self.color = NOW
        else:
            self.heading.setText(f"In {alert.minutes_before} min")
            self.color = urgency_color(alert.minutes_before)
        titles = [e.title for e in alert.events]
        self.title.setText(titles[0] if len(titles) == 1 else " + ".join(titles))
        self.detail.setText(describe(first, self.clock_24h))
        self.shown_at = datetime.now()
        self.setGeometry(self.parentWidget().rect())
        self._pulse_on = True
        self._apply()
        self.show()
        self.raise_()
        self.pulse.start()
        sound.play("now" if alert.minutes_before == 0 else "soon", volume)

    def _toggle(self) -> None:
        self._pulse_on = not self._pulse_on
        self._apply()
        if self.shown_at and datetime.now() - self.shown_at > self.AUTO_DISMISS:
            self.dismiss()

    def _apply(self) -> None:
        bg = self.color if self._pulse_on else BG
        fg = BG if self._pulse_on else self.color
        self.setStyleSheet(f"AlertOverlay {{ background: {bg}; }}")
        for w in (self.heading, self.title, self.detail, self.hint):
            restyle(w, fg)

    def dismiss(self) -> None:
        self.pulse.stop()
        self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.dismiss()


class MainWindow(QWidget):
    def __init__(self, cfg: Config, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.events: list[Event] = demo_events() if demo else []
        self.fired: set = set()
        self.last_sync: datetime | None = None
        self.errors: list[str] = []

        self.setWindowTitle("Desk Calendar")
        self.setStyleSheet(f"background: {BG};")
        self._build()

        self.overlay = AlertOverlay(self, cfg.clock_24h)

        self.fetcher = Fetcher(cfg)
        self.fetcher.done.connect(self._on_fetched)
        self.fetch_timer = QTimer(self, singleShot=True, timeout=self.refresh)

        self.tick_timer = QTimer(self, interval=1000, timeout=self.tick)
        self.tick_timer.start()

        if demo:
            self.last_sync = datetime.now()
        else:
            self.refresh()
        self.tick()

    # ---- layout -------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 12, 28, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.clock = label("", 46, TEXT, 700)
        self.date = label("", 20, MUTED, 400)
        header.addWidget(self.clock)
        header.addStretch()
        header.addWidget(self.date, alignment=Qt.AlignRight | Qt.AlignVCenter)
        root.addLayout(header)

        # "Now" strip, only visible while a meeting is in progress.
        self.now_bar = QFrame(objectName="nowBar")
        self.now_bar.setStyleSheet(
            f"#nowBar {{ background: {CARD}; border-left: 5px solid {NOW}; border-radius: 8px; }}"
        )
        now_layout = QHBoxLayout(self.now_bar)
        now_layout.setContentsMargins(16, 8, 16, 8)
        self.now_tag = label("NOW", 15, NOW, 800)
        self.now_title = label("", 19, TEXT, 600)
        self.now_ends = label("", 16, MUTED, 400)
        now_layout.addWidget(self.now_tag)
        now_layout.addSpacing(10)
        now_layout.addWidget(self.now_title, 1)
        now_layout.addWidget(self.now_ends)
        root.addWidget(self.now_bar)

        # The main "next meeting" card.
        self.card = QFrame(objectName="card")
        card = QVBoxLayout(self.card)
        card.setContentsMargins(24, 16, 24, 18)
        card.setSpacing(6)
        self.next_tag = label("", 18, CALM, 800)
        self.next_title = label("", 34, TEXT, 700)
        self.next_title.setWordWrap(True)
        self.next_detail = label("", 19, MUTED, 400)
        card.addWidget(self.next_tag)
        card.addWidget(self.next_title)
        card.addWidget(self.next_detail)
        card.addStretch()
        root.addWidget(self.card, 1)

        self.later_heading = label("LATER TODAY", 14, MUTED, 800)
        root.addWidget(self.later_heading)
        self.later_rows = []
        for _ in range(2):
            row = QHBoxLayout()
            t = label("", 18, MUTED, 600)
            t.setFixedWidth(110)
            n = label("", 18, TEXT, 400)
            row.addWidget(t)
            row.addWidget(n, 1)
            root.addLayout(row)
            self.later_rows.append((t, n))

        self.status = label("", 13, MUTED, 400)
        self.status.setAlignment(Qt.AlignRight)
        self.status.setWordWrap(True)  # long error text mustn't widen the window
        root.addWidget(self.status)

    def _style_card(self, color: str) -> None:
        self.card.setStyleSheet(
            f"#card {{ background: {CARD}; border-left: 6px solid {color}; border-radius: 12px; }}"
        )

    # ---- data ---------------------------------------------------------
    def refresh(self) -> None:
        if self.demo:
            return
        self.fetcher.start()

    def _on_fetched(self, events: list, errors: list) -> None:
        if events or not errors:
            self.events = events
            self.last_sync = datetime.now()
        self.errors = errors
        if errors:
            log.warning("Fetch errors: %s", errors)
        delay = RETRY_SECONDS if errors else self.cfg.refresh_minutes * 60
        self.fetch_timer.start(int(delay * 1000))
        self.tick()

    # ---- every second -------------------------------------------------
    def tick(self) -> None:
        now = datetime.now().astimezone()
        h24 = self.cfg.clock_24h
        self.clock.setText(schedule.fmt_time(now, h24))
        self.date.setText(f"{now:%A, %B} {now.day}")

        # In progress
        current = schedule.current_events(self.events, now)
        if current:
            e = current[0]
            extra = f"  +{len(current) - 1} more" if len(current) > 1 else ""
            self.now_title.setText(e.title + extra)
            left = int((e.end - now).total_seconds() // 60) + 1
            self.now_ends.setText(f"ends {schedule.fmt_time(e.end, h24)} · {left} min left")
            self.now_bar.show()
        else:
            self.now_bar.hide()

        # Next up
        upcoming = schedule.upcoming_events(self.events, now)
        if upcoming:
            e = upcoming[0]
            minutes_away = (e.start - now).total_seconds() / 60
            color = urgency_color(minutes_away)
            self.next_tag.setText("NEXT  ·  " + schedule.humanize_until(e.start, now, h24).upper())
            restyle(self.next_tag, color)
            self.next_title.setText(e.title)
            self.next_detail.setText(describe(e, h24))
            self._style_card(color)
        else:
            self.next_tag.setText("ALL CLEAR")
            restyle(self.next_tag, NOW)
            self.next_title.setText("No upcoming meetings")
            if not self.cfg.has_sources and not self.demo:
                self.next_detail.setText("Add a calendar to ~/.config/deskcal/config.toml")
            elif self.last_sync is None and not self.demo:
                self.next_detail.setText("Waiting for the calendar (see status below)")
            else:
                self.next_detail.setText("Nothing on the calendar for the next week")
            self._style_card(NOW)

        # Later today (after the next one)
        later = [e for e in upcoming[1:] if e.start.date() == now.date()]
        self.later_heading.setVisible(bool(later))
        for i, (t, n) in enumerate(self.later_rows):
            if i < len(later):
                t.setText(schedule.fmt_time(later[i].start, h24))
                n.setText(later[i].title)
            else:
                t.setText("")
                n.setText("")

        self._update_status(now)

        alert = schedule.due_alert(self.events, now, self.cfg.alert_offsets, self.fired)
        if alert:
            log.info("Alert: %s (%d min)", [e.title for e in alert.events], alert.minutes_before)
            self.overlay.show_alert(alert, self.cfg.volume)

        # Keep the fired set from growing forever.
        if now.second == 0:
            live = {e.key for e in self.events if e.end > now - timedelta(hours=1)}
            self.fired = {k for k in self.fired if k[0] in live}

    def _update_status(self, now: datetime) -> None:
        if self.demo:
            self.status.setText("demo mode")
            return
        if self.last_sync is None:
            text = "syncing…" if not self.errors else "; ".join(self.errors)
        else:
            text = f"synced {schedule.fmt_time(self.last_sync.astimezone(), self.cfg.clock_24h)}"
            if self.errors:
                text = "offline · last " + text
        self.status.setText(text)
        restyle(self.status, SOON if self.errors else MUTED)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.refresh()  # tap the screen to sync now
