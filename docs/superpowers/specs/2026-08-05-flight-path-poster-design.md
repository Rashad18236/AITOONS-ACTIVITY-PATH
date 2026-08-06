# Flight Path Poster — Design

Date: 2026-08-05 · Status: approved approach A (Python backend + one HTML page)

## Goal

Local website (single user, localhost) that converts a FlightRadar24 track export into
3D-printable files for a framed terrain-relief poster with the flight path inlaid as a
separately printed, glued-in strip.

## Decisions (from brainstorming)

- **Input:** KML/CSV file upload only. No FR24 API, no screenshot processing.
- **Deployment:** local only. No hosting, auth, or persistence.
- **Print target:** Bambu 256×256mm plate, poster printed as one piece, default 250×250mm, PLA.
- **Flight scope:** short/regional flights (relief is meaningful at this scale).
- **Path method:** groove carved into relief; path strip printed separately and glued in.
- **Text:** free text field, embossed on the bottom frame bar.

## Architecture

```
app.py            FastAPI: POST /generate (file + params) → {poster.stl, path.stl}; serves static/
poster.py         core pipeline (pure functions, no framework imports)
static/index.html upload form, sliders, three.js preview, download buttons
test_poster.py    self-check
pyproject.toml    fastapi, uvicorn, numpy, trimesh, pillow, requests
```

Run: `uv run uvicorn app:app` → `http://localhost:8000`. Each generate is stateless input→output.

## Pipeline (poster.py)

