"""Test print for the glowing lid: two lithophane discs and the ring that holds them on the light.

  lid_A_contours.3mf   white, Zermatt contour map + ten thickness steps round the edge
  lid_B_city.3mf       white, Zurich old-town city map + the caption round the edge
  lid_ring.3mf         black, slips over the light's top edge and holds either disc

Every size comes from the light. The default is a GUESS (96 mm across), so measure the
light and rerun. Works from any folder, in any terminal:

  python3 ~/Desktop/lid-test-print/make_lid_test.py --light-d 96.0

Sketch-tested recipe rules (docs: the lid page). Map data is cached next to this script.
"""
import argparse, hashlib, math, os, pickle, re, subprocess, sys, time, zipfile
from pathlib import Path

REPO = Path.home() / "Documents/AI Toons/Scripts/Activity Path Poster"
sys.path.insert(0, str(REPO))
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import trimesh
    import activity, poster
except ImportError:
    # started from another project's Python (e.g. the Flight Path Poster venv): rerun this
    # script inside the Activity Path Poster's own environment, once
    if os.environ.get("LID_TEST_RELAUNCHED"):
        raise
    os.environ["LID_TEST_RELAUNCHED"] = "1"
    os.environ.pop("VIRTUAL_ENV", None)
    os.execvp("uv", ["uv", "run", "--project", str(REPO), "python", str(Path(__file__).resolve()), *sys.argv[1:]])

HERE = Path(__file__).resolve().parent
ORCA = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"

# thickness (mm) -> brightness: thin glows, thick is dark. Tops snap to the 0.1 mm layer grid.
LAYER, FIRST = 0.1, 0.2
T_ROUTE, T_WATER, T_LINE, T_DARK = 0.6, 0.7, 1.0, 3.0
WEDGE = (0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.4, 2.8, 3.2)    # clockwise from 12 o'clock
T_MAX = max(WEDGE)
ROUTE_MM, HALO_MM = 1.1, 0.8      # bright route line, dark edge each side (thinner melts)
LINE_MM = 0.85                    # contour lines and streets: the thinnest clean 2-bead line
BAND_MM = 8.0                     # caption / wedge band round the map
NICE = (5, 10, 20, 25, 50, 100, 200, 250, 500)

# the old-town loop used in the previews (synthetic 5 km)
OLD_TOWN = [(47.3769, 8.5417), (47.3741, 8.5399), (47.3706, 8.5392), (47.3672, 8.5399), (47.3660, 8.5440),
            (47.3690, 8.5460), (47.3725, 8.5455), (47.3752, 8.5440), (47.3775, 8.5438), (47.3769, 8.5417)]


# ------------------------------------------------------------------ helpers ----
def grow(m, px):
    if px <= 0:
        return m
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * px + 1))) > 127


def edges2(c):
    """Pixels where an integer level map changes, 2 px wide."""
    e = (np.diff(c, axis=0, prepend=c[:1]) != 0) | (np.diff(c, axis=1, prepend=c[:, :1]) != 0)
    return e | np.roll(e, -1, 0) | np.roll(e, -1, 1)


def line_mask(px, width_mm, res):
    """A line mask about width_mm wide from a 2 px edge mask."""
    return grow(px, max(0, round((width_mm / res - 2) / 2)))


def norm(a, p=(2, 98)):
    lo, hi = np.percentile(a, p)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def hillshade(e, cell_m):
    gy, gx = np.gradient(e, cell_m)
    n = np.dstack([-gx, gy, np.ones_like(gx)])          # rows run south, so +gy faces north
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array((-0.55, 0.6, 0.58)) / np.linalg.norm((-0.55, 0.6, 0.58))
    return np.clip(n @ L, 0, 1)


def overpass(bounds, members, tag):
    """Overpass elements for the bbox, cached on disk next to this script (map data only)."""
    w, s = poster._unmerc(bounds[0], bounds[1])
    e, n = poster._unmerc(bounds[2], bounds[3])
    q = ('[out:json][timeout:120][maxsize:536870912][bbox:%f,%f,%f,%f];(%s);out geom;'
         % (s, w, n, e, "".join(members)))
    f = HERE / "map_cache" / f"{tag}_{hashlib.sha1(q.encode()).hexdigest()[:12]}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    for attempt in range(3):
        try:
            els = poster._overpass(q)
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(pickle.dumps(els))
            return els
        except RuntimeError as err:
            print("  overpass retry", attempt + 1, str(err)[:80])
            poster._overpass.cache_clear()
            time.sleep(20)
    raise RuntimeError("Overpass unavailable; try again in a few minutes")


