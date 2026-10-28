"""Form experiments for the relief: real DEM/OSM data, simple oblique 3D renders.
Not the print mesh; a sketch of what each physical form would look like.
Run from the project folder:
  PYTHONPATH=. uv run python .../forms/render_forms.py
"""
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import render_previews as RP          # palettes T, fetch(), masks(), hexrgb
import render_more                    # noqa: F401  (adds the 22 round-2 palettes to RP.T)
import poster, activity

FONT = poster.FONT_PATHS[0][0]

# map data (not customer data) cached on disk in this scratch folder, so a flaky
# Overpass mirror only has to answer once per area
import hashlib, json, pickle, time
_raw_fetch = RP.fetch


def _cached_fetch(b):
    key = hashlib.sha1(json.dumps([round(v, 7) for v in b]).encode()).hexdigest()[:16]
    f = os.path.join(HERE, f"osm_{key}.pkl")
    if os.path.exists(f):
        return pickle.load(open(f, "rb"))
    for attempt in range(3):
        try:
            els = _raw_fetch(b)
            pickle.dump(els, open(f, "wb"))
            return els
        except RuntimeError as e:
            print("  overpass retry", attempt + 1, str(e)[:60])
            poster._overpass.cache_clear()
            time.sleep(20)
    raise RuntimeError("Overpass unavailable")


RP.fetch = _cached_fetch
BG_TOP, BG_BOT = np.array((238, 234, 226), float), np.array((214, 208, 197), float)


def hexf(h):
    return np.array(RP.hexrgb(h), float)


# ---------------------------------------------------------------- scenes ----
def load(key):
    if key == "zermatt":
        p = os.path.expanduser("~/Desktop/zermatt-trail-run/Zermatt_Trail_Run.gpx")
        return activity.read_activity([("z.gpx", open(p, "rb"))])
    if key == "tri":
        p = os.path.expanduser("~/Desktop/activity-poster-demo/zurich-triathlon.fit")
        return activity.read_activity([("t.fit", open(p, "rb"))])
    if key == "city":
        return RP.city_loop()