1. **Parse** KML (XML coordinates) or FR24 CSV → `[(lat, lon, alt_m), ...]`.
2. **DEM fetch:** bounding box of track + margin % → AWS Terrain Tiles
   (`https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, free, no key).
   Pick zoom so the mosaic is ~512–1024px across. Decode terrarium:
   `elevation = (R*256 + G + B/256) - 32768`.
3. **Compose heightmap** — all 2D numpy pixel ops, never 3D booleans:
   - project lat/lon → mm with equirectangular + cos(mid-lat) correction (regional flights only)
   - normalize terrain to `[0, relief_height × exaggeration]` above base thickness
   - raise flat frame border around the edge (frame width param)
   - emboss text: Pillow renders string to a mask → add to bottom frame bar
   - carve groove: depress pixels within groove_width/2 of the track polyline by groove_depth
4. **Mesh poster:** heightmap grid → top surface + side walls + flat bottom, watertight,
   via trimesh → binary `poster.stl`.
5. **Mesh path strip:** sample the SAME pre-groove heightmap along the track;
   cross-section = groove width − 2×clearance; bottom = groove floor, top = local terrain + 1mm proud.
   Printed lying on its side or with supports — implementer picks what prints cleanest → `path.stl`.
6. **Return** both STLs; browser previews with three.js and offers downloads.

Key invariant: both meshes derive from one heightmap → guaranteed fit (0.30mm clearance/side).

## Parameters (UI sliders/fields, defaults)

| Param | Default |
|---|---|
| Poster size | 250 mm |
| Base thickness | 4 mm |
| Max relief height | 20 mm |
| Vertical exaggeration | 1.5× |
| Bbox margin | 15 % |
| Frame width | 12 mm |
| Groove width / depth | 2 mm / 1.5 mm |
| Strip clearance | 0.30 mm |
| Text + text size | "" / 8 mm |

## Error handling

- Unparseable file → 400 with message shown in UI.
- Tile fetch failure → one retry, then 502 with message.
- Nothing else. Local single-user tool.

## Testing

`test_poster.py` (plain asserts, runnable with `uv run pytest` or `python test_poster.py`):
- parse a bundled sample KML snippet → expected point count/values
- build a small poster mesh from synthetic heightmap → `mesh.is_watertight`
- strip width < groove width by 2×clearance; strip fits within groove depth profile

## Out of scope (deliberate)

- Long-haul/continental flights (projection distortion), multi-tile posters,
  FR24 API fetch, hosting, GPX. Add only when actually needed.

---

# Addendum 2026-08-05: colored relief + split frame (approved)

Supersedes the single-poster output. Three deliverables per generate:

| File | Content | Filament |
|---|---|---|
| `frame.stl` | Backplate (base thickness, full footprint) + frame ring + embossed text, one solid | Black |
| `relief.3mf` | Multi-body, printed in place with AMS: terrain body (green), water caps (blue), big-city caps (grey) | Slots 1/2/3 |
| `path.stl` | Glue-in strip, unchanged geometry (sampled from relief surface) | Red / any |

- Relief plate has its own flat back, footprint = size − 2·frame − 2·fit clearance;
  it glues onto the backplate inside the frame ring.
- Land cover: ESA WorldCover 10m via public Terrascope WMS
  (`https://services.terrascope.be/wms/v2`, layer `WORLDCOVER_2021_MAP`, EPSG:3857 bbox);
  classify PNG pixels by legend palette: water #0064C8 → blue, built-up #FA0000 → grey,
  everything else green. "Big cities only": morphological opening (PIL Min/MaxFilter),
  kernel sized from `city_min_km` real-world width; small water speckle removed with k=3 opening.
- Geometry stays heightmap-only: terrain body top is depressed `cap_mm` under cap masks
  and `groove_d_mm` under the groove (groove pixels excluded from cap masks);
  caps are `cap_mm` slabs following the pre-groove surface, meshed by a new
  `masked_slab_mesh(mask, top, thickness, res_mm)` (cell-based, watertight).
- 3MF is hand-written (zip+XML, no new deps): standard core objects with display colors
  plus Bambu `Metadata/model_settings.config` mapping each body to extruder 1/2/3.
- New Params: `cap_mm=0.6`, `plate_mm=2.0` (relief minimum thickness), `fit_mm=0.2`
  (relief↔frame side clearance), `city_min_km=1.5`. Display colors are constants,
  not Params: green #4CAF50, blue #2196F3, grey #9E9E9E, black #222222, red #CC2222.
- UI: three download links; preview shows frame (black, STLLoader), relief (3MFLoader,
  per-body colors), strip (red) assembled: relief and strip translated by
  (frame+fit, frame+fit, base) onto the backplate.
- Known ceilings (accepted, measured at 250mm defaults): relief.3mf is ~9.4MB zipped —
  the big one is frame.stl at 39.3MB (a near-flat plate meshed at full grid resolution),
  and the JSON response totals ~65MB. Upgrade path is mesh decimation on the frame.
  Text emboss stays black-on-black (frame filament); contrasting text = 4th slot, later.
- check_output.py extends to the trio: frame footprint/watertight, relief bodies
  round-tripped from the 3MF (also validates the writer), caps within relief bounds,
  strip vs relief surface.
- Land-cover fallback (added 2026-08-05, Terrascope WMS down ~30h): on ANY exception
  from the WorldCover WMS, `fetch_landcover` prints one line and falls back to OSM
  standard-style raster tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) via
  the tile-mosaic core now shared with the DEM (`_tile_mosaic`). WorldCover stays
  primary — no behaviour change while it is up. `classify_landcover_osm` matches
  water #AAD3DF ±10 and landuse=residential ±9 around #D8D8D8 (osm-carto darkens that
  fill as it zooms out: #E0DFDF at z≥13, ~#D2D2D2 at z11), then resamples NEAREST —
  bilinear would blend palette colours into no class at all. Unlike WorldCover this is
  a rendering, not a survey: roads and labels are painted over the fills, so both
  classes get a closing pass (cities close at half the city kernel) or motorway
  casings shatter a city below the opening kernel. OSM tile policy compliance:
  identifying User-Agent `FlightPathPoster/1.0 (local single-user 3D-print tool)`,
  zoom floored at 10 (below it osm-carto draws no residential at all, so there are no
  cities to find) and capped at 13, with a hard ~8×8-tile budget per fetch that clamps
  that floor — a wide track must not become a four-figure tile download.
