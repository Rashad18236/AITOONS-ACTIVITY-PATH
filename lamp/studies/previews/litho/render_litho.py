"""Lithophane concepts on the existing round up-light (the Candle Light).
Sketch renders from the real Zermatt data, not print meshes; the light's size is assumed.
Run from the Activity Path Poster folder:
  PYTHONPATH="$PWD" uv run python .../litho/render_litho.py
"""
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "forms"))
import render_forms as RF

poster, FONT = RF.poster, RF.FONT
WARM = np.array((255, 184, 108), float)
WHITE = np.array((243, 241, 235), float)
TMIN, TMAX, K = 0.6, 3.2, 1.1      # lithophane thickness range (mm) and PLA attenuation
S = 4.0                             # texture px per mm
R, HS = 50.0, 150.0                 # lantern shade radius / height (assumed light: dia 96 x 38)
HB, RB = 38.0, 48.0                 # the light: height, radius (assumed)
ZW = 260.0                          # wall distance behind the lamp, mm
LDIR = np.array((-0.55, 0.6, 0.6)) / np.linalg.norm((-0.55, 0.6, 0.6))
CAPTION = ("ZERMATT TRAIL RUN", "14.2 KM  ·  15.08.2026")


def glow(T):
    b = np.exp(-K * np.asarray(T))
    lo, hi = math.exp(-K * TMAX), math.exp(-K * TMIN)
    return np.clip((b - lo) / (hi - lo), 0, 1)


def warm(b):
    # backlit PLA: amber in the thick parts, near white where it is thinnest
    return 255 * (1 - np.exp(-2.6 * np.asarray(b)[..., None] * np.array((1.0, 0.68, 0.36))))


def grow(m, px):
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * px + 1))) > 127


def map_thickness(z, side):
    """Peaks thick (dark), valleys thin, lakes thinner, the route thinnest with a dark halo."""
    hn = (z.H - z.H.min()) / (np.ptp(z.H) + 1e-9)
    sh = RF.lambert(z.H, z.cell, k=3.0)
    sh = (sh - sh.min()) / (np.ptp(sh) + 1e-9)
    v = 0.35 * hn + 0.65 * (1 - sh)
    lo, hi = np.percentile(v, (2, 98))
    T = 0.8 + 2.3 * np.clip((v - lo) / (hi - lo), 0, 1)
    T[z.M["water"]] = 0.7
    route = z.route_col[0] > 0
    T[grow(route, 1) & ~route] = 3.2
    T[route] = 0.6
    return np.asarray(Image.fromarray(T.astype(np.float32), "F").resize((side, side), Image.BICUBIC))


def route_profile(z):
    q = np.concatenate([np.asarray(poster._to_px(list(zip(l.lat, l.lon)), z.b, z.N), float)
                        for _, ls in z.walls for l in ls])
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    e = z.elev[np.clip(q[:, 1].astype(int), 0, z.N - 1), np.clip(q[:, 0].astype(int), 0, z.N - 1)]
    e = np.interp(np.linspace(0, d[-1], 700), d, e)
    return np.convolve(np.pad(e, 8, mode="edge"), np.ones(17) / 17, "valid")


