#!/usr/bin/env bash
# Install dependencies and set Desk Calendar to launch at boot.
set -euo pipefail
cd "$(dirname "$0")"

sudo apt-get install -y python3-pyqt5 qtwayland5 python3-requests \
  python3-icalendar python3-recurring-ical-events fonts-nunito-sans pipewire-bin || \
  echo "WARNING: apt reported errors (see above); continuing" >&2

mkdir -p ~/.config/deskcal
if [ ! -f ~/.config/deskcal/config.toml ]; then
  cp config.example.toml ~/.config/deskcal/config.toml
  echo "Created ~/.config/deskcal/config.toml (add your calendar URL there)"
fi

if [ "$(pwd)" != "$HOME/deskcal" ]; then
  echo "NOTE: the service expects the repo at ~/deskcal (WorkingDirectory=%h/deskcal)" >&2
fi

mkdir -p ~/.config/systemd/user
ln -sf "$(pwd)/systemd/deskcal.service" ~/.config/systemd/user/deskcal.service
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable deskcal.service
systemctl --user restart deskcal.service
echo "Done. Logs: journalctl --user -u deskcal -f"
