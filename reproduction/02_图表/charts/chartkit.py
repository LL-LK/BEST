# -*- coding: utf-8 -*-
"""chartkit - gradient / 3D bar chart primitives (SVG) for BEST-Skill figures.

Style reference: gradient-filled bars with a shallow 3-D depth face, dashed
gridlines, boxed axes, bold value labels and chip legends.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import page, text, FONT, C, sc


# ------------------------------------------------------------- colour util --
def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _hx(t):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in t)


def mix(c1, c2, k):
    """k=0 -> c1, k=1 -> c2"""
    a, b = _hex(c1), _hex(c2)
    return _hx([a[i] + (b[i] - a[i]) * k for i in range(3)])


def lighten(c, k=0.5):
    return mix(c, "#FFFFFF", k)


def darken(c, k=0.25):
    return mix(c, "#101B26", k)


# --------------------------------------------------------------- ramps -----
# (bottom colour, top colour) - light at the base, saturated at the head
RAMPS = {
    "teal":   ("#8FE8DB", "#0E857D"),
    "peri":   ("#BFC6F2", "#4E58C4"),
    "blue":   ("#B6D4EF", "#22619E"),
    "amber":  ("#FFE0A0", "#DE8C0E"),
    "orange": ("#FFBE8C", "#D4501F"),
    "green":  ("#B4E8C2", "#2E8B57"),
    "red":    ("#FFA6B0", "#C01F35"),
    "slate":  ("#DDE4EC", "#7C8B9C"),
}

INK_AXIS = "#24384F"
INK_TICK = "#40546B"
INK_VAL = "#16283C"
GRID = "#C9D3DE"

DX, DY = 8, 6          # 3-D depth offset


class Canvas:
    """collects gradient defs + body while drawing a chart."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.defs = []
        self.body = []
        self._n = 0

    # -------- primitives
    def grad(self, ramp, top=None, bottom=None):
        """vertical gradient id for a ramp (saturated top -> light bottom)"""
        self._n += 1
        gid = f"g{self._n}"
        b, t = RAMPS[ramp]
        t = top or t
        b = bottom or b
        self.defs.append(
            f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{t}"/>'
            f'<stop offset="0.55" stop-color="{mix(t, b, 0.45)}"/>'
            f'<stop offset="1" stop-color="{b}"/></linearGradient>')
        return gid

    def hgrad(self, ramp):
        """horizontal gradient id (light left -> saturated right)"""
        self._n += 1
        gid = f"h{self._n}"
        b, t = RAMPS[ramp]
        self.defs.append(
            f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{b}"/>'
            f'<stop offset="0.45" stop-color="{mix(t, b, 0.55)}"/>'
            f'<stop offset="1" stop-color="{t}"/></linearGradient>')
        return gid

    def add(self, *s):
        self.body.extend(s)

    def svg(self, bg="#FFFFFF"):
        return page(self.w, self.h, "".join(self.defs), "".join(self.body), bg)


# ------------------------------------------------------------------ text ----
def txt(cv, x, y, s, size=17, fill=INK_TICK, weight="500", anchor="start",
        ls=None, style=None):
    cv.add(text(x, y, s, size=size, fill=fill, weight=weight, anchor=anchor,
                ls=ls, style=style))


# ------------------------------------------------------------------ axes ----
def axes(cv, x0, y0, x1, y1, box=True):
    cv.add(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
           f'fill="#FDFEFF" stroke="none"/>')


def frame(cv, x0, y0, x1, y1, lw=1.8):
    cv.add(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
           f'fill="none" stroke="{INK_AXIS}" stroke-width="{lw}"/>')


def gridline_h(cv, x0, x1, y):
    cv.add(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{GRID}" '
           f'stroke-width="1.1" stroke-dasharray="7 6"/>')


def gridline_v(cv, y0, y1, x):
    cv.add(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="{GRID}" '
           f'stroke-width="1.1" stroke-dasharray="7 6"/>')


def tick_left(cv, x0, y, label, size=18):
    cv.add(f'<line x1="{x0 - 7}" y1="{y}" x2="{x0}" y2="{y}" '
           f'stroke="{INK_AXIS}" stroke-width="1.8"/>')
    txt(cv, x0 - 13, y + size * 0.36, label, size=size, fill=INK_TICK,
        anchor="end", weight="700")


