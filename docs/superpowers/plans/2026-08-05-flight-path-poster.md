# Flight Path Poster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local FastAPI website that turns a FlightRadar24 KML/CSV export into two STLs — a terrain-relief poster (frame + embossed text + groove along the track) and a matching glue-in path strip.

**Architecture:** Everything geometric is a 2D numpy heightmap (terrain, frame, text, groove are pixel operations); the poster mesh is the heightmap extruded to a flat back, the path strip is a constant-thickness ribbon swept along the track sampled from the same heightmap. One stateless POST endpoint; one static HTML page with three.js preview.

**Tech Stack:** Python ≥3.11, FastAPI, uvicorn, numpy, trimesh, Pillow, requests, python-multipart; pytest + httpx (dev); three.js from CDN in the browser.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-flight-path-poster-design.md`
- Local single-user tool: no auth, no persistence, no DB.
- No 3D boolean operations anywhere — heightmap pixel ops only.
- DEM source: AWS Terrain Tiles terrarium PNGs, no API key: `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, decode `(R*256 + G + B/256) − 32768` meters.
- Defaults (verbatim from spec): poster 250mm, base 4mm, relief 20mm, exaggeration 1.5×, margin 15%, frame width 12mm, groove 2mm wide / 1.5mm deep, clearance 0.15mm, text size 8mm. Additional fixed choices: frame height 10mm, grid resolution 0.4mm/px, strip stands 1mm proud, text emboss 0.8mm.
- Poster/strip fit invariant: both derive from the same heightmap; strip width = groove width − 2×clearance.
- Heightmap convention: row 0 = north = +y in mm; heights in mm; z=0 is the flat back.
- Run: `uv run uvicorn app:app` → http://localhost:8000. Tests: `uv run pytest -q`.
- Commit after every task (Conventional Commits), push at the end.

---

### Task 1: Scaffold + track parsing

**Files:**
- Create: `pyproject.toml`
- Create: `poster.py` (parsing section)
- Create: `test_poster.py`

**Interfaces:**
- Produces: `parse_track(name: str, data: bytes) -> np.ndarray` — shape (N,3) columns lat, lon, alt_m; raises `ValueError` if <2 points.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "flight-path-poster"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi", "uvicorn", "numpy", "trimesh", "pillow",
    "requests", "python-multipart",
]

[dependency-groups]
dev = ["pytest", "httpx"]
```

- [ ] **Step 2: Write failing tests for both parsers**

```python
# test_poster.py
import numpy as np
import pytest
import poster

KML = """<?xml version="1.0"?><kml xmlns:gx="http://www.google.com/kml/ext/2.2">
<gx:coord>8.55 47.46 430</gx:coord>
<gx:coord>8.60 47.50 900</gx:coord>
<gx:coord>8.70 47.60 1500</gx:coord></kml>"""

CSV = """Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction
1717000000,2026-05-29T00:00:00Z,HB123,"47.46,8.55",1000,120,90
1717000060,2026-05-29T00:01:00Z,HB123,"47.50,8.60",2000,120,90
"""

def test_parse_kml():
    t = poster.parse_track("flight.kml", KML.encode())
    assert t.shape == (3, 3)
    assert t[0, 0] == 47.46 and t[0, 1] == 8.55 and t[0, 2] == 430

def test_parse_kml_linestring_fallback():
    xml = "<kml><coordinates>8.55,47.46,430 8.60,47.50,900</coordinates></kml>"
    t = poster.parse_track("x.kml", xml.encode())
    assert t.shape == (2, 3) and t[1, 0] == 47.50

def test_parse_csv_fr24():
    t = poster.parse_track("flight.csv", CSV.encode())
    assert t.shape == (2, 3)
    assert t[0, 0] == 47.46
    assert abs(t[0, 2] - 1000 * 0.3048) < 1e-6  # feet -> meters

def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        poster.parse_track("x.csv", b"Timestamp,Position\n")
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `uv run pytest test_poster.py -q` — Expected: FAIL (`poster` has no `parse_track`).

- [ ] **Step 4: Implement parsing in poster.py**

