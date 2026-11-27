"""Faithful vectorisation of the hand-drawn Mimic mask.

Layers, bottom to top (each traced separately so the hand-drawn edges stay):
  1. silhouette  - everything inside the outline, filled black (so the mask
                   reads on any background, not only on black)
  2. white       - the white half, the outline and the white details
  3. pink, mint  - the glitch offsets on the eye and the mouth
The source is 320 px, so it is upscaled 4x with smoothing before
thresholding: that rounds off pixel stairs without inventing new shapes.
"""
import os
import sys
from collections import deque

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import numpy as np
import potrace
import pygame

SRC, OUT = sys.argv[1], sys.argv[2]
SCALE = 4
PINK, MINT = np.array([201, 71, 139]), np.array([81, 200, 151])

pygame.display.init(); pygame.display.set_mode((1, 1))
img = pygame.image.load(SRC)
w, h = img.get_size()
big = pygame.transform.smoothscale(img.convert(24), (w * SCALE, h * SCALE))
rgb = pygame.surfarray.array3d(big).swapaxes(0, 1).astype(int)   # (H, W, 3)
H, W = rgb.shape[:2]

lum = rgb.mean(axis=2)
sat = rgb.max(axis=2) - rgb.min(axis=2)
d_pink = np.linalg.norm(rgb - PINK, axis=2)
d_mint = np.linalg.norm(rgb - MINT, axis=2)

white = (lum > 150) & (sat < 60)
pink = (d_pink < 70) & (sat >= 60)
mint = (d_mint < 70) & (sat >= 60)

# Silhouette = not reachable from the border through dark pixels.
dark = lum < 60
outside = np.zeros_like(dark)
q = deque([(0, 0), (0, W - 1), (H - 1, 0), (H - 1, W - 1)])
while q:
    y, x = q.popleft()
    if y < 0 or x < 0 or y >= H or x >= W or outside[y, x] or not dark[y, x]:
        continue
    outside[y, x] = True
    q.extend(((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))
silhouette = ~outside


def path_d(mask, turdsize=8):
    bmp = potrace.Bitmap(~mask)   # potracer traces dark pixels
    plist = bmp.trace(turdsize=turdsize, alphamax=1.0, opticurve=True, opttolerance=0.2)
    parts = []
    for curve in plist:
        s = curve.start_point
        parts.append(f"M{s.x / SCALE:.2f},{s.y / SCALE:.2f}")
        for seg in curve.segments:
            if seg.is_corner:
                parts.append(f"L{seg.c.x / SCALE:.2f},{seg.c.y / SCALE:.2f}"
                             f"L{seg.end_point.x / SCALE:.2f},{seg.end_point.y / SCALE:.2f}")
            else:
                parts.append(f"C{seg.c1.x / SCALE:.2f},{seg.c1.y / SCALE:.2f} "
                             f"{seg.c2.x / SCALE:.2f},{seg.c2.y / SCALE:.2f} "
                             f"{seg.end_point.x / SCALE:.2f},{seg.end_point.y / SCALE:.2f}")
        parts.append("Z")
    return "".join(parts), len(plist)


VARIANT = sys.argv[3] if len(sys.argv) > 3 else "colour"
ink_black = silhouette & ~white & ~pink & ~mint
if VARIANT == "colour":      # master: drawn colours on a dark silhouette
    layers = [("silhouette", silhouette, "#0C0B0E", 40), ("white", white, "#FDFEFE", 6),
              ("pink", pink, "#CC5392", 3), ("mint", mint, "#51C897", 3)]
elif VARIANT == "small":     # 16-48 px: no glitch, no specks; the shape is the message
    layers = [("silhouette", silhouette, "#0C0B0E", 40), ("white", white | pink | mint, "#FDFEFE", 400)]
elif VARIANT == "black":     # one ink on light paper: print only the dark half
    layers = [("ink", ink_black, "#000000", 6)]
elif VARIANT == "white":     # one ink on dark: print only the white half and outline
    layers = [("ink", white, "#FFFFFF", 6)]
body = []
for name, mask, colour, turd in layers:
    d, n = path_d(mask, turd)
    body.append(f'  <path id="{name}" fill="{colour}" fill-rule="evenodd" d="{d}"/>')
    print(f"{name}: {int(mask.sum())} px, {n} paths, {len(d)} chars")

# Crop the viewBox to the silhouette with a small margin.
ys, xs = np.nonzero(silhouette)
m = 4
x0, y0 = xs.min() / SCALE - m, ys.min() / SCALE - m
vw, vh = (xs.max() - xs.min()) / SCALE + 2 * m, (ys.max() - ys.min()) / SCALE + 2 * m
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.1f} {y0:.1f} {vw:.1f} {vh:.1f}">\n'
       f'  <title>Mimic mask (hand-drawn, vectorised)</title>\n' + "\n".join(body) + "\n</svg>\n")
open(OUT, "w", encoding="utf-8").write(svg)
print("wrote", OUT, f"viewBox {vw:.0f}x{vh:.0f}")
