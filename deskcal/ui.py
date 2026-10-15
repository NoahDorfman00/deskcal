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

from PyQt5.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QLinearGradient,
    QRadialGradient,
    QTransform,
)
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import schedule, sound
from .calendar_source import DEMO_SCENES, Event, demo_events, fetch_events
from .config import Config

log = logging.getLogger(__name__)

FONT = "Chakra Petch"
FONT_DIR = Path(__file__).parent / "fonts"
MEDIUM, SEMIBOLD, BOLD = QFont.Medium, QFont.DemiBold, QFont.Bold

# Green phosphor monochrome, like an old benchtop scope. With no second hue,
# emphasis comes from brightness and from inverse video (dark on a lit bar).
BG = "#06100b"
GRID = "#17402b"  # graticule
AXIS = "#2a6b47"  # time axis on the meeting screen
BRIGHT = "#a8ffc6"  # countdown, first trace
TEXT = "#86f0ac"
MUTED = "#4dbb7c"
TRACE2 = "#3f9e68"  # screensaver figure
GLOW = QColor(168, 255, 198, 40)  # phosphor bloom around a trace
HATCH = QColor(168, 255, 198, 50)  # overlap band on the waveform

CALM = SOON = URGENT = NOW = BRIGHT  # alert banner colors

W, H = 800, 480  # design size; scaled to fit the real window
MARGIN = 20
LINE = 6  # trace thickness

RETRY_SECONDS = 30  # retry interval after a failed fetch

# Graticule over the whole face. Behind text it fades to a blurred, dimmer
# copy so the words stay legible, and the text itself gets a phosphor bloom.
DIV = 80  # px per division: 10 x 6 across the panel
TEXT_HALO = 10  # blur radius, in device px, of the zone cleared around text
GRID_SOFT = 3  # blur radius of the grid seen through that zone
SCANLINE = 3  # px between faint horizontal scanlines

# Meeting screen: the graticule is the waveform's timebase. The horizontal
# axis is time, the vertical axis is "now", and every pulse is a meeting.
WAVE = QRectF(0, 4 * DIV, W, 2 * DIV)  # bottom two divisions; top edge is the axis
TIMEBASE = timedelta(minutes=40)  # per division: 40 min back, 6 h ahead
NOW_X = DIV
CURSOR_FADE = 2 * DIV  # how far the "now" axis reaches up into the text
TRACE_ALPHA = 0.45  # meeting traces are dim; the sweeping beam lights them up
SWEEP_SECONDS = 6.0  # time for the beam to cross the screen
SWEEP_REST = 0.25  # fraction of a sweep the beam spends off-screen before the next
SWEEP_TAIL = 160  # px of afterglow behind the beam
# The trace rises one step per meeting at once, between these heights below
# the axis. Steps are sized for the busiest clash on screen, but never for
# fewer than two, so a lone meeting stays at half height.
TRACE_FLOOR = 136
TRACE_CEILING = 30  # leaves room for ringing and interference under the axis
MIN_STEPS = 2
JITTER = 5  # px of interference per extra meeting in a clash
RING = 14  # px of overshoot where the trace jumps into a clash

# Screensaver: a Lissajous figure on the graticule, morphing between ratios.
SCOPE_CENTER = QPointF(W / 2, 4 * DIV)
FIGURES = [(1, 2), (3, 2), (3, 4), (5, 4), (2, 3), (1, 3), (4, 5)]  # x:y frequencies
FIGURE_HOLD = 40.0  # seconds each figure is shown, including the morph
FIGURE_MORPH = 5.0
PHASE_SPEED = 0.35  # rad/s of x phase drift; makes the figure seem to turn
BEAM_SPEED = 1.2  # rad/s the bright spot travels along the figure
BEAM_TAIL = 0.9  # rad of afterglow behind the spot
SCOPE_POINTS = 480
FRAME_MS = 33
PEEK = timedelta(seconds=30)  # a tap on the screensaver shows the full view this long
SCENE_LABEL = timedelta(seconds=3)  # how long a demo scene's name stays up


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