```python
"""Flight Path Poster core: track -> heightmap -> printable meshes."""
import csv, io, math, re
from dataclasses import dataclass
import numpy as np


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
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `uv run pytest test_poster.py -q` — Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml poster.py test_poster.py
git commit -m "feat: project scaffold and FR24 KML/CSV track parsing"
```

---

### Task 2: Mercator bounds + terrarium DEM fetch

**Files:**
- Modify: `poster.py` (append DEM section)
- Modify: `test_poster.py` (append tests)

**Interfaces:**
- Consumes: nothing from Task 1 (independent section).
- Produces:
  - `track_bounds(track: np.ndarray, margin_pct: float) -> tuple[float, float, float, float]` — `(x0, y0, x1, y1)` square in pseudo-mercator radians (x=lon rad, y=asinh(tan(lat))), track bbox + margin, expanded to square about its center.
  - `decode_terrarium(rgb: np.ndarray) -> np.ndarray` — uint8 (H,W,3) → float meters.
  - `fetch_elevation(bounds, px_out: int) -> np.ndarray` — float (px_out, px_out) meters, row 0 = north. Network; NOT unit-tested.

- [ ] **Step 1: Write failing tests (pure parts only)**

```python
def test_track_bounds_square_with_margin():
    t = np.array([[47.0, 8.0, 0], [47.5, 9.0, 0]])
    x0, y0, x1, y1 = poster.track_bounds(t, 15.0)
    assert abs((x1 - x0) - (y1 - y0)) < 1e-12          # square
    import math
    assert x0 < math.radians(8.0) and x1 > math.radians(9.0)  # margin outside track

def test_decode_terrarium():
    rgb = np.array([[[0, 0, 0], [128, 4, 128]]], dtype=np.uint8)
    e = poster.decode_terrarium(rgb)
    assert e[0, 0] == -32768
    assert abs(e[0, 1] - (128 * 256 + 4 + 128 / 256 - 32768)) < 1e-9
```

- [ ] **Step 2: Run tests, verify the new ones fail**

Run: `uv run pytest test_poster.py -q` — Expected: 2 new FAIL.

- [ ] **Step 3: Implement DEM section in poster.py**

```python
import requests
from PIL import Image

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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest test_poster.py -q` — Expected: 6 passed.

- [ ] **Step 5: One-off live sanity check (network)**

Run: `uv run python -c "import poster,numpy as np; t=np.array([[46.5,7.9,0],[46.6,8.1,0]]); e=poster.fetch_elevation(poster.track_bounds(t,15),256); print(e.shape, int(e.min()), int(e.max()))"`
Expected: `(256, 256)` with max around 2500–4000 (Bernese Alps). If offline, note it and move on.

- [ ] **Step 6: Commit**

```bash
git add poster.py test_poster.py
git commit -m "feat: mercator bounds and AWS terrarium elevation fetch"
```

---

### Task 3: Params + heightmap composition (terrain, frame, text, groove)

**Files:**
- Modify: `poster.py` (append Params + compose)
- Modify: `test_poster.py` (append tests)

**Interfaces:**
- Consumes: `track_bounds`, `_merc` from Task 2.
- Produces:
  - `@dataclass Params` — fields exactly: `size_mm=250.0, base_mm=4.0, relief_mm=20.0, exaggeration=1.5, margin_pct=15.0, frame_mm=12.0, frame_height_mm=10.0, groove_w_mm=2.0, groove_d_mm=1.5, clearance_mm=0.15, text="", text_mm=8.0, res_mm=0.4, proud_mm=1.0`.
  - `compose(track, elev, bounds, p) -> (hm, surface, track_px)` — `hm` float (N,N) mm final heightmap (groove carved), `surface` same before groove, `track_px` float (N,2) columns (x_px, y_px) in heightmap pixel coords. `elev` must be shape (N−2·frame_px, N−2·frame_px) where N = int(size_mm/res_mm), frame_px = int(frame_mm/res_mm).

- [ ] **Step 1: Write failing tests**

