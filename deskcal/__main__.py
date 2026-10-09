"""Entry point: python3 -m deskcal [--demo] [--windowed] [--test-sound]."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import config, sound


def main() -> int:
    parser = argparse.ArgumentParser(prog="deskcal", description="Desk meeting display")
    parser.add_argument("--config", type=Path, default=config.DEFAULT_PATH)
    parser.add_argument("--demo", action="store_true", help="show a fake schedule")
    parser.add_argument("--windowed", action="store_true", help="don't go fullscreen")
    parser.add_argument("--test-sound", action="store_true", help="play both chimes and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = config.load(args.config)

    if args.test_sound:
        sound.play("soon", cfg.volume)
        time.sleep(2.5)
        sound.play("now", cfg.volume)
        time.sleep(3)
        return 0

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from .ui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("deskcal")
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # let Ctrl+C / systemd stop us

    win = MainWindow(cfg, demo=args.demo)
    if args.windowed:
        win.resize(800, 480)
        win.show()
    else:
        app.setOverrideCursor(Qt.BlankCursor)
        win.showFullScreen()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
