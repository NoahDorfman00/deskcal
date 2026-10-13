# Desk Calendar

A "what's my next meeting" desk display for a Raspberry Pi touchscreen - shows what's on now and next, and chimes before each meeting starts.

![Desk Calendar counting down to the next meeting above a waveform of the day](docs/screenshot.png)

![Two overlapping meetings shown as a collision](docs/collision.png)

## Overview

Desk Calendar is a native PyQt5 fullscreen app for a small Raspberry Pi touchscreen (800×480) with speakers. It sits on a desk, shows the meeting you're in and the one coming up, and flashes the screen with a chime a few minutes before each meeting starts.

It reads a Google Calendar without an OAuth app. Work accounts often block third-party apps, secret iCal links and external sharing, so the calendar is published by a small Google Apps Script that runs inside the account itself, and the Pi simply polls it over HTTPS.

## Architecture

```
┌─────────────────────────────────────┐
│  Google account                     │
│  └── Apps Script web app (Code.gs)  │
│      └── Calendar API (as you)      │
└──────────────────┬──────────────────┘
                   │ HTTPS, JSON, polled every 5 min
┌──────────────────▼──────────────────┐
│  Raspberry Pi (Python/PyQt5)        │
│  ├── calendar_source  fetch + cache │
│  ├── schedule         now/next/alert│
│  ├── ui               fullscreen    │
│  └── sound            chimes        │
└─────────────────────────────────────┘
```

## Features

- **Logic analyzer display** - an `hh:mm:ss` countdown to the next meeting, its title, and a waveform of the next few hours in which every pulse is a meeting
- **Collisions** - double-booked meetings are listed together under a red banner, and the waveform grows a second trace with the overlap hatched
- **Built for a tiny panel** - the screen is about 70 × 50 mm, so nothing is drawn smaller than 32 px
- **Alerts** - the screen flashes and a chime plays N minutes before each meeting (default 5) and again when it starts; tap to dismiss, or it clears itself after 3 minutes
- **Video badges** - Meet, Zoom, Teams and Webex meetings are labeled
- **Noise filtering** - all-day events, cancelled events, working-location and out-of-office entries, and meetings you declined are skipped
- **Offline tolerant** - the last downloaded copy is kept on disk, so a network blip (or booting before Wi-Fi is up) doesn't blank the screen; a red OFFLINE flag appears next to the clock instead
- **Minimal data exposure** - the feed sends only the fields the display uses, and no attendee names or emails
- **Starts at boot** - runs as a systemd user service and restarts itself if it crashes

## Installation

### Prerequisites

- Raspberry Pi with a display (built on a Pi 5 with an 800×480 touchscreen), running Raspberry Pi OS with the Wayland desktop
- Speakers or an audio HAT for the chimes
- Python 3.11+
- A Google account whose calendar you want to show

### Install

```bash
git clone https://github.com/NoahDorfman00/deskcal.git ~/deskcal
cd ~/deskcal
./install.sh
```

This installs the dependencies, creates `~/.config/deskcal/config.toml` and `~/.config/deskcal/.env`, and enables the start-at-boot service.

### Calendar Feed

One-time setup, signed in with the Google account whose calendar you want:

1. At <https://script.google.com>, create a **New project** and replace the contents of `Code.gs` with [`apps_script/Code.gs`](apps_script/Code.gs).
2. *Services* (left sidebar) → **+** → **Google Calendar API** → *Add*.
3. *Deploy → New deployment → Web app*, with **Execute as: Me** and **Who has access: Anyone**. Approve the calendar permission prompt.
4. Put the **Web app URL** (ends in `/exec`) in `~/.config/deskcal/.env`:
   ```
   DESKCAL_WORK_FEED_URL=https://script.google.com/macros/s/.../exec
   ```
5. Restart the display: `systemctl --user restart deskcal`

Anyone with that URL can read your next week of meetings, so treat it like a password. To revoke it, *Deploy → Manage deployments → Archive*. After editing the script, publish a new version under *Manage deployments* (the URL stays the same).

### Manual Test

```bash
python3 -m deskcal --demo --windowed   # fake schedule in a window
python3 -m deskcal --test-sound        # play both chimes
```

## Configuration

Settings live in `~/.config/deskcal/config.toml`; secrets live next to it in `.env` (kept `chmod 600`) and are referenced by name:

```toml
calendars = [
  { name = "Work", url = "${DESKCAL_WORK_FEED_URL}" },
]

refresh_minutes = 5          # how often to re-download the calendars
alert_minutes_before = [5]   # chime this many minutes before each meeting
alert_at_start = true        # ...and again when it starts
volume = 0.8                 # chime volume, 0.0-1.0
chime = "bells"              # or "beeps" (test equipment), "terminal" (retro buzz)
clock_24h = false
```

Add one feed per Google account to show several calendars; a meeting that appears on more than one is shown once.

## Development

### Project Structure

```
deskcal/
├── apps_script/
│   └── Code.gs               # Apps Script web app (the calendar feed)
├── deskcal/
│   ├── __main__.py           # Entry point and CLI flags
│   ├── calendar_source.py    # Feed download, parsing, disk cache
│   ├── schedule.py           # Now/next, alert timing, time formatting
│   ├── ui.py                 # PyQt5 window and alert overlay
│   ├── fonts/                # Chakra Petch (SIL Open Font License)
│   ├── sound.py              # Chime generation and playback
│   └── config.py             # config.toml and .env loading
├── hardware/
│   └── stand/                # 3D-printable stand (OpenSCAD)
├── tests/                    # Unit tests
├── systemd/
│   └── deskcal.service       # Systemd user service
├── config.example.toml       # Settings template
├── .env.example              # Secrets template
├── install.sh                # Installation script
└── LICENSE                   # MIT license
```

### Key Files

- **`apps_script/Code.gs`** - The calendar feed
  - Runs inside your Google account as a web app
  - Returns the next 8 days of events as JSON
  - Strips descriptions down to their links

- **`deskcal/calendar_source.py`** - Fetching
  - Downloads and parses each feed
  - Filters declined, cancelled and non-meeting entries
  - Falls back to the cached copy when offline

- **`deskcal/schedule.py`** - Scheduling logic
  - Pure functions, no I/O
  - Decides what is on now, what is next and which alert is due

- **`deskcal/ui.py`** - Display
  - Fullscreen PyQt5 window
  - Pulsing alert overlay, tap to dismiss

### Tests

```bash
python3 -m unittest
```

## Usage

Once installed and configured, the display starts at boot and keeps itself in sync.

- Tap the main screen to force a sync
- Tap an alert to dismiss it

```bash
systemctl --user status deskcal        # service
journalctl --user -u deskcal -f        # logs
systemctl --user restart deskcal       # pick up code/config changes
```

To run it on the Pi screen from SSH, stop the service first, then:

```bash
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland python3 -m deskcal --demo
```

## Stand

The Pi, screen, audio HAT and speakers slot into a 3D-printed stand shaped like a mini oscilloscope, to go with the logic analyzer display.

![The stand, with the screen in the middle of an oscilloscope front panel](hardware/stand/preview.png)

- **Slot-in fit** - the screen and Pi tilt in from the back and drop onto a shelf; nothing is screwed down
- **Speakers** - they stand on end behind the side vents
- **Fidget-friendly** - the five knobs spin and the handle folds flat along the top
- **Desk footprint** - 161 × 106 mm and 133 mm tall, with the screen leaning back 18°
- **Easy to print** - every part prints without supports, about 250 g of PLA in all
- **Parametric** - an OpenSCAD model, so a different screen or speakers is a matter of changing a few numbers

The screen mount has been checked with a printed fit test, shown below. The full case has not been printed yet.

<p>
  <img src="hardware/stand/fit_test_front.jpg" alt="The screen counting down to the next meeting in demo mode, seated in the printed fit-test frame" width="56%">
  <img src="hardware/stand/fit_test_back.jpg" alt="The back of the fit test, with the Pi and audio HAT held by the shelf" width="37%">
</p>

The model, STL export script and print and assembly instructions are in [`hardware/stand`](hardware/stand/README.md).

## Troubleshooting

### "Add a calendar to ~/.config/deskcal/config.toml"
- No feed is configured: add an entry under `calendars` and its URL in `.env`

### The display says OFFLINE
- Check the network, then open the feed URL in a browser: it should show JSON
- If it shows a Google sign-in page, the deployment's access isn't set to **Anyone**
- If it shows a script error, check that the **Google Calendar API** service is added

### The app won't start after a config change
- Check the logs: `journalctl --user -u deskcal -f`
- A `${NAME}` used in `config.toml` must be set in `.env`

### No sound
- Run `python3 -m deskcal --test-sound`
- Check the output device and volume in the desktop's audio settings

## License

[MIT](LICENSE)
