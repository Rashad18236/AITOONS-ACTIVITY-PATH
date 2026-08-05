"""Flight Path Poster core: track -> heightmap -> printable meshes."""
import csv, io, math, re
from dataclasses import dataclass
import numpy as np
import requests
import trimesh
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def parse_track(name: str, data: bytes) -> np.ndarray:
    """Return (N,3) array of lat, lon, alt_m from FR24 KML or CSV export."""
    text = data.decode("utf-8", "replace")
    pts = _parse_kml(text) if name.lower().endswith(".kml") else _parse_csv(text)
    t = np.array(pts, dtype=float).reshape(-1, 3)
    if len(t) > 1:  # drop repeated fixes at the same position (parked aircraft)
        t = t[np.r_[True, np.any(np.diff(t[:, :2], axis=0), axis=1)]]
    if len(t) < 2:
        raise ValueError("No track points found — is this a FlightRadar24 KML/CSV export?")
    return t


def _parse_kml(text):
    # ponytail: regex over XML — FR24 exports are machine-generated, fine here
    pts = [(float(la), float(lo), float(al)) for lo, la, al in
           re.findall(r"<gx:coord>([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)</gx:coord>", text)]
    if pts:
        return pts
    # plain <coordinates> fallback: "lon,lat,alt lon,lat,alt ...". FR24 GA exports hold
    # the same flight up to three times over, so pick ONE representation, never concatenate.
    blocks = [[(float(p[1]), float(p[0]), float(p[2]) if len(p) > 2 else 0.0)
               for p in (t.split(",") for t in block.split()) if len(p) >= 2]
              for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, re.S)]
    biggest = max(blocks, key=len, default=[])
    if len(biggest) >= 10:
        return biggest  # 1. classic single-LineString track (ignores 2-point Route lines)
    twos = [b for b in blocks if len(b) == 2]
    if len(twos) >= 10:
        # 2. Trail folder: many 2-point segments, each starting where the last ended and
        # carrying real altitudes. Keep the longest chain; unchained bits are Route lines.
        chains, cur = [], []
        for a, b in twos:
            if cur and abs(cur[-1][0] - a[0]) < 1e-9 and abs(cur[-1][1] - a[1]) < 1e-9:
                cur.append(b)
            else:
                cur = [a, b]
                chains.append(cur)
        return max(chains, key=len)
    return [p for b in blocks for p in b]  # 3. tiny hand-made file: take everything


def _parse_csv(text):
    pts = []
    for row in csv.DictReader(io.StringIO(text)):
        pos = row.get("Position") or ""
        if "," in pos:
            lat, lon = map(float, pos.split(","))
            pts.append((lat, lon, float(row.get("Altitude") or 0) * 0.3048))
    return pts


TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def _merc(lat, lon):
    """Pseudo-mercator in radians: x,y each in [-pi, pi]."""
    return math.radians(lon), math.asinh(math.tan(math.radians(lat)))


def track_bounds(track, margin_pct):
    xy = [_merc(la, lo) for la, lo, _ in track]
    xs, ys = zip(*xy)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    m = margin_pct / 100 * max(x1 - x0, y1 - y0)
    x0, x1, y0, y1 = x0 - m, x1 + m, y0 - m, y1 + m
    side = max(x1 - x0, y1 - y0)  # expand to square, centered
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def decode_terrarium(rgb):
    r, g, b = (rgb[..., i].astype(float) for i in range(3))
    return r * 256 + g + b / 256 - 32768


def _tile_px(x, y, z):
    """Pseudo-mercator point -> global pixel coords at zoom z (py grows southward)."""
    n = (1 << z) * 256
    return (x + math.pi) / (2 * math.pi) * n, (math.pi - y) / (2 * math.pi) * n


def _get(url):
    for attempt in (1, 2):  # one retry, then raise (spec: 502 upstream)
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt == 2:
                raise


