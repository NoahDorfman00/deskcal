# Desk Calendar

A fullscreen "what's my next meeting" display for a Raspberry Pi with a
small touchscreen (800×480) and speakers. It chimes and flashes the screen
before each meeting starts.

![layout](docs/screenshot.png)

## What it shows

- **Clock and date**
- **NOW**: the meeting you're in, and how much time is left
- **NEXT**: the next meeting, with a countdown. The accent color changes as it
  gets close: blue (>15 min), amber (≤15), red (≤5)
- **Later today**: the next couple of meetings after that
- **Sync status**: turns amber with "offline" if the calendar can't be reached
  (the last downloaded copy keeps being used)

**Alerts**: the screen flashes and a chime plays N minutes before each meeting
(default 5) and again when it starts. Tap to dismiss. Alerts auto-dismiss after 3 min.
Tap the main screen to force a sync.

All-day events, cancelled events, and (if `my_emails` is set) meetings you
declined are skipped.

## Setup

```bash
./install.sh                         # deps + config + start-at-boot service
nano ~/.config/deskcal/config.toml   # add your secret iCal URL(s)
systemctl --user restart deskcal
```

Calendars are read from **secret iCal (ICS) URLs**, so no OAuth is needed. See
`config.example.toml` for where to find the URL in Google, Outlook, or iCloud.
The config lives outside the repo because those URLs are secrets.

## Running / developing

```bash
python3 -m deskcal --demo --windowed   # fake schedule in a window
python3 -m deskcal --test-sound        # play both chimes
python3 -m unittest                    # tests

systemctl --user status deskcal        # service
journalctl --user -u deskcal -f        # logs
systemctl --user restart deskcal       # pick up code/config changes
```

To try it on the Pi screen from SSH, stop the service first, then:
`XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland python3 -m deskcal --demo`

## Layout

| Path | |
|---|---|
| `deskcal/calendar_source.py` | download + parse ICS (recurrences, declines, video links), disk cache |
| `deskcal/schedule.py` | pure logic: now/next, alert timing, time formatting |
| `deskcal/ui.py` | PyQt5 fullscreen window and alert overlay |
| `deskcal/sound.py` | generates the chimes and plays them via PipeWire |
| `systemd/deskcal.service` | user service (symlinked into `~/.config/systemd/user`) |

The service runs as a *user* unit (linger is enabled), waits for the labwc
Wayland socket, and restarts automatically if it crashes.
