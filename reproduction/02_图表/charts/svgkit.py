# -*- coding: utf-8 -*-
"""Lightweight SVG builder helpers for STARVISION-style academic flow charts."""

# ---------------------------------------------------------------- palette ----
C = {
    "ink":       "#14315C",
    "ink_txt":   "#1A2A3A",
    "muted":     "#25405D",
    "muted2":    "#4C6076",
    "white":     "#FFFFFF",
    "title_a":   "#1B3A6B",
    "title_b":   "#2B5C9B",
}

# (stop1, stop2, border, deep1, deep2, pale1, pale2, deep_text)
THEMES = {
    "blue":   ("#EAF3FD", "#D2E5FA", "#7FB0E4", "#4E9BE0", "#2468AE", "#6FB0EC", "#2E7BD6", "#14315C"),
    "green":  ("#E9F7F0", "#CFEEE0", "#79C6A0", "#54B98C", "#2E8A5F", "#7FD0A8", "#3E9B6B", "#1E5F44"),
    "purple": ("#F3EEFB", "#E3D7F5", "#B49BD8", "#9C7FCD", "#6B4BA6", "#B49BD8", "#8E6FC0", "#4E3578"),
    "orange": ("#FEF5E4", "#FBE4BE", "#E9B25C", "#F2B84B", "#CE8A1E", "#F2B84B", "#DE9430", "#7A4E12"),
    "red":    ("#FDECEE", "#F9D3D9", "#E8879A", "#E2586E", "#B7203A", "#EE8B9C", "#D0354C", "#8E1C2C"),
    "gold":   ("#FFF8E6", "#FCEBC4", "#E0BE72", "#EDC45C", "#C79A22", "#F2CF74", "#E0A82E", "#7A5210"),
    "teal":   ("#E7F6F7", "#CDECEF", "#79C3CB", "#4FB3BD", "#2A818A", "#7CC9D1", "#3B98A2", "#155A61"),
    "slate":  ("#EEF2F7", "#DCE4EE", "#9DB0C6", "#8CA3BC", "#5C7691", "#A7B9CD", "#7C93AC", "#2C4460"),
}

FONT = ("Microsoft YaHei, Segoe UI, Noto Sans SC, Source Han Sans SC, "
        "PingFang SC, SimHei, sans-serif")


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ------------------------------------------------------------- primitives ----
def rect(x, y, w, h, r=0, fill="#fff", stroke=None, sw=1.6, filt=None,
         extra="", op=None):
    a = f'<rect x="{x}" y="{y}" width="{w}" height="{h}"'
    if r:
        a += f' rx="{r}" ry="{r}"'
    a += f' fill="{fill}"'
    if stroke:
        a += f' stroke="{stroke}" stroke-width="{sw}"'
    if filt:
        a += f' filter="url(#{filt})"'
    if op:
        a += f' opacity="{op}"'
    if extra:
        a += " " + extra
    return a + "/>"


# Global text-size multipliers. Nominal sizes written in the figure scripts are
# scaled at render time, so readability can be tuned in one place.
SIZE_SCALE = 1.10      # applies to every glyph
SMALL_MAX = 19.0       # nominal sizes below this count as "small text"
SMALL_BOOST = 1.14     # additional multiplier applied to small text


def sc(size):
    """effective font size: global scale plus the small-text boost"""
    k = SIZE_SCALE
    if size < SMALL_MAX:
        k *= SMALL_BOOST
    return size * k


