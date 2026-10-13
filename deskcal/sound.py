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

# Each style has a heads-up ("soon") and a starting ("now") sound, as a list
# of (frequency Hz, start offset s) notes.
CHIMES = {
    "bells": {
        "soon": [(659.25, 0.0), (987.77, 0.18)],  # E5 → B5: gentle heads-up
        "now": [(783.99, 0.0), (987.77, 0.15), (1318.51, 0.30), (1318.51, 0.75)],  # G5 B5 E6 E6
    },
    # Flat test-equipment beeps, like a bench instrument: one, then three.
    "beeps": {
        "soon": [(2000.0, 0.0)],
        "now": [(2000.0, 0.0), (2000.0, 0.2), (2000.0, 0.4)],
    },
    # Harsh low buzz, like the bell of an old computer terminal: one, then two.
    "terminal": {
        "soon": [(800.0, 0.0)],
        "now": [(800.0, 0.0), (800.0, 0.34)],
    },
}


def _bell(freq: float, t: float) -> float:
    # Bell-ish tone: fundamental + soft overtone, fast attack, exp decay.
    env = min(1.0, t / 0.005) * math.exp(-t * 3.2)
    return env * (math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(2 * math.pi * freq * 2.01 * t))


BEEP_LENGTH = 0.11


def _beep(freq: float, t: float) -> float:
    # Square-ish wave (first few odd harmonics), gated flat with 3 ms ramps
    # at each end so it doesn't click.
    env = min(1.0, t / 0.003, (BEEP_LENGTH - t) / 0.003)
    return env * sum(math.sin(2 * math.pi * freq * k * t) / k for k in (1, 3, 5))


BUZZ_LENGTH = 0.24


def _buzz(freq: float, t: float) -> float:
    # Hard-edged square wave, gated flat like a speaker switched on and off.
    env = min(1.0, t / 0.002, (BUZZ_LENGTH - t) / 0.002)
    return env * (1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0)


# (waveform, note length s)
VOICES = {"bells": (_bell, 1.4), "beeps": (_beep, BEEP_LENGTH), "terminal": (_buzz, BUZZ_LENGTH)}


def _render(style: str, kind: str, path: Path) -> None:
    notes = CHIMES[style][kind]
    voice, note_length = VOICES[style]
    length = max(t for _, t in notes) + note_length
    samples = [0.0] * (int(RATE * length) + 1)
    for freq, offset in notes:
        begin = int(offset * RATE)
        for i in range(int(note_length * RATE)):
            samples[begin + i] += voice(freq, i / RATE)
    peak = max(abs(s) for s in samples) or 1.0
    frames = b"".join(struct.pack("<h", int(32000 * s / peak)) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)


def chime_path(kind: str, style: str = "bells") -> Path:
    path = CACHE_DIR / f"chime-{style}-{kind}-v2.wav"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _render(style, kind, path)
    return path


def play(kind: str, volume: float = 0.8, style: str = "bells") -> None:
    """Play a chime without blocking. Failures are logged, never raised."""
    try:
        path = chime_path(kind, style)
        if shutil.which("pw-play"):
            cmd = ["pw-play", "--volume", f"{volume:.2f}", str(path)]
        else:
            cmd = ["aplay", "-q", str(path)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log.exception("Could not play chime")
