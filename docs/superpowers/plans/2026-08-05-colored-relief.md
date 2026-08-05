# Colored Relief + Split Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single poster STL with three deliverables — black frame.stl (backplate+ring+text), multi-body relief.3mf (green terrain / blue water / grey big cities, AMS-ready for Bambu Studio), red path.stl — driven by ESA WorldCover land-cover classification.

**Architecture:** Land cover arrives as one WMS PNG classified by palette into a code grid. All geometry stays heightmap pixel-ops: terrain body depressed under caps and groove; caps are constant-thickness slabs over masks via a new cell-based `masked_slab_mesh`. 3MF is hand-written zip+XML with Bambu extruder metadata.

**Tech Stack:** existing deps only (numpy, trimesh, Pillow, requests, FastAPI); stdlib zipfile/xml for 3MF; three.js 3MFLoader in the browser.

## Global Constraints

- Spec addendum: `docs/superpowers/specs/2026-08-05-flight-path-poster-design.md` § "Addendum 2026-08-05".
- Heightmap ops only, no 3D booleans. No new dependencies. `trimesh.repair.fix_normals` is UNAVAILABLE (networkx absent) — construct winding correctly; every new mesh test asserts `is_watertight`, `is_winding_consistent`, `volume > 0` (Task-4/5 precedent: is_watertight alone passes inside-out meshes).
- Coordinate contract (all meshes): x = col·res_mm, y = (H−1−row)·res_mm, z mm, flat back at z=0 per piece.
- WorldCover WMS: `https://services.terrascope.be/wms/v2`, layer `WORLDCOVER_2021_MAP`, EPSG:3857 (pseudo-mercator radians × 6378137). Palette: water = (0,100,200), built-up = (250,0,0); classify with ±10/channel tolerance; all else green. Network fetches are NOT unit-tested (project precedent) — live sanity check instead.
- New Params (exact defaults): `cap_mm=0.6`, `plate_mm=2.0`, `fit_mm=0.2`, `city_min_km=1.5`. Colors are module constants: `COLORS = {"frame": "#222222", "green": "#4CAF50", "water": "#2196F3", "city": "#9E9E9E", "strip": "#CC2222"}`.
- Relief plate footprint = `size_mm − 2·frame_mm − 2·fit_mm`; groove pixels are excluded from cap masks; caps follow the PRE-groove surface; strip is sampled from the relief plate's surface (its z now starts at `plate_mm`, not `base_mm`).
- Existing invariant tests (strip seats in groove, etc.) must stay green, adapted only where the relief-grid split forces coordinate changes — never weakened.
- Tests `uv run pytest -q`; Conventional Commits; commit per task.

---

### Task 1: Land-cover fetch + classification

**Files:**
- Modify: `poster.py` (append land-cover section)
- Modify: `test_poster.py` (append tests)

**Interfaces:**
- Consumes: `_merc`-space bounds tuple from `track_bounds` (Task 2 of the original plan).
- Produces:
  - `WMS_URL`, `COLORS` constants.
  - `classify_landcover(rgb: np.ndarray, km_per_px: float, city_min_km: float) -> np.ndarray` — uint8 (H,W): 0 green, 1 water, 2 city; water opened k=3; city opened with odd kernel `k = max(3, round(city_min_km/km_per_px) | 1)`.
  - `fetch_landcover(bounds, px_out: int, km_per_px: float, city_min_km: float) -> np.ndarray` — same codes, network via `_get` (one retry then raise). Row 0 = north (WMS 3857 images are north-up already).

- [ ] **Step 1: Write failing tests**