def tick_bottom(cv, y1, x, label, size=18):
    cv.add(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y1 + 7}" '
           f'stroke="{INK_AXIS}" stroke-width="1.8"/>')
    txt(cv, x, y1 + 30, label, size=size, fill=INK_TICK, anchor="middle",
        weight="700")


# ------------------------------------------------------------- 3-D bars -----
def vbar3d(cv, x, ytop, w, ybase, ramp, dx=DX, dy=DY):
    g = cv.grad(ramp)
    b, t = RAMPS[ramp]
    # top face
    cv.add(f'<path d="M {x} {ytop} L {x + dx} {ytop - dy} '
           f'L {x + w + dx} {ytop - dy} L {x + w} {ytop} Z" '
           f'fill="{lighten(t, 0.62)}" stroke="{darken(t, 0.10)}" '
           f'stroke-width="0.9"/>')
    # right face
    cv.add(f'<path d="M {x + w} {ytop} L {x + w + dx} {ytop - dy} '
           f'L {x + w + dx} {ybase - dy} L {x + w} {ybase} Z" '
           f'fill="{darken(b, 0.26)}" stroke="{darken(b, 0.36)}" '
           f'stroke-width="0.9"/>')
    # front face
    cv.add(f'<rect x="{x}" y="{ytop}" width="{w}" height="{max(1, ybase - ytop)}" '
           f'fill="url(#{g})" stroke="{darken(t, 0.22)}" stroke-width="1.1"/>')


def hbar3d(cv, x, y, wlen, h, ramp, dx=DX, dy=DY):
    g = cv.hgrad(ramp)
    b, t = RAMPS[ramp]
    # top face
    cv.add(f'<path d="M {x} {y} L {x + dx} {y - dy} L {x + wlen + dx} {y - dy} '
           f'L {x + wlen} {y} Z" fill="{lighten(t, 0.62)}" '
           f'stroke="{darken(t, 0.10)}" stroke-width="0.9"/>')
    # right face
    cv.add(f'<path d="M {x + wlen} {y} L {x + wlen + dx} {y - dy} '
           f'L {x + wlen + dx} {y + h - dy} L {x + wlen} {y + h} Z" '
           f'fill="{darken(t, 0.30)}" stroke="{darken(t, 0.42)}" '
           f'stroke-width="0.9"/>')
    # front face
    cv.add(f'<rect x="{x}" y="{y}" width="{max(1, wlen)}" height="{h}" '
           f'fill="url(#{g})" stroke="{darken(t, 0.22)}" stroke-width="1.1"/>')


def hdot(cv, x, y, ramp, r=8):
    b, t = RAMPS[ramp]
    cv.add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{t}" '
           f'stroke="#FFFFFF" stroke-width="1.8"/>')


# --------------------------------------------------------------- legend -----
def legend_chip(cv, x, y, label, ramp, size=16, cw=30, ch=16):
    g = cv.grad(ramp)
    b, t = RAMPS[ramp]
    cv.add(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" '
           f'fill="url(#{g})" stroke="{darken(t, 0.20)}" stroke-width="1"/>')
    txt(cv, x + cw + 9, y + ch * 0.5 + size * 0.36, label, size=size,
        fill=INK_TICK, weight="500")
    return cw + 9 + _tw(label, size) + 30


def _tw(s, size):
    """estimated rendered width of `s`, honouring the global text scale"""
    k = sc(size)
    w = 0.0
    for ch in s:
        w += k * (1.0 if ord(ch) > 0x2E80 else 0.55)
    return w


def legend_title(cv, x, y, ramp, kind="dot", cw=30, ch=16):
    g = cv.grad(ramp)
    b, t = RAMPS[ramp]
    if kind == "dot":
        cv.add(f'<circle cx="{x + 8}" cy="{y + ch / 2}" r="6.5" fill="{t}" '
               f'stroke="#FFFFFF" stroke-width="1.4"/>')
    else:
        cv.add(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" '
               f'fill="url(#{g})" stroke="{darken(t, 0.20)}" stroke-width="1"/>')
