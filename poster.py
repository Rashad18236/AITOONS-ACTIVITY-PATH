"""Activity Path Poster core: activity -> heightmap -> printable meshes."""
import csv, functools, io, json, math, re, urllib.parse
from dataclasses import dataclass, replace
from pathlib import Path
import numpy as np
import requests
import trimesh
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import activity


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
UA = {"User-Agent": "ActivityPathPoster/1.0 (local single-user 3D-print tool)"}


def _get(url, timeout=20, tries=2):
    for attempt in range(1, tries + 1):  # tiles: one retry, then raise (spec: 502 upstream)
        try:
            r = requests.get(url, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt == tries:
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
# Runways and main roads share the grey band's colour and AMS slot 3 — no new spool.
COLORS["roads"] = COLORS["snow"]

# Grey roads, picked by zoom. A class is drawn while the poster's ground scale
# (m per printed mm) is at most its limit, finest first: Blackpool at 36.7 m/mm gets
# tertiary and up (~8.5% of the plate) plus 0.3% runway; residential would add 15%
# and read as a grey block. No _link roads, taxiways or aprons.
ROAD_MM = 1.2       # printed road width: 3 extrusions, clear of the 0.84 colour floor (print-settings.md section 3)
ROAD_TIERS = (("tertiary", 60), ("secondary", 150), ("primary", 400),
              ("trunk", 1200), ("motorway", 3000))
ROAD_MAX_FRAC = 0.15   # grey plate fraction above which the finest class is dropped
RUNWAY_M = 45.0        # OSM aeroway=runway without a usable width tag

# The relief ceiling spans the terrain range, or the flight's height over the lowest
# ground clipped to this (m), whichever is larger. See compose_parts.
FLIGHT_SPAN_M = (300.0, 1000.0)

# Constant z the slot is carved down to, so the level strip seats on a flat floor
# whatever terrain it crosses. Keeps the relief plate connected under the slot;
# the slot's *depth* therefore varies with the terrain, its floor does not.
# 1.16 = 0.2 + 4*0.24 (see _snap). Not 0.92, the boundary nearer the old 1.0: 0.92 -
# SLOT_CAP_MM leaves only 0.44mm of green under the cap in the slot.
SLOT_FLOOR_MM = 1.16
# Water/road caps drape down into the slot instead of stopping at its edge, so the
# slot walls and floor are blue over the sea and grey on a road, not a green rim.
# 2 layers, not cap_mm's 4: 1.16 - 0.96 would leave only the 0.2mm first layer green,
# while 1.16 - 0.48 = 0.68 = 0.2 + 2*0.24 keeps the green under it on the layer grid.
SLOT_CAP_MM = 0.48

# The slicer's first layer is thicker than the rest (Bambu: nozzle diameter x 50%),
# so a printable height is FIRST_LAYER_MM + n*layer_mm, not n*layer_mm.
FIRST_LAYER_MM = 0.2

# White text body thickness: 5 layers at 0.24. Sits on the (flat) frame ring top.
# Not 0.84: white PLA over black needs ~1.0mm before it stops reading
# warm-grey under a raking lamp, which is the light a wall-hung poster gets. It costs
# one extra 0.1g of white and no extra filament change — the caption is the only
# geometry above the ring, so the plate has exactly one black->white change either way.
TEXT_EMBOSS_MM = 1.20

# Printable stroke target for a 0.4mm nozzle: below ~0.8mm a glyph stroke is under two
# extrusion widths and Arachne flips between one and two beads along its length; 0.84
# is two 0.42 extrusions. A TARGET: _dilation_px stops short of it rather than close a
# counter or weld an i-dot on. See docs/print-settings.md.
MIN_STROKE_MM = 0.84
# Background a counter must keep after the dilation, and survive this much more growth
# with, before _dilation_px trusts it to come off the printer open.
MIN_COUNTER_MM = 0.4

# Bambu build plate. The hard ceiling on BOTH frame axes: size_mm is the width, and
# the chin makes the height size_mm + chin_mm, which is the one that overflows first.
PLATE_MM = 256.0

# ...but a mesh that fits the bare plate does not fit the PRINT. Measured on a real
# 240mm trio: the frame meshes 239.6 x 250.4mm, inside 256 on both axes, and Studio
# still refuses it — the 5mm brim docs/print-settings.md makes mandatory on a plate
# this size takes it to 249.6 x 260.4mm, 4.4mm off the bed, before the prime tower is
# placed at all. The tower is not optional either: relief.3mf's bodies overlap in z
# (caps drape below the terrain top, grey stands on it), so most layers carry two
# colours and the flush has to go somewhere. So the budget every footprint is
# really checked against is the plate less the brim, the tower and the gap between
# them. Both axes, because the tower is a fixed-orientation rectangle Studio parks in
# a front strip — assuming it can be rotated into a side strip buys 10mm and a
# surprise. Raise USABLE_MM only against a slicer screenshot, never on arithmetic.
BRIM_MM = 5.0          # per side, outer brim only (print-settings.md section 6)
TOWER_MM = 16.0        # 130 x 6mm prime tower + its own 5mm brim (TOWER_W_MM, section 3)
TOWER_GAP_MM = 4.0     # tower brim to object brim
USABLE_MM = PLATE_MM - 2 * BRIM_MM - TOWER_GAP_MM - TOWER_MM   # 226.0

# The three sizes the shop sells, and the only ones /generate accepts. Two rules pick
# them, and the large one is where both bite:
#   1. Its frame must fit USABLE_MM with EVERY caption it can be ordered with. The
#      two-line chin decides that — the frame is the tallest deliverable and the only
#      one that ever busts the budget (a 216mm relief is 194mm square, a lap ahead).
#   2. It must be a whole number of res_mm pixels. _grid() truncates (N =
#      int(size_mm/res_mm)), so a size off the grid loses up to a further pixel:
#      245mm is 612.5px and prints 244.4mm, 0.6mm under nominal and outside
#      check_output.py's +-0.5 footprint tolerance. 216 is 540px exactly.
# Hence 216: 215.6 x 226.0mm with two lines, landing exactly on the budget. 240 was
# shipped before the brim and the tower were counted and could not be printed at all.
# Pinned by test_every_offered_size_fits_the_plate. poster.py itself still meshes any
# size — the tests build 40mm posters — the restriction is the shop's, so it lives at
# the API boundary in app.py.
SIZES_MM = (216.0, 170.0, 120.0)

# Caption layout. Line 2 is a subtitle at SUB_RATIO of line 1, GAP_RATIO of line 1
# below it; TEXT_MARGIN_MM of clear ring above and below the block decides the chin.
SUB_RATIO = 0.65
GAP_RATIO = 0.35
TEXT_MARGIN_MM = 3.0

# The text body is meshed on its own grid, TEXT_SUB times finer than the frame's.
# On the terrain's 0.4mm grid an 8mm glyph is ~20px tall, every curve stair-steps by
# 0.4mm and the 1px dilation below fattens the strokes by another 0.4mm. At 4x the
# edge pitch is 0.1mm and the dilation costs 0.1mm — vertices are the only price.
TEXT_SUB = 4


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


# (path, face index), in fallback order. Bold first: a caption stroke has to clear
# MIN_STROKE_MM and a bold face is ~40% of the way there for free, where dilation
# pays for it in closed counters. Trebuchet MS Bold before Arial/Helvetica Bold: those
# two set the g's ear, the t's hook and the i-dot under 0.2mm from their stems at 7mm
# caps, and any dilation welds them; Trebuchet's open forms keep 0.8-1.2mm counters.
# It has no "→" — _glyph_font takes that one glyph from the next face down.
# Helvetica.ttc is a collection — index 1 is its Bold face; the .ttf files are single
# faces, index 0.
# load_default() is a bitmap font whose strokes are ~1px wide at res 0.4 —
# masked_slab_mesh needs all four corners of a cell, so those glyphs mesh as slivers
# or vanish. No new dependency, no bundled font: use what the box has, fall back to
# the regular faces, and to the bitmap only if it has neither.
FONT_PATHS = (("/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf", 0),
              ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
              ("/System/Library/Fonts/Helvetica.ttc", 1),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
              ("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 0),
              ("/System/Library/Fonts/Helvetica.ttc", 0),
              ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
              ("/usr/share/fonts/dejavu/DejaVuSans.ttf", 0))


def _font(px):
    for path, index in FONT_PATHS:
        try:
            f = ImageFont.truetype(path, px, index=index)
            f.getlength("M")   # Helvetica.ttc raises "division by zero" below ~8px
            return f
        except Exception:
            pass
    return ImageFont.load_default(size=px)


@functools.lru_cache(maxsize=None)
def _face(path, index, px):
    return ImageFont.truetype(path, px, index=index)


def _glyph_font(font, ch):
    """`font`, or the first FONT_PATHS face at its size that has a glyph for `ch`.

    A missing glyph renders as the .notdef box. U+FFFF is a noncharacter no font maps,
    so its mask IS that box — getmask("") is an empty mask, not the box, and comparing
    against it never fires."""
    has = lambda f: not np.array_equal(np.asarray(f.getmask(ch)),
                                       np.asarray(f.getmask("￿")))
    if has(font):
        return font
    for path, index in FONT_PATHS:
        try:
            f = _face(path, index, font.size)
            if has(f):
                return f
        except Exception:   # missing file; Helvetica.ttc below ~8px (see _font)
            pass
    return font


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
# tile gave 100m stair-steps. Four public mirrors, tried in order by _overpass.
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter",
                 "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter")
# `out geom` embeds every member way's coordinates, so no second node lookup is
# needed. Overpass does NOT clip geometry to the bbox — the rasteriser does.
OVERPASS_QL = ('[out:json][timeout:120][maxsize:536870912][bbox:{s},{w},{n},{e}];'
               '(way["natural"="water"];relation["natural"="water"];'
               'way["waterway"="riverbank"];relation["waterway"="riverbank"];'
               'way["natural"="coastline"];way["aeroway"="runway"];{roads});'
               'out geom;')
MIN_RING_PX2 = 9.0   # ~3x3 px: below this a lake is a printing artefact, not a lake


@functools.lru_cache(maxsize=None)
def _overpass(q):
    """Overpass elements for query q, as a tuple, from the first mirror that answers
    in FULL. Overpass answers a query that hits [timeout:] or [maxsize:] with HTTP 200,
    the elements gathered so far and a `remark` — roads drop out first, then the coast,
    and a regeneration of the same order printed a different street grid and relief.
    So a remark is a failure, not data. Cached per query string for the server's life:
    the same bbox always gets the same answer. lru_cache does not cache a raise, so a
    total failure is retried on the next call. Tuple, so no caller mutates the cache."""
    ex = None
    for base in OVERPASS_URLS:
        try:
            data = json.loads(_get(f"{base}?data={urllib.parse.quote(q)}", timeout=150, tries=1))
        except Exception as e:   # [:80]: an HTTPError's text carries the whole query URL
            ex = str(e)[:80]
            print(f"water: {base} failed ({ex}) — trying mirror")
            continue
        if data.get("remark") or "elements" not in data:
            ex = data.get("remark") or "no elements"
            print(f"water: {base}: {str(ex)[:80]} — partial response, trying mirror")
            continue
        return tuple(data["elements"])
    raise RuntimeError(f"OSM data unavailable — all {len(OVERPASS_URLS)} Overpass mirrors "
                       f"failed or answered partially (last: {ex}); retry in a few minutes")


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


def _to_px(pts, bounds, px_out):
    """[(lat, lon), ...] -> (K,2) output pixels (x east, y south), row 0 = north."""
    x0, y0, x1, y1 = bounds
    xy = np.array([_merc(la, lo) for la, lo in pts])
    return np.stack([(xy[:, 0] - x0) / (x1 - x0) * px_out,
                     (y1 - xy[:, 1]) / (y1 - y0) * px_out], 1)


def _water_mask_from_elements(els, bounds, px_out):
    """Overpass elements -> bool (px_out, px_out) polygon mask, row 0 = north."""
    img = Image.new("L", (px_out, px_out))
    draw = ImageDraw.Draw(img)

    def paint(ring, fill):
        px = _to_px(ring, bounds, px_out)
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


def _sea_mask(coast, bounds, px_out):
    """natural=coastline ways -> bool (px_out, px_out) sea mask, row 0 = north.

    OSM has no sea polygons: the coast is a line with land on its LEFT. Every way is
    drawn as a 1px 8-connected line (Bresenham), which a 4-connected flood cannot
    cross; the pieces it cuts the grid into are labelled lazily, and each segment
    votes +1 for the piece on its right and -1 for the one on its left. Votes, not one
    seed: a pier doubles back within a pixel of itself and a single seed lands across
    it (one seed flooded 99.8% of Blackpool; voting gives 48.5%). Not the DEM sign: a
    polder behind dunes is below zero and still land. The line itself stays land.
    ponytail: pure-Python floodfill, ~0.2 s at 488 px, ~5 s at res 0.2; swap for
    scipy.ndimage.label if it ever hurts."""
    img = Image.new("I", (px_out, px_out))
    draw = ImageDraw.Draw(img)
    lines = [_to_px([(p["lat"], p["lon"]) for p in el["geometry"]], bounds, px_out)
             for el in coast if len(el.get("geometry") or ()) >= 2]
    for q in lines:
        draw.line([tuple(v) for v in q], fill=-1, width=1)
    votes, n = {}, 0
    for q in lines:
        for a, c in zip(q[:-1], q[1:]):
            v = c - a
            L = math.hypot(*v)
            if L < 1e-9:
                continue
            # pixel y points south, so the way's right hand (the sea) is (-vy, vx)
            right = np.array([-v[1], v[0]]) / L
            for sgn in (1, -1):
                x, y = np.rint((a + c) / 2 + sgn * 1.5 * right).astype(int)
                if not (0 <= x < px_out and 0 <= y < px_out):
                    continue
                k = img.getpixel((int(x), int(y)))
                if k == 0:
                    n += 1
                    ImageDraw.floodfill(img, (int(x), int(y)), n)
                    k = n
                if k > 0:
                    votes[k] = votes.get(k, 0) + sgn
    return np.isin(np.asarray(img), [k for k, s in votes.items() if s > 0])


def _road_mask(items, bounds, px_out):
    """[(pts [(lat, lon), ...], width px), ...] -> bool (px_out, px_out) line mask."""
    img = Image.new("L", (px_out, px_out))
    draw = ImageDraw.Draw(img)
    for pts, w in items:
        draw.line([tuple(q) for q in _to_px(pts, bounds, px_out)], fill=255, width=w,
                  joint="curve")
    return np.asarray(img) > 0


def fetch_osm_masks(bounds, px_out, res_mm):
    """OSM water, sea and grey roads/runways over bounds -> (water, sea, roads), each
    bool (px_out, px_out), row 0 = north. One Overpass call for all three."""
    w, s = _unmerc(bounds[0], bounds[1])
    e, n = _unmerc(bounds[2], bounds[3])
    if e - w > 4.0:   # a transoceanic track; Overpass would time out on the ocean
        print(f"water: {e - w:.1f}deg bbox is too wide for Overpass — no water drawn")
        return tuple(np.zeros((px_out, px_out), bool) for _ in range(3))
    # pseudo-mercator x is longitude in radians: ground metres = dx * R * cos(lat)
    lat = _unmerc(0, (bounds[1] + bounds[3]) / 2)[1]
    m_per_mm = (bounds[2] - bounds[0]) * 6371000 * math.cos(math.radians(lat)) / px_out / res_mm
    classes = [c for c, lim in ROAD_TIERS if m_per_mm <= lim]
    roads = f'way["highway"~"^({"|".join(classes)})$"];' if classes else ""
    els = _overpass(OVERPASS_QL.format(s=s, w=w, n=n, e=e, roads=roads))
    tag = lambda el, k: (el.get("tags") or {}).get(k)
    kind = lambda el: ("sea" if tag(el, "natural") == "coastline" else
                       "runway" if tag(el, "aeroway") == "runway" else
                       # a tunnel is skipped, not "water": a closed roundabout way
                       # would otherwise reach the polygon rasteriser as a lake
                       ("road" if tag(el, "highway") in classes and not tag(el, "tunnel")
                        else None) if tag(el, "highway") else "water")
    # coastline must never reach the polygon rasteriser: a closed coastline way is an
    # island, and painted as a polygon it would print as a lake
    pick = lambda k: [el for el in els if kind(el) == k]
    pts = lambda el: [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
    px = lambda mm: round(mm / res_mm) + 1   # vertex width: 4 px at 0.4 -> 3 cells = 1.2mm

    def runway_m(el):   # "45", "45 m", "45;30" -> 45; missing or garbage -> RUNWAY_M
        try:
            return float(re.match(r"\s*([\d.]+)", tag(el, "width")).group(1))
        except (TypeError, AttributeError, ValueError):
            return RUNWAY_M

    runways = pick("runway")
    areas = [el for el in runways if tag(el, "area") == "yes"]   # drawn as an outline polygon
    runway_items = [(pts(el), px(max(ROAD_MM, runway_m(el) / m_per_mm)))
                    for el in runways if tag(el, "area") != "yes" and len(pts(el)) >= 2]
    road_items = [(tag(el, "highway"), (pts(el), px(ROAD_MM)))
                  for el in pick("road") if len(pts(el)) >= 2]
    while True:
        grey = _road_mask(runway_items + [it for c, it in road_items if c in classes],
                          bounds, px_out)
        if grey.mean() <= ROAD_MAX_FRAC or not classes:
            break
        print(f"roads: {classes[0]} would grey {grey.mean():.0%} of the plate — dropped")
        classes.pop(0)
    return (_water_mask_from_elements(pick("water"), bounds, px_out),
            _sea_mask(pick("sea"), bounds, px_out),
            grey | _water_mask_from_elements(areas, bounds, px_out))


@dataclass
class Params:
    size_mm: float = 216.0   # SIZES_MM[0]; the scaled params still read "@250mm"
    base_mm: float = 4.04    # 0.2 + 16*0.24: the layer boundary nearest 4.0
    relief_mm: float | None = None
    exaggeration: float = 1.5
    margin_pct: float = 15.0
    frame_mm: float | None = None
    frame_height_mm: float | None = None
    groove_w_mm: float | None = None  # slot width; its depth is derived, see SLOT_FLOOR_MM
    clearance_mm: float = 0.30  # per side; FDM PLA seating margin (rasterisation ±1px + elephant-foot)
    text: str = ""
    text2: str = ""          # second caption line, printed smaller (SUB_RATIO)
    text_mm: float | None = None
    chin_mm: float | None = None  # extra frame height BELOW the square, for the caption
    res_mm: float = 0.4
    proud_mm: float | None = None
    wall_mm: float | None = None   # wall height above proud_mm across HR_SCALE_BPM
    cap_mm: float = 0.96     # water cap slab thickness (4 layers); grey is a band, not a cap
    plate_mm: float = 2.12   # relief plate base thickness, 0.2 + 8*0.24 (slot floor sits above 0)
    fit_mm: float = 0.2      # gap per side between relief plate and frame ring
    snow_line_m: float = 2000.0   # grey band from this DEM elevation up
    layer_mm: float = 0.24   # slicer layer height; terrain snaps to it (0 = don't snap)
    # ponytail: measured 0.06 m residual at Blackpool; a metres-based radius only if a print ever shows speckle
    smooth_px: float = 1.0   # DEM blur radius in pixels, kills sub-layer noise (0 = off)


# Visual params: None means "auto" — base value at 250mm, scaled by size, floored so
# it still prints. Everything else in Params is absolute (stiffness, FDM tolerance,
# real-world metres, printer layer height) and must not move with the poster size.
# proud_mm (0.96) is 4 whole 0.24 layers; frame_height_mm's 9.96 base is not (41.5), so
# resolve's _layers rounds it up to 10.08 at 250mm: ring top = base_mm + frame_height_mm
# = 14.12, and terrain + proud_mm both stay on the layer grid.
# {field: (base@250, floor)}
# groove_w_mm's floor is 1.44, not 1.2, because what has to print is the STRIP, and the
# strip is groove_w_mm - 2*clearance_mm wide: at the old floor that left 0.60mm, 1.4
# extrusions at the 0.42mm line width, so a 16mm-tall fin came out as one wobbly bead
# with no perimeter pair to brace it. 1.44 - 0.60 = 0.84mm is exactly 2 x 0.42, the
# "pure perimeter, no gap fill" case docs/print-settings.md section 5 tunes the path for.
_SCALED = {"frame_mm": (12.0, 4.0), "relief_mm": (20.0, 5.0), "frame_height_mm": (9.96, 3.0),
           "text_mm": (8.0, 3.0), "groove_w_mm": (2.0, 1.44), "proud_mm": (0.96, 0.4),
           "wall_mm": (12.0, 3.0)}   # a starting value, tuned on the first test print


def _layers(v, p, mul=1.0):
    """Round a z-direction *thickness* UP to a whole number of layers.

    _snap() puts an absolute z on the FIRST_LAYER_MM + n*layer_mm grid; this is its
    delta form. base_mm and plate_mm already sit on that grid, so a whole-layer
    thickness stacked on them keeps everything above it on the grid too. Up, never
    nearest: these thicknesses all have a printability floor and rounding one down
    can cross it. `mul` snaps the thing the thickness is multiplied by before it
    reaches a real z (relief_mm only matters through the exaggeration)."""
    if p.layer_mm <= 0:
        return v
    return round(math.ceil(v * mul / p.layer_mm - 1e-9) * p.layer_mm / mul, 6)


def _lines(p):
    """[(string, ink height mm), ...] for the caption lines that were asked for."""
    return [(s, h) for s, h in ((p.text, p.text_mm), (p.text2, SUB_RATIO * p.text_mm)) if s]


def resolve(p: Params) -> Params:
    """Params with every auto (None) field filled in — the only place that happens."""
    p = replace(p, **{k: max(floor, round(base * p.size_mm / 250, 2))
                      for k, (base, floor) in _SCALED.items() if getattr(p, k) is None})
    # Scaling lands z heights between layers: at 170mm frame_height_mm came out 6.77,
    # putting the ring top — the black/white colour boundary — 0.05mm above boundary
    # 88 (of the old 0.12 grid), so which layer it printed on was the slicer's rounding to decide. Snap the
    # z-direction params here, once, and every height built on them (ring top, text
    # top, relief ceiling) is on the grid by construction. frame_mm, text_mm,
    # groove_w_mm and chin_mm are XY and are deliberately left alone.
    p = replace(p, frame_height_mm=_layers(p.frame_height_mm, p),
                proud_mm=_layers(p.proud_mm, p), wall_mm=_layers(p.wall_mm, p),
                relief_mm=_layers(p.relief_mm, p, p.exaggeration))
    if p.chin_mm is None:
        # Auto chin: whatever the caption needs beyond the bottom bar it already has.
        # Derived, not scaled — it follows text_mm and frame_mm, which are scaled
        # already. Rounded UP to a whole grid pixel so chin_px * res_mm IS chin_mm
        # (the preview and the checker both offset by the mm value).
        ls = _lines(p)
        block = sum(h for _, h in ls) + GAP_RATIO * p.text_mm * (len(ls) - 1) if ls else 0.0
        # The bar is measured the way the mesher measures it: rows N-fpx..H-1 span
        # (fpx + chin_px - 1) * res_mm of y, one pixel short of the nominal
        # frame_mm + chin_mm. Ask for that pixel back, or the margins come out short.
        ring = (int(p.frame_mm / p.res_mm) - 1) * p.res_mm
        need = max(block + 2 * TEXT_MARGIN_MM - ring, 0.0) if ls else 0.0
        p = replace(p, chin_mm=round(math.ceil(round(need / p.res_mm, 6)) * p.res_mm, 6))
    core = p.groove_w_mm - 2 * p.clearance_mm
    if core < 0.4:   # what is left of the strip between the two clearance gaps
        raise ValueError(f"groove_w_mm ({p.groove_w_mm}mm) leaves a {core:.2f}mm strip "
                         f"core after {p.clearance_mm}mm clearance per side; needs >= 0.4mm")
    return p


def _grid(p):
    """(N, M, fpx, chin_px): full grid px, relief-plate px, ring width px, chin rows.

    The fit gap is rounded UP to a whole pixel. int((frame_mm + fit_mm) / res_mm)
    truncates a 0.2mm gap to zero at every sane resolution (0.2-0.5mm), and the
    relief plate then comes out exactly the size of the ring opening — an
    interference fit no FDM printer wins. Rounding up errs loose, which glues.

    chin_px is extra frame rows appended BELOW the square: N, M and fpx keep their
    formulas, so the ring opening and everything that drops into it are untouched."""
    N = int(p.size_mm / p.res_mm)
    fpx = int(p.frame_mm / p.res_mm)
    return (N, N - 2 * (fpx + math.ceil(p.fit_mm / p.res_mm)), fpx,
            int(round((p.chin_mm or 0.0) / p.res_mm, 6)))


def footprint_mm(p):
    """(width, height) mm the printed frame really occupies, for a RESOLVED p.

    Not (size_mm, size_mm + chin_mm): the mesher spans (N-1) pixels, so the width is
    one grid pixel short of nominal (249.6, not 250, at defaults). chin_px * res_mm IS
    chin_mm — resolve() rounds it to a whole pixel precisely so this holds."""
    N, _, _, chin_px = _grid(p)
    w = round((N - 1) * p.res_mm, 6)
    return w, round(w + chin_px * p.res_mm, 6)


def max_size_mm(p):
    """Largest size_mm, in 0.1mm steps, whose footprint fits USABLE_MM with this caption.

    Takes UNRESOLVED params: the chin follows text_mm and frame_mm, which follow
    size_mm, so shrinking the poster shrinks the chin too and the answer is not
    simply USABLE_MM - chin_mm."""
    # ponytail: 0.1mm linear scan down from the asked-for size — ~50 resolve() calls
    # for the 250mm two-line case, microseconds. Bisect if a caller ever runs it hot.
    s = min(p.size_mm, USABLE_MM)
    while s > 0 and max(footprint_mm(resolve(replace(p, size_mm=s)))) > USABLE_MM:
        s = round(s - 0.1, 1)
    return s


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


def _fit_line(s, ink_px, avail_px):
    """(font, ink bbox) for `s`, ~ink_px tall and never wider than avail_px.

    Size by measured ink, not em: an em box is ~30% taller than its capitals, so
    using the target as the em left glyphs 30% short, whose strokes the dilation in
    _text_mask then fattened shut (B's counters filled). Then shrink again if the
    string is too long — TrueType glyphs run ~40% wider than the bitmap they
    replaced, and an unclamped long callsign clipped off the poster edge."""
    px = max(int(ink_px), 6)
    font = _font(px)
    ink = font.getbbox(s)
    if ink[3] > ink[1]:
        px = max(round(px * ink_px / (ink[3] - ink[1])), 6)
        font = _font(px)
        ink = font.getbbox(s)
    if ink[2] - ink[0] > avail_px:
        font = _font(max(int(px * avail_px / (ink[2] - ink[0])), 6))
        ink = font.getbbox(s)
    return font, ink


# Fraction of a line's ink that must be eroded away before the passes are counted as
# a stroke width. NOT 1.0 (erode until empty): the last pass to survive is the fattest
# feature on the line, and on a real caption that is the head of the "→" or the dot in
# "·", not a stem — "ZURICH → ALTENRHEIN" at 5.4mm caps measures 1.60mm to empty
# against a 1.1mm true stem, and would never be thickened however thin its stems got.
# At 0.75 the measurement matches an "HH" control to within a pixel on both lines.
_STROKE_ERODED = 0.75


def _stroke_mm(mask, res):
    """Stroke width of a glyph mask, in mm, by successive erosion.

    Each MinFilter(3) peels one pixel off every edge, so a stroke of width w loses
    2*res of it per pass and is gone after w/(2*res) passes — count the passes to a
    known fraction of the ink and you have measured w."""
    img = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8))
    box = img.getbbox()
    if box is None:
        return math.inf                 # no ink: nothing to thicken
    # crop to the ink with a 1px rim (crop pads with black outside the source), so a
    # glyph touching the mask edge erodes from that side too, and so the erosion runs
    # over a few hundred kpx instead of the whole poster-sized grid
    img = img.crop((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1))
    left = (1 - _STROKE_ERODED) * int((np.asarray(img) > 0).sum())
    for i in range(1, 33):   # ponytail: ceiling at 32 passes = 6.4mm of stroke at
        img = img.filter(ImageFilter.MinFilter(3))   # 0.1mm — no caption is that fat
        if int((np.asarray(img) > 0).sum()) <= left:
            return 2 * i * res / _STROKE_ERODED
    return 2 * 32 * res


