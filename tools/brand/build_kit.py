"""Mimic identity kit: wordmark "Two eyes" + lockups, all as outlines.

Regenerate: pip install potracer fonttools brotli, then
  python tools/brand/trace_mask.py assets/mimic_logo_animation.gif assets/brand/mimic-mask-colour.svg colour
  (also: small, black, white) and python tools/brand/build_kit.py

Rules encoded here (and written in BRAND.md):
- Wordmark: Instrument Serif Italic "Mimic". The second i-dot glitches like
  the mask's dark-half eye: the same dot offset pink down-left, mint up-right.
- Glitch offset = 2.5 % of the font size (large) or 4 % (small cut, used
  below 200 px wide) so the idea survives when the mark is small.
- Horizontal lockup: mask height = 1.15 x the wordmark's cap height; gap
  between mask and word = 0.3 x mask height.
- Clear space around any lockup = the height of the glitch dot x 2.
"""
import os
import re

from type_layout import ITALIC, MONO, bbox_y, set_word

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "..", "assets", "brand")
GROUND, WHITE, PINK, MINT = "#0C0B0E", "#FDFEFE", "#CC5392", "#51C897"
SIZE, BASE = 200, 190
CAP = 0.0  # filled in below


def wordmark(ink, glitch=True, small=False):
    """Return (svg body, width, dot height) for "Mimic" at SIZE on BASE."""
    letters, width = set_word(ITALIC, "Mimic", SIZE, BASE, x0=0)
    off = SIZE * (0.04 if small else 0.025)
    body, n_i, dot_h = [], 0, 0
    for L in letters:
        if L["ch"] != "i":
            body.append(f'<path fill="{ink}" d="{" ".join(L["d"])}"/>')
            continue
        n_i += 1
        ranked = sorted(range(len(L["raw"])), key=lambda j: bbox_y(L["raw"][j])[0])
        dot = ranked[-1]
        lo, hi = bbox_y(L["raw"][dot])
        dot_h = (hi - lo) * L["s"]
        body.append(f'<path fill="{ink}" d="{" ".join(d for j, d in enumerate(L["d"]) if j != dot)}"/>')
        if n_i == 2 and glitch:
            body.append(f'<path fill="{PINK}" transform="translate({-off:.1f},{off * 0.6:.1f})" d="{L["d"][dot]}"/>')
            body.append(f'<path fill="{MINT}" transform="translate({off:.1f},{-off * 0.6:.1f})" d="{L["d"][dot]}"/>')
        body.append(f'<path fill="{ink}" d="{L["d"][dot]}"/>')
    return "\n".join(body), width, dot_h


def cap_height():
    letters, _ = set_word(ITALIC, "M", SIZE, BASE)
    lo, hi = bbox_y(letters[0]["raw"][0])
    return (hi - lo) * letters[0]["s"]


def mask(variant):
    src = open(os.path.join(KIT, f"mimic-mask-{variant}.svg"), encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', src).group(1).split()]
    return "\n".join(re.findall(r"<path [^>]+/>", src)), vb


def place_mask(variant, x, y, h):
    paths, vb = mask(variant)
    k = h / vb[3]
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({k:.4f}) translate({-vb[0]:.1f},{-vb[1]:.1f})">\n'
            f"{paths}\n</g>"), vb[2] * k


def save(name, w, h, body, title, bg=None):
    rect = f'<rect width="{w:.0f}" height="{h:.0f}" fill="{bg}"/>\n' if bg else ""
    with open(os.path.join(KIT, name), "w", encoding="utf-8") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}">\n'
                f"<title>{title}</title>\n{rect}{body}\n</svg>\n")


def main():
    cap = cap_height()
    top = BASE - cap                      # y of the cap line
    pad_y = 30
    # --- wordmarks (cropped to the glyph box plus glitch room) ---
    for name, ink, glitch, small in (("dark", WHITE, True, False), ("light", GROUND, True, False),
                                     ("dark-small", WHITE, True, True), ("light-small", GROUND, True, True),
                                     ("white", "#FFFFFF", False, False), ("black", "#000000", False, False)):
        body, w, dot_h = wordmark(ink, glitch, small)
        # cropped to the letters: cap line (minus the glitch's upward offset) to baseline
        y0 = top - 24
        save(f"mimic-wordmark-{name}.svg", w + 16, BASE + 16 - y0,
             f'<g transform="translate(8,{-y0:.1f})">{body}</g>', f"Mimic wordmark ({name})")

    # --- lockups ---
    mask_h = cap * 1.15 * 1.45  # mask is taller than wide; its eyes sit near cap height
    for theme, ink, bg in (("dark", WHITE, GROUND), ("light", GROUND, "#EDEBE6")):
        body, w, dot_h = wordmark(ink)
        clear = dot_h * 2
        # horizontal: mask vertically centred on the cap height
        my = top + cap / 2 - mask_h / 2
        g, mw = place_mask("colour", clear, my - (my - clear) if my < clear else my, mask_h)
        y_shift = clear - my if my < clear else 0
        gap = 0.3 * mask_h
        W = clear + mw + gap + w + clear
        H = max(BASE, my + mask_h) + y_shift + clear
        save(f"mimic-lockup-horizontal-{theme}.svg", W, H,
             f'<g transform="translate(0,{y_shift:.1f})">{g}\n<g transform="translate({clear + mw + gap:.1f},0)">{body}</g></g>',
             f"Mimic lockup, horizontal ({theme})", bg)
        # stacked: mask centred above the word
        sm_h = mask_h * 1.3
        g2, mw2 = place_mask("colour", 0, 0, sm_h)
        W2 = max(w, mw2) + 2 * clear
        word_y = clear + sm_h + 0.18 * sm_h - top
        H2 = word_y + BASE + clear * 0.6 + 20
        save(f"mimic-lockup-stacked-{theme}.svg", W2, H2,
             f'<g transform="translate({(W2 - mw2) / 2:.1f},{clear:.1f})">{g2}</g>\n'
             f'<g transform="translate({(W2 - w) / 2:.1f},{word_y:.1f})">{body}</g>',
             f"Mimic lockup, stacked ({theme})", bg)
    print(f"cap {cap:.1f}px, mask {mask_h:.1f}px, glitch dot {dot_h:.1f}px, clear space {clear:.1f}px")

    # --- README banner 1280x640: the horizontal lockup + one line on what it is ---
    body, w, dot_h = wordmark(WHITE)
    g, mw = place_mask("colour", 0, 0, mask_h)
    gap = 0.3 * mask_h
    lw = mw + gap + w
    k = 760 / lw
    tag, tw = set_word(MONO, "EVERY PORT IS A MASK", 22, 0, tracking=6)
    tag_d = " ".join(p for L in tag for p in L["d"])
    my = top + cap / 2 - mask_h / 2
    banner = (f'<g transform="translate({(1280 - lw * k) / 2:.1f},{170 - my * k:.1f}) scale({k:.4f})">'
              f'<g transform="translate(0,{my:.1f})">{g}</g><g transform="translate({mw + gap:.1f},0)">{body}</g></g>\n'
              f'<path fill="#A8A3B0" transform="translate({(1280 - tw + 6) / 2:.1f},540)" d="{tag_d}"/>')
    save("mimic-banner.svg", 1280, 640, banner, "Mimic banner", GROUND)


if __name__ == "__main__":
    main()