def lantern_texture(z):
    """The shade unrolled: map at the front, caption under it, the climb as a skyline round the back."""
    TW, TH = int(round(2 * math.pi * R * S)), int(HS * S)
    T = np.full((TH, TW), 1.4, np.float32)
    rim = int(4 * S)
    side = int(104 * S)
    x0, y0 = TW // 2 - side // 2, int(9 * S)
    T[y0 - 4:y0 + side + 4, x0 - 4:x0 + side + 4] = 3.2
    T[y0:y0 + side, x0:x0 + side] = map_thickness(z, side)
    cap = Image.new("L", (TW, TH), 0)
    d = ImageDraw.Draw(cap)
    yc = y0 + side + int(14 * S)
    d.text((TW // 2, yc), CAPTION[0], font=ImageFont.truetype(FONT, int(9 * S)), fill=255, anchor="mm")
    d.text((TW // 2, yc + int(11 * S)), CAPTION[1], font=ImageFont.truetype(FONT, int(5.5 * S)), fill=255, anchor="mm")
    T[np.asarray(cap) > 127] = 3.2
    e = route_profile(z)
    L = TW - side - int(2 * 18 * S)
    en = np.interp(np.linspace(0, 1, L), np.linspace(0, 1, len(e)), (e - e.min()) / np.ptp(e))
    top = (HS - 26) * S - en * 72 * S
    sil = np.arange(TH)[:, None] >= top[None, :]
    cols = (x0 + side + int(18 * S) + np.arange(L)) % TW
    T[:, cols] = np.where(sil, 3.0, T[:, cols])
    T[:rim] = 3.4
    T[-rim:] = 3.4
    return T


def bilinear(T, r, c):
    TH, TW = T.shape
    r = np.clip(r, 0, TH - 1.001)
    r0 = np.floor(r).astype(int)
    fr = r - r0
    c0 = np.floor(c).astype(int)
    fc = c - c0
    c0 %= TW
    c1 = (c0 + 1) % TW
    a = T[r0, c0] * (1 - fc) + T[r0, c1] * fc
    b = T[r0 + 1, c0] * (1 - fc) + T[r0 + 1, c1] * fc
    return a * (1 - fr) + b * fr


class Cam:
    """Orthographic camera looking down at el degrees; world y up, z towards the viewer."""

    def __init__(self, W, H, s, el, ground_row):
        e = math.radians(el)
        self.W, self.H, self.ce, self.se = W, H, math.cos(e), math.sin(e)
        self.U, self.V = np.meshgrid((np.arange(W) - W / 2) / s, (ground_row - np.arange(H)) / s)

    def cylinder(self, rad, y0, y1):
        th = np.arcsin(np.clip(self.U / rad, -1, 1))
        y = (self.V + rad * np.cos(th) * self.se) / self.ce
        return (np.abs(self.U) < rad) & (y >= y0) & (y <= y1), th, y

    def disk(self, rad, y):
        zz = (y * self.ce - self.V) / self.se
        return self.U ** 2 + zz ** 2 <= rad * rad, self.U, zz


def room(cam, lit, lamp_y):
    U, V = cam.U, cam.V
    zz = -V / cam.se
    floor = zz > -ZW
    if lit:
        yw = (V - ZW * cam.se) / cam.ce
        gw = 0.95 / (1 + (np.hypot(U, yw - lamp_y) / 150) ** 2)
        gf = 1.0 / (1 + (np.maximum(np.hypot(U, zz) - R, 0) / 75) ** 2)
        img = np.array((22, 18, 15), float) + WARM * 0.40 * gw[..., None]
        img[floor] = (np.array((30, 24, 19), float) + WARM * 0.55 * gf[..., None])[floor]
    else:
        t = np.linspace(0, 1, cam.H)[:, None, None]
        img = np.broadcast_to(np.array((238, 234, 226)) * (1 - 0.05 * t), (cam.H, cam.W, 3)).copy()
        sh = 1 - 0.32 * np.exp(-(np.maximum(np.hypot(U - 22, zz + 22) - R, 0) / 16) ** 2)
        img[floor] = (np.array((220, 213, 202)) * sh[..., None])[floor]
    return img


def side_shade(th, lit, y=None, top=None):
    if lit:
        return 0.30 + 0.22 * np.cos(th) + (0.35 * np.clip(y / top, 0, 1) ** 3 if y is not None else 0)
    return 0.40 + 0.62 * np.clip(np.sin(th) * LDIR[0] + np.cos(th) * LDIR[2], 0, 1)


def bloom(img, r=22, k=0.45):
    hot = Image.fromarray(np.clip(img - 150, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))
    return img + k * np.asarray(hot, float)


def finish(img, name, crop=None):
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if crop:
        im = im.crop(crop)
    im.save(f"{HERE}/{name}.jpg", quality=88, optimize=True)
    print("  wrote", name, im.size)


def lantern(z, T, lit):
    TH, TW = T.shape
    cam = Cam(760, 1000, 3.2, 12, 900)
    CH = 8.0
    Y0, Y1 = HB + CH, HB + CH + HS
    img = room(cam, lit, (Y0 + Y1) / 2)
    m, th, y = cam.cylinder(RB, 0, HB)                       # the existing light
    img[m] = (np.array((58, 56, 54)) * side_shade(th, lit, y, HB)[..., None])[m]
    m, th, y = cam.cylinder(51.0, HB, Y0)                    # printed collar
    img[m] = (np.array((30, 30, 31)) * side_shade(th, lit, y - HB, CH)[..., None])[m]
    m, th, y = cam.cylinder(R, Y0, Y1)                       # the lithophane shade
    rr, cc = (Y1 - y) * S, th / (2 * math.pi) * TW + TW / 2
    t = bilinear(T, rr, cc)
    if lit:
        Ly = 0.86 + 0.14 * np.exp(-((y - Y0 - 0.4 * HS) / (0.45 * HS)) ** 2)
        c = warm(glow(t) * Ly * (0.62 + 0.38 * np.cos(th)))
    else:
        gr, gc = np.gradient(T, 1 / S)
        gs, gy = bilinear(gc, rr, cc), -bilinear(gr, rr, cc)
        n = np.stack([np.sin(th) - gs * np.cos(th), -gy, np.cos(th) + gs * np.sin(th)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        c = WHITE * (0.40 + 0.64 * np.clip(n @ LDIR, 0, 1))[..., None]
    img[m] = c[m]
    m, xx, zz = cam.disk(R, Y1)                              # lid with the press-through button
    rad = np.hypot(xx, zz)
    tl = np.where(rad < 13, 3.0, np.where(rad < 14.5, 3.4, np.where(rad > R - 3, 3.4, 1.8)))
    if lit:
        c = warm(glow(tl) * 0.92)
    else:
        c = WHITE * np.where(rad < 13, 0.9, np.where(rad < 14.5, 0.78, 0.97))[..., None]
    img[m] = c[m]
    if lit:
        img = bloom(img)
    finish(img, f"litho_lantern_{'on' if lit else 'off'}", (100, 120, 660, 1000))


def disc_texture(z, RD):
    D = int(2 * RD * S)
    yy, xx = np.mgrid[0:D, 0:D]
    rr = np.hypot(xx - D / 2 + 0.5, yy - D / 2 + 0.5) / S
    T = np.full((D, D), 3.2, np.float32)
    inner = int(2 * (RD - 8) * S)
    o = (D - inner) // 2
    sub, rin = T[o:o + inner, o:o + inner], rr[o:o + inner, o:o + inner] < RD - 8
    sub[rin] = map_thickness(z, inner)[rin]
    T[(rr > RD - 8.6) & (rr < RD - 8)] = 1.0
    txt = RF.arc_text_mask((D, D), (D / 2, D / 2), (RD - 4.2) * S, "  ·  ".join(CAPTION),
                           int(5.0 * S), bottom=True, track=3)
    T[txt] = 0.8
    return T


def lid_disc(z, lit):
    RD, RR = 46.5, 50.0
    YR, YD = HB + 7.0, HB + 5.5
    T = disc_texture(z, RD)
    D = T.shape[0]
    cam = Cam(900, 820, 4.4, 38, 640)
    img = room(cam, lit, HB)
    m, th, y = cam.cylinder(RB, 0, HB)
    img[m] = (np.array((58, 56, 54)) * side_shade(th, lit, y, HB)[..., None])[m]
    m, th, y = cam.cylinder(RR, HB, YR)
    img[m] = (np.array((30, 30, 31)) * side_shade(th, lit, y - HB, YR - HB)[..., None])[m]
    m, xx, zz = cam.disk(RD, YD)
    r, c = (zz + RD) * S, (xx + RD) * S
    t = bilinear(T, r, c)
    if lit:
        col = warm(glow(t) * (0.88 + 0.12 * np.exp(-(np.hypot(xx, zz) / 30) ** 2)))
    else:
        gr, gc = np.gradient(T, 1 / S)
        n = np.stack([-bilinear(gc, r, c), np.ones_like(t), -bilinear(gr, r, c)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        col = WHITE * (0.42 + 0.62 * np.clip(n @ LDIR, 0, 1))[..., None]
    img[m] = col[m]
    m, xx, zz = cam.disk(RR, YR)
    ring = m & (np.hypot(xx, zz) > RD)
    img[ring] = (np.array((30, 30, 31)) * (0.6 if lit else 1.25))
    if lit:
        img = bloom(img, 18, 0.55)
    finish(img, f"litho_disc_{'on' if lit else 'off'}", (160, 290, 740, 800))


def unrolled(T):
    T = np.roll(T, -(T.shape[1] // 2 - int(70 * S)), axis=1)   # map on the left, the skyline after it
    im = Image.fromarray(np.clip(warm(glow(T)), 0, 255).astype(np.uint8))
    im = im.resize((im.width * 2 // 3, im.height * 2 // 3), Image.LANCZOS)
    im.save(f"{HERE}/litho_unrolled.jpg", quality=88, optimize=True)
    print("  wrote litho_unrolled", im.size)


def main():
    z = RF.Scene(RF.load("zermatt"), 360, "classic")
    T = lantern_texture(z)
    for lit in (True, False):
        lantern(z, T, lit)
        lid_disc(z, lit)
    unrolled(T)


if __name__ == "__main__":
    main()
