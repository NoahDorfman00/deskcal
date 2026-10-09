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
nano ~/.config/deskcal/config.toml   # add iCal URL(s) and/or Google calendars
systemctl --user restart deskcal
```

Calendars are read from **secret iCal (ICS) URLs**, so no OAuth is needed. See
`config.example.toml` for where to find the URL in Google, Outlook, or iCloud.
The config lives outside the repo because those URLs are secrets.

## Google Calendar sign-in (when iCal links are blocked)

Reads your calendar through the Google Calendar API with read-only access
(`calendar.readonly`). One-time setup:

1. **Create an OAuth client.** At <https://console.cloud.google.com>, signed in
   with your **work** account if your company lets you create projects (best:
   an "Internal" app needs no Google review, and its sign-in doesn't expire):
   - Create a project (e.g. "Desk Calendar").
   - *APIs & Services → Library*: enable **Google Calendar API**.
   - *Google Auth Platform / OAuth consent screen*: audience **Internal**
     (work project), or **External** (personal project; then *Publish app*,
     because in "Testing" mode Google expires the sign-in every 7 days).
   - *Data access*: add scope `.../auth/calendar.readonly`.
   - *Clients → Create client → Desktop app*, then download the JSON.
2. **Copy it to the Pi** as `~/.config/deskcal/google_client.json`:
   `scp client_secret_*.json tars@lil-ark.local:.config/deskcal/google_client.json`
3. **Sign in.** From your laptop:
   ```bash
   ssh -L 8085:localhost:8085 tars@lil-ark.local
   cd ~/deskcal && python3 -m deskcal --login
   ```
   Open the printed link in your laptop's browser and sign in with your work
   account. Google redirects back to `localhost:8085`, which the tunnel carries
   to the Pi. The token is saved to `~/.config/deskcal/google_token.json` and
   the display restarts.

Set `google_calendars = ["primary"]` in the config (add other calendar IDs if
you want them too). If Google says the app is blocked, your Workspace admin
needs to allow it.

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
| `deskcal/google_source.py` | Google Calendar API source + `--login` flow |
| `deskcal/schedule.py` | pure logic: now/next, alert timing, time formatting |
| `deskcal/ui.py` | PyQt5 fullscreen window and alert overlay |
| `deskcal/sound.py` | generates the chimes and plays them via PipeWire |
| `systemd/deskcal.service` | user service (symlinked into `~/.config/systemd/user`) |

The service runs as a *user* unit (linger is enabled), waits for the labwc
Wayland socket, and restarts automatically if it crashes.