```python
def _params(**kw):
    return poster.Params(**{"size_mm": 40.0, "frame_mm": 4.0, "res_mm": 0.5, **kw})

def _synthetic():
    p = _params()
    N = int(p.size_mm / p.res_mm)              # 80
    fpx = int(p.frame_mm / p.res_mm)           # 8
    inner = N - 2 * fpx                        # 64
    elev = np.tile(np.linspace(0, 1000, inner), (inner, 1))  # E-W gradient
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    bounds = poster.track_bounds(track, p.margin_pct)
    return p, N, fpx, elev, track, bounds

def test_compose_shapes_and_frame():
    p, N, fpx, elev, track, bounds = _synthetic()
    hm, surface, tpx = poster.compose(track, elev, bounds, p)
    assert hm.shape == (N, N) and surface.shape == (N, N)
    assert hm[0, 0] == p.base_mm + p.frame_height_mm       # frame ring is flat
    assert abs(hm[N // 2, fpx] - p.base_mm) < p.relief_mm  # relief starts at base
    assert hm[fpx:N-fpx, fpx:N-fpx].max() <= p.base_mm + p.relief_mm * p.exaggeration + 1e-6

def test_compose_groove_carved():
    p, N, fpx, elev, track, bounds = _synthetic()
    hm, surface, tpx = poster.compose(track, elev, bounds, p)
    mid = tpx[len(tpx) // 2]
    x, y = int(round(mid[0])), int(round(mid[1]))
    assert surface[y, x] - hm[y, x] == p.groove_d_mm       # carved by exactly groove depth
    assert fpx <= x < N - fpx and fpx <= y < N - fpx       # track inside relief area

def test_compose_text_embossed():
    p, N, fpx, elev, track, bounds = _synthetic()
    p2 = _params(text="TEST", text_mm=3.0)
    hm, _, _ = poster.compose(track, elev, bounds, p2)
    bar = hm[N - fpx:, :]
    assert bar.max() > p.base_mm + p.frame_height_mm       # something raised on bottom bar
```

- [ ] **Step 2: Run tests, verify the new ones fail**

Run: `uv run pytest test_poster.py -q` — Expected: 3 new FAIL.

- [ ] **Step 3: Implement Params + compose**

```python
from PIL import ImageDraw, ImageFont


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
    ImageDraw.Draw(img).line([tuple(q) for q in track_px], fill=255,
                             width=max(int(p.groove_w_mm / p.res_mm), 2), joint="curve")
    hm[np.asarray(img) > 0] -= p.groove_d_mm
    return hm, surface, track_px
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest test_poster.py -q` — Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py
git commit -m "feat: params and heightmap composition with frame, text, groove"
```

---

### Task 4: Poster mesh from heightmap

**Files:**
- Modify: `poster.py` (append meshing section)
- Modify: `test_poster.py` (append tests)

**Interfaces:**
- Consumes: nothing (pure function of an (H,W) array).
- Produces: `heightmap_mesh(hm: np.ndarray, res_mm: float) -> trimesh.Trimesh` — watertight solid: top = heightmap, flat back at z=0, x = col·res, y = (H−1−row)·res.

- [ ] **Step 1: Write failing tests**

```python
def test_heightmap_mesh_watertight():
    rng = np.random.default_rng(0)
    hm = 4.0 + rng.random((20, 30)) * 5
    m = poster.heightmap_mesh(hm, 0.5)
    assert m.is_watertight
    assert m.volume > 0
    assert abs(m.bounds[1][0] - 29 * 0.5) < 1e-6   # x extent = (W-1)*res
    assert abs(m.bounds[1][2] - hm.max()) < 1e-6   # top = max height
    assert m.bounds[0][2] == 0                     # flat back at z=0
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest test_poster.py::test_heightmap_mesh_watertight -q` — Expected: FAIL.

- [ ] **Step 3: Implement heightmap_mesh**

```python
import trimesh


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
    faces = [_grid_faces(idx), _grid_faces(idx + H * W)[:, ::-1]]
    for edge in (idx[0], idx[:, -1], idx[-1][::-1], idx[:, 0][::-1]):
        t0, t1 = edge[:-1], edge[1:]
        faces.append(np.stack([t0, t1, t1 + H * W], 1))
        faces.append(np.stack([t0, t1 + H * W, t0 + H * W], 1))
    m = trimesh.Trimesh(np.vstack([V]), np.vstack(faces), process=False)
    trimesh.repair.fix_normals(m)
    return m