def text(x, y, s, size=16, fill=C["ink_txt"], weight="400", anchor="start",
         family=FONT, ls=None, op=None, style=None):
    a = (f'<text x="{x}" y="{y}" font-family="{family}" '
         f'font-size="{sc(size):.2f}" '
         f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"')
    if ls is not None:
        a += f' letter-spacing="{ls}"'
    if op is not None:
        a += f' opacity="{op}"'
    if style:
        a += f' font-style="{style}"'
    return a + f'>{esc(s)}</text>'


def tspans(x, y, parts, size=16, fill=C["ink_txt"], anchor="start", lh=None,
           family=FONT):
    """parts: list of (txt, weight, color, size_override)"""
    out = [f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
           f'fill="{fill}" text-anchor="{anchor}">']
    for p in parts:
        t, wt, col = p[0], p[1], p[2]
        sz = p[3] if len(p) > 3 else None
        st = f' font-weight="{wt}"' if wt else ""
        cs = f' fill="{col}"' if col else ""
        ss = f' font-size="{sz}"' if sz else ""
        out.append(f'<tspan{st}{cs}{ss}>{esc(t)}</tspan>')
    out.append("</text>")
    return "".join(out)


def grad(gid, c1, c2, x1=0, y1=0, x2=0, y2=1, rot=None):
    if rot is not None:
        g = f'gradientTransform="rotate({rot} 0.5 0.5)"'
    else:
        g = ""
    return (f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {g}>'
            f'<stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient>')


def vgrad(gid, c1, c2):
    return grad(gid, c1, c2, 0, 0, 0, 1)


def hgrad(gid, c1, c2):
    return grad(gid, c1, c2, 0, 0, 1, 0)


def marker(mid, color, w=3.2, size=20):
    return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerUnits="userSpaceOnUse" markerWidth="{size}" '
            f'markerHeight="{size}" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>')


def path(d, stroke, sw=3.2, fill="none", marker_end=None, marker_start=None,
         dash=None, cap="round"):
    a = f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="{cap}" stroke-linejoin="round"'
    if dash:
        a += f' stroke-dasharray="{dash}"'
    if marker_end:
        a += f' marker-end="url(#{marker_end})"'
    if marker_start:
        a += f' marker-start="url(#{marker_start})"'
    return a + "/>"


def line(x1, y1, x2, y2, stroke, sw=2, dash=None, cap="round"):
    a = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
         f'stroke-width="{sw}" stroke-linecap="{cap}"')
    if dash:
        a += f' stroke-dasharray="{dash}"'
    return a + "/>"


def pill(x, y, w, h, label, theme_deep, size=17, dy=None, bold=True,
         family=FONT, ls=None):
    c = THEMES[theme_deep]
    gid = f"pg_{theme_deep}_{abs(hash(label)) % 100000}"
    body = [vgrad(gid, c[5], c[6] + "" if False else c[6])] if False else []
    out = [vgrad(gid, c[5], c[6]),
           rect(x, y, w, h, r=h / 2, fill=f"url(#{gid})"),
           text(x + w / 2, y + (dy if dy is not None else h / 2 + size * 0.36),
                label, size=size, fill="#fff" if bold else c[7],
                weight="700" if bold else "500", anchor="middle", ls=ls)]
    return "".join(out)


def chip(x, y, w, h, label, theme_deep, size=17, r=10, fill="#fff"):
    """solid rounded-square metric chip"""
    c = THEMES[theme_deep]
    gid = f"cg_{theme_deep}_{abs(hash(label)) % 100000}"
    return "".join([
        vgrad(gid, c[5], c[6]),
        rect(x, y, w, h, r=r, fill=f"url(#{gid})"),
        text(x + w / 2, y + h / 2 + size * 0.36, label, size=size,
             fill="#fff", weight="700", anchor="middle"),
    ])


def box(x, y, w, h, theme, r=12, filt="sh", sw=1.7):
    c = THEMES[theme]
    gid = f"bg_{theme}_{int(x)}_{int(y)}"
    return "".join([
        vgrad(gid, c[0], c[1]),
        rect(x, y, w, h, r=r, fill=f"url(#{gid})", stroke=c[2], sw=sw, filt=filt),
    ])


def band(x, y, w, h, label, theme_deep, size=22, r=12, ls=2, sub=None):
    """section header band with a 3D lip"""
    c = THEMES[theme_deep]
    gid = f"hd_{theme_deep}_{int(x)}_{int(y)}"
    out = [hgrad(gid, c[4], c[5]),
           rect(x, y + 5, w, h, r=r, fill=c[4], op=0.45)]
    out.append(rect(x, y, w, h, r=r, fill=f"url(#{gid})", filt="shs"))
    out.append(rect(x + 3, y + 3, w - 6, h * 0.34, r=r * 0.6,
                    fill="#ffffff", op=0.16))
    out.append(text(x + w / 2, y + h / 2 + size * 0.36, label, size=size,
                    fill="#fff", weight="700", anchor="middle", ls=ls))
    if sub:
        out.append(text(x + w - 16, y + h / 2 + 5, sub, size=13, fill="#fff",
                        anchor="end", op=0.85))
    return "".join(out)


