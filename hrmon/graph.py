"""A small, sleek scrolling heart rate graph."""

import math
import time
from datetime import datetime
from collections import deque

import cairo
from gi.repository import Gtk, Pango, PangoCairo

LINE = (0.88, 0.11, 0.14)
GAP_SECONDS = 6  # break the line if no data for this long
HISTORY_SECONDS = 60 * 60


class HeartRateGraph(Gtk.DrawingArea):
    def __init__(self, window_seconds=300):
        super().__init__(hexpand=True, vexpand=True)
        self.set_size_request(260, 120)
        self.window_seconds = window_seconds
        self.samples = deque()  # (monotonic time, bpm)
        self.resting = None
        self.hover_x = None
        self.set_draw_func(self._draw)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _on_motion(self, _ctl, x, _y):
        self.hover_x = x
        self.queue_draw()

    def _on_leave(self, _ctl):
        self.hover_x = None
        self.queue_draw()

    def add(self, bpm: int):
        now = time.monotonic()
        self.samples.append((now, bpm))
        while self.samples and now - self.samples[0][0] > HISTORY_SECONDS:
            self.samples.popleft()
        self.queue_draw()

    def set_window(self, seconds: int):
        self.window_seconds = seconds
        self.queue_draw()

    def visible(self):
        start = time.monotonic() - self.window_seconds
        return [(t, v) for t, v in self.samples if t >= start]

    def _draw(self, _area, cr, width, height):
        fg = self.get_color()
        pts = self.visible()
        now = time.monotonic()

        if pts:
            values = [v for _, v in pts]
            lo = math.floor((min(values) - 5) / 10) * 10
            hi = math.ceil((max(values) + 5) / 10) * 10
        else:
            lo, hi = 60, 100
        if hi - lo < 30:
            hi = lo + 30

        left, right, top, bottom = 30, 4, 6, 6
        gw, gh = width - left - right, height - top - bottom

        def y_of(v):
            return top + gh * (1 - (v - lo) / (hi - lo))

        def x_of(t):
            return left + gw * (1 - (now - t) / self.window_seconds)

        # grid + labels
        step = 10 if hi - lo <= 60 else 20
        layout = PangoCairo.create_layout(cr)
        font = self.get_pango_context().get_font_description().copy()
        font.set_size(int(font.get_size() * 0.75))
        layout.set_font_description(font)
        cr.set_line_width(1)
        for v in range(int(lo), int(hi) + 1, step):
            y = round(y_of(v)) + 0.5
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10)
            cr.move_to(left, y)
            cr.line_to(width - right, y)
            cr.stroke()
            layout.set_text(str(v), -1)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
            cr.move_to(left - tw - 6, y - th / 2)
            PangoCairo.show_layout(cr, layout)

        if not pts:
            return

        # resting heart rate as a subtle dashed line
        if self.resting and lo < self.resting < hi:
            y = round(y_of(self.resting)) + 0.5
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
            cr.set_dash([4, 4])
            cr.move_to(left, y)
            cr.line_to(width - right, y)
            cr.stroke()
            cr.set_dash([])

        # split into continuous segments
        segments, seg = [], []
        for i, (t, v) in enumerate(pts):
            if seg and t - pts[i - 1][0] > GAP_SECONDS:
                segments.append(seg)
                seg = []
            seg.append((x_of(t), y_of(v)))
        segments.append(seg)

        cr.save()
        cr.rectangle(left, 0, gw, height)
        cr.clip()
        for seg in segments:
            if len(seg) < 2:
                cr.set_source_rgb(*LINE)
                cr.arc(seg[0][0], seg[0][1], 2, 0, 2 * math.pi)
                cr.fill()
                continue
            # fill under the curve
            cr.move_to(seg[0][0], top + gh)
            for x, y in seg:
                cr.line_to(x, y)
            cr.line_to(seg[-1][0], top + gh)
            cr.close_path()
            grad = cairo.LinearGradient(0, top, 0, top + gh)
            grad.add_color_stop_rgba(0, *LINE, 0.30)
            grad.add_color_stop_rgba(1, *LINE, 0.0)
            cr.set_source(grad)
            cr.fill()
            # line
            cr.move_to(*seg[0])
            for x, y in seg[1:]:
                cr.line_to(x, y)
            cr.set_source_rgb(*LINE)
            cr.set_line_width(2)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.stroke()
        cr.restore()

        # dot at the latest value
        x, y = segments[-1][-1]
        if now - pts[-1][0] < GAP_SECONDS:
            cr.set_source_rgb(*LINE)
            cr.arc(x, y, 3.5, 0, 2 * math.pi)
            cr.fill()

        if self.hover_x is not None and left <= self.hover_x <= width - right:
            self._draw_hover(cr, pts, now, x_of, y_of, layout, fg, top, gh, left, width - right)

    def _draw_hover(self, cr, pts, now, x_of, y_of, layout, fg, top, gh, x_min, x_max):
        t_hover = now - self.window_seconds * (1 - (self.hover_x - x_min) / (x_max - x_min))
        t, bpm = min(pts, key=lambda p: abs(p[0] - t_hover))
        if abs(t - t_hover) > GAP_SECONDS:
            return  # nothing recorded near the cursor
        x, y = x_of(t), y_of(bpm)

        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.4)
        cr.set_line_width(1)
        cr.move_to(round(x) + 0.5, top)
        cr.line_to(round(x) + 0.5, top + gh)
        cr.stroke()
        cr.set_source_rgb(*LINE)
        cr.arc(x, y, 4, 0, 2 * math.pi)
        cr.fill()

        clock = datetime.fromtimestamp(time.time() - (now - t)).strftime("%H:%M:%S")
        layout.set_markup(f"<b>{bpm} bpm</b>  {clock}", -1)
        tw, th = layout.get_pixel_size()
        pad = 5
        bw, bh = tw + 2 * pad, th + 2 * pad
        bx = x + 8 if x + 8 + bw <= x_max else x - 8 - bw
        by = min(max(y - bh - 8, top), top + gh - bh)
        cr.set_source_rgba(0.12, 0.12, 0.14, 0.92)
        r = 5
        cr.new_sub_path()
        cr.arc(bx + bw - r, by + r, r, -math.pi / 2, 0)
        cr.arc(bx + bw - r, by + bh - r, r, 0, math.pi / 2)
        cr.arc(bx + r, by + bh - r, r, math.pi / 2, math.pi)
        cr.arc(bx + r, by + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(bx + pad, by + pad)
        PangoCairo.show_layout(cr, layout)