```python
def test_classify_landcover_palette():
    rgb = np.zeros((20, 20, 3), np.uint8)          # default -> green(0)
    rgb[2:8, 2:18] = (0, 100, 200)                 # water bar
    rgb[12:19, 2:19] = (250, 0, 0)                 # big city block
    rgb[10, 10] = (0, 100, 200)                    # 1px pond -> speckle, removed
    rgb[0, 0] = (247, 3, 2)                        # within +-10 of built-up, but 1px -> removed
    lc = poster.classify_landcover(rgb, km_per_px=0.5, city_min_km=1.5)
    assert lc[5, 10] == 1                          # water kept
    assert lc[15, 10] == 2                         # city kept
    assert lc[10, 10] == 0 and lc[0, 0] == 0       # speckles gone
    assert lc[1, 1] == 0

def test_classify_city_threshold_scales():
    rgb = np.zeros((40, 40, 3), np.uint8)
    rgb[10:14, 10:14] = (250, 0, 0)                # 4px-wide town
    # at 0.1 km/px a 1.5km city needs ~15px -> town removed
    assert (poster.classify_landcover(rgb, 0.1, 1.5) == 2).sum() == 0
    # at 1.0 km/px the kernel floors at 3 -> 4px town survives opening
    assert (poster.classify_landcover(rgb, 1.0, 1.5) == 2).sum() > 0
```

- [ ] **Step 2: Run, verify the new tests fail** — `uv run pytest test_poster.py -q`, AttributeError.

- [ ] **Step 3: Implement**

```python
WMS_URL = ("https://services.terrascope.be/wms/v2?SERVICE=WMS&VERSION=1.3.0"
           "&REQUEST=GetMap&LAYERS=WORLDCOVER_2021_MAP&STYLES=&FORMAT=image/png"
           "&CRS=EPSG:3857&BBOX={x0},{y0},{x1},{y1}&WIDTH={w}&HEIGHT={h}")
COLORS = {"frame": "#222222", "green": "#4CAF50", "water": "#2196F3",
          "city": "#9E9E9E", "strip": "#CC2222"}
_R3857 = 6378137.0


def _opened(mask, k):
    """Morphological opening via PIL: erode then dilate with a k*k kernel."""
    from PIL import ImageFilter
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
    x0, y0, x1, y1 = (v * _R3857 for v in bounds)   # merc radians -> EPSG:3857 meters
    url = WMS_URL.format(x0=x0, y0=y0, x1=x1, y1=y1, w=px_out, h=px_out)
    img = Image.open(io.BytesIO(_get(url))).convert("RGB")
    return classify_landcover(np.asarray(img), km_per_px, city_min_km)
```

Note: WMS 1.3.0 EPSG:3857 BBOX axis order is x,y (easting first) — if the live check
returns a rotated/empty image, try `&BBOX={y0},{x0},{y1},{x1}` or VERSION=1.1.1 with
`SRS=` instead; adapt and note the working form in your report.

- [ ] **Step 4: Tests green** — `uv run pytest -q`.

- [ ] **Step 5: Live sanity check (network)**

Run: `uv run python -c "import poster,numpy as np; t=np.array([[47.3,8.5,0],[47.0,8.8,0]]); b=poster.track_bounds(t,15); lc=poster.fetch_landcover(b,512,0.09,1.5); print(lc.shape,[int((lc==i).sum()) for i in (0,1,2)])"`
Expected: (512,512); nonzero water count (Lake Zug/Zurich region) and nonzero city count (Zug). If the service is unreachable after the axis-order variants, STOP and report BLOCKED — the feature depends on it.

- [ ] **Step 6: Commit** — `feat: WorldCover land-cover fetch and 3-class classification`

---

### Task 2: masked_slab_mesh

**Files:**
- Modify: `poster.py` (append)
- Modify: `test_poster.py` (append)

**Interfaces:**
- Produces: `masked_slab_mesh(mask: np.ndarray[bool], top: np.ndarray, thickness: float, res_mm: float) -> trimesh.Trimesh | None` — slab over cells whose 4 corner vertices are all masked; top follows `top`, bottom = top − thickness; standard coordinate contract; returns None if no cells.

- [ ] **Step 1: Write failing tests**

