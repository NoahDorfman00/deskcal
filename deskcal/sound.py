"""Generate and play alert chimes (no audio assets needed)."""

from __future__ import annotations

import logging
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from .calendar_source import CACHE_DIR

log = logging.getLogger(__name__)

RATE = 44100

# (frequency Hz, start offset s) per note
CHIMES = {
    "soon": [(659.25, 0.0), (987.77, 0.18)],  # E5 → B5: gentle heads-up
    "now": [(783.99, 0.0), (987.77, 0.15), (1318.51, 0.30), (1318.51, 0.75)],  # G5 B5 E6 E6
}


def _render(notes: list[tuple[float, float]], path: Path) -> None:
    length = max(t for _, t in notes) + 1.4
    samples = [0.0] * int(RATE * length)
    for freq, offset in notes:
        begin = int(offset * RATE)
        for i in range(int(1.4 * RATE)):
            t = i / RATE
            # Bell-ish tone: fundamental + soft overtone, fast attack, exp decay.
            env = min(1.0, t / 0.005) * math.exp(-t * 3.2)
            val = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(2 * math.pi * freq * 2.01 * t)
            samples[begin + i] += 0.35 * env * val
    peak = max(abs(s) for s in samples) or 1.0
    frames = b"".join(struct.pack("<h", int(32000 * s / peak)) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)


def chime_path(kind: str) -> Path:
    path = CACHE_DIR / f"chime-{kind}-v1.wav"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _render(CHIMES[kind], path)
    return path


def play(kind: str, volume: float = 0.8) -> None:
    """Play a chime without blocking. Failures are logged, never raised."""
    try:
        path = chime_path(kind)
        if shutil.which("pw-play"):
            cmd = ["pw-play", "--volume", f"{volume:.2f}", str(path)]
        else:
            cmd = ["aplay", "-q", str(path)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log.exception("Could not play chime")