```

Note for implementer: if `is_watertight` fails, the walls' winding vs. the grid direction is the usual culprit — check each of the four `edge` traversals goes counter-clockwise seen from outside, or flip the offending edge's order. The test is the gate; iterate until green.

- [ ] **Step 4: Run test, verify it passes**

Run: `uv run pytest test_poster.py -q` — Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py
git commit -m "feat: watertight poster mesh from heightmap"
```

---

### Task 5: Path strip mesh + build_poster orchestration

**Files:**
- Modify: `poster.py` (append strip + build_poster)
- Modify: `test_poster.py` (append tests)

**Interfaces:**
- Consumes: `Params`, `compose`, `heightmap_mesh`, `track_bounds`, `fetch_elevation`.
- Produces:
  - `strip_mesh(track_px, surface, p) -> trimesh.Trimesh` — ribbon along track: width `groove_w_mm − 2·clearance_mm`, bottom at `surface − groove_d_mm`, top at `surface + proud_mm`, same mm coordinate frame as `heightmap_mesh`.
  - `build_poster(track, p=Params()) -> (bytes, bytes)` — (poster STL, path strip STL), binary.

- [ ] **Step 1: Write failing tests**

```python
def test_strip_mesh_geometry():
    p = _params()
    N = int(p.size_mm / p.res_mm)
    surface = np.full((N, N), 10.0)
    track_px = np.array([[10.0, 40.0], [40.0, 40.0], [70.0, 45.0]])
    m = poster.strip_mesh(track_px, surface, p)
    assert m.is_watertight
    zmin, zmax = m.bounds[0][2], m.bounds[1][2]
    assert abs(zmax - (10.0 + p.proud_mm)) < 1e-6
    assert abs(zmin - (10.0 - p.groove_d_mm)) < 1e-6
    # width across a straight section = groove - 2*clearance
    xs = m.vertices[np.abs(m.vertices[:, 0] - 25 * p.res_mm) < p.res_mm]
    width = xs[:, 1].max() - xs[:, 1].min()
    assert abs(width - (p.groove_w_mm - 2 * p.clearance_mm)) < 0.2

def test_build_poster_end_to_end(monkeypatch):
    p = _params()
    N = int(p.size_mm / p.res_mm); fpx = int(p.frame_mm / p.res_mm)
    inner = N - 2 * fpx
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda bounds, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    track = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])
    stl_a, stl_b = poster.build_poster(track, p)
    assert stl_a[:5] != b"solid" and len(stl_a) > 84   # binary STL
    assert len(stl_b) > 84
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest test_poster.py -q` — Expected: 2 new FAIL.

- [ ] **Step 3: Implement strip_mesh + build_poster**

```python
def strip_mesh(track_px, surface, p):
    """Constant-thickness ribbon that seats in the groove and stands proud."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(track_px, axis=0).T))]
    n = max(int(d[-1]), 8)  # ~1 sample per heightmap pixel
    t = np.linspace(0, d[-1], n)
    cx = np.interp(t, d, track_px[:, 0])
    cy = np.interp(t, d, track_px[:, 1])
    tang = np.gradient(np.stack([cx, cy], 1), axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-12
    nrm = np.stack([-tang[:, 1], tang[:, 0]], 1)
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm  # px
    H, W = surface.shape
    # ponytail: nearest-neighbour surface sampling; bilinear if strip shows steps
    zc = surface[np.clip(cy.round().astype(int), 0, H - 1),
                 np.clip(cx.round().astype(int), 0, W - 1)]
    z_top, z_bot = zc + p.proud_mm, zc - p.groove_d_mm
    C = np.stack([cx, cy], 1)
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
    m = trimesh.Trimesh(V, np.vstack(f), process=False)
    trimesh.repair.fix_normals(m)
    return m


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
```