class Scene:
    """Terrain heights (mm), top colours and route walls on an N x N grid."""

    def __init__(self, legs, N, theme, relief_mm=25.92, snow=2000.0, walls=None, bounds=None):
        self.N, self.theme = N, RP.T[theme]
        self.walls = walls or activity.group_walls(legs)
        self.b = bounds or poster.legs_bounds([l for _, ls in self.walls for l in ls], 15.0)
        self.elev = np.asarray(poster.fetch_elevation(self.b, N), float)
        els = RP.fetch(self.b)
        RP.PX = N
        self.M = RP.masks(els, self.b, self.theme["groups"], RP.m_per_mm(self.b))
        e0, e1 = self.elev.min(), self.elev.max()
        self.span = max(e1 - e0, 300.0)
        self.e0 = e0
        self.H = (self.elev - e0) / self.span * relief_mm          # mm above the plate
        self.H[self.M["water"]] = np.minimum(self.H[self.M["water"]],
                                             np.percentile(self.H[self.M["water"]], 10)
                                             if self.M["water"].any() else 0)
        self.cell = 195.0 / N                                        # mm per cell on a 216 poster
        self.snow = snow
        self.route_h, self.route_col = self._walls()

    def _walls(self):
        N = self.N
        h = Image.new("F", (N, N), 0.0)
        c = Image.new("L", (N, N), 0)
        dh, dc = ImageDraw.Draw(h), ImageDraw.Draw(c)
        w = max(2, round(1.2 / self.cell) + 1)
        legs_col = self.theme.get("legs", ("#FFFFFF", "#CC2222", "#F4EE2A"))
        for k, (name, ls) in enumerate(self.walls):
            idx = 1 + ["strip", "swim", "bike", "run"].index(name)
            for l in ls:
                q = poster._to_px(list(zip(l.lat, l.lon)), self.b, N)
                hr = activity.smooth_hr(l.t, l.hr)
                step = max(1, len(q) // 1500)
                for i in range(0, len(q) - step, step):
                    v = hr[i]
                    hh = 1.0 + (0 if not np.isfinite(v) else np.clip((v - 100) / 100, 0, 1)) * 9.0
                    seg = [tuple(q[i]), tuple(q[i + step])]
                    dh.line(seg, fill=float(hh), width=w)
                    dc.line(seg, fill=idx, width=w)
        cols = {1: self.theme["path"], 2: legs_col[0], 3: legs_col[1], 4: legs_col[2]}
        return np.asarray(h), (np.asarray(c), cols)

    def top_colours(self, light=True):
        t, M = self.theme, self.M
        sh = lambert(self.H, self.cell) if light else np.ones_like(self.H)
        img = hexf(t["land"])[None, None, :] * (0.62 + 0.5 * sh[..., None])
        if t["band"]:
            band = self.elev >= self.snow
            img[band] = (hexf(t["band"])[None, :] * (0.62 + 0.5 * sh[band, None]))
        img[M["water"]] = hexf(t["water"]) * (0.95 + 0.05 * sh[M["water"], None])
        det = t["detail"] or t["band"]
        if det:
            img[M["detail"]] = hexf(det)
            img[M["buildings"]] = hexf(det) * 1.08
        return np.clip(img, 0, 255)

    def apply_walls(self, H, C, off=(0, 0)):
        """Raise the route walls into a (sub)grid at offset off; paint their colour."""
        r0, c0 = off
        rc, cols = self.route_col
        m = rc > 0
        sl = (slice(r0, r0 + self.N), slice(c0, c0 + self.N))
        Hs, Cs = H[sl], C[sl]
        Hs[m] += self.route_h[m]
        for k, hx in cols.items():
            Cs[rc == k] = hexf(hx)


def lambert(Hmm, cell, light=(-0.55, -0.6, 0.58), k=1.6):
    gy, gx = np.gradient(Hmm * k, cell)
    n = np.dstack([-gx, -gy, np.ones_like(gx)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array(light) / np.linalg.norm(light)
    return np.clip(n @ L, 0, 1)


# -------------------------------------------------------------- renderer ----
def render(H, C, present, cell, el=36, unit=2, skew=0.12, side_dark=0.58,
           strata=None, strata_mm=2.4, side=None, bg=True, shadow=True, pad=60):
    """Oblique painter's render of a height field. H mm above the table, C (R,C,3) top
    colours, present: which cells exist. Back rows first; each cell paints its top face
    (one row deep) then its front face down to the table."""
    R, Cn = H.shape
    ce, se = math.cos(math.radians(el)), math.sin(math.radians(el))
    zc = H / cell
    dy, zs = ce * unit, se * unit
    top = zc[present].max() * zs + pad
    Hs = int(R * dy + top + pad)
    Ws = int(Cn * unit + R * skew * unit + 2 * pad)
    can = np.zeros((Hs, Ws, 3), np.float32)
    alpha = np.zeros((Hs, Ws), bool)
    for r in range(R):
        pres = present[r]
        if not pres.any():
            continue
        yfloor = top + r * dy
        ytop = yfloor - zc[r] * zs
        ya, yb = int(max(0, ytop[pres].min() - 1)), int(min(Hs, yfloor + dy + 2))
        yy = np.arange(ya, yb, dtype=np.float32)[:, None]
        mt = (yy >= ytop) & (yy < ytop + dy) & pres
        ms = (yy >= ytop + dy) & (yy < yfloor + dy) & pres
        x0 = int(pad + r * skew * unit)
        ctop = np.repeat(C[r], unit, axis=0)[None]
        # a small step to the next row is terrain, not an edge: shade it like the top
        # (painting it dark striped gentle slopes like false contour lines)
        if r + 1 < R:
            drop = (zc[r] - zc[r + 1]) * zs
            soft = present[r + 1] & (drop <= 4)
        else:
            soft = np.zeros(Cn, bool)
        if strata is None:
            base = C[r] if side is None else np.broadcast_to(side, C[r].shape)
            cs_col = np.where(soft[:, None], C[r] * 0.86, base * side_dark)
            cs = np.repeat(cs_col, unit, axis=0)[None]
        else:
            zpix = (yfloor + dy - yy) / zs * cell            # mm above the table
            band = (zpix // strata_mm).astype(int) % len(strata)
            cs = np.where(soft[None, :, None], (C[r] * 0.86)[None], strata[band] * side_dark)
            cs = np.repeat(cs, unit, axis=1)
        mt, ms = np.repeat(mt, unit, axis=1), np.repeat(ms, unit, axis=1)
        reg = can[ya:yb, x0:x0 + Cn * unit]
        a = alpha[ya:yb, x0:x0 + Cn * unit]
        reg[mt] = np.broadcast_to(ctop, mt.shape + (3,))[mt]
        reg[ms] = np.broadcast_to(cs, ms.shape + (3,))[ms]
        a |= mt | ms
    out = background(Hs, Ws) if bg else np.zeros((Hs, Ws, 3), np.float32)
    if shadow:
        sh = Image.fromarray((alpha * 255).astype(np.uint8)).transform(
            (Ws, Hs), Image.AFFINE, (1, 0, -22, 0, 1, -30)).filter(ImageFilter.GaussianBlur(16))
        out *= (1 - 0.38 * np.asarray(sh, np.float32)[..., None] / 255)
    out[alpha] = can[alpha]
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    bbox = Image.fromarray((alpha * 255).astype(np.uint8)).getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        img = img.crop((max(0, x0 - 50), max(0, y0 - 40), min(Ws, x1 + 70), min(Hs, y1 + 70)))
    return img


def background(h, w):
    t = np.linspace(0, 1, h)[:, None, None]
    return np.broadcast_to(BG_TOP * (1 - t) + BG_BOT * t, (h, w, 3)).astype(np.float32).copy()


# ------------------------------------------------------------ text masks ----
def text_mask(shape, xy, text, size, anchor="mm"):
    img = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(img).text(xy, text, font=ImageFont.truetype(FONT, size), fill=255, anchor=anchor)
    return np.asarray(img) > 127


def arc_text_mask(shape, centre, radius, text, size, bottom=True, track=1.0):
    img = Image.new("L", (shape[1], shape[0]), 0)
    f = ImageFont.truetype(FONT, size)
    total = sum(f.getlength(ch) + track for ch in text)
    span = total / radius
    a = (math.pi / 2 + span / 2) if bottom else (3 * math.pi / 2 - span / 2)
    for ch in text:
        adv = f.getlength(ch) + track
        a_mid = a - adv / 2 / radius if bottom else a + adv / 2 / radius
        g = Image.new("L", (size * 2, size * 2), 0)
        ImageDraw.Draw(g).text((size, size), ch, font=f, fill=255, anchor="mm")
        rot = math.degrees(math.pi / 2 - a_mid) if bottom else math.degrees(3 * math.pi / 2 - a_mid)
        g = g.rotate(rot, resample=Image.BICUBIC)
        x = centre[0] + radius * math.cos(a_mid) - size
        y = centre[1] + radius * math.sin(a_mid) - size
        img.paste(g, (int(x), int(y)), g)
        a = a - adv / radius if bottom else a + adv / radius
    return np.asarray(img) > 127


# ------------------------------------------------------------------ forms ----
def save(img, name):
    img.convert("RGB").save(f"{HERE}/{name}.jpg", quality=86, optimize=True)
    print("  wrote", name, img.size)


def form_framed_profile(z):
    """Today's frame, with the chin carrying the run's elevation profile."""
    N, F, CH = z.N, 20, 58
    R, Cn = N + 2 * F + CH, N + 2 * F
    H = np.full((R, Cn), 14.12)
    t = z.theme
    C = np.broadcast_to(hexf(t["frame"]), (R, Cn, 3)).copy()
    H[F:F + N, F:F + N] = 4.04 + z.H
    C[F:F + N, F:F + N] = z.top_colours()
    z.apply_walls(H, C, (F, F))
    # profile: elevation along the route, as a raised silhouette on the chin
    leg = z.walls[0][1][0]
    px = poster._to_px(list(zip(leg.lat, leg.lon)), z.b, N)
    e = z.elev[np.clip(px[:, 1].astype(int), 0, N - 1), np.clip(px[:, 0].astype(int), 0, N - 1)]
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(px, axis=0).T))]
    xs = np.linspace(0, d[-1], Cn - 2 * F - 20)
    ep = np.interp(xs, d, e)
    ep = (ep - ep.min()) / (ep.max() - ep.min() + 1e-9)
    y0 = F + N + 8
    prof = np.zeros((R, Cn), bool)
    for i, v in enumerate(ep):
        c = F + 10 + i
        top = int(y0 + (1 - v) * 18)
        prof[top:y0 + 20, c] = True
    txt = text_mask((R, Cn), (Cn / 2, y0 + 33), "ZERMATT TRAIL RUN · 14.2 KM · +1735 M", 13)
    for m in (prof, txt):
        H[m] = 15.32
        C[m] = hexf(t["text"])
    C[F + N:, :][~(prof | txt)[F + N:, :]] = hexf(t["frame"])
    save(render(H, C, np.ones((R, Cn), bool), z.cell), "form_framed_profile")


def form_medal(z, theme="medal"):
    """A finisher medal: round relief, raised bronze rim with text on the arc, ribbon tab."""
    N = z.N
    ring, tab_h = 30, 46
    Ro = N / 2 + ring
    R, Cn = int(2 * Ro + tab_h + 6), int(2 * Ro + 6)
    cy, cx = tab_h + Ro + 3, Ro + 3
    yy, xx = np.mgrid[0:R, 0:Cn]
    r = np.hypot(yy - cy, xx - cx)
    disc, rim = r < N / 2, (r >= N / 2) & (r < Ro)
    tab = (np.abs(xx - cx) < 52) & (yy > 6) & (yy < cy - Ro + 18)
    slot = (np.abs(xx - cx) < 34) & (yy > 16) & (yy < 30)
    present = disc | rim | (tab & ~slot)
    bronze = hexf("#C98A3E")
    H = np.zeros((R, Cn))
    C = np.zeros((R, Cn, 3))
    o = (int(cy - N / 2), int(cx - N / 2))
    sub = (slice(o[0], o[0] + N), slice(o[1], o[1] + N))
    H[sub], C[sub] = 5.0 + z.H * 0.8, z.top_colours()
    Hz = np.zeros((R, Cn)); Cz = np.zeros((R, Cn, 3))
    Hz[sub], Cz[sub] = H[sub], C[sub]
    z.apply_walls(Hz, Cz, o)
    H[disc], C[disc] = Hz[disc], Cz[disc]
    # rim: a domed bronze band; text on the arcs in the darker metal
    dome = np.sin(np.clip((r - N / 2) / ring, 0, 1) * math.pi)
    H[rim] = 11 + 2.2 * dome[rim]
    H[tab & ~slot] = 9.0
    sh = lambert(H, z.cell, k=2.5)
    C[rim | tab] = (bronze * (0.55 + 0.75 * sh[..., None]))[rim | tab]
    tm = arc_text_mask((R, Cn), (cx, cy), N / 2 + ring / 2 - 1,
                       "ZERMATT TRAIL RUN · 14.2 KM · 15.08.2026", 16, bottom=True) & rim
    H[tm] += 1.0
    C[tm] = hexf("#6E4A1E")
    save(render(H, C, present, z.cell, el=40), "form_medal")


def form_ribbon(z):
    """Only the land you crossed: the relief is a band around the route."""
    N = z.N
    img = Image.new("L", (N, N), 0)
    w = int(26 / z.cell)
    for name, ls in z.walls:
        for l in ls:
            q = poster._to_px(list(zip(l.lat, l.lon)), z.b, N)
            ImageDraw.Draw(img).line([tuple(v) for v in q[::max(1, len(q) // 800)]], fill=255,
                                     width=w, joint="curve")
    band = np.asarray(img.filter(ImageFilter.GaussianBlur(2))) > 128
    H = 6.0 + z.H
    C = z.top_colours()
    z.apply_walls(H, C)
    save(render(H, C, band, z.cell, el=40, side=hexf("#8C7A62")), "form_ribbon")


def form_terraces(z):
    """Stacked contour layers, like a laser-cut topo model, two wood tones alternating."""
    step = z.span / 9
    lev = np.floor((z.elev - z.e0) / step)
    H = 3.0 + lev * 2.4
    tones = [hexf("#EFE6D6"), hexf("#D6BE98")]
    C = np.where((lev % 2 == 0)[..., None], tones[0], tones[1]) * (
        0.82 + 0.25 * lambert(z.H, z.cell)[..., None])
    edge = np.zeros_like(lev, bool)
    edge[1:] |= lev[1:] != lev[:-1]
    edge[:, 1:] |= lev[:, 1:] != lev[:, :-1]
    C[edge] *= 0.78
    w = z.M["water"]
    C[w] = hexf("#8FB3C4")
    z.apply_walls(H, C)
    st = np.array([tones[i % 2] for i in range(40)])
    save(render(H, C, np.ones_like(H, bool), z.cell, el=34, strata=st, strata_mm=2.4, side_dark=0.8),
         "form_terraces")


def form_fins(z):
    """Ridgeline fins: parallel terrain profiles standing on a black plate."""
    N = z.N
    H = np.full((N, N), 3.0)
    fin = (np.arange(N) % 16 < 2)[:, None] & np.ones((1, N), bool)
    H[fin] = 3.0 + (z.H[fin] - z.H.min()) * 4.2
    C = np.broadcast_to(hexf("#141414"), (N, N, 3)).copy()
    C[fin] = hexf("#F2F2EE")
    rc, _ = z.route_col
    hit = fin & (rc > 0)
    C[hit] = hexf("#FF4D00")
    side = np.where(hit[..., None], hexf("#FF4D00") / 0.58, hexf("#222222") / 0.58)
    Hn = H.copy()
    img = render_side(Hn, C, side, z.cell)
    save(img, "form_fins")


def render_side(H, C, side_cols, cell):
    """render() with a per-cell side colour."""
    R, Cn = H.shape
    out = None
    # pack per-cell side colours through the strata path: reuse render with side=None
    # by temporarily encoding the side colour as the top colour of a shadow copy
    img = render(H, C, np.ones((R, Cn), bool), cell, el=28, side_dark=1.0,
                 side=None) if False else None
    # simple direct implementation (same as render, per-cell side colour)
    el, unit, skew, pad = 16, 2, 0.12, 60
    ce, se = math.cos(math.radians(el)), math.sin(math.radians(el))
    zc = H / cell
    dy, zs = ce * unit, se * unit
    top = zc.max() * zs + pad
    Hs, Ws = int(R * dy + top + pad), int(Cn * unit + R * skew * unit + 2 * pad)
    can = np.zeros((Hs, Ws, 3), np.float32)
    alpha = np.zeros((Hs, Ws), bool)
    for r in range(R):
        yfloor = top + r * dy
        ytop = yfloor - zc[r] * zs
        ya, yb = int(max(0, ytop.min() - 1)), int(min(Hs, yfloor + dy + 2))
        yy = np.arange(ya, yb, dtype=np.float32)[:, None]
        mt = (yy >= ytop) & (yy < ytop + max(dy, 1.6))
        ms = (yy >= ytop + max(dy, 1.6)) & (yy < yfloor + dy)
        x0 = int(pad + r * skew * unit)
        ctop = np.repeat(C[r], unit, axis=0)[None]
        shade = np.clip(1.0 - (yy - ytop) / (zc[r] * zs + 1e-6) * 0.35, 0.6, 1.0)
        cs = np.repeat(side_cols[r] * 0.58, unit, axis=0)[None] * np.repeat(shade, unit, axis=1)[..., None]
        mt, ms = np.repeat(mt, unit, axis=1), np.repeat(ms, unit, axis=1)
        reg = can[ya:yb, x0:x0 + Cn * unit]
        a = alpha[ya:yb, x0:x0 + Cn * unit]
        reg[mt] = np.broadcast_to(ctop, mt.shape + (3,))[mt]
        reg[ms] = cs[ms]
        a |= mt | ms
    out = background(Hs, Ws)
    sh = Image.fromarray((alpha * 255).astype(np.uint8)).transform(
        (Ws, Hs), Image.AFFINE, (1, 0, -22, 0, 1, -30)).filter(ImageFilter.GaussianBlur(16))
    out *= (1 - 0.38 * np.asarray(sh, np.float32)[..., None] / 255)
    out[alpha] = can[alpha]
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    x0, y0, x1, y1 = Image.fromarray((alpha * 255).astype(np.uint8)).getbbox()
    return img.crop((max(0, x0 - 50), max(0, y0 - 40), min(Ws, x1 + 70), min(Hs, y1 + 70)))


def form_island(z):
    """No frame: the mountains rise out of a round plinth and fade at the edge."""
    N = z.N
    yy, xx = np.mgrid[0:N, 0:N]
    r = np.hypot(yy - N / 2, xx - N / 2) / (N / 2)
    fall = np.clip((1.0 - r) / 0.3, 0, 1)
    fall = fall * fall * (3 - 2 * fall)
    H = 3.0 + z.H * fall
    white = hexf("#F3F2EE")
    C = white * (0.42 + 0.68 * lambert(H, z.cell, k=3.2)[..., None])
    C[z.M["water"] & (r < 1)] = hexf("#DCDDDA")
    rc, cols = z.route_col
    m = (rc > 0) & (r < 0.97)
    H[m] += z.route_h[m] * 0.7
    C[m] = hexf("#1A1A1A")
    save(render(H, C, r < 1, z.cell, el=34, side=white * 0.95), "form_island")


def form_contours(z):
    """Line art: a flat plate with raised contour lines, the lake inlaid, the route in red."""
    N = z.N
    step = 80.0
    lev = np.floor((poster._smooth(z.elev, 2) - z.e0) / step)
    edge = np.zeros_like(lev, bool)
    edge[1:] |= lev[1:] != lev[:-1]
    edge[:, 1:] |= lev[:, 1:] != lev[:, :-1]
    edge = np.asarray(Image.fromarray((edge * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
    H = np.full((N, N), 4.0)
    C = np.broadcast_to(hexf("#F2F0EB"), (N, N, 3)).copy()
    H[edge], C[edge] = 5.2, hexf("#1C1C1C")
    w = z.M["water"]
    C[w] = hexf("#1F4FBF")
    rc, cols = z.route_col
    m = rc > 0
    H[m], C[m] = 4.0 + 1.2 + z.route_h[m] * 0.6, hexf("#E63312")
    save(render(H, C, np.ones((N, N), bool), z.cell, el=38, side=hexf("#E8E5DE")), "form_contours")


def form_block(z):
    """A desk block: a thick slab whose cut faces show sandstone strata."""
    H = 30.0 + z.H
    C = z.top_colours()
    z.apply_walls(H, C)
    st = np.array([hexf(h) for h in ("#E2B98A", "#C98E5E", "#A96F4B", "#D9A877", "#B87A52", "#EBC9A0")])
    save(render(H, C, np.ones_like(H, bool), z.cell, el=30, strata=st, strata_mm=3.0, side_dark=0.9),
         "form_block")


def hexmask(n, R):
    yy, xx = np.mgrid[0:n, 0:n] - n / 2 + 0.5
    q = np.abs(xx) / (math.sqrt(3) / 2 * R)
    return (q <= 1) & (np.abs(yy) <= R - np.abs(xx) / math.sqrt(3))


def form_hex(scenes):
    """A collection: one hexagon per race, tiling on the wall."""
    Rh = scenes[0].N / 2
    n = scenes[0].N
    wx = math.sqrt(3) * Rh + 8
    centres = [(Rh + 4, Rh + 4), (Rh + 4, Rh + 4 + wx), (Rh + 4 + 1.5 * Rh + 7, Rh + 4 + wx / 2)]
    R = int(max(cy for cy, _ in centres) + n / 2 + 10)
    Cn = int(max(cx for _, cx in centres) + n / 2 + 10)
    H = np.zeros((R, Cn)); C = np.zeros((R, Cn, 3)); P = np.zeros((R, Cn), bool)
    hm = hexmask(n, Rh - 2)
    for s, (cy, cx) in zip(scenes, centres):
        r0, c0 = int(cy - n / 2), int(cx - n / 2)
        Hs = 6.0 + s.H * 0.8
        Cs = s.top_colours()
        Hz = np.zeros((n, n)); Cz = np.zeros((n, n, 3))
        Hz[:], Cz[:] = Hs, Cs
        s.apply_walls(Hz, Cz)
        sl = (slice(r0, r0 + n), slice(c0, c0 + n))
        H[sl][hm], C[sl][hm], P[sl][hm] = Hz[hm], Cz[hm], True
    save(render(H, C, P, scenes[0].cell, el=38, side=hexf("#3C3A36")), "form_hex")


def form_triptych(legs):
    """Three panels for a triathlon, each leg at its own zoom."""
    n, F, G, CH = 170, 9, 16, 26
    R, Cn = n + 2 * F + CH, 3 * (n + 2 * F) + 2 * G
    H = np.zeros((R, Cn)); C = np.zeros((R, Cn, 3)); P = np.zeros((R, Cn), bool)
    theme = "triathlon"
    labels = {"swim": "SWIM 3.8", "bike": "BIKE 180", "run": "RUN 42.2"}
    cell = None
    for i, leg in enumerate(legs):
        s = Scene([leg], n, theme, walls=[(leg.sport, [leg])], bounds=poster.legs_bounds([leg], 15.0))
        cell = s.cell * 2.2
        x0 = i * (n + 2 * F + G)
        sl = (slice(0, R), slice(x0, x0 + n + 2 * F))
        H[sl], C[sl], P[sl] = 12.0, hexf(s.theme["frame"]), True
        Hs = np.zeros((n, n)); Cs = np.zeros((n, n, 3))
        Hs[:], Cs[:] = 4.0 + s.H * 0.55, s.top_colours()
        s.apply_walls(Hs, Cs)
        H[F:F + n, x0 + F:x0 + F + n], C[F:F + n, x0 + F:x0 + F + n] = Hs, Cs
        tm = text_mask((R, Cn), (x0 + F + n / 2, F + n + CH / 2 + 2), labels[leg.sport], 13)
        H[tm], C[tm] = 13.2, hexf("#FFFFFF")
    save(render(H, C, P, cell, el=36, unit=2), "form_triptych")


def form_lithophane(z):
    """A backlit lithophane: thin white PLA, the terrain read in light; the route glows."""
    N = z.N
    hn = (z.H - z.H.min()) / (np.ptp(z.H) + 1e-9)
    T = 0.8 + 3.2 * hn
    T[z.M["water"]] = 0.8
    rc, _ = z.route_col
    T[rc > 0] = 0.5
    T = poster._smooth(T, 1)
    light = np.exp(-1.05 * T)
    light = (light - light.min()) / (light.max() - light.min())
    warm = np.array((255, 196, 128), float)
    img = warm[None, None] * (0.05 + 0.98 * light[..., None] ** 2.2)
    S = 2
    big = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((N * S, N * S), Image.BICUBIC)
    Fp = 34
    W = N * S + 2 * Fp
    room = Image.new("RGB", (W + 160, W + 200), (18, 16, 14))
    glow = Image.new("L", room.size, 0)
    ImageDraw.Draw(glow).rectangle((80 - 20, 60 - 20, 80 + W + 20, 60 + W + 20), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(50))
    room = Image.composite(Image.new("RGB", room.size, (120, 80, 40)), room, glow)
    d = ImageDraw.Draw(room)
    d.rectangle((80, 60, 80 + W, 60 + W), fill=(44, 30, 22))
    room.paste(big, (80 + Fp, 60 + Fp))
    d.rectangle((80 + W / 2 - 90, 60 + W + 10, 80 + W / 2 + 90, 60 + W + 40), fill=(44, 30, 22))
    d.text((80 + W / 2, 60 + W + 70), "ZERMATT TRAIL RUN", font=ImageFont.truetype(FONT, 26),
           fill=(230, 190, 140), anchor="mm")
    room.convert("RGB").save(f"{HERE}/form_lithophane.jpg", quality=88, optimize=True)
    print("  wrote form_lithophane")


def main():
    only = set(sys.argv[1:])
    run = lambda k: not only or k in only
    zl = load("zermatt")
    if any(run(k) for k in ("framed", "medal", "ribbon", "island", "contours", "fins", "terraces", "block", "litho")):
        print("zermatt scenes")
    if run("framed"):
        form_framed_profile(Scene(zl, 360, "alpine_hiking"))
    if run("medal"):
        form_medal(Scene(zl, 330, "medal"))
    if run("ribbon"):
        form_ribbon(Scene(zl, 360, "alpine_hiking"))
    if run("terraces"):
        form_terraces(Scene(zl, 360, "scandi_oak"))
    if run("fins"):
        form_fins(Scene(zl, 300, "mono_dark"))
    if run("island"):
        form_island(Scene(zl, 360, "gallery"))
    if run("contours"):
        form_contours(Scene(zl, 360, "bauhaus"))
    if run("block"):
        form_block(Scene(zl, 320, "sandstone"))
    if run("litho"):
        form_lithophane(Scene(zl, 360, "classic"))
    if run("hex"):
        form_hex([Scene(zl, 230, "rams"), Scene(load("tri"), 230, "rams"), Scene(load("city"), 230, "rams")])
    if run("triptych"):
        form_triptych(load("tri"))
    print("done")


if __name__ == "__main__":
    main()