def blur(img: QImage, radius: int, boost: int = 1) -> QImage:
    """Cheap blur: shrink, then smoothly scale back up.

    `boost` stacks the result on itself to widen the solid core.
    """
    size = img.size()
    small = img.scaled(
        QSize(max(1, size.width() // radius), max(1, size.height() // radius)),
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )
    out = small.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if boost > 1:
        p = QPainter(out)
        for _ in range(boost - 1):
            p.drawImage(0, 0, out)
        p.end()
    return out


def layer(size: QSize) -> QImage:
    img = QImage(size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


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
        self.scene = 0
        self.scene_shown: datetime | None = None
        self.fired: set = set()
        self.last_sync: datetime | None = None
        self.errors: list[str] = []
        self.peek_until: datetime | None = None
        self.t0 = time.monotonic()
        # Cached per size and screen: graticule (sharp, soft), CRT glass.
        self.layers: tuple[tuple, QImage, QImage, QImage] | None = None
        # Grid + text, composed in tick() so animation frames only add the trace.
        self.backdrop: QImage | None = None
        self.backdrop_key = None

        self.setWindowTitle("Desk Calendar")
        load_fonts()

        self.overlay = AlertOverlay(self, cfg.clock_24h)

        self.fetcher = Fetcher(cfg)
        self.fetcher.done.connect(self._on_fetched)
        self.fetch_timer = QTimer(self, singleShot=True, timeout=self.refresh)

        # Faster than once a second so the countdown never skips a beat.
        self.tick_timer = QTimer(self, interval=250, timeout=self.tick)
        self.tick_timer.start()
        # Animation: the screensaver figure and the beam sweeping the meetings.
        self.frame_timer = QTimer(self, interval=FRAME_MS, timeout=self.update)
        self.frame_timer.start()

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
        self.compose(now)
        self.update()

        alert = schedule.due_alert(self.events, now, self.cfg.alert_offsets, self.fired)
        if alert:
            log.info("Alert: %s (%d min)", [e.title for e in alert.events], alert.minutes_before)
            self.overlay.show_alert(alert, self.cfg.volume, self.cfg.chime)

        # Keep the fired set from growing forever.
        if now.second == 0:
            live = {e.key for e in self.events if e.end > now - timedelta(hours=1)}
            self.fired = {k for k in self.fired if k[0] in live}

    # ---- drawing ------------------------------------------------------
    def design(self) -> QTransform:
        """Maps the 800 x 480 design onto the real window, centred."""
        scale = min(self.width() / W, self.height() / H)
        t = QTransform()
        t.translate((self.width() - W * scale) / 2, (self.height() - H * scale) / 2)
        t.scale(scale, scale)
        return t

    def painter(self, device) -> QPainter:
        p = QPainter(device)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setTransform(self.design())
        return p

    def _layers(self, idle: bool) -> tuple[QImage, QImage, QImage]:
        """Graticule (sharp, soft) and CRT glass, cached per size and screen."""
        key = (self.size(), idle)
        if self.layers and self.layers[0] == key:
            return self.layers[1:]
        size = self.size()
        inverse, _ = self.design().inverted()
        area = inverse.mapRect(QRectF(self.rect()))  # visible design area

        grid = layer(size)
        p = self.painter(grid)
        ink = QColor(GRID)
        # No lines on the very edge: the panel smears its edge pixels into a bar.
        x = math.floor(area.left() / DIV + 1) * DIV
        while x < area.right() - 1:
            p.fillRect(QRectF(x - 1, area.top(), 2, area.height()), ink)
            x += DIV
        y = math.floor(area.top() / DIV + 1) * DIV
        while y < area.bottom() - 1:
            p.fillRect(QRectF(area.left(), y - 1, area.width(), 2), ink)
            y += DIV
        p.end()
        # Axes go on the sharp grid only, so they vanish cleanly behind text.
        soft = blur(grid, GRID_SOFT, 2)
        p = self.painter(grid)
        if idle:
            self._paint_scope_axes(p, area)
        else:
            self._paint_wave_axes(p, area)
        p.end()

        # CRT glass: faint scanlines and darkened corners.
        glass = layer(size)
        p = QPainter(glass)
        for y in range(0, size.height(), SCANLINE):
            p.fillRect(0, y, size.width(), 1, QColor(0, 0, 0, 24))
        r = math.hypot(size.width(), size.height()) / 2
        shade = QRadialGradient(QPointF(size.width() / 2, size.height() / 2), r)
        shade.setColorAt(0.55, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 170))
        p.fillRect(glass.rect(), shade)
        p.end()

        self.layers = (key, grid, soft, glass)
        return self.layers[1:]

    def _paint_scope_axes(self, p: QPainter, area: QRectF) -> None:
        self._paint_axes(p, area, SCOPE_CENTER, QColor(GRID))

    def _paint_wave_axes(self, p: QPainter, area: QRectF) -> None:
        """Time axis along the top of the waveform; "now" axis fading up into the text."""
        c = QPointF(NOW_X, WAVE.top())
        fade = QLinearGradient(0, c.y(), 0, c.y() - CURSOR_FADE)
        fade.setColorAt(0, QColor(AXIS))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(area.left(), c.y() - 1, area.width(), 2), QColor(AXIS))
        p.fillRect(QRectF(c.x() - 1, area.top(), 2, area.height()), fade)
        self._paint_axes(p, area, c, fade)

    def _paint_axes(self, p: QPainter, area: QRectF, c: QPointF, ink) -> None:
        """Minor ticks along the axes through `c`, five per division.

        None on the screen edges, where the panel would smear them into a bar.
        """
        step = DIV / 5
        x = c.x() - math.floor((c.x() - area.left()) / step) * step
        if x < area.left() + 2:
            x += step
        while x < area.right() - 1:
            p.fillRect(QRectF(x - 1, c.y() - 6, 2, 12), ink)
            x += step
        y = c.y() - math.floor((c.y() - area.top()) / step) * step
        if y < area.top() + 2:
            y += step
        while y < area.bottom() - 1:
            p.fillRect(QRectF(c.x() - 6, y - 1, 12, 2), ink)
            y += step

    def compose(self, now: datetime) -> None:
        """Build the backdrop: graticule, cleared and blurred behind the text."""
        idle = self.idle(now)
        if idle:  # the screensaver's text changes once a minute
            key = (self.size(), schedule.fmt_time(now, self.cfg.clock_24h), now.date(), bool(self.errors))
            if key == self.backdrop_key and self.backdrop:
                return
        else:
            key = None
        self.backdrop_key = key
        grid, soft, _ = self._layers(idle)

        text = layer(self.size())
        p = self.painter(text)
        if idle:
            self._paint_clock(p, now)
        else:
            self._paint_header(p, now)
            group = schedule.next_group(self.events, now)
            if len(group) > 1:
                self._paint_collision(p, now, group)
            elif group:
                self._paint_next(p, now, group[0])
            else:
                self._paint_clear(p)
        p.end()
        halo = blur(text, TEXT_HALO, 4)

        sharp = grid.copy()
        p = QPainter(sharp)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        p.drawImage(0, 0, halo)
        p.end()
        hazy = soft.copy()
        p = QPainter(hazy)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, halo)
        p.end()

        out = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(QColor(BG))
        p = QPainter(out)
        p.drawImage(0, 0, sharp)
        p.setOpacity(0.7)
        p.drawImage(0, 0, hazy)
        p.setOpacity(0.6)
        p.drawImage(0, 0, blur(text, 4))  # phosphor bloom
        p.setOpacity(1)
        p.drawImage(0, 0, text)
        p.end()
        self.backdrop = out

    # ---- drawing ------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        now = datetime.now().astimezone()
        if self.backdrop is None or self.backdrop.size() != self.size():
            self.compose(now)
        p = QPainter(self)
        p.drawImage(0, 0, self.backdrop)
        p.setRenderHints(QPainter.Antialiasing)
        p.setTransform(self.design())
        if self.idle(now):
            self._paint_scope(p)
        else:
            self._paint_wave(p, now)
        if self.scene_shown and datetime.now() - self.scene_shown < SCENE_LABEL:
            name = f"DEMO {self.scene + 1}/{len(DEMO_SCENES)} · {DEMO_SCENES[self.scene].upper()}"
            draw_inverse(p, QRectF(W - MARGIN - 560, H - 56, 560, 40), name, 32, SEMIBOLD)
        p.resetTransform()
        p.drawImage(0, 0, self._layers(self.idle(now))[2])

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
        # Up to three meetings fit between the banner and the waveform.
        rows = sorted(group, key=lambda e: (e.start, e.end))
        more = len(rows) - 3 if len(rows) > 3 else 0
        rows = rows[: 2 if more else 3]
        height = 144 / len(rows) if len(rows) + bool(more) < 3 else 160 / 3
        size = 52 if len(rows) + bool(more) < 3 else 44
        y = 154
        for e in rows:
            row = QRectF(MARGIN, y, wide, height)
            p.fillRect(QRectF(row.left(), row.center().y() - 14, 28, 28), QColor(BRIGHT))
            ends = "to " + schedule.fmt_time(e.end, self.cfg.clock_24h)
            drawn = draw_text(p, row, ends, 32, MEDIUM, MUTED, Qt.AlignRight)
            title = QRectF(row.left() + 42, y, drawn.left() - row.left() - 58, row.height())
            draw_text(p, title, e.title, size, SEMIBOLD, min_size=36)
            y += height
        if more:
            draw_text(p, QRectF(MARGIN + 42, y, wide - 42, height), f"+{more + 1} more", 32, MEDIUM, MUTED)

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

    def _paint_clock(self, p: QPainter, now: datetime) -> None:
        wide = W - 2 * MARGIN
        clock = schedule.fmt_time(now, self.cfg.clock_24h)
        draw_text(p, QRectF(MARGIN, 8, wide, 132), clock, 128, BOLD, BRIGHT, min_size=96, tabular=True)
        row = QRectF(MARGIN, 144, wide, 44)
        used = draw_text(p, row, f"{now:%A, %B} {now.day}", 36, MEDIUM, MUTED)
        if self.errors:
            draw_inverse(p, QRectF(used.right() + 20, row.top(), 200, row.height()), "OFFLINE", 32, SEMIBOLD)

    def _paint_scope(self, p: QPainter) -> None:
        c = SCOPE_CENTER
        rx, ry = 2.5 * DIV, 1.5 * DIV  # five divisions wide, three tall

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

    def _paint_wave(self, p: QPainter, now: datetime) -> None:
        """One trace: high during a meeting, higher and full of interference
        where meetings clash."""
        start = now - NOW_X / DIV * TIMEBASE
        end = now + (W - NOW_X) / DIV * TIMEBASE
        shown = [e for e in schedule.timed(self.events) if e.end > start and e.start < end]

        def x_of(t: datetime) -> float:
            return NOW_X + (t - now) / TIMEBASE * DIV

        # Inset each meeting so back-to-back ones read as separate pulses.
        spans = [(x_of(e.start) + LINE, max(x_of(e.end) - LINE, x_of(e.start) + 2 * LINE)) for e in shown]
        runs = schedule.concurrency(spans)
        clashes = [(a, b) for a, b, n in runs if n > 1]
        t = time.monotonic() - self.t0

        steps = max([MIN_STEPS] + [n for _, _, n in runs])
        rise = (TRACE_FLOOR - TRACE_CEILING) / steps

        def y_of(n: int) -> float:
            return WAVE.top() + TRACE_FLOOR - n * rise

        base = y_of(0)
        path = QPainterPath(QPointF(WAVE.left() - LINE, base))
        level = 0
        for a, b, n in runs:
            if path.currentPosition().x() < a:  # dropped back to nothing between runs
                if level:
                    path.lineTo(path.currentPosition().x(), base)
                path.lineTo(a, base)
                level = 0
            y = y_of(n)
            path.lineTo(a, y)
            if n > 1:
                x = a
                while x < b:
                    x = min(x + 3, b)
                    d = x - a
                    ring = RING * math.exp(-d / 14) * math.cos(d * 0.5)
                    noise = math.sin(x * 0.9 + t * 23) * 0.6 + math.sin(x * 0.37 - t * 11) * 0.4
                    jitter = min(JITTER * (n - 1), rise / 2)  # busier clashes are noisier
                    path.lineTo(x, y - ring + jitter * noise * (1 - math.exp(-d / 6)))
                path.lineTo(b, y)
            else:
                path.lineTo(b, y)
            level = n
        if level:
            path.lineTo(path.currentPosition().x(), base)
        path.lineTo(WAVE.right() + LINE, base)

        p.save()
        p.setClipRect(WAVE)
        p.setPen(QPen(HATCH, LINE, Qt.SolidLine, Qt.FlatCap))
        for a, b in clashes:
            band = QRectF(a, WAVE.top(), b - a, WAVE.height())
            p.setClipRect(band.intersected(WAVE))
            x = band.left() - WAVE.height()
            while x < band.right():
                p.drawLine(QPointF(x, WAVE.bottom()), QPointF(x + WAVE.height(), WAVE.top()))
                x += 16
        p.setClipRect(WAVE)

        dim = QColor(BRIGHT)
        dim.setAlphaF(TRACE_ALPHA)
        for ink, width in ((GLOW, LINE * 3), (dim, LINE)):
            p.setPen(QPen(ink, width, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
            p.drawPath(path)
        x = (t / SWEEP_SECONDS) % (1 + SWEEP_REST) * W
        self._paint_beam(p, path, x, BRIGHT, flare=any(a <= x <= b for a, b in clashes))
        p.restore()

    def _paint_beam(
        self, p: QPainter, path: QPainterPath, x: float, color: str, flare: bool = False
    ) -> None:
        """A bright spot where `path` reaches `x`, with a fading afterglow behind it.

        With `flare`, the spot blooms, as it does crossing a clash.
        """
        if x > W:
            return  # resting off-screen between sweeps
        lo, hi = 0.0, path.length()  # the path only moves rightward: bisect for x
        for _ in range(20):
            mid = (lo + hi) / 2
            if path.pointAtPercent(path.percentAtLength(mid)).x() < x:
                lo = mid
            else:
                hi = mid
        head = hi
        steps = 32
        points = [
            path.pointAtPercent(path.percentAtLength(max(0.0, head - SWEEP_TAIL * (1 - k / steps))))
            for k in range(steps + 1)
        ]
        beam = QColor(color)
        for k in range(1, len(points)):
            beam.setAlphaF(k / steps)
            p.setPen(QPen(beam, LINE, Qt.SolidLine, Qt.FlatCap))
            p.drawLine(points[k - 1], points[k])
        p.setPen(Qt.NoPen)
        p.setBrush(GLOW)
        p.drawEllipse(points[-1], 14, 14)
        if flare:
            p.drawEllipse(points[-1], 26, 26)
        p.setBrush(QColor(BRIGHT))
        p.drawEllipse(points[-1], 9 if flare else 6, 9 if flare else 6)
        p.setBrush(Qt.NoBrush)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.overlay.setGeometry(self.rect())
        self.compose(datetime.now().astimezone())
        super().resizeEvent(event)

    def next_scene(self) -> None:
        """Demo mode: tap through the scenarios."""
        self.scene = (self.scene + 1) % len(DEMO_SCENES)
        self.events = demo_events(scene=self.scene)
        self.fired = set()  # so the alert scene goes off every time round
        self.scene_shown = datetime.now()
        log.info("Demo scene: %s", DEMO_SCENES[self.scene])
        self.tick()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.demo:
            self.next_scene()
            return
        now = datetime.now().astimezone()
        if self.idle(now):
            self.peek_until = now + PEEK  # show the full view for a moment
            self.tick()
        self.refresh()  # tap the screen to sync now