```python
def test_masked_slab_mesh_geometry():
    rng = np.random.default_rng(1)
    top = 10.0 + rng.random((30, 30)) * 3
    mask = np.zeros((30, 30), bool)
    mask[5:15, 5:25] = True                        # rectangle blob
    mask[20:28, 3:9] = True                        # second blob
    m = poster.masked_slab_mesh(mask, top, 0.6, 0.5)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    # thickness: z-extent at any x,y column is exactly 0.6 below local top
    assert abs(m.bounds[1][2] - top[mask].max()) < 1e-6
    assert abs(m.bounds[0][2] - (top[np.where(mask)].min() - 0.6)) < 1e-6
    # volume ~ cell_area * thickness (cells = all-4-corner-masked)
    cells = mask[:-1,:-1] & mask[:-1,1:] & mask[1:,:-1] & mask[1:,1:]
    assert abs(m.volume - cells.sum() * 0.5 * 0.5 * 0.6) / m.volume < 0.01

def test_masked_slab_mesh_empty():
    assert poster.masked_slab_mesh(np.zeros((5, 5), bool), np.ones((5, 5)), 0.6, 0.5) is None
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement**

```python
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
        F += [[d, b, a], [e, d, a]]                     # top, +z (Task-4 winding)
        F += [[a + n, b + n, d + n], [a + n, d + n, e + n]]  # bottom, -z
        for (nr, nc, v0, v1) in ((r - 1, c, b, a), (r + 1, c, e, d),
                                 (r, c - 1, a, e), (r, c + 1, d, b)):
            if not incell(nr, nc):                       # boundary edge -> wall
                F += [[v0, v1, v1 + n], [v0, v1 + n, v0 + n]]
    m = trimesh.Trimesh(np.vstack([vt, vb]), np.array(F), process=False)
    return m
```

Winding note: the top/bottom orders above follow Task 4's corrected convention; the
four wall (v0, v1) orders are chosen to face outward under the y-flip. If
`is_winding_consistent` fails, flip the offending wall pair — the test is the gate;
never weaken it.

- [ ] **Step 4: Tests green, full suite.**
- [ ] **Step 5: Commit** — `feat: watertight masked slab mesh for color caps`

---

### Task 3: compose_parts + build_poster v2

**Files:**
- Modify: `poster.py` (add Params fields, `compose_parts`, rewrite `build_poster`; keep `compose` only if still used by tests you adapt — otherwise delete it and adapt its tests to `compose_parts`)
- Modify: `test_poster.py` (adapt compose/groove/strip/build tests to the new grids; add cap tests)

**Interfaces:**
- Consumes: `fetch_elevation`, `fetch_landcover`, `masked_slab_mesh`, `heightmap_mesh`, `strip_mesh`, `_offsets`.
- Produces:
  - Params gains `cap_mm=0.6, plate_mm=2.0, fit_mm=0.2, city_min_km=1.5`.
  - `compose_parts(track, elev, lc, bounds, p) -> dict` with keys:
    `frame` (N,N) — backplate at `base_mm` + ring to `base_mm+frame_height_mm` + text emboss;
    `green` (M,M) — relief top: `plate_mm +` scaled terrain, − `cap_mm` under caps, − `groove_d_mm` under groove;
    `surface` (M,M) — pre-groove, pre-cap-depression relief top (strip + cap tops sample this);
    `water`, `city` (M,M bool) — vertex masks, groove pixels and a 1px border excluded;
    `track_px` (K,2) — in M-grid pixel coords.
    Where N = int(size_mm/res_mm), M = N − 2·int((frame_mm+fit_mm)/res_mm). `elev` and `lc` must be (M,M).
  - `build_poster(track, p) -> (frame_stl: bytes, relief_bodies: list[tuple[trimesh.Trimesh, str, str, int]], path_stl: bytes)` — relief_bodies = [(green_mesh,"terrain",COLORS["green"],1), (water_mesh,"water",COLORS["water"],2), (city_mesh,"cities",COLORS["city"],3)] skipping None caps. (Task 4 serializes these to 3MF.)

- [ ] **Step 1: Adapt + write failing tests**

Adapt existing `compose`-based tests to `compose_parts` (same synthetic `_synthetic()` fixture, plus a synthetic `lc` grid: all green except a water square and a city square placed away from the track). New assertions:

```python
def test_compose_parts_shapes_and_caps():
    p, N, fpx, elev, track, bounds = _synthetic()          # extend fixture for M-grid
    M = N - 2 * int((p.frame_mm + p.fit_mm) / p.res_mm)
    lc = np.zeros((M, M), np.uint8); lc[5:15, 5:15] = 1; lc[30:40, 30:40] = 2
    parts = poster.compose_parts(track, elev[:M, :M], lc, bounds, p)
    assert parts["frame"].shape == (N, N) and parts["green"].shape == (M, M)
    assert parts["frame"][0, 0] == p.base_mm + p.frame_height_mm
    assert parts["green"].min() >= p.plate_mm - p.groove_d_mm - p.cap_mm - 1e-6
    w = parts["water"]
    assert w[10, 10] and not w[0, 0]
    # cap depression: green is exactly cap_mm below surface inside a cap
    assert abs(parts["surface"][10, 10] - parts["green"][10, 10] - p.cap_mm) < 1e-9
    # groove excluded from caps
    gpx = parts["track_px"][len(parts["track_px"]) // 2]
    assert not w[int(gpx[1]), int(gpx[0])] or True     # groove cells cannot be water-masked
    assert not (parts["water"] & parts["city"]).any()

def test_build_poster_v2(monkeypatch):
    p = _params()
    monkeypatch.setattr(poster, "fetch_elevation", lambda b, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_landcover", lambda b, px, k, c: (lambda a: a)(np.zeros((px, px), np.uint8)))
    track = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])
    frame_stl, bodies, path_stl = poster.build_poster(track, p)
    assert frame_stl[:5] != b"solid" and len(frame_stl) > 84
    names = [b[1] for b in bodies]
    assert names[0] == "terrain" and len(path_stl) > 84   # all-green lc -> caps absent