Note for implementer: same watertight-vs-winding guidance as Task 4; end caps and the 4 swept sides must all face outward. Test is the gate.

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest test_poster.py -q` — Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py
git commit -m "feat: glue-in path strip mesh and build_poster pipeline"
```

---

### Task 6: FastAPI app

**Files:**
- Create: `app.py`
- Modify: `test_poster.py` (append endpoint test)

**Interfaces:**
- Consumes: `poster.parse_track`, `poster.build_poster`, `poster.Params`.
- Produces: `POST /generate` — multipart `file` + form field `params` (JSON string of Params overrides) → `{"poster": <b64 stl>, "path": <b64 stl>}`; 400 on bad file, 502 on generation/DEM failure. Serves `static/` at `/`.

- [ ] **Step 1: Write failing test**

```python
def test_generate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda bounds, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    client = TestClient(appmod.app)
    params = '{"size_mm": 40, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files={"file": ("f.kml", KML.encode())},
                    data={"params": params})
    assert r.status_code == 200
    import base64
    assert len(base64.b64decode(r.json()["poster"])) > 84
    assert len(base64.b64decode(r.json()["path"])) > 84

def test_generate_bad_file():
    from fastapi.testclient import TestClient
    import app as appmod
    r = TestClient(appmod.app).post(
        "/generate", files={"file": ("x.csv", b"junk")}, data={"params": "{}"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest test_poster.py -q` — Expected: FAIL (no `app` module). `mkdir -p static && touch static/.gitkeep` if StaticFiles complains before Task 7.

- [ ] **Step 3: Implement app.py**

