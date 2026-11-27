"""Type layout helpers for the Mimic wordmark (outlines, no live text), plus the
three round-1 concepts (A was chosen) kept for the record.

Fonts: Instrument Serif (SIL OFL 1.1: logo use allowed), the same family as
the dashboard headings, so the logo and the product speak with one voice.
"""
import os
import re
import sys

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dashboard", "static", "fonts") + os.sep
ITALIC = TTFont(FONTS + "instrument-serif-italic.woff2")
REGULAR = TTFont(FONTS + "instrument-serif-regular.woff2")
MONO = TTFont(FONTS + "ibm-plex-mono-500.woff2")
INK, PAPER, PINK, MINT = "#111111", "#FFFFFF", "#CC5392", "#51C897"


def glyph_contours(font, ch):
    """Return the glyph's contours as separate pen recordings (font units)."""
    gs = font.getGlyphSet()
    name = font.getBestCmap()[ord(ch)]
    rec = RecordingPen()
    gs[name].draw(rec)
    contours, cur = [], []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(cur)
            cur = []
    return contours, gs[name].width


def contour_d(contour, scale, dx, dy):
    pen = SVGPathPen(None)
    tp = TransformPen(pen, (scale, 0, 0, -scale, dx, dy))
    for op, args in contour:
        getattr(tp, op)(*args)
    return pen.getCommands()


def bbox_y(contour):
    ys = [pt[1] for _, args in contour for pt in args]
    return min(ys), max(ys)


def set_word(font, text, size, baseline, x0=0.0, tracking=0.0, kern=None):
    """Lay out text. Returns list of dicts: ch, contours (d strings), x, advance."""
    upm = font["head"].unitsPerEm
    s = size / upm
    x, out = x0, []
    for i, ch in enumerate(text):
        if kern and i in kern:
            x += kern[i]
        contours, adv = glyph_contours(font, ch)
        out.append({"ch": ch, "x": x, "raw": contours, "s": s, "baseline": baseline,
                    "d": [contour_d(c, s, x, baseline) for c in contours]})
        x += adv * s + tracking
    return out, x


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}">\n'
            f'<title>{title}</title>\n{body}\n</svg>\n')


def mask_group(x, y, height):
    """Embed the vectorised mask (mask-v1.svg) scaled to height."""
    src = open(os.path.join(os.path.dirname(__file__), "mask-v1.svg"), encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', src).group(1).split()]
    paths = "\n".join(re.findall(r"<path [^>]+/>", src))
    k = height / vb[3]
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({k:.4f}) translate({-vb[0]:.1f},{-vb[1]:.1f})">'
            f"\n{paths}\n</g>", vb[2] * k)


# ---------------------------------------------------------------- A: two eyes
# "Mimic" has two i's; their dots are the mask's two eyes. The first dot is
# plain: the calm white half. The second glitches exactly like the mask's
# dark-half eye: the same dot, offset pink down-left and mint up-right.
# It looks like an ordinary word until you look at it twice.
def concept_a(dark=False):
    ink = PAPER if dark else INK
    letters, width = set_word(ITALIC, "Mimic", 200, 190, x0=12)
    body, n_i = [], 0
    for L in letters:
        if L["ch"] == "i":
            n_i += 1
            ranked = sorted(range(len(L["raw"])), key=lambda j: bbox_y(L["raw"][j])[0])
            dot = ranked[-1]
            stem = [d for j, d in enumerate(L["d"]) if j != dot]
            body.append(f'<path fill="{ink}" d="{" ".join(stem)}"/>')
            if n_i == 2:
                body.append(f'<path fill="{PINK}" transform="translate(-5,3)" d="{L["d"][dot]}"/>')
                body.append(f'<path fill="{MINT}" transform="translate(5,-3)" d="{L["d"][dot]}"/>')
            body.append(f'<path fill="{ink}" d="{L["d"][dot]}"/>')
        else:
            body.append(f'<path fill="{ink}" d="{" ".join(L["d"])}"/>')
    return body, width + 12


# ---------------------------------------------------------------- B: split
# The word is split down the middle exactly like the mask: the left half
# solid (the face it shows), the right half only an outline (what's hollow
# behind it). A honeypot is a real-looking front with nothing inside.
def concept_b(dark=False):
    ink = PAPER if dark else INK
    letters, width = set_word(REGULAR, "mimic", 210, 190, x0=12, tracking=2)
    d = " ".join(p for L in letters for p in L["d"])
    mid = (12 + width) / 2
    body = [
        f'<defs><clipPath id="L"><rect x="0" y="0" width="{mid:.1f}" height="256"/></clipPath>'
        f'<clipPath id="R"><rect x="{mid:.1f}" y="0" width="{width:.1f}" height="256"/></clipPath></defs>',
        f'<path clip-path="url(#L)" fill="{ink}" d="{d}"/>',
        f'<path clip-path="url(#R)" fill="none" stroke="{ink}" stroke-width="3" d="{d}"/>',
        f'<rect x="{mid - 1:.1f}" y="40" width="2" height="190" fill="{ink}" opacity="0"/>',
    ]
    return body, width + 12


# ---------------------------------------------------------------- C: ticket stub
# The mask is the only drawn, expressive thing; the name steps back and is
# set like the label on a ticket stub (the dashboard's mono voice). One
# hand-made face, one machine-made name: the honeypot and the code.
def concept_c(dark=False):
    ink = PAPER if dark else INK
    letters, width = set_word(MONO, "MIMIC", 120, 168, x0=12, tracking=42)
    body = [f'<path fill="{ink}" d="{" ".join(p for L in letters for p in L["d"])}"/>']
    return body, width - 42 + 12


def write(name, body, w, title):
    open(os.path.join(os.path.dirname(__file__), name), "w", encoding="utf-8").write(svg(w, 256, "\n".join(body), title))


if __name__ == "__main__":
    for key, fn, title in (("a", concept_a, "Mimic: two eyes"), ("b", concept_b, "Mimic: split"),
                           ("c", concept_c, "Mimic: ticket stub")):
      body, w = fn()
      write(f"concept-{key}-wordmark.svg", body, w, title)
      # horizontal lockup on dark: mask + wordmark, mask height = cap-height x 1.6
      mg, mw = mask_group(16, 28, 200)
      wb, ww = fn(dark=True)
      gap = 36
      lock = [f'<rect width="{16 + mw + gap + ww + 24:.0f}" height="256" fill="#0C0B0E"/>', mg,
              f'<g transform="translate({16 + mw + gap:.1f},0)">', *wb, "</g>"]
      write(f"concept-{key}-lockup.svg", lock, 16 + mw + gap + ww + 24, title + " lockup")
      print(key, "ok", round(w), round(16 + mw + gap + ww + 24))