def _topology(mask):
    """(ink blobs, holes) of a glyph mask — what a dilation must not change.

    Blobs are 4-connected, the mesher's own rule: two pixels touching only at a corner
    share no full cell and print apart. Holes are then counted with an 8-connected
    background, the only pairing under which a ring is one blob around one hole, and
    via the Euler number (Gray's bit quads: E = blobs - holes, from 2x2 window counts)
    rather than a second round of floods — PIL's floodfill is 4-connected only.
    ponytail: one pure-PIL floodfill per blob, ~20 per line; scipy.ndimage.label if
    /generate or the tests ever crawl."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return 0, 0
    m = np.pad(mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 2)
    q = m[:-1, :-1].astype(np.int8), m[:-1, 1:], m[1:, :-1], m[1:, 1:]
    s = q[0] + q[1] + q[2] + q[3]
    euler = ((s == 1).sum() - (s == 3).sum() + 2 * ((s == 2) & (q[0] == q[3])).sum()) // 4
    # .copy(): a fromarray() image shares the numpy buffer and floodfill's writes
    # never show up in the array read back — the fill silently does nothing
    img = Image.fromarray(np.where(m, 255, 0).astype(np.uint8)).copy()
    blobs = 0
    while True:
        ys, xs = np.nonzero(np.asarray(img) == 255)
        if not len(ys):
            return blobs, blobs - int(euler)
        ImageDraw.floodfill(img, (int(xs[0]), int(ys[0])), 1)
        blobs += 1


def _dilation_px(render, res):
    """Fine pixels one caption line grows by: 1 for the mesher, plus MIN_STROKE_MM.

    The 1px is structural — masked_slab_mesh only meshes cells with all four corners
    set, so a stroke survives only where every glyph pixel is cell-interior, and after
    one MaxFilter(3) each pixel has all 8 neighbours, i.e. four full cells. On this
    grid that costs 0.1mm of fattening, not the frame grid's 0.4mm. Every pixel past
    the first is bought stroke width.

    render(n) is the line tracked by 2n. The stroke target is given up a pixel at a
    time until the dilated line has the raw render's topology — no letter or i-dot
    welded on, no counter shut — and every counter survives MIN_COUNTER_MM more growth.
    Checked on the TRACKED render, so the letter gaps (paid for by tracking) never veto;
    only the vertical gaps and counters do. n=1 is kept even if it changes something."""
    raw = render(0)
    stroke = _stroke_mm(raw, res)
    want = 1 + max(math.ceil((MIN_STROKE_MM - stroke) / 2 / res - 1e-9), 0)
    t0, guard = _topology(raw), math.ceil(MIN_COUNTER_MM / 2 / res - 1e-9)
    for n in range(want, 0, -1):
        m = render(n)
        if _topology(_dilate(m, n)) == t0 and _topology(_dilate(m, n + guard))[1] == t0[1]:
            break
    else:
        print(f"text: even the mesher's 1px leaves a counter or gap on this line under "
              f"{MIN_COUNTER_MM}mm, or changes its topology {t0}")
    if n < want:
        print(f"text: {stroke:.2f}mm strokes want {want}px, {n}px keeps every counter and gap open")
    return n


def _dilate(mask, n):
    img = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8))
    for _ in range(n):    # ponytail: n cheap MaxFilter(3)s — one MaxFilter(2n+1) is
        img = img.filter(ImageFilter.MaxFilter(3))   # the same square, at O(n^2)/px
    return np.asarray(img) > 0


def _line_mask(shape, s, font, extra, top):
    """(`s` drawn centred in a `shape` mask, its ink width), tracked by `extra` px.

    ImageDraw.text has no tracking parameter, so the line is laid out here instead:
    pen x accumulates font.getlength(ch) + extra and each glyph is drawn on its own.
    `extra` is what pays for the dilation in _dilate — a glyph grown by n pixels on
    every side eats n off each side of every gap, so an advance has to grow by 2n or
    the letters touch, which is exactly what the thickening was meant to prevent.

    The cost of drawing glyph by glyph is kerning: per-character advances only, so
    pairs like "VA" sit a shade loose. Loose is the direction this whole function is
    pushing anyway. `top` is the em-box top, as ImageDraw.text takes it.

    Each glyph comes from _glyph_font, so a character the face lacks ("→" in
    Trebuchet) is drawn from a fallback face — on the line's baseline, not at `top`:
    two faces' ascenders differ (Trebuchet 0.95em, Arial 0.91em), and an em-box-top
    anchor would set the borrowed glyph ~0.4mm high."""
    xs, fs, x, l, r = [], [], 0.0, math.inf, -math.inf
    for ch in s:
        f = _glyph_font(font, ch)
        b = f.getbbox(ch)
        if b[2] > b[0]:                       # ink-bearing: a space moves no bbox
            l, r = min(l, x + b[0]), max(r, x + b[2])
        xs.append(x)
        fs.append(f)
        x += f.getlength(ch) + extra
    if r < l:
        return np.zeros(shape, bool), 0.0
    img = Image.new("L", (shape[1], shape[0]))
    d = ImageDraw.Draw(img)
    x0 = (shape[1] - 1 - (r - l)) / 2 - l     # centred on the tracked ink, not the em
    base = top + font.getmetrics()[0]         # "la" anchors the em top at ascent above it
    for ch, x, f in zip(s, xs, fs):
        d.text((x0 + x, base), ch, fill=255, font=f, anchor="ls")
    return np.asarray(img) > 0, r - l


def _text_mask(H, N, fpx, chin_px, p):
    """(bool glyph mask, its res_mm) for the caption, on the TEXT_SUB-finer grid.

    The mask spans the frame's EXACT physical extent, so the text body it meshes
    lands in the frame's own coordinates — but on its own pitch, which is the whole
    point: glyph edges step by res_mm/TEXT_SUB instead of by the terrain's res_mm.

    (H-1)*TEXT_SUB+1 rows, not H*TEXT_SUB. Both meshers map row -> (rows-1-row)*res,
    and that -1 is a VERTEX count, not a cell count: it does not scale with TEXT_SUB.
    An H*TEXT_SUB mask put every glyph (1 - 1/TEXT_SUB)*res_mm — 0.3mm at defaults —
    north of where the frame thinks that row is. Sized this way, fine row r*TEXT_SUB
    is exactly frame row r, in both axes, at every resolution.

    Lines are centred in the bottom bar (frame rows N-fpx..H-1), line 2 at SUB_RATIO
    of line 1 with GAP_RATIO of line 1 between them."""
    res = p.res_mm / TEXT_SUB
    W, Hf = (N - 1) * TEXT_SUB + 1, (H - 1) * TEXT_SUB + 1
    lines = _lines(p)
    if not lines:
        return np.zeros((Hf, W), bool), res
    bar_top = (N - fpx) * TEXT_SUB          # frame row N-fpx, exactly
    bar_h = Hf - 1 - bar_top                # ...down to the last frame row, exactly
    # Ring opening, in fine columns, less one pixel per side for the dilation below:
    # keeps the text off the corners where the side bars meet. Frame cols fpx..N-fpx-1
    # are fine cols fpx*TEXT_SUB..(N-fpx-1)*TEXT_SUB, so the span is (N-2*fpx-1) coarse.
    avail = (N - 2 * fpx - 1) * TEXT_SUB - 2
    hs = [h / res for _, h in lines]
    gap = GAP_RATIO * p.text_mm / res
    block = sum(hs) + gap * (len(hs) - 1)
    # An auto chin already sized the bar to hold this. An explicit chin_mm (or a
    # frame_mm narrower than text_mm, with chin_mm=0) may not, so scale the block
    # down to fit — never off the bar, ever, whatever the caller asked for.
    room = max(bar_h - 2 * TEXT_MARGIN_MM / res, 0.6 * bar_h)
    if block > room:
        hs = [h * room / block for h in hs]
        gap *= room / block
        block = room
    y = bar_top + (bar_h - block) / 2
    mask = np.zeros((Hf, W), bool)
    # One image per line, thickened on its own: line 2 is the smaller face, so its
    # strokes are thinner and it needs more dilation than line 1 to clear the floor.
    for s, h in zip((s for s, _ in lines), hs):
        font, ink = _fit_line(s, h, avail)
        # The dilation is measured off a first, untracked render, because it depends
        # only on the rendered stroke; the tracking that answers it then changes the
        # width, so the width fit is redone against the TRACKED ink or a long line
        # walks off the bar. n is not re-measured after that shrink: tracking and
        # dilation must stay the same number, and a hair under MIN_STROKE_MM beats a
        # line whose letters touch.
        n = _dilation_px(lambda k: _line_mask((Hf, W), s, font, 2 * k, y - ink[1])[0], res)
        glyphs, w = _line_mask((Hf, W), s, font, 2 * n, y - ink[1])
        if w > avail:
            font = _font(max(int(font.size * avail / w), 6))
            glyphs = _line_mask((Hf, W), s, font, 2 * n, y - font.getbbox(s)[1])[0]
        mask |= _dilate(glyphs, n)
        y += h + gap                        # nominal, so a width-shrunk line cannot crowd
    return mask, res


def compose_parts(track, elev, lc, bounds, p):
    """Split the poster into its printable pieces, all heights in mm.

    `elev` arrives already smoothed (build_poster blurs once and shares the array
    with the snow threshold, so nothing gets blurred twice).

    frame (N+chin_px, N): backplate + raised ring, flat — printed alone. The chin
    rows hang below the square (heightmap_mesh maps y = (H-1-row)*res, so appending
    rows extends the poster southward); the opening keeps its indices.
    text_mask / text_res: the glyph pixels on their own TEXT_SUB-times finer grid,
    printed as their own white body on top of the ring (empty when no text).
    green/surface/water/roads/snow/snow_cells/z_snow/track_px: the (M,M) relief plate
    that drops into the ring, its pre-slot pre-cap top, the water, road and grey vertex masks,
    the grey band's meshed cells and the horizontal plane it starts from, and the
    track in relief-plate pixels. water_cells/road_cells/cap_top/cap_bot: the caps'
    meshed cells and the vertex surfaces they span (draped to the slot floor in the groove).
    alt_mm: flight altitude per original track point, on the same vertical scale
    as `surface`, for the path wall."""
    N, M, fpx, chin_px = _grid(p)
    H = N + chin_px
    frame = np.full((H, N), p.base_mm)
    ring = np.ones((H, N), bool)
    ring[fpx:N - fpx, fpx:N - fpx] = False   # unchanged indices -> chin rows are all ring
    frame[ring] = p.base_mm + p.frame_height_mm
    text_mask, text_res = _text_mask(H, N, fpx, chin_px, p)
    e0, e1 = float(elev.min()), float(elev.max())
    # Terrain range alone stretched 30m of Blackpool coast over the whole relief
    # (0.86mm/m): flat land read as hills and the 335m circuit hit the strip ceiling
    # as a flat fence. Spanning the flight too (clipped, so an airliner cannot flatten
    # the Alps and a low hop over a polder still shows ground) gives 0.077mm/m there;
    # in the mountains the terrain range wins and nothing changes.
    span = max(e1 - e0, float(np.clip(np.asarray(track, float)[:, 2].max() - e0, *FLIGHT_SPAN_M)))
    to_mm = lambda m: p.plate_mm + (m - e0) / span * p.relief_mm * p.exaggeration
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
    # The outer vertex ring is a
    # cap-only exclusion: a conformal cap is a thin slab floating at `surface - cap_mm`,
    # and on the boundary ring it has nothing under it, so its wall hangs off the plate
    # edge. The band is not a slab, it is a solid from the flat z_snow plane up to the
    # surface, resting on the green below it — it cannot overhang, and a boundary cell's
    # wall is coplanar with the terrain's own skirt. Excluding it there was the real cause
    # of green towering above the plane: the plate's skirt stayed green up to the terrain
    # height wherever the bbox runs a mountain off the edge (31.52mm against a 16.88mm
    # plane on HB-EZE), which is 123 of the 266 layers holding two colours.
    border = np.zeros((M, M), bool)
    border[1:-1, 1:-1] = True
    # Water and road caps are NOT kept off the groove: they drape into it, cap_top
    # dropping to the slot floor, so the slot's walls and floor take the cap colour.
    # Kept off, 0.3mm clearance plus up to 0.4mm of full-height green rim showed on
    # each side of the strip along the whole path, even over the sea. The strip still
    # seats on SLOT_FLOOR_MM, now on the cap's top; the cap there is SLOT_CAP_MM thick.
    water = (lc == 1) & border
    roads = (lc == 3) & border
    snow = (lc == 2) & ~gmask              # the band stays out, as before
    cap_top = np.where(gmask, SLOT_FLOOR_MM, surface)
    cap_bot = np.where(gmask, SLOT_FLOOR_MM - SLOT_CAP_MM, surface - p.cap_mm)
    water_cells, road_cells = _slab_cells(water), _slab_cells(roads)
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
    green = surface.copy()
    # carved only under cells the mesher really meshes: a vertex-mask carve left orphan
    # pits along every edge a cap's four-corner cell rule drops (a 4px road loses one)
    cv = _cell_verts(water_cells | road_cells)
    green[cv] = cap_bot[cv]
    green[_cell_verts(snow_cells)] = z_snow
    green[gmask & ~cv] = SLOT_FLOOR_MM  # full-depth slot, constant floor
    return dict(frame=frame, text_mask=text_mask, text_res=text_res,
                green=green, surface=surface, water=water, roads=roads,
                water_cells=water_cells, road_cells=road_cells,
                cap_top=cap_top, cap_bot=cap_bot,
                snow=snow, snow_cells=snow_cells, z_snow=z_snow,
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


# One heart-rate scale for every customer, so a relaxed run prints low, a race tall,
# and two posters compare. At or under the low end (or no HR) the wall is proud_mm.
HR_SCALE_BPM = (100.0, 200.0)
# The walls are rasterised on a grid this much finer than res_mm, like TEXT_SUB: a
# 1.4mm strip is 3.5 px at 0.4mm and would stair-step by a third of its width.
WALL_SUB = 4
# Fine pixels added to the drawn strip width: rasterising and the four-corner cell rule
# each shave about a pixel off a drawn width, and the meshed strip must never come out
# under its core groove_w_mm - 2*clearance_mm (spec 6.5 allows "a couple" of pixels).
WALL_PAD_PX = 2


def wall_height(hr: np.ndarray, p: Params) -> np.ndarray:
    """mm above the ground under each station: proud_mm, plus wall_mm across HR_SCALE_BPM."""
    lo, hi = HR_SCALE_BPM
    return p.proud_mm + np.nan_to_num(np.clip((hr - lo) / (hi - lo), 0, 1)) * p.wall_mm


def _wall_dims(p: Params) -> tuple[float, float, int, float]:
    """(res_f, W_mm, dil_px, lane_mm) for rasterising the walls of a RESOLVED p.

    res_f   fine-grid pixel, res_mm / WALL_SUB.
    W_mm    the drawn strip width: the strip core groove_w_mm - 2*clearance_mm plus
            WALL_PAD_PX fine pixels, so the meshed strip never comes out under the core.
    dil_px  fine pixels the crossing cut grows a wall by, clearance_mm rounded UP.
    lane_mm centre-to-centre spacing of side-by-side walls: one W_mm strip plus its
            dil_px cut plus one fine pixel, so a neighbour's cut never bites this wall."""
    res_f = p.res_mm / WALL_SUB
    W = p.groove_w_mm - 2 * p.clearance_mm + WALL_PAD_PX * res_f
    dil = math.ceil(round(p.clearance_mm / res_f, 6))   # 0.3/0.1 is 2.9999999999999996
    return res_f, W, dil, W + (dil + 1) * res_f


