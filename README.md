# HRMon

A tiny GTK4/libadwaita heart rate monitor for Linux. It connects to any Bluetooth LE chest strap
that uses the standard Heart Rate profile (e.g. COOSPO H6), shows your live BPM and a graph of the
last few minutes, and puts the current BPM in the system tray (KDE Plasma / any StatusNotifierItem tray).

## Setup

```sh
mise install          # Python from mise.toml
mise run install      # PyGObject + pycairo into .venv
mise run run          # start
mise run desktop      # optional: add HRMon to the app launcher
```

Bluetooth access goes straight through BlueZ over D-Bus, so there's no extra BLE library.

## Usage

- Put the strap on (it only turns on when it touches skin). HRMon searches for it and connects by itself.
  You don't need to pair it in the system settings.
- The first sensor HRMon finds is saved to `~/.config/hrmon/config.json` and preferred next time.
- If the connection drops, HRMon reconnects automatically.
- Closing the window hides it to the tray. Left-click the tray icon to show or hide it.
  Use the tray's right-click menu or <kbd>Ctrl</kbd>+<kbd>Q</kbd> to quit.
- `HRMON_DEMO=1 mise run run` shows the UI with fake data.
