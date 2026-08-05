"""Flight Path Poster core: track -> heightmap -> printable meshes."""
import csv, io, math, re
from dataclasses import dataclass
import numpy as np
import requests
import trimesh
from PIL import Image, ImageDraw, ImageFont


def parse_track(name: str, data: bytes) -> np.ndarray:
    """Return (N,3) array of lat, lon, alt_m from FR24 KML or CSV export."""
    text = data.decode("utf-8", "replace")
    pts = _parse_kml(text) if name.lower().endswith(".kml") else _parse_csv(text)
    if len(pts) < 2:
        raise ValueError("No track points found — is this a FlightRadar24 KML/CSV export?")
    return np.array(pts, dtype=float)


def _parse_kml(text):
    # ponytail: regex over XML — FR24 exports are machine-generated, fine here
    pts = [(float(la), float(lo), float(al)) for lo, la, al in
           re.findall(r"<gx:coord>([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)</gx:coord>", text)]
    if not pts:  # plain LineString fallback: "lon,lat,alt lon,lat,alt ..."
        for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, re.S):
            for triple in block.split():
                p = triple.split(",")
                if len(p) >= 2:
                    pts.append((float(p[1]), float(p[0]),
                                float(p[2]) if len(p) > 2 else 0.0))
    return pts


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
    clearance_mm: float = 0.15
    text: str = ""
    text_mm: float = 8.0
    res_mm: float = 0.4
    proud_mm: float = 1.0


def compose(track, elev, bounds, p):
    """One (N,N) heightmap in mm: terrain + frame + text, then groove carved.

    Returns (hm, surface_before_groove, track_px)."""
    N = int(p.size_mm / p.res_mm)
    fpx = int(p.frame_mm / p.res_mm)
    hm = np.full((N, N), p.base_mm)
    e0, e1 = float(elev.min()), float(elev.max())
    hm[fpx:N - fpx, fpx:N - fpx] += (elev - e0) / max(e1 - e0, 1e-9) \
        * p.relief_mm * p.exaggeration
    ring = np.ones((N, N), bool)
    ring[fpx:N - fpx, fpx:N - fpx] = False
    hm[ring] = p.base_mm + p.frame_height_mm
    if p.text:
        img = Image.new("L", (N, N))
        d = ImageDraw.Draw(img)
        font = ImageFont.load_default(size=max(int(p.text_mm / p.res_mm), 6))
        w = d.textlength(p.text, font=font)
        d.text(((N - w) / 2, N - fpx + (fpx - p.text_mm / p.res_mm) / 2),
               p.text, fill=255, font=font)
        hm[np.asarray(img) > 0] += 0.8  # emboss height, mm
    # project track into heightmap pixels (row 0 = north)
    x0, y0, x1, y1 = bounds
    inner = N - 2 * fpx
    xy = np.array([_merc(la, lo) for la, lo, _ in track])
    tx = (xy[:, 0] - x0) / (x1 - x0) * inner + fpx
    ty = (y1 - xy[:, 1]) / (y1 - y0) * inner + fpx
    track_px = np.stack([tx, ty], 1)
    surface = hm.copy()
    img = Image.new("L", (N, N))
    d = ImageDraw.Draw(img)
    # carve the groove from the strip's own offset geometry: line(width=) is not a
    # constant perpendicular width (1.42mm at 45° for a nominal 2.0mm), so the strip
    # would not seat. Per-segment quads, not one ribbon polygon — a single polygon
    # even-odd fills leaves holes where the track hairpins back over itself.
    C, nrm = _offsets(track_px)
    L, R = C + nrm * (p.groove_w_mm / 2 / p.res_mm), C - nrm * (p.groove_w_mm / 2 / p.res_mm)
    for i in range(len(C) - 1):
        d.polygon([tuple(L[i]), tuple(L[i + 1]), tuple(R[i + 1]), tuple(R[i])], fill=255)
    hm[np.asarray(img) > 0] -= p.groove_d_mm
    return hm, surface, track_px


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
    bot = top.copy(); bot[:, 2] = 0.0
    V = np.vstack([top, bot])
    idx = np.arange(H * W).reshape(H, W)
    # top winds CCW seen from +z (reversed), back keeps grid order so it faces -z
    faces = [_grid_faces(idx)[:, ::-1], _grid_faces(idx + H * W)]
    for edge in (idx[0], idx[:, -1], idx[-1][::-1], idx[:, 0][::-1]):  # boundary loop
        t0, t1 = edge[:-1], edge[1:]
        faces.append(np.stack([t0, t1, t1 + H * W], 1))
        faces.append(np.stack([t0, t1 + H * W, t0 + H * W], 1))
    return trimesh.Trimesh(V, np.vstack(faces), process=False)


def strip_mesh(track_px, surface, p):
    """Constant-thickness ribbon that seats in the groove and stands proud."""
    C, nrm = _offsets(track_px)  # same centerline compose() carved the groove from
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
    """Track -> (poster_stl_bytes, path_strip_stl_bytes)."""
    bounds = track_bounds(track, p.margin_pct)
    N = int(p.size_mm / p.res_mm)
    fpx = int(p.frame_mm / p.res_mm)
    elev = fetch_elevation(bounds, N - 2 * fpx)
    hm, surface, track_px = compose(track, elev, bounds, p)
    poster_m = heightmap_mesh(hm, p.res_mm)
    strip_m = strip_mesh(track_px, surface, p)
    return (poster_m.export(file_type="stl"), strip_m.export(file_type="stl"))
