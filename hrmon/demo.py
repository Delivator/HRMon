"""Fake sensor for trying the UI without a strap (HRMON_DEMO=1)."""

import math
import random

from gi.repository import GLib, GObject


class DemoSensor(GObject.Object):
    __gsignals__ = {
        "heart-rate": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "device-found": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self):
        super().__init__()
        self.state, self.message, self.t = "connected", "Demo sensor", 0

    def start(self):
        GLib.timeout_add(250, self._tick)  # 4x speed

    def _tick(self):
        self.t += 1
        bpm = 80 + 25 * math.sin(self.t / 40) + random.uniform(-3, 3)
        self.emit("heart-rate", round(bpm))
        return GLib.SOURCE_CONTINUE

    def stop(self):
        pass