def fetch_elevation(bounds, px_out):
    """Terrarium mosaic for bounds, cropped and resampled to (px_out, px_out) meters."""
    x0, y0, x1, y1 = bounds
    z = min(12, max(1, math.ceil(math.log2(px_out * 2 * math.pi / ((x1 - x0) * 256)))))
    pxL, pyB = _tile_px(x0, y0, z)   # west, south  (bottom of image)
    pxR, pyT = _tile_px(x1, y1, z)   # east, north  (top of image)
    tx0, tx1 = int(pxL // 256), int(pxR // 256)
    ty0, ty1 = int(pyT // 256), int(pyB // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            img = Image.open(io.BytesIO(_get(TILE_URL.format(z=z, x=tx, y=ty))))
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256,
                   (tx - tx0) * 256:(tx - tx0 + 1) * 256] = np.asarray(img.convert("RGB"))
    elev = decode_terrarium(mosaic)
    # ponytail: integer-pixel crop (<1 tile-px misalignment), subpixel crop if seams show
    a, c = int(pxL - tx0 * 256), int(pxR - tx0 * 256)
    b, d = int(pyT - ty0 * 256), int(pyB - ty0 * 256)
    crop = elev[b:max(d, b + 2), a:max(c, a + 2)].astype(np.float32)
    return np.asarray(Image.fromarray(crop, "F").resize((px_out, px_out), Image.BILINEAR))


WMS_URL = ("https://services.terrascope.be/wms/v2?SERVICE=WMS&VERSION=1.3.0"
           "&REQUEST=GetMap&LAYERS=WORLDCOVER_2021_MAP&STYLES=&FORMAT=image/png"
           "&CRS=EPSG:3857&BBOX={x0},{y0},{x1},{y1}&WIDTH={w}&HEIGHT={h}")
COLORS = {"frame": "#222222", "green": "#4CAF50", "water": "#2196F3",
          "city": "#9E9E9E", "strip": "#CC2222"}
_R3857 = 6378137.0


def _opened(mask, k):
    """Morphological opening via PIL: erode then dilate with a k*k kernel."""
    img = Image.fromarray(mask.astype(np.uint8) * 255)
    img = img.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
    return np.asarray(img) > 0


def classify_landcover(rgb, km_per_px, city_min_km):
    """WorldCover RGB -> codes: 0 green, 1 water, 2 big-city."""
    def near(target):
        return (np.abs(rgb.astype(int) - target).max(axis=2) <= 10)
    water = _opened(near((0, 100, 200)), 3)                     # drop 1px speckle
    k = max(3, int(round(city_min_km / km_per_px)) | 1)         # odd, >=3
    city = _opened(near((250, 0, 0)), k)                        # villages vanish
    lc = np.zeros(rgb.shape[:2], np.uint8)
    lc[water] = 1
    lc[city & ~water] = 2
    return lc


def fetch_landcover(bounds, px_out, km_per_px, city_min_km):
    """WorldCover land-cover codes for bounds, (px_out, px_out), row 0 = north."""
    x0, y0, x1, y1 = (v * _R3857 for v in bounds)   # merc radians -> EPSG:3857 meters
    url = WMS_URL.format(x0=x0, y0=y0, x1=x1, y1=y1, w=px_out, h=px_out)
    img = Image.open(io.BytesIO(_get(url))).convert("RGB")
    return classify_landcover(np.asarray(img), km_per_px, city_min_km)


@dataclass
class Params:
    size_mm: float = 250.0
    base_mm: float = 4.0
    relief_mm: float = 20.0
    exaggeration: float = 1.5
    margin_pct: float = 15.0
    frame_mm: float = 12.0
    frame_height_mm: float = 10.0
    groove_w_mm: float = 2.0
    groove_d_mm: float = 1.5
    clearance_mm: float = 0.30  # per side; FDM PLA seating margin (rasterisation ±1px + elephant-foot)
    text: str = ""
    text_mm: float = 8.0
    res_mm: float = 0.4
    proud_mm: float = 1.0
    cap_mm: float = 0.6      # colour-cap slab thickness
    plate_mm: float = 2.0    # relief plate base thickness (groove floor sits above 0)
    fit_mm: float = 0.2      # gap per side between relief plate and frame ring
    city_min_km: float = 1.5


def _grid(p):
    """(N, M, fpx): full grid px, relief-plate grid px, frame ring width px.

    The fit gap is rounded UP to a whole pixel. int((frame_mm + fit_mm) / res_mm)
    truncates a 0.2mm gap to zero at every sane resolution (0.2-0.5mm), and the
    relief plate then comes out exactly the size of the ring opening — an
    interference fit no FDM printer wins. Rounding up errs loose, which glues."""
    N = int(p.size_mm / p.res_mm)
    fpx = int(p.frame_mm / p.res_mm)
    return N, N - 2 * (fpx + math.ceil(p.fit_mm / p.res_mm)), fpx


def _groove_mask(track_px, shape, p):
    """Boolean groove footprint on a (H,W) grid, from the strip's own offset geometry.

    line(width=) is not a constant perpendicular width (1.42mm at 45° for a nominal
    2.0mm), so the strip would not seat. Per-segment quads, not one ribbon polygon —
    a single polygon even-odd fills leaves holes where the track hairpins over itself."""
    H, W = shape
    img = Image.new("L", (W, H))
    d = ImageDraw.Draw(img)
    C, nrm = _offsets(track_px)
    half = p.groove_w_mm / 2 / p.res_mm
    L, R = C + nrm * half, C - nrm * half
    for i in range(len(C) - 1):
        d.polygon([tuple(L[i]), tuple(L[i + 1]), tuple(R[i + 1]), tuple(R[i])], fill=255)
    return np.asarray(img) > 0


def compose_parts(track, elev, lc, bounds, p):
    """Split the poster into its printable pieces, all heights in mm.

    frame (N,N): backplate + raised ring + embossed text — printed alone.
    green/surface/water/city/track_px: the (M,M) relief plate that drops into the
    ring, its pre-groove pre-cap top, the two colour-cap vertex masks, and the
    track in relief-plate pixels."""
    N, M, fpx = _grid(p)
    frame = np.full((N, N), p.base_mm)
    ring = np.ones((N, N), bool)
    ring[fpx:N - fpx, fpx:N - fpx] = False
    frame[ring] = p.base_mm + p.frame_height_mm
    if p.text:
        img = Image.new("L", (N, N))
        d = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=max(int(p.text_mm / p.res_mm), 6))
        w = d.textlength(p.text, font=font)
        d.text(((N - w) / 2, N - fpx + (fpx - p.text_mm / p.res_mm) / 2),
               p.text, fill=255, font=font)
        frame[np.asarray(img) > 0] += 0.8  # emboss height, mm
    e0, e1 = float(elev.min()), float(elev.max())
    surface = p.plate_mm + (elev - e0) / max(e1 - e0, 1e-9) * p.relief_mm * p.exaggeration
    # project track into relief-plate pixels (row 0 = north)
    x0, y0, x1, y1 = bounds
    xy = np.array([_merc(la, lo) for la, lo, _ in track])
    track_px = np.stack([(xy[:, 0] - x0) / (x1 - x0) * M,
                         (y1 - xy[:, 1]) / (y1 - y0) * M], 1)
    gmask = _groove_mask(track_px, (M, M), p)
    # caps are separate slabs: keep them off the groove (the strip goes there) and off
    # the outer vertex ring, where a slab wall would hang over the plate edge.
    border = np.zeros((M, M), bool)
    border[1:-1, 1:-1] = True
    water = (lc == 1) & ~gmask & border
    city = (lc == 2) & ~gmask & border
    green = surface - p.cap_mm * (water | city)
    green[gmask] -= p.groove_d_mm
    return dict(frame=frame, green=green, surface=surface,
                water=water, city=city, track_px=track_px)


