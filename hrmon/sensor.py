"""Heart rate sensor access via BlueZ over D-Bus (standard BLE Heart Rate profile)."""

from gi.repository import Gio, GLib, GObject

BLUEZ = "org.bluez"
OBJ_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
GATT_CHAR = "org.bluez.GattCharacteristic1"

HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"

RETRY_SECONDS = 3


def parse_hr_measurement(data: bytes) -> int | None:
    """Parse a Heart Rate Measurement characteristic value (GATT 0x2A37)."""
    if len(data) < 2:
        return None
    if data[0] & 0x01:  # 16-bit value
        if len(data) < 3:
            return None
        return int.from_bytes(data[1:3], "little")
    return data[1]


class HeartRateSensor(GObject.Object):
    """Finds, connects to and streams from the first BLE heart rate sensor.

    States: "searching", "connecting", "connected", "disconnected", "error".
    """

    __gsignals__ = {
        "heart-rate": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "device-found": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, preferred_address: str | None = None):
        super().__init__()
        self.preferred_address = (preferred_address or "").upper() or None
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.state = "idle"
        self.message = ""
        self.adapter = None  # object path
        self.device = None  # object path
        self.device_name = ""
        self.char = None  # object path
        self._discovering = False
        self._retry_id = 0

        flags = Gio.DBusSignalFlags.NONE
        self.bus.signal_subscribe(BLUEZ, PROPS, "PropertiesChanged", None, None,
                                  flags, self._on_properties_changed)
        self.bus.signal_subscribe(BLUEZ, OBJ_MANAGER, "InterfacesAdded", None, None,
                                  flags, self._on_interfaces_added)

    # ------------------------------------------------------------------ helpers
    def _set_state(self, state: str, message: str = ""):
        if (state, message) != (self.state, self.message):
            self.state, self.message = state, message
            self.emit("state-changed", state, message)

    def _call(self, path, iface, method, params=None, callback=None, timeout=25000):
        def done(bus, res):
            try:
                result = bus.call_finish(res)
                error = None
            except GLib.Error as e:
                result, error = None, e
            if callback:
                callback(result.unpack() if result else None, error)

        self.bus.call(BLUEZ, path, iface, method, params, None,
                      Gio.DBusCallFlags.NONE, timeout, None, done)

    def _schedule_restart(self, seconds=RETRY_SECONDS):
        if self._retry_id:
            GLib.source_remove(self._retry_id)

        def fire():
            self._retry_id = 0
            self.start()
            return GLib.SOURCE_REMOVE

        self._retry_id = GLib.timeout_add_seconds(seconds, fire)

    @staticmethod
    def _is_hr_device(props: dict) -> bool:
        return HR_SERVICE in [u.lower() for u in props.get("UUIDs", [])]

    # ------------------------------------------------------------ main flow
    def start(self):
        """(Re)start the search/connect cycle."""
        self.char = None
        self._call("/", OBJ_MANAGER, "GetManagedObjects", callback=self._on_objects)

    def _on_objects(self, result, error):
        if error:
            self._set_state("error", "BlueZ not available")
            self._schedule_restart(5)
            return
        objects = result[0]

        adapters = [(p, i[ADAPTER]) for p, i in objects.items() if ADAPTER in i]
        if not adapters:
            self._set_state("error", "No Bluetooth adapter")
            self._schedule_restart(5)
            return
        self.adapter, adapter_props = sorted(adapters)[0]
        if not adapter_props.get("Powered"):
            self._set_state("error", "Bluetooth is off")
            self._schedule_restart(5)
            return

        candidates = []
        for path, ifaces in objects.items():
            dev = ifaces.get(DEVICE)
            if not dev or not path.startswith(self.adapter + "/"):
                continue
            address = dev.get("Address", "").upper()
            if address == self.preferred_address:
                candidates.insert(0, (path, dev))
            elif self._is_hr_device(dev):
                candidates.append((path, dev))

        if candidates:
            self._connect(*candidates[0])
        else:
            self._start_discovery()

    def _start_discovery(self):
        self._set_state("searching", "Searching for sensor…")
        if self._discovering:
            return
        filt = {"UUIDs": GLib.Variant("as", [HR_SERVICE]),
                "Transport": GLib.Variant("s", "le")}
        self._call(self.adapter, ADAPTER, "SetDiscoveryFilter",
                   GLib.Variant("(a{sv})", (filt,)))

        def started(_res, error):
            if error and "InProgress" not in error.message:
                self._set_state("error", "Could not start scan")
                self._schedule_restart(5)
            else:
                self._discovering = True

        self._call(self.adapter, ADAPTER, "StartDiscovery", callback=started)

    def _stop_discovery(self):
        if self._discovering:
            self._discovering = False
            self._call(self.adapter, ADAPTER, "StopDiscovery")

    def _connect(self, path, props):
        self._stop_discovery()
        self.device = path
        self.device_name = props.get("Alias") or props.get("Name") or props.get("Address", "")
        self._set_state("connecting", f"Connecting to {self.device_name}…")

        def connected(_res, error):
            if error:
                self._set_state("disconnected", "Sensor not reachable – retrying")
                self._schedule_restart()
                return
            self.emit("device-found", props.get("Address", ""), self.device_name)
            self._call(self.device, PROPS, "Get",
                       GLib.Variant("(ss)", (DEVICE, "ServicesResolved")),
                       callback=lambda r, e: r and r[0] and self._find_characteristic())

        self._call(path, DEVICE, "Connect", callback=connected)

    def _find_characteristic(self):
        if self.char:
            return

        def got(result, error):
            if error:
                self._schedule_restart()
                return
            for path, ifaces in result[0].items():
                ch = ifaces.get(GATT_CHAR)
                if ch and path.startswith(self.device + "/") \
                        and ch.get("UUID", "").lower() == HR_MEASUREMENT:
                    self.char = path
                    self._call(path, GATT_CHAR, "StartNotify", callback=self._on_notify_started)
                    return
            self._set_state("error", "Device has no heart rate service")

        self._call("/", OBJ_MANAGER, "GetManagedObjects", callback=got)

    def _on_notify_started(self, _res, error):
        if error and "InProgress" not in error.message:
            self._set_state("error", f"Could not subscribe: {error.message}")
            self._schedule_restart()
        else:
            self._set_state("connected", self.device_name)

    def stop(self):
        """Disconnect so the strap is free for other devices (e.g. a phone)."""
        self._stop_discovery()
        if self.device and self.state == "connected":
            try:
                self.bus.call_sync(BLUEZ, self.device, DEVICE, "Disconnect", None, None,
                                   Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass

    # -------------------------------------------------------------- signals
    def _on_interfaces_added(self, _bus, _sender, _path, _iface, _signal, params):
        path, ifaces = params.unpack()
        dev = ifaces.get(DEVICE)
        if self.state == "searching" and dev and self._is_hr_device(dev):
            self._connect(path, dev)

    def _on_properties_changed(self, _bus, _sender, path, _iface, _signal, params):
        iface, changed, _invalidated = params.unpack()

        if iface == GATT_CHAR and path == self.char and "Value" in changed:
            bpm = parse_hr_measurement(bytes(changed["Value"]))
            if bpm:
                self.emit("heart-rate", bpm)

        elif iface == DEVICE and path == self.device:
            if changed.get("ServicesResolved") and self.state == "connecting":
                self._find_characteristic()
            if changed.get("Connected") is False and self.state in ("connected", "connecting"):
                self.char = None
                self._set_state("disconnected", "Connection lost – reconnecting")
                self._schedule_restart()

        elif iface == DEVICE and self.state == "searching" and self._is_hr_device(changed):
            self.start()  # a known device just advertised the HR service

        elif iface == ADAPTER and path == self.adapter and "Powered" in changed:
            self._schedule_restart(1)