WATER = ('way["natural"="water"];relation["natural"="water"];'
         'way["waterway"="riverbank"];relation["waterway"="riverbank"];')


# --------------------------------------------------------------- the disc map ----
class Lid:
    """Vertex grid for the disc: res mm per px, centre at the middle, row 0 = north."""

    def __init__(self, legs, RD, res):
        self.res, self.RD = res, RD
        self.map_r = RD - BAND_MM
        self.n = int(round(2 * RD / res)) + 1
        c = (self.n - 1) / 2
        yy, xx = np.mgrid[0:self.n, 0:self.n]
        self.x, self.y = (xx - c) * res, (c - yy) * res              # mm, y north
        self.r = np.hypot(self.x, self.y)
        # bounds so the route fills ~82% of the map circle, and the raster covers the whole disc
        xy = np.array([poster._merc(la, lo) for l in legs for la, lo in zip(l.lat, l.lon)])
        cx, cy = (xy[:, 0].min() + xy[:, 0].max()) / 2, (xy[:, 1].min() + xy[:, 1].max()) / 2
        half = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy).max() / 0.82 * RD / self.map_r
        self.b = (cx - half, cy - half, cx + half, cy + half)
        lat = math.degrees(math.atan(math.sinh(cy)))
        self.width_m = 2 * half * 6371000 * math.cos(math.radians(lat))
        self.mpm = self.width_m / (2 * RD)                              # ground m per printed mm
        self.cell_m = self.width_m / self.n
        self.legs = legs
        print(f"  map {self.width_m / 1000 * self.map_r / RD:.1f} km across the {2 * self.map_r:.0f} mm map,"
              f" {self.mpm:.0f} m per mm")
        self.elev = np.asarray(poster.fetch_elevation(self.b, self.n), float)

    def route(self):
        img = Image.new("L", (self.n, self.n), 0)
        d = ImageDraw.Draw(img)
        for l in self.legs:
            d.line([tuple(p) for p in poster._to_px(list(zip(l.lat, l.lon)), self.b, self.n)],
                   fill=255, width=max(3, round(ROUTE_MM / self.res)), joint="curve")
        return np.asarray(img) > 127

    def finish(self, T, water):
        """Shared by both recipes: lakes bright, the route brightest with a dark edge."""
        T = T.copy()
        T[water] = T_WATER
        route = self.route()
        T[grow(route, round(HALO_MM / self.res)) & ~route] = T_DARK
        T[route] = T_ROUTE
        return T


def contour_map(lid, water):
    """Recipe 5: even glow, dark contour lines; round spacing, >= 2 mm apart on the steep tenth."""
    e = poster._smooth(lid.elev, max(1, round(0.65 / lid.res)))
    gy, gx = np.gradient(e, lid.cell_m)
    inside = lid.r < lid.map_r
    need = max((np.percentile(e[inside], 99) - np.percentile(e[inside], 1)) / 12,
               2.0 * lid.mpm * np.percentile(np.hypot(gx, gy)[inside], 90))
    iv = next((v for v in NICE if v >= need), NICE[-1])
    T = np.full(e.shape, 1.2)
    T[line_mask(edges2(np.floor(e / iv)), LINE_MM, lid.res)] = 2.6
    T[line_mask(edges2(np.floor(e / (5 * iv))), 1.25, lid.res)] = T_DARK
    print(f"  contour lines every {iv} m, bold every {5 * iv} m")
    return lid.finish(T, water)