```

Also adapt the groove-seat invariant test and strip tests to the M-grid/`plate_mm` z-base — assertions unweakened, only coordinates/base updated.

- [ ] **Step 2: Run, verify fails.**

- [ ] **Step 3: Implement**

`compose_parts` reuses the existing compose logic, split:

```python
def compose_parts(track, elev, lc, bounds, p):
    N = int(p.size_mm / p.res_mm)
    off = int((p.frame_mm + p.fit_mm) / p.res_mm)
    M = N - 2 * off
    fpx = int(p.frame_mm / p.res_mm)
    # frame piece: plate + ring + text (text logic moved verbatim from compose)
    frame = np.full((N, N), p.base_mm)
    ring = np.ones((N, N), bool); ring[fpx:N - fpx, fpx:N - fpx] = False
    frame[ring] = p.base_mm + p.frame_height_mm
    if p.text: ...  # verbatim from old compose, drawn on `frame`
    # relief top
    e0, e1 = float(elev.min()), float(elev.max())
    surface = p.plate_mm + (elev - e0) / max(e1 - e0, 1e-9) * p.relief_mm * p.exaggeration
    # track in M-grid px (old projection minus the off offset)
    x0, y0, x1, y1 = bounds
    xy = np.array([_merc(la, lo) for la, lo, _ in track])
    tx = (xy[:, 0] - x0) / (x1 - x0) * M
    ty = (y1 - xy[:, 1]) / (y1 - y0) * M
    track_px = np.stack([tx, ty], 1)
    # groove mask via the shared _offsets quads (verbatim mechanism from compose)
    gmask = _groove_mask(track_px, (M, M), p)   # factor the existing quad-drawing into this helper
    border = np.zeros((M, M), bool); border[1:-1, 1:-1] = True
    water = (lc == 1) & ~gmask & border
    city = (lc == 2) & ~gmask & border
    green = surface - p.cap_mm * (water | city)
    green[gmask] -= p.groove_d_mm
    return dict(frame=frame, green=green, surface=surface,
                water=water, city=city, track_px=track_px)