def accent(x, y, h, theme_deep, w=7):
    c = THEMES[theme_deep]
    return rect(x, y, w, h, r=w / 2, fill=c[6], op=0.95)


def ribbon_v(cx, y, h, w, label, theme_deep, size=26, r=None, lh=32):
    """vertical ribbon with one character per line, stacked top-to-bottom"""
    c = THEMES[theme_deep]
    gid = f"rv_{theme_deep}_{int(cx)}_{int(y)}"
    if r is None:
        r = w / 2
    out = [
        hgrad(gid, c[5], c[6]),
        rect(cx - w / 2, y, w, h, r=r, fill=f"url(#{gid})", filt="shs"),
        rect(cx - w / 2 + 4, y + 4, w * 0.3, h - 8, r=w * 0.15,
             fill="#ffffff", op=0.18),
    ]
    n = len(label)
    block = (n - 1) * lh + size
    top = y + (h - block) / 2
    for i, ch in enumerate(label):
        out.append(text(cx, top + i * lh + size * 0.85, ch, size=size,
                        fill="#fff", weight="700", anchor="middle"))
    return "".join(out)


def dblarrow(x1, x2, y, c_out, c_in, m_out, m_in, sep=17):
    """two opposing horizontal arrows"""
    g = []
    g.append(path(f"M {x1} {y - sep} L {x2} {y - sep}", c_out, 5.0,
                  marker_end=m_out))
    g.append(path(f"M {x2} {y + sep} L {x1} {y + sep}", c_in, 5.0,
                  marker_end=m_in))
    return "".join(g)


# ------------------------------------------------------------------ page ----
def page(w, h, defs_extra, body, bg="#FFFFFF"):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<defs>'
        f'<filter id="sh" x="-25%" y="-25%" width="150%" height="170%">'
        f'<feDropShadow dx="0" dy="3.5" stdDeviation="4.5" flood-color="#0F2440" flood-opacity="0.17"/>'
        f'</filter>'
        f'<filter id="shs" x="-30%" y="-30%" width="160%" height="180%">'
        f'<feDropShadow dx="0" dy="2" stdDeviation="2.4" flood-color="#0F2440" flood-opacity="0.18"/>'
        f'</filter>'
        f'<filter id="shd" x="-40%" y="-40%" width="180%" height="200%">'
        f'<feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#0F2440" flood-opacity="0.20"/>'
        f'</filter>'
        + defs_extra +
        f'</defs>'
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="{bg}"/>'
        + body +
        '</svg>'
    )


def caption(cx, y, cn, en):
    return "".join([
        text(cx, y, cn, size=24, fill=C["ink"], weight="700", anchor="middle",
             ls=1.5),
        text(cx, y + 31, en, size=14.5, fill=C["muted2"], anchor="middle",
             weight="400", style="italic", ls=0.3),
    ])


def frame(w, h, inset=14):
    """outer double-line frame around the whole figure"""
    return "".join([
        rect(inset, inset - 2, w - 2 * inset, h - 2 * inset + 4, r=20,
             fill="#FCFDFF", stroke="#A9C4E2", sw=2.4),
        rect(inset + 7, inset + 5, w - 2 * inset - 14, h - 2 * inset - 10,
             r=15, fill="none", stroke="#E2ECF7", sw=1.2),
    ])


def dotted_band(x, y, w, h, theme, r=16, dash="9 7", op=1.0):
    c = THEMES[theme]
    return rect(x, y, w, h, r=r, fill=c[0], stroke=c[2], sw=1.9, op=op,
                extra=f'stroke-dasharray="{dash}"')