def city_map(lid, els):
    """Recipe 7: streets dark, buildings half dark, water bright; streets/buildings only when zoomed in."""
    tag = lambda el, k: (el.get("tags") or {}).get(k)
    pts = lambda el: [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
    ok = {hw for name, lim, rx in poster.ROAD_TIERS if lid.mpm <= lim and name != "trails" for hw in rx.split("|")}
    ok.discard("service")            # driveways and parking aisles: clutter at this size
    w = max(3, round(LINE_MM / lid.res))
    roads = [(pts(el), w) for el in els if tag(el, "highway") in ok and not tag(el, "tunnel") and len(pts(el)) >= 2]
    roads += [(pts(el), w) for el in els if tag(el, "railway") == "rail" and not tag(el, "tunnel")
              and not tag(el, "service") and len(pts(el)) >= 2]
    sh = norm(hillshade(lid.elev, lid.cell_m))
    T = 1.0 + 0.3 * (1 - sh)
    if lid.mpm <= 30:
        T[poster._water_mask_from_elements([el for el in els if tag(el, "building")], lid.b, lid.n)] = 2.0
    T[poster._road_mask(roads, lid.b, lid.n)] = 2.7
    water = poster._water_mask_from_elements([el for el in els if tag(el, "natural") == "water"
                                              or tag(el, "waterway") == "riverbank"], lid.b, lid.n)
    print(f"  {len(roads)} streets and rail lines" + (", buildings" if lid.mpm <= 30 else ", no buildings (too small)"))
    return lid.finish(T, water)


def arc_text(lid, text, cap_mm):
    """Caption along the bottom arc of the band, reading left to right, tops toward the centre."""
    size = int(round(cap_mm / 0.7 / lid.res))
    path, index = poster.FONT_PATHS[0]
    f = ImageFont.truetype(path, size, index=index)
    img = Image.new("L", (lid.n, lid.n), 0)
    c = (lid.n - 1) / 2
    radius = (lid.RD - BAND_MM / 2 - 0.3) / lid.res
    track = 0.5 / lid.res
    total = sum(f.getlength(ch) + track for ch in text)
    a = math.pi / 2 + total / radius / 2
    for ch in text:
        adv = f.getlength(ch) + track
        mid = a - adv / 2 / radius
        g = Image.new("L", (size * 2, size * 2), 0)
        ImageDraw.Draw(g).text((size, size), ch, font=f, fill=255, anchor="mm")
        g = g.rotate(math.degrees(math.pi / 2 - mid), resample=Image.BICUBIC)
        img.paste(g, (int(c + radius * math.cos(mid) - size), int(c + radius * math.sin(mid) - size)), g)
        a -= adv / radius
    return grow(np.asarray(img) > 127, 1)          # one pixel more: glowing strokes ~0.9 mm


def disc(lid, Tmap, band):
    """Map inside, the band (wedge or caption) round it, solid rim; snapped to the layer grid."""
    r, mr = lid.r, lid.map_r
    T = np.full(Tmap.shape, T_DARK)
    T[r < mr] = Tmap[r < mr]
    T[(r >= mr) & (r < mr + 0.6)] = T_LINE
    if band == "wedge":
        ang = np.degrees(np.arctan2(lid.x, lid.y)) % 360
        seg = (r > mr + 1.2) & (r < lid.RD - 1.4)
        k = np.minimum((ang / 36).astype(int), 9)
        T[seg] = np.asarray(WEDGE)[k[seg]]
        T[seg & ((ang % 36) < 1.5)] = T_DARK
    else:
        T[arc_text(lid, band, 3.6) & (r > mr + 0.6)] = 0.8
    T[r > lid.RD - 1.0] = T_DARK
    T = np.maximum(T_ROUTE, FIRST + np.round((T - FIRST) / LAYER) * LAYER)
    return np.round(T, 3)


def disc_mesh(lid, T):
    inside = lid.r <= lid.RD
    m = poster._slab_mesh(poster._slab_cells(inside), T, np.zeros_like(T), lid.res)
    m.vertices[:, :2] -= (lid.n - 1) / 2 * lid.res               # centre on the origin
    return m


def preview(lid, T, name):
    """What the lid should look like lit (same model as the page's renders)."""
    k = 1.1
    lo, hi = math.exp(-k * T_MAX), math.exp(-k * T_ROUTE)
    b = np.clip((np.exp(-k * T) - lo) / (hi - lo), 0, 1)
    b = np.asarray(Image.fromarray((b * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.45 / lid.res)), float) / 255
    img = 255 * (1 - np.exp(-2.6 * b[..., None] * np.array((1.0, 0.68, 0.36))))
    img[lid.r > lid.RD] = (20, 18, 16)
    Image.fromarray(img.astype(np.uint8)).resize((700, 700), Image.LANCZOS).save(HERE / f"{name}_preview.jpg", quality=88)


# ------------------------------------------------------------------- the ring ----
def ring_profile(a):
    """(r, z) outline of the ring, z = 0 at the lamp's top edge. A sleeve grips the lamp, a seat
    rests on its edge, flaring out (45 deg, no support) to a cup round the wider disc. The disc
    floats in the cup on the lamp's button (plus a spacer); the stop ledge a.float below it ends
    the press, so the whole map is the switch."""
    rs = a.light_d / 2 + a.fit                     # sleeve inner radius
    rc = a.disc_d / 2 + a.disc_fit                 # cup inner radius
    ro = max(rc, rs) + a.wall
    flare = ro - (rs + a.wall)                     # 45 deg flare, ending at the stop ledge's height
    assert a.stop - flare > -a.sleeve + 0.8, "sleeve too short for the flare out to the disc"
    top = a.stop + a.float + T_MAX + 0.4
    ch = 0.6                                       # lead-in chamfer at the sleeve mouth
    return [(rs + ch, -a.sleeve), (rs + a.wall, -a.sleeve), (rs + a.wall, a.stop - flare), (ro, a.stop),
            (ro, top), (rc, top), (rc, a.stop), (rs - a.ledge, a.stop), (rs - a.ledge, 0.0),
            (rs, 0.0), (rs, -a.sleeve + ch)]


def ring_mesh(a):
    prof = ring_profile(a)
    m = trimesh.creation.revolve(np.array(prof + prof[:1]), sections=360)
    if m.volume < 0:
        m.invert()
    return m


SPACERS = (0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.2)   # mm; the height is engraved on top


def spacer_bodies(d=10.0, res=0.05):
    """Coins that sit on the lamp's button under the disc's centre: pick the one that makes the
    disc float just clear of the stop ledge, so a press on the map clicks the button."""
    n = int(round(d / res)) + 1
    c = (n - 1) / 2
    yy, xx = np.mgrid[0:n, 0:n]
    cells = poster._slab_cells(np.hypot(xx - c, yy - c) * res <= d / 2)
    path, index = poster.FONT_PATHS[0]
    f = ImageFont.truetype(path, int(round(2.6 / 0.7 / res)), index=index)
    out = []
    for i, h in enumerate(SPACERS):
        img = Image.new("L", (n, n), 0)
        ImageDraw.Draw(img).text((c, c), f"{h:.1f}", font=f, fill=255, anchor="mm")
        top = np.where(np.asarray(img) > 127, h - 0.2, h)        # 0.2 mm deep label
        m = poster._slab_mesh(cells, top, np.zeros_like(top), res)
        m.vertices[:, 0] += i * (d + 4)
        out.append((m, f"spacer_{h:.1f}", "#FFFFFF", 1))
    return out


def section_png(a, button_mm=0.8):
    """Cut-away of lamp, button, spacer, disc and ring; heights drawn 3x so the gaps show."""
    s, k, W, H = 7.0, 3.0, 1120, 420
    ox, oz = 400, 250
    P = lambda r, z: (ox + r * s, oz - z * s * k)
    im = Image.new("RGB", (W, H), (246, 243, 236))
    d = ImageDraw.Draw(im)
    path, index = poster.FONT_PATHS[0]
    f = ImageFont.truetype(path, 15, index=index)
    L, R = a.light_d / 2, a.disc_d / 2
    zb = a.stop + a.float                                        # disc bottom at rest
    d.rectangle([P(-L, 0), P(L, -a.sleeve - 6)], fill=(150, 150, 150))                    # lamp
    d.rectangle([P(-L + 3, 0), P(L - 3, -0.35)], fill=(250, 200, 90))                      # its light
    d.rectangle([P(-5, button_mm), P(5, 0)], fill=(70, 70, 70))                            # button
    d.rectangle([P(-5, zb), P(5, button_mm)], fill=(255, 255, 255), outline=(60, 60, 60))  # spacer
    d.rectangle([P(-R, zb + 2.2), P(R, zb)], fill=(255, 255, 255), outline=(60, 60, 60))   # disc
    for sgn in (1, -1):
        d.polygon([P(sgn * r, z) for r, z in ring_profile(a)], fill=(34, 34, 34))
    d.line([P(0, zb + 7), P(0, zb + 2.6)], fill=(180, 70, 30), width=4)
    d.polygon([P(-1.6, zb + 3.6), P(1.6, zb + 3.6), P(0, zb + 2.5)], fill=(180, 70, 30))
    txt = [((0, zb + 7.6), "press anywhere on the map", (180, 70, 30)),
           ((R + 6, zb + 1.2), "disc floats in the cup", (40, 40, 40)),
           ((R + 6, a.stop - 0.6), f"stop ledge, {a.float:g} mm below", (40, 40, 40)),
           ((10, button_mm + 0.2), "spacer coin, if needed", (40, 40, 40)),
           ((-L + 4, -2.5), f"lamp {a.light_d:g} mm", (255, 255, 255)),
           ((-R + 4, zb + 1.1), f"lithophane disc {a.disc_d:g} mm", (40, 40, 40))]
    for (r, z), t, col in txt:
        x, y = P(r, z)
        d.text((x, y), t, font=f, fill=col, anchor="mm" if r == 0 else "lm")
    d.text((10, H - 22), "cut-away, heights drawn 3x", font=f, fill=(120, 120, 120))
    im.save(HERE / "ring_section.png")


# ------------------------------------------------------------- Orca projects ----
poster.SLOTS |= {"lid": ("text",), "lid_ring": ("frame",), "lid_spacers": ("text",)}   # white, black, white
poster.PLATES |= {
    # solid all the way through (every layer within 40 of a top), fine layers, one filament
    "lid": {"layer_height": f"{LAYER:g}", "initial_layer_print_height": f"{FIRST:g}",
            "enable_prime_tower": "0", "wall_loops": "2", "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag", "top_shell_layers": "40", "bottom_shell_layers": "4",
            "ironing_type": "no ironing", "brim_type": "no_brim", "brim_width": "0"},
    "lid_ring": {"layer_height": "0.2", "initial_layer_print_height": "0.2", "enable_prime_tower": "0",
                 "wall_loops": "3", "sparse_infill_density": "15%", "top_shell_layers": "4",
                 "bottom_shell_layers": "4", "ironing_type": "no ironing", "brim_type": "no_brim",
                 "brim_width": "0"}}
poster.PLATES["lid_spacers"] = poster.PLATES["lid_ring"]


def write_bodies(bodies, name, plate):
    for m, *_ in bodies:
        assert m.is_watertight, f"{name} is not watertight"
    f = HERE / f"{name}.3mf"
    f.write_bytes(poster.write_3mf(bodies, plate=plate))
    print(f"  wrote {f.name}: {len(bodies)} part(s)")
    return f


def write(mesh, name, plate, colour):
    assert mesh.is_watertight, f"{name} is not watertight"
    f = HERE / f"{name}.3mf"
    f.write_bytes(poster.write_3mf([(mesh, name, colour, 1)], plate=plate))
    ext = mesh.bounds[1] - mesh.bounds[0]
    print(f"  wrote {f.name}: {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.2f} mm, {len(mesh.faces)} triangles")
    return f


def slice_check(f):
    """Slice headless with the settings the file carries; report time and filament."""
    if not os.path.exists(ORCA):
        return "OrcaSlicer not found, not sliced"
    out = HERE / "sliced" / f.stem
    out.mkdir(parents=True, exist_ok=True)
    (out / "plate_1.gcode").unlink(missing_ok=True)
    r = subprocess.run([ORCA, "--slice", "0", "--export-3mf", "sliced.3mf", "--outputdir", str(out), str(f)],
                       capture_output=True, timeout=1200)
    if r.returncode != 0:
        return f"SLICE FAILED ({r.returncode}): {r.stdout[-400:]!r}"
    (out / "plate_1.gcode").unlink(missing_ok=True)      # the same G-code is inside sliced.3mf
    g = zipfile.ZipFile(out / "sliced.3mf").read("Metadata/plate_1.gcode").decode(errors="replace")
    pick = lambda pat: (re.search(pat, g) or [None, "?"])[1]
    return (f"sliced OK: layer {pick(r'; layer_height = (.*)')} mm, "
            f"time {pick(r'model printing time: ([^;]*)')}, "
            f"{pick(r'; filament used \[g\] = (.*)')} g")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--light-d", type=float, default=84.0, help="outer diameter of the lamp's top edge, mm (measured)")
    ap.add_argument("--disc-d", type=float, default=94.1, help="lithophane disc diameter, mm (the printed test discs)")
    ap.add_argument("--sleeve", type=float, default=5.0, help="how far the ring reaches down the lamp's side, mm (stays above the seam)")
    ap.add_argument("--stop", type=float, default=1.2, help="stop ledge height above the lamp's top edge, mm")
    ap.add_argument("--float", type=float, default=0.8, help="how far the disc can be pressed before the stop, mm")
    ap.add_argument("--ledge", type=float, default=1.6, help="how far the seat reaches in over the lamp's edge, mm")
    ap.add_argument("--ring-only", action="store_true", help="only the ring, spacers and drawing; keep the discs")
    ap.add_argument("--wall", type=float, default=2.0, help="ring wall, mm")
    ap.add_argument("--fit", type=float, default=0.2, help="ring to light clearance per side, mm")
    ap.add_argument("--disc-fit", type=float, default=0.3, help="disc to ring clearance per side, mm")
    ap.add_argument("--res", type=float, default=0.15, help="mesh resolution, mm")
    ap.add_argument("--gpx", default=str(Path.home() / "Desktop/zermatt-trail-run/Zermatt_Trail_Run.gpx"),
                    help="route for disc A (contours)")
    ap.add_argument("--no-slice", action="store_true")
    a = ap.parse_args()

    RD = a.disc_d / 2
    print(f"lamp {a.light_d} mm, disc {a.disc_d} mm, map {2 * (RD - BAND_MM):.1f} mm")
    files = []

    if not a.ring_only:
        files += discs(a, RD)

    print("ring, spacers, drawing")
    files.append(write(ring_mesh(a), "lid_ring", "lid_ring", "#222222"))
    files.append(write_bodies(spacer_bodies(), "lid_spacers", "lid_spacers"))
    section_png(a)

    if not a.no_slice:
        print("slicing with OrcaSlicer (headless)")
        for f in files:
            print(f"  {f.name}: {slice_check(f)}")


def discs(a, RD):
    files = []
    print("disc A: contour lines + thickness steps")
    legs = activity.read_activity([(Path(a.gpx).name, open(a.gpx, "rb"))])
    lid = Lid(legs, RD, a.res)
    water = poster._water_mask_from_elements(overpass(lid.b, [WATER], "water"), lid.b, lid.n)
    T = disc(lid, contour_map(lid, water), "wedge")
    preview(lid, T, "lid_A_contours")
    files.append(write(disc_mesh(lid, T), "lid_A_contours", "lid", "#FFFFFF"))

    print("disc B: city map + caption")
    la, lo = np.array([p for (p0, p1) in zip(OLD_TOWN[:-1], OLD_TOWN[1:])
                       for p in [(p0[0] + (p1[0] - p0[0]) * i / 60, p0[1] + (p1[1] - p0[1]) * i / 60)
                                 for i in range(60)]]).T
    city = [activity.Leg("run", la, lo, np.arange(len(la), dtype=float), np.full(len(la), np.nan), "old-town")]
    lid = Lid(city, RD, a.res)
    els = overpass(lid.b, [WATER, 'way["highway"];way["railway"="rail"];way["building"];'], "city")
    T = disc(lid, city_map(lid, els), "ZÜRICH OLD TOWN 5K  ·  5.0 KM  ·  12.10.2026")
    preview(lid, T, "lid_B_city")
    files.append(write(disc_mesh(lid, T), "lid_B_city", "lid", "#FFFFFF"))
    return files


if __name__ == "__main__":
    main()