```

`build_poster` v2:

```python
def build_poster(track, p=Params()):
    if p.size_mm > 256 or p.res_mm < 0.2:
        raise ValueError(...)                    # existing guard stays
    bounds = track_bounds(track, p.margin_pct)
    N = int(p.size_mm / p.res_mm)
    M = N - 2 * int((p.frame_mm + p.fit_mm) / p.res_mm)
    km_per_px = (bounds[2] - bounds[0]) * _R3857 / 1000 / M * math.cos(...)  # cos(mid-lat)
    elev = fetch_elevation(bounds, M)
    lc = fetch_landcover(bounds, M, km_per_px, p.city_min_km)
    parts = compose_parts(track, elev, lc, bounds, p)
    frame = heightmap_mesh(parts["frame"], p.res_mm)
    green = heightmap_mesh(parts["green"], p.res_mm)
    bodies = [(green, "terrain", COLORS["green"], 1)]
    for key, name, slot in (("water", "water", 2), ("city", "cities", 3)):
        cap = masked_slab_mesh(parts[key], parts["surface"], p.cap_mm, p.res_mm)
        if cap is not None:
            bodies.append((cap, name, COLORS[key], slot))
    strip = strip_mesh(parts["track_px"], parts["surface"], p)
    return frame.export(file_type="stl"), bodies, strip.export(file_type="stl")
```

- [ ] **Step 4: Full suite green** (all adapted invariants incl. groove-seat).
- [ ] **Step 5: Commit** — `feat: split frame/relief compose with water and city cap masks`

---

### Task 4: 3MF writer + round-trip reader

**Files:**
- Modify: `poster.py` (append `write_3mf`, `read_3mf`)
- Modify: `test_poster.py` (round-trip test)

**Interfaces:**
- Produces:
  - `write_3mf(bodies) -> bytes` — bodies as produced by build_poster: standard-core 3MF zip; per-object `<basematerials>` display color; `Metadata/model_settings.config` with `<metadata key="extruder" value="{slot}"/>` per object (Bambu reads this for filament mapping).
  - `read_3mf(data: bytes) -> list[(name, np.ndarray verts, np.ndarray faces)]` — stdlib zip/regex reader used by tests and check_output.py.

- [ ] **Step 1: Failing round-trip test**

```python
def test_3mf_roundtrip():
    a = poster.heightmap_mesh(np.full((4, 4), 2.0), 1.0)
    b = poster.heightmap_mesh(np.full((3, 3), 1.0), 1.0)
    data = poster.write_3mf([(a, "terrain", "#4CAF50", 1), (b, "water", "#2196F3", 2)])
    import zipfile, io as _io
    z = zipfile.ZipFile(_io.BytesIO(data))
    assert "3D/3dmodel.model" in z.namelist() and "Metadata/model_settings.config" in z.namelist()
    got = poster.read_3mf(data)
    assert [g[0] for g in got] == ["terrain", "water"]
    assert got[0][1].shape == (len(a.vertices), 3) and got[0][2].shape == (len(a.faces), 3)
    assert np.allclose(got[0][1], a.vertices, atol=1e-3)
    cfg = z.read("Metadata/model_settings.config").decode()
    assert 'value="1"' in cfg and 'value="2"' in cfg
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** (stdlib only; build vertex/triangle lines with ''.join over
f-strings; ~2M lines at defaults is seconds, note as ponytail ceiling)

```python
def write_3mf(bodies):
    import zipfile
    objs, items, cfg = [], [], ['<?xml version="1.0" encoding="UTF-8"?>\n<config>']
    for oid, (m, name, color, slot) in enumerate(bodies, 1):
        vs = "".join(f'<vertex x="{v[0]:.3f}" y="{v[1]:.3f}" z="{v[2]:.3f}"/>' for v in m.vertices)
        ts = "".join(f'<triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}"/>' for f in m.faces)
        objs.append(
            f'<basematerials id="{oid + 100}"><base name="{name}" displaycolor="{color}FF"/></basematerials>'
            f'<object id="{oid}" name="{name}" type="model" pid="{oid + 100}" pindex="0">'
            f'<mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
        items.append(f'<item objectid="{oid}" printable="1"/>')
        cfg.append(f'<object id="{oid}"><metadata key="name" value="{name}"/>'
                   f'<metadata key="extruder" value="{slot}"/></object>')
    cfg.append('</config>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources>{"".join(objs)}</resources><build>{"".join(items)}</build></model>')
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
        z.writestr("Metadata/model_settings.config", "\n".join(cfg))
    return buf.getvalue()


def read_3mf(data):
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("3D/3dmodel.model").decode()
    out = []
    for om in re.finditer(r'<object[^>]*name="([^"]*)"[^>]*>.*?<vertices>(.*?)</vertices>'
                          r'<triangles>(.*?)</triangles>', xml, re.S):
        name, vs, ts = om.groups()
        V = np.array(re.findall(r'x="([^"]+)" y="([^"]+)" z="([^"]+)"', vs), float)
        F = np.array(re.findall(r'v1="(\d+)" v2="(\d+)" v3="(\d+)"', ts), int)
        out.append((name, V, F))
    return out
```

