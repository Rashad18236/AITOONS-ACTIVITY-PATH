"""Flight Path Poster core: track -> heightmap -> printable meshes."""
import csv, io, json, math, re, urllib.parse
from dataclasses import dataclass, replace
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


# Identifying User-Agent on every request: overpass-api.de answers python-requests'
# default UA with a bare 406, and it is what public-tile policies ask for anyway.
UA = {"User-Agent": "FlightPathPoster/1.0 (local single-user 3D-print tool)"}


def _get(url, timeout=20):
    for attempt in (1, 2):  # one retry, then raise (spec: 502 upstream)
        try:
            r = requests.get(url, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt == 2:
                raise


def _tile_mosaic(bounds, px_out, url_tmpl, max_zoom=12):
    """Slippy-map tiles covering bounds, stitched and cropped -> (H,W,3) uint8 RGB.

    Native tile resolution, NOT resampled to px_out — px_out only picks the zoom.
    The caller resamples: elevation must decode to float metres first, because
    bilinear on terrarium RGB is nonsense."""
    x0, y0, x1, y1 = bounds
    fit = math.ceil(math.log2(px_out * 2 * math.pi / ((x1 - x0) * 256)))  # ~1 tile px out
    z = max(1, min(max_zoom, fit))
    pxL, pyB = _tile_px(x0, y0, z)   # west, south  (bottom of image)
    pxR, pyT = _tile_px(x1, y1, z)   # east, north  (top of image)
    tx0, tx1 = int(pxL // 256), int(pxR // 256)
    ty0, ty1 = int(pyT // 256), int(pyB // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            img = Image.open(io.BytesIO(_get(url_tmpl.format(z=z, x=tx, y=ty))))
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256,
                   (tx - tx0) * 256:(tx - tx0 + 1) * 256] = np.asarray(img.convert("RGB"))
    # ponytail: integer-pixel crop (<1 tile-px misalignment), subpixel crop if seams show
    a, c = int(pxL - tx0 * 256), int(pxR - tx0 * 256)
    b, d = int(pyT - ty0 * 256), int(pyB - ty0 * 256)
    return mosaic[b:max(d, b + 2), a:max(c, a + 2)]


def fetch_elevation(bounds, px_out):
    """Terrarium mosaic for bounds, cropped and resampled to (px_out, px_out) meters."""
    elev = decode_terrarium(_tile_mosaic(bounds, px_out, TILE_URL)).astype(np.float32)
    return np.asarray(Image.fromarray(elev, "F").resize((px_out, px_out), Image.BILINEAR))


COLORS = {"frame": "#222222", "text": "#FFFFFF", "green": "#4CAF50",
          "water": "#2196F3", "snow": "#9E9E9E", "strip": "#CC2222"}

# Constant z the slot is carved down to, so the level strip seats on a flat floor
# whatever terrain it crosses. Keeps the relief plate connected under the slot;
# the slot's *depth* therefore varies with the terrain, its floor does not.
SLOT_FLOOR_MM = 1.0

# The slicer's first layer is thicker than the rest (Bambu: nozzle diameter x 50%),
# so a printable height is FIRST_LAYER_MM + n*layer_mm, not n*layer_mm.
FIRST_LAYER_MM = 0.2


def _snap(z, p, rnd=np.round):
    """Snap z onto the printable layer grid FIRST_LAYER_MM + n*layer_mm.

    `round(z / layer) * layer` was wrong: it assumes every layer is layer_mm thick,
    so with a 0.2mm first layer the whole terrain sat half a layer off every boundary
    — exactly the ragged sub-layer islands the snapping exists to prevent.
    layer_mm = 0 opts out. `rnd` is np.floor (plus an epsilon) where a hard ceiling
    is wanted instead of the nearest boundary."""
    if p.layer_mm <= 0:
        return z
    return FIRST_LAYER_MM + rnd((z - FIRST_LAYER_MM) / p.layer_mm) * p.layer_mm


def _opened(mask, k):
    """Morphological opening via PIL: erode then dilate with a k*k kernel."""
    img = Image.fromarray(mask.astype(np.uint8) * 255)
    img = img.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
    return np.asarray(img) > 0


def _closed(mask, k):
    """Morphological closing: dilate then erode — the mirror of _opened.

    Bridges gaps narrower than k, so neighbouring ridge slivers become one massif."""
    img = Image.fromarray(mask.astype(np.uint8) * 255)
    img = img.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    return np.asarray(img) > 0


# A real face, in fallback order. load_default() is a bitmap font whose strokes are
# ~1px wide at res 0.4 — masked_slab_mesh needs all four corners of a cell, so those
# glyphs mesh as slivers or vanish. No new dependency, no bundled font: use what the
# box has, and fall back to the bitmap if it has nothing.
FONT_PATHS = ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf")


def _font(px):
    for path in FONT_PATHS:
        try:
            f = ImageFont.truetype(path, px)
            f.getlength("M")   # Helvetica.ttc raises "division by zero" below ~8px
            return f
        except Exception:
            pass
    return ImageFont.load_default(size=px)


def _snow_mask(elev, p):
    """Grey caps: threshold, then close+open at the smallest printable blob width.

    Closing first merges the ridge slivers a bare threshold leaves scattered; the
    opening then drops whatever is still thinner than snow_min_mm. Opening alone
    (Task 7) kept every sliver, and cell-based slabs turned 1px slivers into dots."""
    k = max(3, int(round(p.snow_min_mm / p.res_mm)) | 1)   # odd, PIL rank filters want it
    return _opened(_closed(elev >= p.snow_line_m, k), k)


def _smooth(a, px):
    """Blur `a` by a separable box mean of radius `px` px, edges clamped.

    PIL's GaussianBlur has no mode-F path (ValueError: image has wrong mode), and
    DEM noise only needs to drop below one layer height, so a box blur it is.
    ponytail: one pass per axis; run it three times for a real gaussian if the
    box's ringing ever shows up in the print."""
    r = int(round(px))
    if r < 1:
        return a
    w = 2 * r + 1

    def rows(x):     # running mean along axis 1, over an edge-replicated pad
        c = np.cumsum(np.pad(x.astype(float), ((0, 0), (r, r)), "edge"), axis=1)
        c = np.pad(c, ((0, 0), (1, 0)))                    # leading zero: C[k]=sum(P[:k])
        return (c[:, w:] - c[:, :-w]) / w

    return rows(rows(a).T).T


# Water comes from OSM vector polygons via Overpass (free, no key): rasterised at
# the poster's own resolution it gives crisp shorelines, where a low-zoom raster
# tile gave 100m stair-steps. Two public mirrors, either one will do.
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter")
# `out geom` embeds every member way's coordinates, so no second node lookup is
# needed. Overpass does NOT clip geometry to the bbox — the rasteriser does.
OVERPASS_QL = ('[out:json][timeout:120][maxsize:536870912][bbox:{s},{w},{n},{e}];'
               '(way["natural"="water"];relation["natural"="water"];'
               'way["waterway"="riverbank"];relation["waterway"="riverbank"];);'
               'out geom;')
MIN_RING_PX2 = 9.0   # ~3x3 px: below this a lake is a printing artefact, not a lake


def _unmerc(x, y):
    """Pseudo-mercator radians -> (lon, lat) degrees."""
    return math.degrees(x), math.degrees(math.atan(math.sinh(y)))


def _stitch_rings(segs):
    """Join way fragments end-to-end into closed rings -> (rings, n_broken).

    A multipolygon relation hands out its outline as unordered, arbitrarily wound
    way fragments; only their shared endpoints say how they join. Keys are exact
    (1e-7 deg, OSM's own storage precision) — the same node is bit-identical in
    every member, so no tolerance is needed and none is wanted (a tolerance would
    fuse two lakes that happen to touch).
    ponytail: O(n^2) rescan per chain. Members per relation are tens, not
    thousands; index by endpoint key if a river network ever makes this hurt."""
    key = lambda pt: (round(pt[0] * 1e7), round(pt[1] * 1e7))
    pool = [list(s) for s in segs if len(s) >= 2]
    rings, broken = [], 0
    while pool:
        chain = pool.pop()
        grew = True
        while grew and key(chain[0]) != key(chain[-1]):
            grew = False
            for i, s in enumerate(pool):
                if key(s[0]) == key(chain[-1]):
                    chain = chain + s[1:]
                elif key(s[-1]) == key(chain[-1]):
                    chain = chain + s[-2::-1]
                elif key(s[-1]) == key(chain[0]):
                    chain = s[:-1] + chain
                elif key(s[0]) == key(chain[0]):
                    chain = s[:0:-1] + chain
                else:
                    continue
                pool.pop(i)
                grew = True
                break
        if len(chain) >= 4 and key(chain[0]) == key(chain[-1]):
            rings.append(chain)
        else:
            broken += 1
    return rings, broken


def _water_mask_from_elements(els, bounds, px_out):
    """Overpass elements -> bool (px_out, px_out) water mask, row 0 = north."""
    x0, y0, x1, y1 = bounds
    img = Image.new("L", (px_out, px_out))
    draw = ImageDraw.Draw(img)

    def paint(ring, fill):
        xy = np.array([_merc(la, lo) for la, lo in ring])
        px = np.stack([(xy[:, 0] - x0) / (x1 - x0) * px_out,
                       (y1 - xy[:, 1]) / (y1 - y0) * px_out], 1)
        a, b = px[:, 0], px[:, 1]                      # shoelace, in output pixels
        if abs(a @ np.roll(b, -1) - b @ np.roll(a, -1)) / 2 < MIN_RING_PX2:
            return                                     # pond/pool below print resolution
        draw.polygon([tuple(q) for q in px], fill=fill)  # PIL clips off-canvas itself

    def members(el, roles):
        return [[(p["lat"], p["lon"]) for p in m.get("geometry") or []]
                for m in el.get("members", ())
                if m.get("type") == "way" and m.get("role", "") in roles]

    broken = 0
    for el in els:
        if el.get("type") == "way":
            g = [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
            if len(g) >= 4 and g[0] == g[-1]:          # standalone closed way = a lake
                paint(g, 255)
        elif el.get("type") == "relation":
            outers, nb_o = _stitch_rings(members(el, ("outer", "")))
            inners, nb_i = _stitch_rings(members(el, ("inner",)))
            broken += nb_o + nb_i
            for r in outers:
                paint(r, 255)
            for r in inners:                           # islands, punched back out
                paint(r, 0)
    if broken:
        print(f"water: {broken} unclosed ring(s) in the Overpass response, skipped")
    return np.asarray(img) > 0


def fetch_water_mask(bounds, px_out):
    """OSM water polygons over bounds -> bool (px_out, px_out), row 0 = north."""
    w, s = _unmerc(bounds[0], bounds[1])
    e, n = _unmerc(bounds[2], bounds[3])
    if e - w > 4.0:   # a transoceanic track; Overpass would time out on the ocean
        print(f"water: {e - w:.1f}deg bbox is too wide for Overpass — no water drawn")
        return np.zeros((px_out, px_out), bool)
    q = OVERPASS_QL.format(s=s, w=w, n=n, e=e)
    for i, base in enumerate(OVERPASS_URLS):
        try:
            data = json.loads(_get(f"{base}?data={urllib.parse.quote(q)}", timeout=180))
            break
        except Exception as ex:
            if i == len(OVERPASS_URLS) - 1:
                raise
            print(f"water: {base} failed ({ex}) — trying mirror")
    return _water_mask_from_elements(data.get("elements", ()), bounds, px_out)


@dataclass
class Params:
    size_mm: float = 250.0
    base_mm: float = 4.0
    relief_mm: float | None = None
    exaggeration: float = 1.5
    margin_pct: float = 15.0
    frame_mm: float | None = None
    frame_height_mm: float | None = None
    groove_w_mm: float | None = None  # slot width; its depth is derived, see SLOT_FLOOR_MM
    clearance_mm: float = 0.30  # per side; FDM PLA seating margin (rasterisation ±1px + elephant-foot)
    text: str = ""
    text_mm: float | None = None
    res_mm: float = 0.4
    proud_mm: float | None = None
    cap_mm: float = 0.6      # water cap slab thickness; grey is a band, not a cap
    plate_mm: float = 2.0    # relief plate base thickness (slot floor sits above 0)
    fit_mm: float = 0.2      # gap per side between relief plate and frame ring
    snow_line_m: float = 2000.0   # grey band from this DEM elevation up
    snow_min_mm: float | None = None   # smallest printed grey blob (auto, scaled)
    layer_mm: float = 0.2    # slicer layer height; terrain snaps to it (0 = don't snap)
    smooth_px: float = 2.0   # DEM blur radius in pixels, kills sub-layer noise (0 = off)


# Visual params: None means "auto" — base value at 250mm, scaled by size, floored so
# it still prints. Everything else in Params is absolute (stiffness, FDM tolerance,
# real-world metres, printer layer height) and must not move with the poster size.
# {field: (base@250, floor)}
_SCALED = {"frame_mm": (12.0, 4.0), "relief_mm": (20.0, 5.0), "frame_height_mm": (10.0, 3.0),
           "text_mm": (8.0, 3.0), "groove_w_mm": (2.0, 1.2), "proud_mm": (1.0, 0.4),
           "snow_min_mm": (3.0, 1.5)}


def resolve(p: Params) -> Params:
    """Params with every auto (None) field filled in — the only place that happens."""
    p = replace(p, **{k: max(floor, round(base * p.size_mm / 250, 2))
                      for k, (base, floor) in _SCALED.items() if getattr(p, k) is None})
    core = p.groove_w_mm - 2 * p.clearance_mm
    if core < 0.4:   # what is left of the strip between the two clearance gaps
        raise ValueError(f"groove_w_mm ({p.groove_w_mm}mm) leaves a {core:.2f}mm strip "
                         f"core after {p.clearance_mm}mm clearance per side; needs >= 0.4mm")
    return p


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
    C, nrm = _offsets(track_px)[:2]
    half = p.groove_w_mm / 2 / p.res_mm
    L, R = C + nrm * half, C - nrm * half
    for i in range(len(C) - 1):
        d.polygon([tuple(L[i]), tuple(L[i + 1]), tuple(R[i + 1]), tuple(R[i])], fill=255)
    return np.asarray(img) > 0


def compose_parts(track, elev, lc, bounds, p):
    """Split the poster into its printable pieces, all heights in mm.

    `elev` arrives already smoothed (build_poster blurs once and shares the array
    with the snow threshold, so nothing gets blurred twice).

    frame (N,N): backplate + raised ring, flat — printed alone.
    text_mask (N,N): the glyph pixels, printed as their own white body on top of
    the ring (empty when no text was asked for).
    green/surface/water/snow/snow_cells/z_snow/track_px: the (M,M) relief plate that
    drops into the ring, its pre-slot pre-cap top, the water and grey vertex masks,
    the grey band's meshed cells and the horizontal plane it starts from, and the
    track in relief-plate pixels.
    alt_mm: flight altitude per original track point, on the same vertical scale
    as `surface`, for the path wall."""
    N, M, fpx = _grid(p)
    frame = np.full((N, N), p.base_mm)
    ring = np.ones((N, N), bool)
    ring[fpx:N - fpx, fpx:N - fpx] = False
    frame[ring] = p.base_mm + p.frame_height_mm
    text_mask = np.zeros((N, N), bool)
    if p.text:
        img = Image.new("L", (N, N))
        d = ImageDraw.Draw(img)
        # Target ink height: text_mm, but never taller than the ring band it sits on
        # (frame_mm can be smaller than text_mm), leaving 2px each side for the
        # dilation below. fpx >= 8 always (frame_mm floors at 4mm, res_mm caps at 0.5).
        px = max(min(int(p.text_mm / p.res_mm), fpx - 4), 6)
        font = _font(px)
        # Size by measured ink, not em: an em box is ~30% taller than its capitals, so
        # `px` as the em left 14px-tall glyphs whose strokes the 1px dilation below
        # fattened shut (B's counters filled). Scaling to a px-tall ink box keeps the
        # strokes wide enough that the counters survive the dilation.
        ink = font.getbbox(p.text)
        if ink[3] > ink[1]:
            px = max(round(px * px / (ink[3] - ink[1])), 6)
            font = _font(px)
            ink = font.getbbox(p.text)
        # ...then shrink again if the string is too long for the bar. TrueType glyphs
        # run ~40% wider than the bitmap this replaced, and nothing clamped the width:
        # a long callsign silently clipped off the poster edge. Fit it to the ring
        # opening, which keeps it off the corners where the side bars meet.
        avail = N - 2 * fpx
        if ink[2] - ink[0] > avail:
            font = _font(max(int(px * avail / (ink[2] - ink[0])), 6))
            ink = font.getbbox(p.text)
        h = ink[3] - ink[1]
        d.text(((N - (ink[2] - ink[0])) / 2 - ink[0], N - fpx + (fpx - h) / 2 - ink[1]),
               p.text, fill=255, font=font)
        # Dilate 1px: masked_slab_mesh only meshes cells with all four corners set, so
        # a stroke survives only where every glyph pixel is cell-interior. After a
        # MaxFilter(3) each original pixel has all 8 neighbours, i.e. four full cells.
        text_mask = np.asarray(img.filter(ImageFilter.MaxFilter(3))) > 0
    e0, e1 = float(elev.min()), float(elev.max())
    to_mm = lambda m: p.plate_mm + (m - e0) / max(e1 - e0, 1e-9) * p.relief_mm * p.exaggeration
    # Snap the terrain to whole slicer layers, before the caps and the slot are cut,
    # so those keep their exact offsets. Sub-layer DEM wobble otherwise slices into
    # scattered single-layer islands all over the flat ground.
    surface = _snap(to_mm(elev), p)
    alt_mm = to_mm(np.asarray(track, float)[:, 2])   # same scale: the flight rides the relief
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
    snow = (lc == 2) & ~gmask & border
    # Grey is a BAND, not a cap: the terrain solid is split at the horizontal plane
    # z_snow (the snow line on the relief's own scale, on a layer boundary), green
    # below it and grey above. A conformal cap surfaced as a `cap_mm / slope` stripe
    # — 0.26mm on median alpine ground, under one extrusion width — which the slicer
    # merges into the neighbouring colour and prints in transition filament.
    # Clamped to the plate so a snow line under the whole DEM cannot thin it.
    z_snow = _snap(max(to_mm(p.snow_line_m), p.plate_mm), p)
    # Cells, not vertices: the band's footprint has to be exactly what the mesher
    # meshes, or the green top drops to z_snow along a rim the grey does not cover
    # and the assembled surface gains a gash.
    snow_cells = _slab_cells(snow & (surface > z_snow))
    green = surface - p.cap_mm * water
    green[_cell_verts(snow_cells)] = z_snow
    green[gmask] = SLOT_FLOOR_MM        # full-depth slot, constant floor
    return dict(frame=frame, text_mask=text_mask, green=green, surface=surface,
                water=water, snow=snow, snow_cells=snow_cells, z_snow=z_snow,
                track_px=track_px, alt_mm=alt_mm)


def _offsets(track_px):
    """Resample the centerline to ~1 sample/pixel -> (C, unit normals, d, t), pixel space.

    d is the input points' cumulative distance and t the resampled stations, handed
    back so a caller can carry a per-point quantity (altitude) onto the same
    stations with the same np.interp — no second, drift-prone copy of this maths."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(track_px, axis=0).T))]
    t = np.linspace(0, d[-1], max(int(d[-1]), 8))
    C = np.stack([np.interp(t, d, track_px[:, 0]), np.interp(t, d, track_px[:, 1])], 1)
    tang = np.gradient(C, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-12
    return C, np.stack([-tang[:, 1], tang[:, 0]], 1), d, t


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


def _unpinch(cells):
    """Drop cells that meet another only at a corner.

    Two diagonal cells with neither shared orthogonal neighbour present pinch at
    one vertex; the vertical wall edge there ends up in four wall quads instead of
    two, and the slab is not watertight. Dropping one cell of each pair is the only
    fix that cannot grow the cap into the groove — filling the notch could, and a
    cap slab over the groove fights the strip.
    ponytail: a 1px diagonal staircase decimates to isolated cells. The masks are
    already speckle-opened upstream, so this bites nothing real; duplicate the
    pinch vertex per connected component instead if a cap ever visibly frays."""
    while True:
        a = cells[:-1, :-1] & cells[1:, 1:] & ~cells[:-1, 1:] & ~cells[1:, :-1]
        b = cells[:-1, 1:] & cells[1:, :-1] & ~cells[:-1, :-1] & ~cells[1:, 1:]
        if not (a.any() or b.any()):
            return cells
        cells = cells.copy()
        cells[1:, 1:] &= ~a
        cells[1:, :-1] &= ~b


def _slab_cells(mask):
    """Cells a slab over `mask` actually meshes: all four corners set, pinches dropped."""
    return _unpinch(mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:])


def _cell_verts(cells):
    """The (H,W) vertex footprint of an (H-1,W-1) cell mask."""
    v = np.zeros(np.array(cells.shape) + 1, bool)
    for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
        v[dr:dr + cells.shape[0], dc:dc + cells.shape[1]] |= cells
    return v


def masked_slab_mesh(mask, top, thickness, res_mm):
    """Constant-thickness slab over masked cells; top follows `top` surface."""
    return _slab_mesh(_slab_cells(mask), top, top - thickness, res_mm)


def band_mesh(parts, p):
    """Grey elevation band: solid from the flat z_snow plane up to the terrain surface."""
    return _slab_mesh(parts["snow_cells"], parts["surface"],
                      np.full_like(parts["surface"], parts["z_snow"]), p.res_mm)


def _slab_mesh(cells, top, bot, res_mm):
    """Watertight solid over `cells`, between the (H,W) vertex surfaces `bot` and `top`."""
    H, W = top.shape
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
    vb = vt.copy(); vb[:, 2] = bot[vy, vx]
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


def strip_mesh(track_px, alt_mm, surface, p):
    """Altitude-following wall: constant width, swept along the track from the flat
    slot floor up to the flight altitude, clamped to proud of the terrain below it.

    `alt_mm` is per original track point (compose_parts' own scale) and is resampled
    onto the same arc-length stations as the centerline. Where the aircraft flew
    below the terrain the poster shows (or the altitude is a missing 0), the clamp
    takes over and the wall rides terrain + proud_mm — it never sinks into the relief.

    The wall is capped at the relief's own ceiling (a full-scale peak plus proud_mm):
    an airliner at 12000m over 500m terrain maps to a 722mm wall, which is not a
    poster. Above the ceiling the flight simply rides a level line over the highest
    ground the relief can show."""
    C, nrm, d, t = _offsets(track_px)  # same centerline _groove_mask() carved the slot from
    n = len(C)
    cx, cy = C[:, 0], C[:, 1]
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm  # px
    H, W = surface.shape
    # ponytail: nearest-neighbour surface sampling; bilinear if the top looks off
    zc = surface[np.clip(cy.round().astype(int), 0, H - 1),
                 np.clip(cx.round().astype(int), 0, W - 1)]
    alt = np.interp(t, d, np.asarray(alt_mm, float))   # altitude onto the same stations
    ceiling = p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm
    # a layer-aligned cap keeps the snap below it (round is monotone); floor, never
    # round, or the cap itself would land above the relief's own ceiling
    ceiling = float(_snap(ceiling, p, lambda x: np.floor(x + 1e-6)))
    if (over := alt > ceiling).any():
        print(f"path: flight above the relief ceiling on {over.mean() * 100:.0f}% of the "
              f"track — wall capped at {ceiling:.2f}mm")
    z_top = _snap(np.minimum(np.maximum(alt, zc + p.proud_mm), ceiling), p)
    z_bot = SLOT_FLOOR_MM
    L, R = C + nrm * half, C - nrm * half

    def mm(q, z):
        return np.stack([q[:, 0] * p.res_mm, (H - 1 - q[:, 1]) * p.res_mm,
                         np.broadcast_to(z, (len(q),)).astype(float)], 1)

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
    """Track -> (frame_bodies, relief_bodies, path_strip_stl).

    Both body lists are [(mesh, name, hex_colour, extruder_slot), ...] for write_3mf."""
    p = resolve(p)   # auto (None) visual params -> concrete mm; everything below is mm
    # ponytail: reject rather than clamp — a typo'd 2500mm is a mistake to surface,
    # not to silently honour, and N^2 grids OOM the box. Raise the cap if a bigger
    # plate ever shows up.
    if p.size_mm > 256 or p.res_mm < 0.2:
        raise ValueError("size_mm must be <= 256 (plate limit) and res_mm >= 0.2")
    for label, v in (("slot floor", SLOT_FLOOR_MM), ("water cap", p.cap_mm)):
        if p.plate_mm <= v:   # slot floor above the plate top / caps push terrain negative
            raise ValueError(f"{label} ({v}mm) must be less than the relief plate "
                             f"thickness ({p.plate_mm}mm)")
    bounds = track_bounds(track, p.margin_pct)
    M = _grid(p)[1]
    # smoothed once here and shared: the snow threshold and the relief surface must
    # see the same terrain, and blurring twice would wash the mountains out
    elev = _smooth(fetch_elevation(bounds, M), p.smooth_px)
    lc = np.zeros((M, M), np.uint8)
    lc[_snow_mask(elev, p)] = 2
    try:   # water last: high Alpine lakes sit above the snow line and stay blue
        lc[fetch_water_mask(bounds, M)] = 1
    except Exception as e:
        print(f"water: Overpass unavailable ({e}) — poster without water")
    parts = compose_parts(track, elev, lc, bounds, p)
    bodies = [(heightmap_mesh(parts["green"], p.res_mm), "terrain", COLORS["green"], 1)]
    # water stays a conformal cap (lakes are flat, so its slices are lake-wide anyway);
    # grey is a band standing on the z_snow plane, which green's top is clamped to
    for name, slot, m in (("water", 2, masked_slab_mesh(parts["water"], parts["surface"],
                                                        p.cap_mm, p.res_mm)),
                          ("snow", 3, band_mesh(parts, p))):
        if m is not None:
            bodies.append((m, name, COLORS[name], slot))
    frame_bodies = [(heightmap_mesh(parts["frame"], p.res_mm), "frame", COLORS["frame"], 1)]
    # text is its own white body standing 0.8mm proud of the ring, printed in slot 2
    text = masked_slab_mesh(parts["text_mask"], parts["frame"] + 0.8, 0.8, p.res_mm)
    if text is not None:
        frame_bodies.append((text, "text", COLORS["text"], 2))
    strip = strip_mesh(parts["track_px"], parts["alt_mm"], parts["surface"], p)
    return frame_bodies, bodies, strip.export(file_type="stl")


def write_3mf(bodies):
    """[(mesh, name, "#RRGGBB", extruder_slot), ...] -> 3MF zip bytes.

    ONE build item: the bodies are components of a single container object, the
    standard 3MF/Bambu multi-part form. One <item> per body made Bambu Studio treat
    them as N independent models, drop each to the bed and auto-arrange — which
    destroys the co-registration every body is meshed to share.
    Per-body <basematerials> stay for the display colour in non-Bambu viewers;
    the filament slots live in Bambu's Metadata/model_settings.config, per <part>
    (the old object-level extruder key left the slots unassigned). Written by hand:
    trimesh's 3MF support is export-only via lib3mf and carries neither."""
    import zipfile
    assert len(bodies) < 100, "basematerials ids are oid+100 — they'd collide"
    # ponytail: f-string per vertex/triangle — ~2M lines and a few seconds at default
    # res. Swap in np.savetxt or a binary extension only if generation time hurts.
    objs, comps, parts = [], [], []
    for oid, (m, name, color, slot) in enumerate(bodies, 1):
        vs = "".join(f'<vertex x="{v[0]:.3f}" y="{v[1]:.3f}" z="{v[2]:.3f}"/>' for v in m.vertices)
        ts = "".join(f'<triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}"/>' for f in m.faces)
        objs.append(
            f'<basematerials id="{oid + 100}"><base name="{name}" displaycolor="{color}FF"/></basematerials>'
            f'<object id="{oid}" name="{name}" type="model" pid="{oid + 100}" pindex="0">'
            f'<mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
        # identity transform: the bodies are already meshed in one shared world frame
        comps.append(f'<component objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
        parts.append(f'<part id="{oid}" subtype="normal_part">'
                     f'<metadata key="name" value="{name}"/>'
                     f'<metadata key="extruder" value="{slot}"/></part>')
    cid = len(bodies) + 1
    top = bodies[0][1] if bodies else "model"
    objs.append(f'<object id="{cid}" name="{top}" type="model">'
                f'<components>{"".join(comps)}</components></object>')
    cfg = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
           f'<object id="{cid}"><metadata key="name" value="{top}"/>{"".join(parts)}</object>\n'
           '</config>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources>{"".join(objs)}</resources>'
             f'<build><item objectid="{cid}" printable="1"/></build></model>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            '<Default Extension="config" ContentType="text/xml"/></Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", cfg)
    return buf.getvalue()


def read_3mf(data):
    """3MF bytes -> [(name, (V,3) vertices, (F,3) triangles), ...], build order.

    Reads what write_3mf writes, for tests and check_output.py."""
    import zipfile
    # ponytail: split over XML — we generated it, single namespace, objects don't nest.
    # The mesh-less container object write_3mf appends has no <vertices> and drops out.
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("3D/3dmodel.model").decode()
    out = []
    for chunk in xml.split("<object ")[1:]:
        obj = chunk.split("</object>", 1)[0]
        name = re.search(r'name="([^"]*)"', obj)
        vs = re.search(r"<vertices>(.*?)</vertices>", obj, re.S)
        ts = re.search(r"<triangles>(.*?)</triangles>", obj, re.S)
        if not (name and vs and ts):
            continue
        V = np.array(re.findall(r'x="([^"]+)" y="([^"]+)" z="([^"]+)"', vs.group(1)), float)
        F = np.array(re.findall(r'v1="(\d+)" v2="(\d+)" v3="(\d+)"', ts.group(1)), int)
        out.append((name.group(1), V, F))
    return out
