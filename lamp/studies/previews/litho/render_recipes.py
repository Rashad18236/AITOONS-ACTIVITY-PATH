"""What glows on the lid: thickness recipes for the disc lithophane, rendered straight down,
with the flat print's layer steps and the light spreading inside the plastic simulated.
Run from the Activity Path Poster folder:
  PYTHONPATH="$PWD" uv run python .../litho/render_recipes.py
"""
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_litho as RL

RF, poster = RL.RF, RL.poster
S = 6.0                      # px per mm
RD = 46.5                    # disc radius on the assumed light
MAP_R = RD - 8.0             # round map radius
FIRST, LAYER = 0.2, 0.08     # flat print: first layer, then fine layers
SPREAD_MM = 0.45             # light spreading inside the plastic (blur sigma)
DARK = np.array((20, 18, 16), float)
LIGHT = np.array((236, 232, 224), float)
LDIR = np.array((-0.6, -0.6, 0.5)) / np.linalg.norm((-0.6, -0.6, 0.5))   # x right, y down, z up


def norm(a, p=(2, 98)):
    lo, hi = np.percentile(a, p)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def resize(a, n):
    return np.asarray(Image.fromarray(np.asarray(a, np.float32), "F").resize((n, n), Image.BICUBIC))


def blur(a, sigma_px):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(sigma_px))
    return np.asarray(im, float) / 255


def tone(v):
    return 0.7 + 2.3 * v


def route_mask(z, width_mm=1.1):
    img = Image.new("L", (z.N, z.N), 0)
    d = ImageDraw.Draw(img)
    w = max(2, round(width_mm / (2 * MAP_R / z.N)))
    for _, ls in z.walls:
        for l in ls:
            d.line([tuple(p) for p in poster._to_px(list(zip(l.lat, l.lon)), z.b, z.N)], fill=255, width=w, joint="curve")
    return np.asarray(img) > 127


def edges(c):
    return (np.diff(c, axis=0, prepend=c[:1]) != 0) | (np.diff(c, axis=1, prepend=c[:, :1]) != 0)


# ------------------------------------------------------------ recipes ----
def recipes(z):
    hn = norm(z.elev)
    sh = norm(RF.lambert(z.H, z.cell, k=3.0))
    e = poster._smooth(np.asarray(z.elev, float), 2)
    T = {
        "height": tone(hn),
        "shade": tone(1 - sh),
        "blend": tone(norm(0.35 * hn + 0.65 * (1 - sh))),
        "peaks": tone(norm(0.65 * (1 - hn) + 0.35 * (1 - sh))),
    }
    c = np.full(e.shape, 1.2)
    c[RL.grow(edges(np.floor(e / 200)), 2)] = 2.5
    c[RL.grow(edges(np.floor(e / 1000)), 3)] = 3.0
    T["contours"] = c
    m = 1.1 + 0.5 * (1 - sh)
    m[RL.grow(z.M["detail"], 1)] = 2.6
    T["map"] = m
    return T


def city_map(z):
    sh = norm(RF.lambert(z.H, z.cell, k=3.0))
    m = 1.0 + 0.3 * (1 - sh)
    m[z.M["buildings"]] = 2.0
    m[RL.grow(z.M["detail"], 1)] = 2.7
    return m


def finish_map(z, T):
    """Shared by every recipe: lakes bright, the route brightest with a dark edge."""
    T = T.copy()
    T[z.M["water"]] = 0.7
    route = route_mask(z)
    T[RL.grow(route, 4) & ~route] = 3.0   # ~0.85 mm dark edge, narrower melts into the glow
    T[route] = 0.6
    return T


def disc(Tmap, ring=None, caption=RL.CAPTION):
    D = int(2 * RD * S)
    yy, xx = np.mgrid[0:D, 0:D]
    rr = np.hypot(xx - D / 2 + 0.5, yy - D / 2 + 0.5) / S
    T = np.full((D, D), 3.0, np.float32)
    inner = int(2 * MAP_R * S)
    o = (D - inner) // 2
    sub, rin = T[o:o + inner, o:o + inner], rr[o:o + inner, o:o + inner] < MAP_R
    sub[rin] = resize(Tmap, inner)[rin]
    T[(rr >= MAP_R) & (rr < MAP_R + 0.6)] = 1.0
    if ring is None:
        txt = RF.arc_text_mask((D, D), (D / 2, D / 2), (RD - 4.3) * S, "  ·  ".join(caption),
                               int(5.2 * S), bottom=True, track=3)
        T[txt] = 0.8
    else:
        ang = (np.degrees(np.arctan2(xx - D / 2, -(yy - D / 2))) + 360) % 360
        band = (rr > MAP_R + 1.2) & (rr < RD - 1.4)
        k = np.minimum((ang / (360 / len(ring))).astype(int), len(ring) - 1)
        T[band] = np.asarray(ring)[k[band]]
        gap = band & ((ang % (360 / len(ring))) < 1.2)
        T[gap] = 3.0
    T[rr > RD - 1.0] = 3.0
    return T, rr