def legs_bounds(legs: list[activity.Leg], margin_pct: float) -> tuple:
    """track_bounds over every point of every leg: one square map for the whole order."""
    return track_bounds([(la, lo, 0.0) for l in legs for la, lo in zip(l.lat, l.lon)],
                        margin_pct)


def leg_stations(leg: activity.Leg, bounds, M: int) -> tuple[np.ndarray, np.ndarray]:
    """(P (k,2) relief-plate px about 1 px apart, hr (k,) smoothed bpm, NaN where none).

    HR is carried as a weighted interpolation: the NaN-zeroed signal and its finite
    weight v are interpolated separately and divided, so a station keeps the finite
    neighbours' bpm where they carry at least half the weight, and is NaN (the low
    line) where the gap does. A plain interp of s would smear NaN one fix wide."""
    C, _, d, t = _offsets(_to_px(zip(leg.lat, leg.lon), bounds, M))
    s = activity.smooth_hr(leg.t, leg.hr)
    v = np.interp(t, d, np.isfinite(s))
    return C, np.divide(np.interp(t, d, np.nan_to_num(s)), v,
                        out=np.full(len(t), np.nan), where=v >= 0.5)


def _rows(m, n):
    """Row slices of an (m, n) pairwise job, ~2M cells each, so memory stays flat."""
    # ponytail: O(n^2) in chunks; grid buckets if a wall ever passes ~20k stations
    step = max(1, 2_000_000 // max(n, 1))
    return [slice(s, s + step) for s in range(0, m, step)]


def _near(X, Y, r):
    """Yield (rows, |X[rows] - Y| < r) as a (rows, len(Y)) bool block."""
    for sl in _rows(len(X), len(Y)):
        yield sl, np.hypot(X[sl, :1] - Y[:, 0], X[sl, 1:] - Y[:, 1]) < r


def _nearest_on_segments(Q: np.ndarray, A: np.ndarray, B: np.ndarray
                         ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(feet (m,2), dist (m,), segment index (m,)) of each Q on its nearest A[k]-B[k].

    A segment with A == B is a point; the index is how a caller finds the direction."""
    AB, feet = B - A, np.empty((len(Q), 2))
    L2, dist, k = (AB ** 2).sum(1), np.empty(len(Q)), np.empty(len(Q), int)
    for sl in _rows(len(Q), len(A)):
        q = Q[sl, None]
        t = ((q - A) * AB).sum(-1)
        t = np.clip(np.divide(t, L2, out=np.zeros_like(t), where=L2 > 0), 0, 1)
        F = A + t[..., None] * AB
        d = np.hypot(*(q - F).transpose(2, 0, 1))
        k[sl] = j = d.argmin(1)
        r = np.arange(len(j))
        feet[sl], dist[sl] = F[r, j], d[r, j]
    return feet, dist, k


def _ramp(mask: np.ndarray, piece: np.ndarray, k: int) -> np.ndarray:
    """Per station, min(1, d/k), d the index distance to the nearest False of its own piece.

    Eases a snap in and out over k stations instead of kinking the wall. False is 0, a
    piece with no False is all 1: a piece end is not False, so a pass that starts or
    ends on a shared road needs no ramp there."""
    d = np.full(len(mask), np.inf)
    for g in np.unique(piece):
        s = np.flatnonzero(piece == g)
        f = np.flatnonzero(~mask[s])
        if len(f):
            x = np.arange(len(s))
            j = np.searchsorted(f, x)
            d[s] = np.minimum(abs(x - f[np.maximum(j - 1, 0)]), abs(f[np.minimum(j, len(f) - 1)] - x))
    return np.minimum(1.0, d / k)


def collapse_passes(pieces: list[tuple[np.ndarray, np.ndarray]], r_px: float, ramp: int
                    ) -> list[tuple[np.ndarray, np.ndarray]]:
    """One wall's (P, hr) pieces, in time order -> the same shapes, repeats collapsed.

    A station within r_px of an earlier one (another piece, or more than 3*r_px
    stations back in its own) is a repeat pass: it snaps, eased by _ramp, onto the
    polyline of the non-repeats, so a lap or an out-and-back prints one wall, never two
    offset by GPS drift (spec 6.5). Every station's hr is then the mean of the finite
    hr within r_px of its new position: no-HR passes do not dilute it, and a stretch
    no pass has HR on stays NaN, the low line."""
    n_k = [len(q) for q, _ in pieces]
    P = np.concatenate([q for q, _ in pieces]).astype(float)
    hr = np.concatenate([h for _, h in pieces]).astype(float)
    g = np.repeat(np.arange(len(pieces)), n_k)
    a = np.concatenate([np.arange(m) for m in n_k])
    i = np.arange(len(P))
    rep = np.zeros(len(P), bool)
    for sl, near in _near(P, P, r_px):
        rep[sl] = (near & (i < i[sl, None])
                   & ((g != g[sl, None]) | (a[sl, None] - a > 3 * r_px))).any(1)
    canon = ~rep
    seg = np.flatnonzero(canon[:-1] & canon[1:] & (g[:-1] == g[1:]))
    lone = canon.copy(); lone[seg] = lone[seg + 1] = False   # no canonical neighbour
    lone = np.flatnonzero(lone)
    new = P.copy()
    if rep.any():
        foot = _nearest_on_segments(P[rep], P[np.r_[seg, lone]], P[np.r_[seg + 1, lone]])[0]
        new[rep] += _ramp(rep, g, ramp)[rep, None] * (foot - P[rep])
    ok = np.isfinite(hr)
    hw = np.stack([np.where(ok, hr, 0.0), ok], 1)
    out = np.full(len(P), np.nan)
    for sl, near in _near(new, new, r_px):
        s, c = (near @ hw).T
        out[sl] = np.divide(s, c, out=np.full(len(c), np.nan), where=c > 0)
    cut = np.cumsum(n_k)[:-1]
    return list(zip(np.split(new, cut), np.split(out, cut)))


def assign_lanes(walls: list[list[tuple[np.ndarray, np.ndarray]]], lane_px: float,
                 r_px: float, ramp: int) -> list[list[tuple[np.ndarray, np.ndarray]]]:
    """Collapsed walls, earliest first -> the same walls, shared roads in side-by-side lanes.

    Wall 0 stays put. A station of a later wall takes lane = the number of earlier
    walls whose INPUT polyline lies strictly within r_px, and moves to lane * lane_px
    left of the earliest of them (left of that wall's travel, so the side never flips
    with this wall's direction), eased in and out by _ramp (spec 6.6). hr is untouched.
    Zero-length segments (collapse snaps several stations onto one vertex) are left out
    of a reference; they have no direction and their point is a neighbour's end anyway."""
    refs = []
    for w in walls:
        A = np.concatenate([q[:-1] for q, _ in w]).astype(float)
        B = np.concatenate([q[1:] for q, _ in w]).astype(float)
        # ponytail: a one-station piece is no reference (no direction to lane beside);
        # give it a point segment and a fallback normal if such pieces ever reach here
        keep = (A != B).any(1)
        refs.append((A[keep], B[keep]))
    out = [walls[0]]
    for i, w in enumerate(walls[1:], 1):
        n_k = [len(q) for q, _ in w]
        P = np.concatenate([q for q, _ in w]).astype(float)
        lane, foot, nrm = np.zeros(len(P), int), np.zeros_like(P), np.zeros_like(P)
        for A, B in refs[i - 1::-1]:          # earliest last, so it ends up the ref
            if not len(A):
                continue                      # a wall of single stations has no road
            f, d, k = _nearest_on_segments(P, A, B)
            m = d < r_px
            u = (B - A)[k[m]]
            lane += m
            foot[m], nrm[m] = f[m], np.stack([-u[:, 1], u[:, 0]], 1) / np.hypot(*u.T)[:, None]
        m = lane > 0
        new = P.copy()
        new[m] += _ramp(m, np.repeat(np.arange(len(w)), n_k), ramp)[m, None] * (
            foot[m] + lane[m, None] * lane_px * nrm[m] - P[m])
        out.append(list(zip(np.split(new, np.cumsum(n_k)[:-1]), [h for _, h in w])))
    return out


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
    an airliner at 12000m over 500m terrain maps to a 362mm wall, which is not a
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
    """Track -> (frame_bodies, relief_bodies, strip_bodies).

    All three are [(mesh, name, hex_colour, extruder_slot), ...] for write_3mf."""
    p0, p = p, resolve(p)   # auto (None) visual params -> concrete mm; all mm below
    # ponytail: reject rather than clamp — a typo'd 2500mm is a mistake to surface,
    # not to silently honour, and N^2 grids OOM the box. Raise the cap if a bigger
    # plate ever shows up.
    if p.res_mm < 0.2:
        raise ValueError("res_mm must be >= 0.2")
    # The whole footprint, chin included: a caption makes the frame taller than it is
    # wide, so the height is what overflows first and only check_output.py used to say
    # so — after the 20 minutes of meshing that produced an unprintable file.
    w, h = footprint_mm(p)
    if max(w, h) > USABLE_MM:
        alt = {1: ", or drop the caption",
               2: ", or use one caption line"}.get(len(_lines(p)), "")
        raise ValueError(f"frame would be {w:.1f} x {h:.1f}mm — over the {USABLE_MM:.0f}mm "
                         f"printable budget ({PLATE_MM:.0f}mm plate less {BRIM_MM:.0f}mm brim "
                         f"per side and {TOWER_MM:.0f}mm for the prime tower). Reduce poster "
                         f"size to <={max_size_mm(p0):g}mm{alt}.")
    for label, v in (("slot floor", SLOT_FLOOR_MM), ("water cap", p.cap_mm)):
        if p.plate_mm <= v:   # slot floor above the plate top / caps push terrain negative
            raise ValueError(f"{label} ({v}mm) must be less than the relief plate "
                             f"thickness ({p.plate_mm}mm)")
    bounds = track_bounds(track, p.margin_pct)
    M = _grid(p)[1]
    elev = fetch_elevation(bounds, M)
    # No soft-fail: a poster without its coast keeps the seabed in the DEM and prints
    # different relief from the same order, so Overpass being down is a 502.
    water, sea, roads = fetch_osm_masks(bounds, M, p.res_mm)
    # the sea is flat; terrarium carries bathymetry (Blackpool: -7.85 m seabed,
    # 45% of the grid). np.where, not in place: fetch_elevation's array is read-only
    elev = np.where(sea, 0.0, elev)
    water = water | sea
    # smoothed once here and shared: the snow threshold and the relief surface must
    # see the same terrain, and blurring twice would wash the mountains out. After the
    # sea flatten, so the shore blends land with 0, not with the seabed.
    elev = _smooth(elev, p.smooth_px)
    lc = np.zeros((M, M), np.uint8)
    # Bare threshold, no morphology: grey is a BAND, so every bit of ground above the
    # snow line is a solid volume that prints fine, however small its footprint. An
    # opening (the old conformal-cap defence against 1px slivers) dropped small peaks
    # from grey while leaving them in green — green then towered above the z_snow
    # plane and the two colours shared layers. Sub-2-cell blobs still go: _slab_cells.
    lc[elev >= p.snow_line_m] = 2
    lc[water] = 1   # high Alpine lakes sit above the snow line and stay blue
    lc[roads & (lc != 2)] = 3   # after water, so a bridge is grey across the river; never over snow
    parts = compose_parts(track, elev, lc, bounds, p)
    bodies = [(heightmap_mesh(parts["green"], p.res_mm), "terrain", COLORS["green"], 1)]
    # water and roads stay conformal caps (lakes are flat, so their slices are lake-wide
    # anyway) draped into the slot; grey is a band standing on the z_snow plane
    cap = lambda k: _slab_mesh(parts[k], parts["cap_top"], parts["cap_bot"], p.res_mm)
    for name, slot, m in (("water", 2, cap("water_cells")),
                          ("snow", 3, band_mesh(parts, p)),
                          ("roads", 3, cap("road_cells"))):
        if m is not None:
            bodies.append((m, name, COLORS[name], slot))
    ring_top = p.base_mm + p.frame_height_mm
    frame_bodies = [(heightmap_mesh(parts["frame"], p.res_mm), "frame", COLORS["frame"], 1)]
    # Text is its own white body standing TEXT_EMBOSS_MM proud of the ring, in slot 2.
    # Its top is a CONSTANT, not parts["frame"] + emboss: the text sits on the flat
    # ring, so it needs no heightmap of its own — which is what frees it to be meshed
    # on a finer grid than the frame (see _text_mask).
    tm = parts["text_mask"]
    text = masked_slab_mesh(tm, np.full(tm.shape, ring_top + TEXT_EMBOSS_MM),
                            TEXT_EMBOSS_MM, parts["text_res"])
    if text is not None:
        frame_bodies.append((text, "text", COLORS["text"], 2))
    strip = strip_mesh(parts["track_px"], parts["alt_mm"], parts["surface"], p)
    return frame_bodies, bodies, [(strip, "strip", COLORS["strip"], 1)]


# Every output is a finished OrcaSlicer 2.3.2 project for the Bambu Lab A1, 0.4 nozzle:
# open, slice, print. Orca fills a project's config from compiled defaults and applies
# it as "(modified)" edits over the preset print_settings_id names, so a partial config
# would blank machine_start_gcode and every key it left out. The whole flattened system
# chain is therefore vendored (orca_profile.py -> orca_a1_pla.json) and these tables go
# on top. They are the truth; docs/print-settings.md is the why. All values are strings,
# as Orca writes them; filament lists carry one entry per slot.
_ORCA = json.loads(Path(__file__).with_name("orca_a1_pla.json").read_text())
FILAMENT, PRINTER, PROCESS = "Bambu PLA Basic @BBL A1", "Bambu Lab A1 0.4 nozzle", "0.24mm Draft @BBL A1"
# Tower centred in x at the front of the bed: y BRIM_MM..~11, its brim 0..16 (TOWER_MM),
# TOWER_GAP_MM clear, then the object's brim. write_3mf centres the object in what is
# left. Sliced at 0.24 (216 order): the frame's tower is 6.75mm deep, Orca's height-based
# stability minimum (at 0.12 a 180 tower sliced the same), so widening buys nothing. Its
# brim reaches y 16.8, 3.6mm short of the frame's own brim.
TOWER_W_MM = 130
TOWER_X = (PLATE_MM - TOWER_W_MM) / 2   # 63
COMMON = {
    "precise_z_height": "0", "slice_closing_radius": "0.01", "wall_generator": "arachne",
    "detect_thin_wall": "1", "wall_sequence": "inner-outer-inner wall",
    "staggered_inner_seams": "1", "seam_slope_type": "none", "enable_arc_fitting": "0",
    "precise_outer_wall": "1", "reduce_crossing_wall": "1", "reduce_infill_retraction": "0",
    "timelapse_type": "0", "xy_hole_compensation": "0", "xy_contour_compensation": "0",
    "line_width": "0.42", "initial_layer_line_width": "0.5", "outer_wall_line_width": "0.4",
    "inner_wall_line_width": "0.45", "top_surface_line_width": "0.4",
    "internal_solid_infill_line_width": "0.45", "sparse_infill_line_width": "0.45",
    "top_shell_thickness": "0", "bottom_shell_thickness": "0",
    "top_surface_pattern": "monotonicline", "sparse_infill_pattern": "grid",
    "infill_wall_overlap": "25%", "infill_combination": "0",
    "detect_narrow_internal_solid_infill": "1", "only_one_wall_top": "1",
    "enable_prime_tower": "1", "prime_tower_width": str(TOWER_W_MM),
    "prime_tower_brim_width": "5", "prime_volume": "45",
    "flush_into_infill": "0", "flush_into_objects": "0", "flush_into_support": "1",
    "interface_shells": "0", "mmu_segmented_region_max_width": "0",
    "brim_type": "outer_only", "brim_object_gap": "0", "enable_support": "0",
    "initial_layer_speed": "50", "top_surface_speed": "50"}
# User's standard: every print speed 50 mm/s under the A1 Draft preset (200/230 -> 150/180,
# first-layer infill 105 -> 55), top surfaces at 50. Already-slow speeds (first layer and
# bridges at 50, the path's and the caption's own) are left alone rather than zeroed.
SLOWER_MM_S = 50
COMMON.update({k: str(int(_ORCA["process"][k][0]) - SLOWER_MM_S) for k in (
    "outer_wall_speed", "inner_wall_speed", "sparse_infill_speed",
    "internal_solid_infill_speed", "gap_infill_speed", "initial_layer_infill_speed")})
PLATES = {
    # 0.24 layers, walls 2, top 3: the user's print-time cut (docs/print-settings.md head)
    "relief": {"wall_loops": "2", "top_shell_layers": "3", "bottom_shell_layers": "3",
               "sparse_infill_density": "10%", "ironing_type": "no ironing", "brim_width": "5",
               "mmu_segmented_region_interlocking_depth": "0.72",
               "flush_volumes_matrix": ["0", "400", "550", "350", "0", "600", "250", "300", "0"]},
    # no ironing (it was over half the frame's print time), top 3 x 0.24 = the old 6 x 0.12
    "frame": {"wall_loops": "2", "top_shell_layers": "3", "bottom_shell_layers": "3",
              "sparse_infill_density": "7%", "ironing_type": "no ironing",
              "seam_position": "nearest", "brim_width": "5",
              "wall_transition_filter_deviation": "50%", "min_feature_size": "10%",
              "outer_wall_acceleration": "1000", "outer_wall_jerk": "5",
              "small_perimeter_speed": "50%", "small_perimeter_threshold": "3",
              "resolution": "0.008", "nozzle_temperature": ["220", "210"],
              "fan_min_speed": ["60", "100"], "fan_max_speed": ["80", "100"],
              "slow_down_layer_time": ["8", "8"], "flush_volumes_matrix": ["0", "999", "150", "0"]},
    # a 28 x 1.1mm fin on the A1's slinging bed: slow walls, capped acceleration
    "path": {"wall_loops": "2", "sparse_infill_density": "0%", "top_shell_layers": "2",
             "bottom_shell_layers": "2", "ironing_type": "no ironing", "brim_width": "8",
             "outer_wall_speed": "50", "inner_wall_speed": "80",
             "outer_wall_acceleration": "1000", "flush_volumes_matrix": ["0"]}}
# Per part, on top of the plate: the caption's 1.07-1.33mm strokes as 3 walls at 0.40.
# Caption top = one outline + a monotonic top surface, the user's proven "AIToons Sopra"
# look. 3 walls with only_one_wall_top off filled the 1.1-1.3mm strokes with beads alone:
# no top surface was ever generated and Orca showed hollow outline letters.
PART_OVERRIDES = {"text": {
    "wall_loops": "2", "outer_wall_line_width": "0.4", "inner_wall_line_width": "0.4",
    "top_surface_line_width": "0.4", "internal_solid_infill_line_width": "0.4",
    "sparse_infill_line_width": "0.4", "wall_sequence": "inner wall/outer wall",
    "ironing_type": "no ironing", "top_shell_layers": "5", "bottom_shell_layers": "1",
    "only_one_wall_top": "1", "sparse_infill_density": "100%", "outer_wall_speed": "50",
    "inner_wall_speed": "80", "top_surface_speed": "40"}}
# AMS slot order per plate, fixed: relief.3mf always declares three filaments, even
# when a dry lowland poster only uses slot 1 (or 1 and 3), so the slots never shift.
SLOTS = {"relief": ("green", "water", "snow"), "frame": ("frame", "text"), "path": ("strip",)}


def _project_settings(plate):
    """Metadata/project_settings.config for one plate, as a dict."""
    colours = [COLORS[k] for k in SLOTS[plate]]
    n = len(colours)
    cfg = {**_ORCA["machine"], **_ORCA["process"],
           **{k: v * n if isinstance(v, list) and len(v) == 1 else v
              for k, v in _ORCA["filament"].items()}}
    cfg.update(version="2.3.2", **{"from": "project"}, name="project_settings",
               printer_settings_id=PRINTER, print_settings_id=PROCESS,
               print_compatible_printers=[PRINTER], filament_settings_id=[FILAMENT] * n,
               filament_ids=["GFA00"] * n, curr_bed_type="Textured PEI Plate",
               filament_colour=colours, filament_multi_colour=colours,
               filament_colour_type=["1"] * n, default_filament_colour=[""] * n,
               filament_map=["1"] * n, filament_map_mode="Auto For Flush",
               flush_volumes_vector=["140"] * 2 * n, flush_multiplier=["1"],
               wipe_tower_rotation_angle="0", wipe_tower_x=[f"{TOWER_X:g}"],
               wipe_tower_y=[f"{BRIM_MM:g}"])
    cfg.update(COMMON)
    cfg.update(PLATES[plate])
    # Orca's GUI only treats the keys listed here as "(modified)" over the named system
    # presets: [print, filament 1..n, printer]. Left out, the first edit + save in the GUI
    # wrote the bare 0.24mm Draft preset back (classic walls, 35mm tower, 15% crosshatch)
    # with only the user's own change on top. The CLI slices the full config either way.
    first = lambda v: v[0] if isinstance(v, list) else v
    over = {k for k in {**COMMON, **PLATES[plate]} if k != "flush_volumes_matrix"}  # project-level
    fil = {k for k in over if k in _ORCA["filament"]}
    mach = {k for k in over - fil if k in _ORCA["machine"]}
    proc = over - fil - mach
    diff = lambda keys, base, i=None: ";".join(sorted(
        k for k in keys if str(cfg[k][i] if i is not None else first(cfg[k])) != str(first(base.get(k)))))
    cfg["different_settings_to_system"] = (
        [diff(proc, _ORCA["process"])]
        + [diff({k for k in fil if isinstance(cfg[k], list)}, _ORCA["filament"], i) for i in range(n)]
        + [diff(mach, _ORCA["machine"])])
    cfg["inherits_group"] = [""] * (n + 2)   # all three are system presets, nothing inherited
    return cfg


def write_3mf(bodies, plate=None):
    """[(mesh, name, "#RRGGBB", extruder_slot), ...] -> OrcaSlicer project 3MF bytes.

    ONE build item: the bodies are components of a single container object, the
    standard 3MF/Bambu multi-part form. One <item> per body made Bambu Studio treat
    them as N independent models, drop each to the bed and auto-arrange — which
    destroys the co-registration every body is meshed to share.
    Per-body <basematerials> stay for the display colour in non-Bambu viewers;
    the filament slots live in Bambu's Metadata/model_settings.config, per <part>
    (the old object-level extruder key left the slots unassigned). Written by hand:
    trimesh's 3MF support is export-only via lib3mf and carries neither.

    `plate` picks the print settings (PLATES); by default it follows the first body.
    The bodies keep their local frame — check_output.py measures raw vertices — and
    the item alone carries the bed placement: centred in x, centred in y in the space
    behind the prime tower, dropped onto the bed (the strip's own floor is at 1.16)."""
    import zipfile
    plate = plate or {"frame": "frame", "strip": "path"}.get(bodies[0][1], "relief")
    cfg = _project_settings(plate)
    assert max(b[3] for b in bodies) <= len(cfg["filament_colour"]), "slot without a filament"
    assert len(bodies) < 100, "basematerials ids are oid+100 — they'd collide"
    lo = np.min([m.bounds[0] for m, *_ in bodies], 0)
    hi = np.max([m.bounds[1] for m, *_ in bodies], 0)
    tx = PLATE_MM / 2 - (lo[0] + hi[0]) / 2
    ty = (PLATE_MM + TOWER_MM + TOWER_GAP_MM) / 2 - (lo[1] + hi[1]) / 2   # 138 - h/2
    tz = 0.0 - lo[2]   # not -lo[2]: that writes "-0.0000" for a body already on the bed
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
        over = "".join(f'<metadata key="{k}" value="{v}"/>'
                       for k, v in PART_OVERRIDES.get(name, {}).items())
        parts.append(f'<part id="{oid}" subtype="normal_part">'
                     f'<metadata key="name" value="{name}"/>'
                     f'<metadata key="extruder" value="{slot}"/>{over}</part>')
    cid = len(bodies) + 1
    top = bodies[0][1]
    objs.append(f'<object id="{cid}" name="{top}" type="model">'
                f'<components>{"".join(comps)}</components></object>')
    settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
                f'<object id="{cid}"><metadata key="name" value="{top}"/>'
                f'<metadata key="flush_into_objects" value="0"/>{"".join(parts)}</object>\n'
                '</config>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">'
             '<metadata name="Application">BambuStudio-2.3.2</metadata>'
             '<metadata name="BambuStudio:3mfVersion">1</metadata>'
             f'<resources>{"".join(objs)}</resources>'
             f'<build><item objectid="{cid}" transform="1 0 0 0 1 0 0 0 1 '
             f'{tx:.4f} {ty:.4f} {tz:.4f}" printable="1"/></build></model>')
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
        z.writestr("Metadata/model_settings.config", settings)
        z.writestr("Metadata/project_settings.config", json.dumps(cfg, indent=1))
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
