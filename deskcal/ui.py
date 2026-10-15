"""Fullscreen PyQt5 display styled as a logic analyzer.

Clock, hh:mm:ss countdown to the next meeting, its title, and a waveform of
the hours ahead in which every pulse is a meeting. The panel is about
70 x 50 mm, so nothing on it is drawn smaller than 32 px.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import schedule, sound
from .calendar_source import Event, demo_events, fetch_events
from .config import Config

log = logging.getLogger(__name__)

FONT = "Chakra Petch"
FONT_DIR = Path(__file__).parent / "fonts"
MEDIUM, SEMIBOLD, BOLD = QFont.Medium, QFont.DemiBold, QFont.Bold

# Green phosphor monochrome, like an old benchtop scope. With no second hue,
# emphasis comes from brightness and from inverse video (dark on a lit bar).
BG = "#06100b"
PANEL = "#0a1a12"  # waveform background
GRID = "#17402b"  # graticule
BRIGHT = "#a8ffc6"  # countdown, first trace
TEXT = "#86f0ac"
MUTED = "#4dbb7c"
TRACE2 = "#3f9e68"  # second trace
GLOW = QColor(168, 255, 198, 40)  # phosphor bloom around a trace
HATCH = QColor(168, 255, 198, 110)  # overlap band on the waveform

CALM = SOON = URGENT = NOW = BRIGHT  # alert banner colors

W, H = 800, 480  # design size; scaled to fit the real window
MARGIN = 20
WAVE = QRectF(MARGIN, 324, W - 2 * MARGIN, 140)
WAVE_BEFORE = timedelta(hours=1)  # history shown left of the "now" cursor
WAVE_SPAN = timedelta(hours=6)
LINE = 6  # trace thickness

RETRY_SECONDS = 30  # retry interval after a failed fetch

# Screensaver: a Lissajous figure on a scope screen, morphing between ratios.
SCOPE = QRectF(MARGIN, 204, W - 2 * MARGIN, 260)
SCOPE_DIVS = (10, 4)  # graticule divisions across, down
FIGURES = [(1, 2), (3, 2), (3, 4), (5, 4), (2, 3), (1, 3), (4, 5)]  # x:y frequencies
FIGURE_HOLD = 40.0  # seconds each figure is shown, including the morph
FIGURE_MORPH = 5.0
PHASE_SPEED = 0.35  # rad/s of x phase drift; makes the figure seem to turn
BEAM_SPEED = 1.2  # rad/s the bright spot travels along the figure
BEAM_TAIL = 0.9  # rad of afterglow behind the spot
SCOPE_POINTS = 480
FRAME_MS = 33
PEEK = timedelta(seconds=30)  # a tap on the screensaver shows the full view this long


def urgency_color(minutes_away: float) -> str:
    if minutes_away <= 5:
        return URGENT
    if minutes_away <= 15:
        return SOON
    return CALM


def label(text: str = "", size: int = 32, color: str = TEXT, weight: int = 500) -> QLabel:
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


def describe(e: Event, clock_24h: bool, now: datetime | None = None) -> str:
    parts = [schedule.fmt_range(e, clock_24h)]
    if now and e.start.date() != now.date():
        days = (e.start.date() - now.date()).days
        parts.insert(0, "Tomorrow" if days == 1 else f"{e.start:%a}")
    if e.video:
        parts.append(e.video)
    if e.location:
        parts.append(e.location)
    return " · ".join(parts)


def load_fonts() -> None:
    for ttf in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(ttf)) < 0:
            log.warning("Could not load font %s", ttf.name)


def draw_text(
    p: QPainter,
    rect: QRectF,
    text: str,
    size: int,
    weight: int = MEDIUM,
    color: str = TEXT,
    align: Qt.AlignmentFlag = Qt.AlignLeft,
    min_size: int | None = None,
    tabular: bool = False,
) -> QRectF:
    """Draw one line in `rect`, shrinking then eliding it to fit the width.

    With `tabular`, digits get equal-width cells so a ticking countdown
    doesn't jitter. Returns the rectangle the text actually covers.
    """

    def measure(px: int):
        font = QFont(FONT)
        font.setPixelSize(px)
        font.setWeight(weight)
        fm = QFontMetricsF(font)
        digit = max(fm.horizontalAdvance(d) for d in "0123456789")
        cells = [digit if tabular and c.isdigit() else fm.horizontalAdvance(c) for c in text]
        return font, fm, cells, sum(cells) if tabular else fm.horizontalAdvance(text)

    font, fm, cells, width = measure(size)
    while width > rect.width() and size > (min_size or size):
        size -= 2
        font, fm, cells, width = measure(size)
    if width > rect.width():
        text = fm.elidedText(text, Qt.ElideRight, rect.width())
        tabular = False
        width = fm.horizontalAdvance(text)

    x = rect.right() - width if align == Qt.AlignRight else rect.left()
    baseline = rect.top() + (rect.height() + fm.ascent() - fm.descent()) / 2
    p.setFont(font)
    p.setPen(QColor(color))
    if tabular:
        cx = x
        for c, cell in zip(text, cells):
            p.drawText(QPointF(cx + (cell - fm.horizontalAdvance(c)) / 2, baseline), c)
            cx += cell
    else:
        p.drawText(QPointF(x, baseline), text)
    return QRectF(x, rect.top(), width, rect.height())


def draw_inverse(p: QPainter, rect: QRectF, text: str, size: int, weight: int = MEDIUM) -> QRectF:
    """Draw one line as inverse video: dark text on a lit bar."""
    inner = rect.adjusted(10, 0, -10, 0)
    bar = draw_text(p, inner, text, size, weight, BRIGHT).adjusted(-10, 0, 10, 0)
    p.fillRect(bar, QColor(BRIGHT))
    draw_text(p, inner, text, size, weight, BG)
    return bar


def lissajous(t: float, s0: float = 0.0, span: float = 2 * math.pi, n: int = SCOPE_POINTS):
    """Points (x, y) in [-1, 1] along the screensaver figure at time `t`.

    Each figure holds for FIGURE_HOLD seconds, then morphs into the next.
    """
    i, held = divmod(t, FIGURE_HOLD)
    a1, b1 = FIGURES[int(i) % len(FIGURES)]
    a2, b2 = FIGURES[(int(i) + 1) % len(FIGURES)]
    mix = min(1.0, max(0.0, (held - FIGURE_HOLD + FIGURE_MORPH) / FIGURE_MORPH))
    mix = mix * mix * (3 - 2 * mix)  # ease in and out
    phase = t * PHASE_SPEED
    points = []
    for k in range(n + 1):
        s = s0 + span * k / n
        x = (1 - mix) * math.sin(a1 * s + phase) + mix * math.sin(a2 * s + phase)
        y = (1 - mix) * math.sin(b1 * s) + mix * math.sin(b2 * s)
        points.append((x, y))
    return points


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
            events, errors = fetch_events(self.cfg.calendars)
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
        layout.setContentsMargins(24, 16, 24, 16)
        layout.addStretch()
        self.heading = label("", 88, TEXT, 700)
        self.title = label("", 52, TEXT, 600)
        self.title.setWordWrap(True)
        self.detail = label("", 32, TEXT, 500)
        for w in (self.heading, self.title, self.detail):
            w.setAlignment(Qt.AlignCenter)
            layout.addWidget(w)
            layout.addSpacing(8)
        layout.addStretch()

        self.pulse = QTimer(self, interval=700, timeout=self._toggle)
        self.hide()

    def show_alert(self, alert: schedule.Alert, volume: float, chime: str = "bells") -> None:
        first = alert.events[0]
        if alert.minutes_before == 0:
            self.heading.setText("STARTING NOW")
            self.color = NOW
        else:
            self.heading.setText(f"IN {alert.minutes_before} MIN")
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
        sound.play("now" if alert.minutes_before == 0 else "soon", volume, chime)

    def _toggle(self) -> None:
        self._pulse_on = not self._pulse_on
        self._apply()
        if self.shown_at and datetime.now() - self.shown_at > self.AUTO_DISMISS:
            self.dismiss()

    def _apply(self) -> None:
        bg = self.color if self._pulse_on else BG
        fg = BG if self._pulse_on else self.color
        self.setStyleSheet(f"AlertOverlay {{ background: {bg}; }}")
        for w in (self.heading, self.title, self.detail):
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
        self.peek_until: datetime | None = None
        self.t0 = time.monotonic()

        self.setWindowTitle("Desk Calendar")
        load_fonts()

        self.overlay = AlertOverlay(self, cfg.clock_24h)

        self.fetcher = Fetcher(cfg)
        self.fetcher.done.connect(self._on_fetched)
        self.fetch_timer = QTimer(self, singleShot=True, timeout=self.refresh)

        # Faster than once a second so the countdown never skips a beat.
        self.tick_timer = QTimer(self, interval=250, timeout=self.tick)
        self.tick_timer.start()
        # Only runs while the screensaver is up.
        self.frame_timer = QTimer(self, interval=FRAME_MS, timeout=self.update)

        if demo:
            self.last_sync = datetime.now()
        else:
            self.refresh()
        self.tick()

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

    def idle(self, now: datetime) -> bool:
        """Screensaver time: synced, and nothing for `screensaver_hours`."""
        if self.cfg.screensaver_hours <= 0 or (self.last_sync is None and not self.demo):
            return False
        if self.peek_until and now < self.peek_until:
            return False
        horizon = timedelta(hours=self.cfg.screensaver_hours)
        return schedule.is_idle(self.events, now, horizon)

    def tick(self) -> None:
        now = datetime.now().astimezone()
        self.update()
        if self.idle(now) != self.frame_timer.isActive():
            if self.frame_timer.isActive():
                self.frame_timer.stop()
            else:
                self.frame_timer.start()

        alert = schedule.due_alert(self.events, now, self.cfg.alert_offsets, self.fired)
        if alert:
            log.info("Alert: %s (%d min)", [e.title for e in alert.events], alert.minutes_before)
            self.overlay.show_alert(alert, self.cfg.volume, self.cfg.chime)

        # Keep the fired set from growing forever.
        if now.second == 0:
            live = {e.key for e in self.events if e.end > now - timedelta(hours=1)}
            self.fired = {k for k in self.fired if k[0] in live}

    # ---- drawing ------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        now = datetime.now().astimezone()
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QColor(BG))
        scale = min(self.width() / W, self.height() / H)
        p.translate((self.width() - W * scale) / 2, (self.height() - H * scale) / 2)
        p.scale(scale, scale)

        if self.idle(now):
            self._paint_screensaver(p, now)
            return
        self._paint_header(p, now)
        group = schedule.next_group(self.events, now)
        if len(group) > 1:
            self._paint_collision(p, now, group)
        elif group:
            self._paint_next(p, now, group[0])
        else:
            self._paint_clear(p)
        self._paint_wave(p, now)

    def _paint_header(self, p: QPainter, now: datetime) -> None:
        row = QRectF(MARGIN, 16, W - 2 * MARGIN, 40)
        used = draw_text(p, row, schedule.fmt_time(now, self.cfg.clock_24h), 40, SEMIBOLD)
        if self.errors:
            rest = QRectF(used.right() + 20, row.top(), 200, row.height())
            used = draw_inverse(p, rest, "OFFLINE", 32, SEMIBOLD)
        right = QRectF(used.right() + 60, row.top(), row.right() - used.right() - 60, row.height())

        current = schedule.current_events(self.events, now)
        if not current:
            draw_text(p, right, f"{now:%a %b} {now.day}", 32, MEDIUM, MUTED, Qt.AlignRight)
            return
        title = current[0].title + (f" +{len(current) - 1}" if len(current) > 1 else "")
        drawn = draw_text(p, right, title, 32, SEMIBOLD, TEXT, Qt.AlignRight)
        p.fillRect(QRectF(drawn.left() - 30, row.center().y() - 9, 18, 18), QColor(TEXT))

    def _paint_next(self, p: QPainter, now: datetime, e: Event) -> None:
        wide = W - 2 * MARGIN
        countdown = schedule.fmt_countdown(e.start, now)
        draw_text(p, QRectF(MARGIN, 64, wide, 116), countdown, 116, BOLD, BRIGHT, tabular=True)
        draw_text(p, QRectF(MARGIN, 186, wide, 68), e.title, 64, SEMIBOLD, min_size=48)
        detail = describe(e, self.cfg.clock_24h, now)
        draw_text(p, QRectF(MARGIN, 262, wide, 40), detail, 32, MEDIUM, MUTED)

    def _paint_collision(self, p: QPainter, now: datetime, group: list[Event]) -> None:
        wide = W - 2 * MARGIN
        banner = f"{len(group)} AT ONCE · {schedule.fmt_countdown(group[0].start, now)}"
        bar = QRectF(MARGIN, 62, wide, 80)
        p.fillRect(bar, QColor(BRIGHT))
        draw_text(p, bar.adjusted(12, 0, -12, 0), banner, 72, BOLD, BG, min_size=48, tabular=True)
        rows = sorted(group, key=lambda e: (e.start, e.end))[:2]  # same order as the traces
        for e, color, y in zip(rows, (BRIGHT, TRACE2), (154, 226)):
            row = QRectF(MARGIN, y, wide, 56)
            p.fillRect(QRectF(row.left(), row.center().y() - 14, 28, 28), QColor(color))
            ends = "to " + schedule.fmt_time(e.end, self.cfg.clock_24h)
            drawn = draw_text(p, row, ends, 32, MEDIUM, MUTED, Qt.AlignRight)
            title = QRectF(row.left() + 42, y, drawn.left() - row.left() - 58, row.height())
            draw_text(p, title, e.title, 52, SEMIBOLD, min_size=40)

    def _paint_clear(self, p: QPainter) -> None:
        wide = W - 2 * MARGIN
        if not self.cfg.calendars and not self.demo:
            detail = "Add a calendar in config.toml"
        elif self.last_sync is None and not self.demo:
            detail = "Waiting for the calendar" if self.errors else "Syncing…"
        else:
            detail = "Nothing in the next week"
        draw_text(p, QRectF(MARGIN, 64, wide, 116), "ALL CLEAR", 104, BOLD, BRIGHT)
        draw_text(p, QRectF(MARGIN, 186, wide, 68), "No meetings", 64, SEMIBOLD)
        draw_text(p, QRectF(MARGIN, 262, wide, 40), detail, 32, MEDIUM, MUTED)

    def _paint_screensaver(self, p: QPainter, now: datetime) -> None:
        wide = W - 2 * MARGIN
        clock = schedule.fmt_time(now, self.cfg.clock_24h)
        draw_text(p, QRectF(MARGIN, 8, wide, 132), clock, 128, BOLD, BRIGHT, min_size=96, tabular=True)
        row = QRectF(MARGIN, 144, wide, 44)
        used = draw_text(p, row, f"{now:%A, %B} {now.day}", 36, MEDIUM, MUTED)
        if self.errors:
            draw_inverse(p, QRectF(used.right() + 20, row.top(), 200, row.height()), "OFFLINE", 32, SEMIBOLD)

        p.save()
        p.setClipRect(SCOPE)
        p.fillRect(SCOPE, QColor(PANEL))
        cols, rows = SCOPE_DIVS
        dx, dy = SCOPE.width() / cols, SCOPE.height() / rows
        for i in range(1, cols):
            p.fillRect(QRectF(SCOPE.left() + i * dx - 1, SCOPE.top(), 2, SCOPE.height()), QColor(GRID))
        for j in range(1, rows):
            p.fillRect(QRectF(SCOPE.left(), SCOPE.top() + j * dy - 1, SCOPE.width(), 2), QColor(GRID))
        # Minor ticks on the centre axes, five per division.
        c = SCOPE.center()
        for i in range(cols * 5):
            p.fillRect(QRectF(SCOPE.left() + i * dx / 5 - 1, c.y() - 6, 2, 12), QColor(GRID))
        for j in range(rows * 5):
            p.fillRect(QRectF(c.x() - 6, SCOPE.top() + j * dy / 5 - 1, 12, 2), QColor(GRID))

        rx, ry = 2.5 * dx, 1.5 * dy  # five divisions wide, three tall

        def polygon(points) -> QPolygonF:
            return QPolygonF([QPointF(c.x() + x * rx, c.y() - y * ry) for x, y in points])

        t = time.monotonic() - self.t0
        trace = polygon(lissajous(t))
        for ink, width in ((GLOW, 12), (QColor(TRACE2), 3)):
            p.setPen(QPen(ink, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(trace)
        # The beam: a bright spot with a fading afterglow behind it.
        head = (t * BEAM_SPEED) % (2 * math.pi)
        tail = polygon(lissajous(t, head - BEAM_TAIL, BEAM_TAIL, 40))
        beam = QColor(BRIGHT)
        for k in range(1, tail.size()):
            beam.setAlphaF(k / (tail.size() - 1))
            p.setPen(QPen(beam, LINE, Qt.SolidLine, Qt.FlatCap))
            p.drawLine(tail[k - 1], tail[k])
        p.setPen(Qt.NoPen)
        p.setBrush(GLOW)
        p.drawEllipse(tail[tail.size() - 1], 14, 14)
        p.setBrush(QColor(BRIGHT))
        p.drawEllipse(tail[tail.size() - 1], 6, 6)
        p.restore()

    def _paint_wave(self, p: QPainter, now: datetime) -> None:
        """Every pulse is a meeting; a second trace appears when two overlap."""
        start = now - WAVE_BEFORE
        end = start + WAVE_SPAN
        shown = [e for e in schedule.timed(self.events) if e.end > start and e.start < end]
        rows = schedule.lanes(shown)

        def x_of(t: datetime) -> float:
            return WAVE.left() + (t - start) / WAVE_SPAN * WAVE.width()

        p.save()
        p.setClipRect(WAVE)
        p.fillRect(WAVE, QColor(PANEL))
        # Graticule: a line on every hour, plus the horizontal centre line.
        hour = start.replace(minute=0, second=0, microsecond=0)
        while hour < end:
            p.fillRect(QRectF(x_of(hour) - 1, WAVE.top(), 2, WAVE.height()), QColor(GRID))
            hour += timedelta(hours=1)
        p.fillRect(QRectF(WAVE.left(), WAVE.center().y() - 1, WAVE.width(), 2), QColor(GRID))
        if len(rows) > 1:
            traces = [(rows[0], BRIGHT, 17, 61), ([e for r in rows[1:] for e in r], TRACE2, 81, 125)]
        else:
            traces = [(rows[0] if rows else [], BRIGHT, 33, 107)]
        for events, color, top, base in traces:
            top, base = WAVE.top() + top, WAVE.top() + base
            path = QPainterPath(QPointF(WAVE.left(), base))
            edge = WAVE.left()
            for e in sorted(events, key=lambda e: e.start):
                # Inset so back-to-back meetings read as separate pulses.
                x0 = max(x_of(e.start) + LINE, edge)
                x1 = max(x_of(e.end) - LINE, x0 + LINE)
                for point in ((x0, base), (x0, top), (x1, top), (x1, base)):
                    path.lineTo(*point)
                edge = x1
            path.lineTo(WAVE.right(), base)
            for ink, width in ((GLOW, LINE * 3), (QColor(color), LINE)):
                p.setPen(QPen(ink, width, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
                p.drawPath(path)

        p.setPen(QPen(HATCH, LINE, Qt.SolidLine, Qt.FlatCap))
        for a, b in schedule.overlaps(shown):
            band = QRectF(x_of(a), WAVE.top(), x_of(b) - x_of(a), WAVE.height())
            p.setClipRect(band.intersected(WAVE))
            x = band.left() - WAVE.height()
            while x < band.right():
                p.drawLine(QPointF(x, WAVE.bottom()), QPointF(x + WAVE.height(), WAVE.top()))
                x += 16
        p.setClipRect(WAVE)
        p.fillRect(QRectF(x_of(now) - 2, WAVE.top(), 4, WAVE.height()), QColor(BRIGHT))
        p.restore()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        now = datetime.now().astimezone()
        if self.idle(now):
            self.peek_until = now + PEEK  # show the full view for a moment
            self.tick()
        self.refresh()  # tap the screen to sync now