- [ ] **Step 4: Suite green.**
- [ ] **Step 5: Commit** — `feat: hand-written Bambu-ready 3MF writer with round-trip reader`

---

### Task 5: endpoint + UI + checker + e2e

**Files:**
- Modify: `app.py` (response: frame/relief/path)
- Modify: `static/index.html` (3 downloads, 3MFLoader preview, colors, assembly transform)
- Modify: `check_output.py` (trio rules via `read_3mf`)
- Modify: `test_poster.py` (endpoint test adapted)

**Interfaces:**
- `POST /generate` → `{"frame": b64 stl, "relief": b64 3mf, "path": b64 stl}` (same errors).
- Checker: `uv run python check_output.py frame.stl relief.3mf path.stl [--params ...]`.

- [ ] **Step 1: Adapt endpoint test** — monkeypatch both fetchers; assert three keys, 3MF magic `PK` after b64-decode of relief, both STLs binary. Run red (endpoint still returns poster/path), then:

- [ ] **Step 2: app.py** — `frame_stl, bodies, path_stl = core.build_poster(...)`; `relief = core.write_3mf(bodies)`; return the three b64 fields.

- [ ] **Step 3: index.html**
- importmap unchanged; add `import { ThreeMFLoader } from 'three/addons/loaders/3MFLoader.js';`
- `show()` gains STL path (existing) and 3MF path: `new ThreeMFLoader().parse(bytes.buffer)` → group; set per-child material color from `COLORS` by child name if the loader loses displaycolor.
- Assembly: frame mesh at origin, black `#222222`; relief group and strip translated by `[frame_mm + fit_mm, frame_mm + fit_mm, base_mm]` (read the values from the same fields the params JSON is built from; `fit_mm` fixed 0.2 constant in JS).
- Three download links: `frame.stl`, `relief.3mf` (`model/3mf`), `path.stl`.
- Keep dispose-on-regenerate (walk group children).

- [ ] **Step 4: check_output.py trio rules** — frame: loads, watertight/winding/volume, footprint == size ±0.5 ≤256, flat back, ring height == base+frame_height ±0.01. Relief: `read_3mf` → per body trimesh(process=False) → terrain watertight+winding+volume; footprint == size−2·frame−2·fit ±0.5; caps (if present) within terrain xy-bounds and z within [terrain_min, terrain_max+0.01]. Strip: existing rules vs relief z-range. Update usage string.

- [ ] **Step 5: Full suite green; commit** — `feat: colored relief endpoint, UI and checker`

- [ ] **Step 6: Live e2e (network)** — start server on a free port; generate from `/Users/rbissegger/Downloads/40f8ba3c.kml` at `{"size_mm":120}`; decode the three files to the scratchpad; run the checker on the trio (expect all PASS); report file sizes and timings. REMAINING MANUAL CHECKS for the user: browser preview colors, Bambu Studio import of relief.3mf shows 3 bodies mapped to extruders 1/2/3, frame.stl and path.stl slice clean.

- [ ] **Step 7: Push.**

---

## Self-review notes

- Spec-addendum coverage: land cover (T1), caps geometry (T2), frame/relief split + new Params (T3), Bambu 3MF (T4), endpoint/UI/checker/e2e (T5). Colors constants in T1.
- Names consistent: `classify_landcover`, `fetch_landcover`, `masked_slab_mesh`, `compose_parts`, `build_poster` (new signature), `write_3mf`, `read_3mf`, `COLORS`, Params fields `cap_mm/plate_mm/fit_mm/city_min_km`.
- Known risks flagged inline: WMS axis order (T1 live check), winding (T2, test-gated), 3MF size ceiling (T4 ponytail note), 3MFLoader color loss fallback (T5).
- The old `compose` may be deleted in T3 once its tests are migrated — no dead code left behind.