def quant(T, layer=LAYER):
    return FIRST + np.round((T - FIRST) / layer) * layer


def lit(T, rr, layer=LAYER, raw=False):
    b = RL.glow(T) if raw else blur(RL.glow(quant(T, layer)), SPREAD_MM * S)
    b = b * (0.9 + 0.1 * np.exp(-(rr / 28) ** 2))
    img = RL.warm(b)
    img[rr > RD] = DARK
    img[(rr > RD) & (rr < RD + 3.5)] = (40, 38, 36)
    return img


def off(T, rr):
    gr, gc = np.gradient(quant(T), 1 / S)
    n = np.dstack([-gc, -gr, np.ones_like(gc)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    img = RL.WHITE * (0.48 + 0.56 * np.clip(n @ LDIR, 0, 1))[..., None]
    img[rr > RD] = LIGHT
    img[(rr > RD) & (rr < RD + 3.5)] = (34, 34, 35)
    return img


def pad(img, bg, p=16):
    h, w, _ = img.shape
    out = np.empty((h + 2 * p, w + 2 * p, 3))
    out[:] = bg
    out[p:p + h, p:p + w] = img
    return out


def save(img, name, scale=1.0):
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if scale != 1.0:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    im.save(f"{HERE}/{name}.jpg", quality=86, optimize=True)
    print("  wrote", name, im.size)


def pair(T, rr, name):
    save(np.concatenate([pad(lit(T, rr), DARK), pad(off(T, rr), LIGHT)], axis=1), name, 0.8)


def wedge(steps):
    w, h, gap = 104, 104, 10
    im = Image.new("RGB", (len(steps) * (w + gap) + gap, h + 52), tuple(int(v) for v in DARK))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(RF.FONT, 19)
    for i, t in enumerate(steps):
        x = gap + i * (w + gap)
        d.rectangle((x, gap, x + w, gap + h), fill=tuple(int(v) for v in RL.warm(RL.glow(t))))
        d.text((x + w / 2, gap + h + 22), f"{t:.1f} mm", font=f, fill=(222, 210, 192), anchor="mm")
    im.save(f"{HERE}/litho_wedge.jpg", quality=90)
    print("  wrote litho_wedge", im.size)


def main():
    z = RF.Scene(RF.load("zermatt"), 360, "alpine_hiking")
    for key, Tm in recipes(z).items():
        T, rr = disc(finish_map(z, Tm))
        pair(T, rr, f"recipe_{key}")
        if key == "blend":
            Tb, rb = T, rr
    c = RF.Scene(RF.load("city"), 360, "city_marathon")
    T, rr = disc(finish_map(c, city_map(c)), caption=("ZURICH OLD TOWN 5K", "5.0 KM  ·  12.10.2026"))
    pair(T, rr, "recipe_city")
    # layer steps: one crop of the blend recipe at three flat-print layer heights
    D = Tb.shape[0]
    cy, cx, hw = int(D * 0.40), int(D * 0.56), int(13 * S)
    crops = []
    for im, bg in ((lit(Tb, rb, raw=True), DARK), (lit(Tb, rb), DARK), (off(Tb, rb), LIGHT)):
        im = im[cy - hw:cy + hw, cx - hw:cx + hw]
        crops.append(pad(np.asarray(Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).resize(
            (hw * 5, hw * 5), Image.BICUBIC), float), bg, 10))
    save(np.concatenate(crops, axis=1), "litho_detail", 0.7)
    steps = (0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2, 2.6, 3.0)
    wedge(steps)
    T, rr = disc(finish_map(z, recipes(z)["blend"]), ring=(0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.4, 2.8, 3.2))
    save(pad(lit(T, rr), DARK), "litho_testlid", 0.8)


if __name__ == "__main__":
    main()
