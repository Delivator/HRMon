"""HRMon main application window."""

import json
import os
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .graph import HeartRateGraph  # noqa: E402
from .sensor import HeartRateSensor  # noqa: E402
from .tray import TrayIcon  # noqa: E402

APP_ID = "io.github.hrmon.HRMon"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hrmon" / "config.json"
WINDOWS = [1, 2, 5, 10, 15, 30, 60]  # minutes
STALE_SECONDS = 5

CSS = b"""
.bpm { font-size: 64px; font-weight: 800; font-feature-settings: "tnum"; }
.bpm-unit { font-size: 15px; font-weight: 600; }
.heart { color: #e01b24; font-size: 26px; transition: opacity 120ms ease-out; }
.heart.beat { opacity: 0.35; }
"""


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except OSError as e:
        print("Could not save config:", e, file=sys.stderr)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, window_minutes):
        super().__init__(application=app, title="HRMon", default_width=400, default_height=320)

        self.title = Adw.WindowTitle(title="HRMon", subtitle="Starting…")
        header = Adw.HeaderBar(title_widget=self.title)

        minutes = window_minutes if window_minutes in WINDOWS else 5
        self.range = Gtk.DropDown.new_from_strings([f"{m} min" for m in WINDOWS])
        self.range.set_selected(WINDOWS.index(minutes))
        self.range.set_tooltip_text("Graph time range")
        self.range.add_css_class("flat")
        header.pack_start(self.range)

        self.heart = Gtk.Label(label="♥", css_classes=["heart"], valign=Gtk.Align.BASELINE_FILL)
        self.bpm = Gtk.Label(label="–", css_classes=["bpm"])
        unit = Gtk.Label(label="bpm", css_classes=["bpm-unit", "dim-label"], valign=Gtk.Align.BASELINE_FILL)
        value_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, baseline_position=Gtk.BaselinePosition.BOTTOM)
        for w in (self.heart, self.bpm, unit):
            value_row.append(w)

        self.stats = Gtk.Label(label=" ", css_classes=["dim-label", "caption"])
        self.graph = HeartRateGraph(minutes * 60)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                          margin_start=12, margin_end=12, margin_bottom=12)
        content.append(value_row)
        content.append(self.stats)
        content.append(self.graph)

        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.set_content(view)

    def update_stats(self):
        values = [v for _, v in self.graph.visible()]
        if values:
            avg = round(sum(values) / len(values))
            self.stats.set_label(f"min {min(values)}  ·  avg {avg}  ·  max {max(values)}")
        else:
            self.stats.set_label(" ")

    def beat(self):
        self.heart.add_css_class("beat")
        GLib.timeout_add(150, lambda: self.heart.remove_css_class("beat"))


class HRMonApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        GLib.set_prgname(APP_ID)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.cfg = load_config()
        self.window = None
        self.tray = None
        self.sensor = None
        self.last_bpm = None
        self.last_time = 0.0

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self.quit_app())
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        self.window = MainWindow(self, self.cfg.get("window_minutes", 5))
        self.window.range.connect("notify::selected", self._on_range_changed)

        try:
            self.tray = TrayIcon(self.toggle_window, self.quit_app)
            # with a tray icon, closing the window just hides it
            self.window.set_hide_on_close(True)
            self.hold()
        except Exception as e:  # tray is optional
            print("Tray icon unavailable:", e, file=sys.stderr)

        if os.environ.get("HRMON_DEMO"):
            from .demo import DemoSensor
            self.sensor = DemoSensor()
        else:
            self.sensor = HeartRateSensor(self.cfg.get("device"))
        self.sensor.connect("heart-rate", self._on_heart_rate)
        self.sensor.connect("state-changed", lambda *_: self._refresh())
        self.sensor.connect("device-found", self._on_device_found)
        self.sensor.start()

        GLib.timeout_add_seconds(1, self._tick)

    def do_activate(self):
        self.window.present()

    # ------------------------------------------------------------ actions
    def toggle_window(self):
        if self.window.get_visible() and self.window.is_active():
            self.window.set_visible(False)
        else:
            self.window.present()

    def quit_app(self):
        self.sensor.stop()
        self.quit()

    # ------------------------------------------------------------ events
    def _on_range_changed(self, dropdown, _pspec):
        minutes = WINDOWS[dropdown.get_selected()]
        self.window.graph.set_window(minutes * 60)
        self.window.update_stats()
        self.cfg["window_minutes"] = minutes
        save_config(self.cfg)

    def _on_device_found(self, _sensor, address, _name):
        if address and self.cfg.get("device") != address:
            self.cfg["device"] = address
            save_config(self.cfg)

    def _on_heart_rate(self, _sensor, bpm):
        self.last_bpm, self.last_time = bpm, time.monotonic()
        self.window.graph.add(bpm)
        self.window.beat()
        self._refresh()

    def _tick(self):
        self.window.graph.queue_draw()
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _refresh(self):
        live = (self.sensor.state == "connected" and self.last_bpm is not None
                and time.monotonic() - self.last_time < STALE_SECONDS)
        w = self.window
        w.bpm.set_label(str(self.last_bpm) if self.last_bpm else "–")
        if live:
            w.bpm.remove_css_class("dim-label")
        else:
            w.bpm.add_css_class("dim-label")
        w.heart.set_opacity(1.0 if live else 0.3)

        if self.sensor.state == "connected":
            subtitle = self.sensor.message if live else f"{self.sensor.message} · waiting for data"
        else:
            subtitle = self.sensor.message or self.sensor.state
        w.title.set_subtitle(subtitle)
        w.update_stats()

        if self.tray:
            text = str(self.last_bpm) if live else "–"
            tip = f"{self.last_bpm} bpm" if live else subtitle
            self.tray.update(text, live, tip)


def main():
    return HRMonApp().run(sys.argv)
