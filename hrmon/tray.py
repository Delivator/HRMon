"""Minimal StatusNotifierItem tray icon (works with KDE Plasma) showing the live BPM."""

import os
import sys

import cairo
from gi.repository import Gio, GLib

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ias)"/></signal>
  </interface>
</node>"""

SNI_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"

RED = (0.88, 0.11, 0.14)
GREY = (0.47, 0.46, 0.48)


def render_icon(text: str, active: bool, size: int):
    """Render a rounded badge with the BPM number into an SNI pixmap (ARGB32, big endian)."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    r = size * 0.24
    cr.new_sub_path()
    for cx, cy, a in ((size - r, r, -90), (size - r, size - r, 0), (r, size - r, 90), (r, r, 180)):
        cr.arc(cx, cy, r, a * 3.14159 / 180, (a + 90) * 3.14159 / 180)
    cr.close_path()
    cr.set_source_rgb(*(RED if active else GREY))
    cr.fill()

    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(size * 0.62)
    ext = cr.text_extents(text)
    max_w = size * 0.88
    if ext.width > max_w:
        cr.set_font_size(size * 0.62 * max_w / ext.width)
        ext = cr.text_extents(text)
    cr.move_to((size - ext.width) / 2 - ext.x_bearing, (size - ext.height) / 2 - ext.y_bearing)
    cr.set_source_rgb(1, 1, 1)
    cr.show_text(text)
    surf.flush()

    data = bytes(surf.get_data())
    if sys.byteorder == "little":  # cairo stores BGRA in memory here; SNI wants ARGB
        out = bytearray(len(data))
        out[0::4], out[1::4], out[2::4], out[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
        data = bytes(out)
    return (size, size, data)


class TrayIcon:
    """Tray icon. Left click calls on_activate, menu offers Show/Hide and Quit."""

    def __init__(self, on_activate, on_quit):
        self.on_activate = on_activate
        self.on_quit = on_quit
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.text, self.active, self.tooltip = "–", False, "Not connected"
        self.registered = False
        self._pixmaps = self._render()

        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.bus.register_object(SNI_PATH, sni_info, self._sni_method, self._sni_prop, None)
        self.bus.register_object(MENU_PATH, menu_info, self._menu_method, self._menu_prop, None)
        Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        # (Re-)register whenever the Plasma tray (watcher) appears, e.g. after a plasmashell restart
        Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._on_watcher_appeared, self._on_watcher_vanished)

    def _on_watcher_appeared(self, bus, _name, _owner):
        def done(bus, res):
            try:
                bus.call_finish(res)
                self.registered = True
            except GLib.Error as e:
                print("Tray registration failed:", e.message, file=sys.stderr)

        bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                 GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None, done)

    def _on_watcher_vanished(self, _bus, _name):
        self.registered = False

    # ----------------------------------------------------------- public API
    def update(self, text: str, active: bool, tooltip: str):
        if (text, active) != (self.text, self.active):
            self.text, self.active = text, active
            self._pixmaps = self._render()
            self._emit("NewIcon")
        if tooltip != self.tooltip:
            self.tooltip = tooltip
            self._emit("NewToolTip")

    # -------------------------------------------------------------- internals
    def _render(self):
        return [render_icon(self.text, self.active, s) for s in (22, 32, 48, 64)]

    def _emit(self, signal):
        self.bus.emit_signal(None, SNI_PATH, "org.kde.StatusNotifierItem", signal, None)

    def _sni_prop(self, _bus, _sender, _path, _iface, prop):
        values = {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", "hrmon"),
            "Title": ("s", "HRMon"),
            "Status": ("s", "Active"),
            "IconName": ("s", ""),
            "IconPixmap": ("a(iiay)", self._pixmaps),
            "ToolTip": ("(sa(iiay)ss)", ("", [], "Heart rate", self.tooltip)),
            "ItemIsMenu": ("b", False),
            "Menu": ("o", MENU_PATH),
        }
        if prop in values:
            return GLib.Variant(*values[prop])
        return None

    def _sni_method(self, _bus, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self.on_activate)
        invocation.return_value(None)

    # ---- dbusmenu: 1 = Show/Hide, 2 = separator, 3 = Quit
    _ITEMS = {
        1: {"label": GLib.Variant("s", "Show / Hide")},
        2: {"type": GLib.Variant("s", "separator")},
        3: {"label": GLib.Variant("s", "Quit"), "icon-name": GLib.Variant("s", "application-exit")},
    }

    def _menu_prop(self, _bus, _sender, _path, _iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    def _menu_method(self, _bus, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            children = [GLib.Variant("(ia{sv}av)", (i, props, [])) for i, props in self._ITEMS.items()]
            root = (0, {"children-display": GLib.Variant("s", "submenu")}, children)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, root)))
        elif method == "GetGroupProperties":
            ids = args[0] or list(self._ITEMS)
            result = [(i, self._ITEMS[i]) for i in ids if i in self._ITEMS]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            value = self._ITEMS.get(args[0], {}).get(args[1], GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            self._menu_event(args[0], args[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event, _data, _ts in args[0]:
                self._menu_event(item_id, event)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _menu_event(self, item_id, event):
        if event != "clicked":
            return
        if item_id == 1:
            GLib.idle_add(self.on_activate)
        elif item_id == 3:
            GLib.idle_add(self.on_quit)