```python
"""Flight Path Poster — local web app. Run: uv run uvicorn app:app"""
import base64, json
from dataclasses import fields
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
import poster as core

app = FastAPI()
_ALLOWED = {f.name for f in fields(core.Params)}


@app.post("/generate")
async def generate(file: UploadFile, params: str = Form("{}")):
    kw = {k: v for k, v in json.loads(params).items() if k in _ALLOWED}
    try:
        track = core.parse_track(file.filename or "", await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        stl_poster, stl_strip = core.build_poster(track, core.Params(**kw))
    except Exception as e:  # DEM fetch or meshing failed
        raise HTTPException(502, f"Generation failed: {e}")
    return {"poster": base64.b64encode(stl_poster).decode(),
            "path": base64.b64encode(stl_strip).decode()}


app.mount("/", StaticFiles(directory="static", html=True))
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest test_poster.py -q` — Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py test_poster.py static/.gitkeep
git commit -m "feat: FastAPI generate endpoint"
```

---

### Task 7: Frontend page + end-to-end check

**Files:**
- Create: `static/index.html`

**Interfaces:**
- Consumes: `POST /generate` contract from Task 6.
- Produces: browser UI — file input, text + parameter fields, Generate button, three.js preview of both meshes assembled, two download links.

- [ ] **Step 1: Write static/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Flight Path Poster</title>
<style>
  body { font: 14px system-ui; margin: 0; display: flex; height: 100vh; }
  #panel { width: 300px; padding: 16px; overflow-y: auto; background: #f4f4f4; }
  #panel label { display: block; margin: 10px 0 2px; color: #444; }
  #panel input { width: 100%; box-sizing: border-box; }
  #view { flex: 1; }
  button { margin-top: 14px; width: 100%; padding: 8px; }
  a.dl { display: block; margin-top: 8px; }
  #status { margin-top: 10px; color: #a00; white-space: pre-wrap; }
</style>
<script type="importmap">
{ "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
} }
</script>
</head>
<body>
<div id="panel">
  <h3>Flight Path Poster</h3>
  <label>FR24 track (KML/CSV)</label><input type="file" id="file" accept=".kml,.csv">
  <label>Text (bottom frame bar)</label><input id="text" placeholder="ZRH → GVA · 12.07.2026">
  <label>Poster size mm</label><input id="size_mm" type="number" value="250">
  <label>Max relief mm</label><input id="relief_mm" type="number" value="20">
  <label>Vertical exaggeration</label><input id="exaggeration" type="number" step="0.1" value="1.5">
  <label>Margin %</label><input id="margin_pct" type="number" value="15">
  <label>Groove width mm</label><input id="groove_w_mm" type="number" step="0.1" value="2">
  <label>Groove depth mm</label><input id="groove_d_mm" type="number" step="0.1" value="1.5">
  <button id="go">Generate</button>
  <div id="status"></div>
  <a class="dl" id="dlPoster" style="display:none">Download poster.stl</a>
  <a class="dl" id="dlPath" style="display:none">Download path.stl</a>
</div>
<div id="view"></div>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const view = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdddddd);
const camera = new THREE.PerspectiveCamera(45, 1, 1, 5000);
camera.position.set(200, -250, 250);
camera.up.set(0, 0, 1);
const renderer = new THREE.WebGLRenderer({ antialias: true });
view.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 1.2));
const dir = new THREE.DirectionalLight(0xffffff, 1.5);
dir.position.set(1, -1, 2);
scene.add(dir);
function resize() {
  camera.aspect = view.clientWidth / view.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(view.clientWidth, view.clientHeight);
}
window.addEventListener('resize', resize); resize();
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

let meshes = [];
function show(b64, color) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const geo = new STLLoader().parse(bytes.buffer);
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color }));
  meshes.push(m); scene.add(m);
  return bytes;
}
function dl(el, bytes, name) {
  el.href = URL.createObjectURL(new Blob([bytes], { type: 'model/stl' }));
  el.download = name; el.style.display = 'block';
}

document.getElementById('go').onclick = async () => {
  const f = document.getElementById('file').files[0];
  const status = document.getElementById('status');
  if (!f) { status.textContent = 'Pick a KML/CSV file first.'; return; }
  status.textContent = 'Generating… (terrain download + meshing, ~10-30s)';
  const params = { text: document.getElementById('text').value };
  for (const id of ['size_mm','relief_mm','exaggeration','margin_pct','groove_w_mm','groove_d_mm'])
    params[id] = parseFloat(document.getElementById(id).value);
  const fd = new FormData();
  fd.append('file', f);
  fd.append('params', JSON.stringify(params));
  const r = await fetch('/generate', { method: 'POST', body: fd });
  if (!r.ok) { status.textContent = 'Error: ' + (await r.json()).detail; return; }
  const j = await r.json();
  meshes.forEach(m => scene.remove(m)); meshes = [];
  const pb = show(j.poster, 0xf0f0f0);
  const sb = show(j.path, 0xcc2222);
  const box = new THREE.Box3().setFromObject(meshes[0]).getCenter(controls.target);
  dl(document.getElementById('dlPoster'), pb, 'poster.stl');
  dl(document.getElementById('dlPath'), sb, 'path.stl');
  status.textContent = 'Done. Red = glue-in path strip (shown in place).';
};
</script>
</body>
</html>
```

- [ ] **Step 2: Full test suite**

Run: `uv run pytest test_poster.py -q` — Expected: 14 passed.

- [ ] **Step 3: Manual end-to-end check (network + browser)**

1. `uv run uvicorn app:app` → open http://localhost:8000
2. Upload a real FR24 KML (or save the test KML string from `test_poster.py` as `sample.kml`), set text, Generate.
3. Verify: relief visible, frame ring flat, groove line visible, red strip sits in groove, both downloads open in Bambu Studio without repair warnings.
4. Report result honestly; if Bambu Studio flags non-manifold geometry, fix winding before closing the task.

- [ ] **Step 4: Commit + push**

```bash
git add static/index.html
git commit -m "feat: web UI with three.js preview and downloads"
git push
```

---

## Self-review notes

- Spec coverage: input (T1), DEM (T2), heightmap+frame+text+groove (T3), poster mesh (T4), strip + fit invariant (T5), endpoint + error codes 400/502 (T6), UI + preview + params (T7). GPX correctly absent (out of scope).
- Names consistent across tasks: `parse_track`, `track_bounds`, `decode_terrarium`, `fetch_elevation`, `Params`, `compose`, `heightmap_mesh`, `strip_mesh`, `build_poster`.
- Winding/watertight risk in T4/T5 flagged with explicit iterate-until-green guidance; tests are the gate.