def _offsets(track_px):
    """Resample the centerline to ~1 sample/pixel -> (C, unit normals), pixel space."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(track_px, axis=0).T))]
    t = np.linspace(0, d[-1], max(int(d[-1]), 8))
    C = np.stack([np.interp(t, d, track_px[:, 0]), np.interp(t, d, track_px[:, 1])], 1)
    tang = np.gradient(C, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-12
    return C, np.stack([-tang[:, 1], tang[:, 0]], 1)


def _grid_faces(idx):
    a = idx[:-1, :-1].ravel(); b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel(); d = idx[1:, :-1].ravel()
    return np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])


def heightmap_mesh(hm, res_mm):
    """Watertight solid: heightmap top, vertical walls, flat back at z=0."""
    H, W = hm.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    top = np.stack([xx * res_mm, (H - 1 - yy) * res_mm, hm], -1).reshape(-1, 3)
    idx = np.arange(H * W).reshape(H, W)
    # boundary loop, no repeated corners: north edge E, east edge S, south W, west N
    ring = np.concatenate([idx[0], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
    bot = top[ring].copy(); bot[:, 2] = 0.0   # back only needs the boundary ring
    V = np.vstack([top, bot])
    b = H * W + np.arange(len(ring))
    t0, t1, b0, b1 = ring, np.roll(ring, -1), b, np.roll(b, -1)
    faces = [_grid_faces(idx)[:, ::-1],       # top winds CCW seen from +z (reversed)
             np.stack([t0, t1, b1], 1), np.stack([t0, b1, b0], 1)]   # walls
    # flat back: one fan off b[0] instead of a full-resolution grid (half the STL)
    faces.append(np.stack([np.full(len(b) - 2, b[0]), b[1:-1], b[2:]], 1))
    return trimesh.Trimesh(V, np.vstack(faces), process=False)


def masked_slab_mesh(mask, top, thickness, res_mm):
    """Constant-thickness slab over masked cells; top follows `top` surface."""
    H, W = top.shape
    cells = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    rc = np.argwhere(cells)
    if not len(rc):
        return None
    used = np.zeros((H, W), bool)
    for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
        used[rc[:, 0] + dr, rc[:, 1] + dc] = True
    idx = -np.ones((H, W), int)
    vy, vx = np.where(used)
    idx[vy, vx] = np.arange(len(vy))
    n = len(vy)
    vt = np.stack([vx * res_mm, (H - 1 - vy) * res_mm, top[vy, vx]], 1)
    vb = vt.copy(); vb[:, 2] -= thickness
    F = []
    # ponytail: python loop over cells, vectorize if generation time hurts
    incell = lambda r, c: 0 <= r < H - 1 and 0 <= c < W - 1 and cells[r, c]
    for r, c in rc:
        a, b, d, e = idx[r, c], idx[r, c + 1], idx[r + 1, c + 1], idx[r + 1, c]
        F += [[d, b, a], [e, d, a]]                     # top, +z
        F += [[a + n, b + n, d + n], [a + n, d + n, e + n]]  # bottom, -z
        # wall edge order is the reverse of the top face's edge, so the two agree
        for (nr, nc, v0, v1) in ((r - 1, c, a, b), (r + 1, c, d, e),
                                 (r, c - 1, e, a), (r, c + 1, b, d)):
            if not incell(nr, nc):                       # boundary edge -> wall
                F += [[v0, v1, v1 + n], [v0, v1 + n, v0 + n]]
    return trimesh.Trimesh(np.vstack([vt, vb]), np.array(F), process=False)


def strip_mesh(track_px, surface, p):
    """Constant-thickness ribbon that seats in the groove and stands proud."""
    C, nrm = _offsets(track_px)  # same centerline _groove_mask() carved the groove from
    n = len(C)
    cx, cy = C[:, 0], C[:, 1]
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm  # px
    H, W = surface.shape
    # ponytail: nearest-neighbour surface sampling; bilinear if strip shows steps
    zc = surface[np.clip(cy.round().astype(int), 0, H - 1),
                 np.clip(cx.round().astype(int), 0, W - 1)]
    z_top, z_bot = zc + p.proud_mm, zc - p.groove_d_mm
    L, R = C + nrm * half, C - nrm * half

    def mm(q, z):
        return np.stack([q[:, 0] * p.res_mm, (H - 1 - q[:, 1]) * p.res_mm, z], 1)

    V = np.vstack([mm(L, z_bot), mm(R, z_bot), mm(R, z_top), mm(L, z_top)])
    f = []
    for k in range(4):  # 4 sides of the swept rectangle
        a = np.arange(n - 1) + k * n
        c = np.arange(n - 1) + ((k + 1) % 4) * n
        f.append(np.stack([a, a + 1, c + 1], 1))
        f.append(np.stack([a, c + 1, c], 1))
    e = n - 1
    f.append(np.array([[0, n, 2 * n], [0, 2 * n, 3 * n],
                       [e, e + 2 * n, e + n], [e, e + 3 * n, e + 2 * n]]))
    # mm() flips y, so the whole ring winds inward — reverse every face once
    return trimesh.Trimesh(V, np.vstack(f)[:, ::-1], process=False)


def build_poster(track, p=Params()):
    """Track -> (frame_stl, [(mesh, name, hex_colour, slot), ...], path_strip_stl)."""
    # ponytail: reject rather than clamp — a typo'd 2500mm is a mistake to surface,
    # not to silently honour, and N^2 grids OOM the box. Raise the cap if a bigger
    # plate ever shows up.
    if p.size_mm > 256 or p.res_mm < 0.2:
        raise ValueError("size_mm must be <= 256 (plate limit) and res_mm >= 0.2")
    if p.plate_mm <= p.groove_d_mm:
        raise ValueError("plate_mm must exceed groove_d_mm — the groove would cut through")
    bounds = track_bounds(track, p.margin_pct)
    M = _grid(p)[1]
    # mercator x-span is ground distance only at the equator; scale by cos(mid-lat)
    km_per_px = ((bounds[2] - bounds[0]) * _R3857 / 1000 / M
                 * math.cos(math.radians(float(np.mean(track[:, 0])))))
    elev = fetch_elevation(bounds, M)
    lc = fetch_landcover(bounds, M, km_per_px, p.city_min_km)
    parts = compose_parts(track, elev, lc, bounds, p)
    bodies = [(heightmap_mesh(parts["green"], p.res_mm), "terrain", COLORS["green"], 1)]
    for key, name, slot in (("water", "water", 2), ("city", "cities", 3)):
        cap = masked_slab_mesh(parts[key], parts["surface"], p.cap_mm, p.res_mm)
        if cap is not None:
            bodies.append((cap, name, COLORS[key], slot))
    strip = strip_mesh(parts["track_px"], parts["surface"], p)
    return (heightmap_mesh(parts["frame"], p.res_mm).export(file_type="stl"),
            bodies, strip.export(file_type="stl"))
