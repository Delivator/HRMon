"""HRMon main application window."""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from .graph import HeartRateGraph  # noqa: E402
from .resting import RestingHeartRate  # noqa: E402
from .sensor import HeartRateSensor  # noqa: E402
from .tray import TrayIcon  # noqa: E402

APP_ID = "io.github.hrmon.HRMon"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hrmon" / "config.json"
WINDOWS = [1, 2, 5, 10, 15, 30, 60]  # minutes
STALE_SECONDS = 5

CSS = b"""
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
    if os.environ.get("HRMON_DEMO"):  # never let fake data touch the real config
        return
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except OSError as e:
        print("Could not save config:", e, file=sys.stderr)


class BigNumber(Gtk.DrawingArea):
    """The big BPM number, drawn with cairo.

    A plain Gtk.Label at this size goes through GTK's glyph atlas, which can show
    stray lines and clipped glyph tops; drawing it ourselves avoids that.
    """

    SIZE_PX = 64

    def __init__(self):
        super().__init__()
        self.text = "–"
        self.set_draw_func(self._draw)
        self._resize()

    def set_label(self, text):
        if text != self.text:
            self.text = text
            self._resize()
            self.queue_draw()

    def _layout(self, ctx_layout):
        font = self.get_pango_context().get_font_description().copy()
        font.set_absolute_size(self.SIZE_PX * Pango.SCALE)
        font.set_weight(Pango.Weight.ULTRABOLD)
        ctx_layout.set_font_description(font)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_font_features_new("tnum"))
        ctx_layout.set_attributes(attrs)
        ctx_layout.set_text(self.text, -1)
        return ctx_layout

    def _resize(self):
        layout = self._layout(self.create_pango_layout(None))
        _ink, logical = layout.get_pixel_extents()
        self.set_content_width(logical.width)
        self.set_content_height(logical.height)

    def _draw(self, _area, cr, width, height):
        layout = self._layout(PangoCairo.create_layout(cr))
        _ink, logical = layout.get_pixel_extents()
        fg = self.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
        cr.move_to((width - logical.width) / 2, (height - logical.height) / 2)
        PangoCairo.show_layout(cr, layout)


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

        menu = Gio.Menu()
        axis = Gio.Menu()
        for label, mode in (("Time ago", "ago"), ("Since start", "elapsed"), ("Time of day", "clock")):
            axis.append(label, f"app.time-axis::{mode}")
        menu.append_section("Time axis", axis)
        app_section = Gio.Menu()
        app_section.append("Quit", "app.quit")
        menu.append_section(None, app_section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Settings"))

        self.heart = Gtk.Label(label="♥", css_classes=["heart"], valign=Gtk.Align.END, margin_bottom=12)
        self.bpm = BigNumber()
        unit = Gtk.Label(label="bpm", css_classes=["bpm-unit", "dim-label"], valign=Gtk.Align.END,
                         margin_bottom=14)
        value_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        for w in (self.heart, self.bpm, unit):
            value_row.append(w)

        self.resting = None
        self.stats = Gtk.Label(label=" ", css_classes=["dim-label", "caption"])
        self.stats.set_tooltip_text("Resting: lowest 3-minute average today")
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
        parts = []
        if self.resting:
            parts.append(f"resting {self.resting}")
        values = [v for _, v in self.graph.visible()]
        if values:
            avg = round(sum(values) / len(values))
            parts += [f"min {min(values)}", f"avg {avg}", f"max {max(values)}"]
        self.stats.set_label("  ·  ".join(parts) or " ")

    def beat(self):
        self.heart.add_css_class("beat")
        GLib.timeout_add(150, lambda: self.heart.remove_css_class("beat"))


class HRMonApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID + (".Demo" if os.environ.get("HRMON_DEMO") else ""))
        GLib.set_prgname(APP_ID)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.cfg = load_config()
        self.window = None
        self.tray = None
        self.sensor = None
        self.last_bpm = None
        self.last_time = 0.0
        self._beat_id = 0
        saved = self.cfg.get("resting", {})
        today = date.today().isoformat()
        self.resting = RestingHeartRate(saved.get("bpm") if saved.get("date") == today else None)
        self.resting_date = today

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
        self.window.resting = self.window.graph.resting = self.resting.value

        mode = self.cfg.get("time_axis", "ago")
        self.window.graph.set_time_mode(mode)
        axis_action = Gio.SimpleAction.new_stateful(
            "time-axis", GLib.VariantType.new("s"), GLib.Variant("s", self.window.graph.time_mode))
        axis_action.connect("change-state", self._on_time_axis_changed)
        self.add_action(axis_action)

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

    def _on_time_axis_changed(self, action, value):
        action.set_state(value)
        self.window.graph.set_time_mode(value.get_string())
        self.cfg["time_axis"] = value.get_string()
        save_config(self.cfg)

    def _on_device_found(self, _sensor, address, _name):
        if address and self.cfg.get("device") != address:
            self.cfg["device"] = address
            save_config(self.cfg)

    def _on_heart_rate(self, _sensor, bpm):
        self.last_bpm, self.last_time = bpm, time.monotonic()
        self.window.graph.add(bpm)
        self._update_resting(bpm)
        self._refresh()

    def _update_resting(self, bpm):
        today = date.today().isoformat()
        if today != self.resting_date:  # new day, new resting HR
            self.resting, self.resting_date = RestingHeartRate(), today
        if self.resting.add(self.last_time, bpm):
            self.cfg["resting"] = {"date": today, "bpm": self.resting.value}
            save_config(self.cfg)
        self.window.resting = self.resting.value
        self.window.graph.resting = self.resting.value

    def _tick(self):
        self.window.graph.queue_draw()
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _is_live(self):
        return (self.sensor.state == "connected" and self.last_bpm is not None
                and time.monotonic() - self.last_time < STALE_SECONDS)

    def _schedule_beat(self):
        """Pulse the heart at the current BPM (free-running, not tied to sensor updates)."""
        if self._beat_id or not self._is_live():
            return

        def beat():
            self._beat_id = 0
            if self._is_live():
                self.window.beat()
                self._schedule_beat()
            return GLib.SOURCE_REMOVE

        self._beat_id = GLib.timeout_add(round(60000 / self.last_bpm), beat)

    def _refresh(self):
        live = self._is_live()
        self._schedule_beat()
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
