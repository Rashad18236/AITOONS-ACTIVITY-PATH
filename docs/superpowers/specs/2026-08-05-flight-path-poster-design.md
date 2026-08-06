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
| `relief.3mf` | Multi-body, printed in place with AMS: terrain body (green), water caps (blue), snow caps (grey) | Slots 1/2/3 |
| `path.stl` | Glue-in strip, unchanged geometry (sampled from relief surface) | Red / any |

- Relief plate has its own flat back, footprint = size − 2·frame − 2·fit clearance;
  it glues onto the backplate inside the frame ring.
- Colour classes (see the 2026-08-06 addendum, which supersedes the original
  WorldCover scheme): blue = OSM water polygons, grey = DEM elevation, green = the rest.
- Geometry stays heightmap-only: terrain body top is depressed `cap_mm` under cap masks
  and `groove_d_mm` under the groove (groove pixels excluded from cap masks);
  caps are `cap_mm` slabs following the pre-groove surface, meshed by a new
  `masked_slab_mesh(mask, top, thickness, res_mm)` (cell-based, watertight).
- 3MF is hand-written (zip+XML, no new deps): standard core objects with display colors
  plus Bambu `Metadata/model_settings.config` mapping each body to extruder 1/2/3.
- New Params: `cap_mm=0.6`, `plate_mm=2.0` (relief minimum thickness), `fit_mm=0.2`
  (relief↔frame side clearance), `snow_line_m=2000`. Display colors are constants,
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

# Addendum 2026-08-06: vector water + elevation grey caps (approved)

Supersedes the WorldCover/OSM-raster land-cover scheme entirely — that machinery
(`fetch_landcover`, `classify_landcover*`, the WMS and OSM-tile constants, the
`min_zoom`/tile-budget logic in `_tile_mosaic`, `Params.city_min_km`) is deleted.
Raster land cover produced Minecraft-block shorelines at the zooms a poster-wide
bbox allows, and grey-for-cities put the poster's only neutral colour on exactly
the flat parts of an Alpine flight.

- **Water = OSM vector polygons via Overpass** (free, no key, no new dependency).
  `OVERPASS_QL` asks a bbox for `natural=water` and `waterway=riverbank`, ways and
  relations, with `out geom` — member coordinates are embedded, so no node lookup.
  Two mirrors (`overpass-api.de`, `overpass.kumi.systems`) tried in order,
  `timeout=180` (`_get` grew a timeout kwarg; tiles keep 20s).
  `_water_mask_from_elements` rasterises straight into a PIL `L` image at the
  relief grid's own resolution: standalone closed ways filled 255; relations
  stitched by `_stitch_rings` (exact `round(coord*1e7)` endpoint keys, segments
  reversed as needed), outers filled 255 then inners punched to 0. Rings under
  `MIN_RING_PX2` = 9 px² are skipped (pools and farm ponds, ~99.8% of standalone
  ways in a Swiss bbox). Overpass does **not** clip geometry to the bbox; PIL's
  polygon rasteriser clips off-canvas coordinates itself, so nothing else has to.
  Unclosed chains are counted, skipped, and reported in one line.
  Soft-fail: any Overpass exception in `build_poster` prints one line and yields a
  water-less poster rather than a 502. Guard: a bbox wider than 4° of longitude
  (transoceanic) returns zeros without querying — no water speckle is worth an
  Overpass timeout over an ocean.
  Out of scope, documented: seas and oceans (coastline is `natural=coastline`
  ways, not closed polygons — this is an Alpine tool); a bbox lying entirely
  inside one giant lake; rivers narrower than 2 px, which leave a ~0.6mm capless
  trench (`_opened(water, 3)` is the one-line fix if it ever shows).
- **Grey = elevation**, not cities: `lc[_opened(elev >= p.snow_line_m, 3)] = 2` off
  the DEM already fetched — no second network source. New `Params.snow_line_m=2000.0`,
  exposed in the UI as "Grey caps above [m]". The k=3 opening drops single-pixel
  DEM spikes that would otherwise mesh into 0.4mm grey confetti.
  Water is assigned **after** snow, so a high Alpine lake stays blue.
- Renames through the stack: `compose_parts` key `city`→`snow`, `COLORS["city"]`→
  `COLORS["snow"]` (same #9E9E9E), 3MF body name `cities`→`snow` (still slot 3),
  and the preview's `COLORS` map in `static/index.html`.
- `_tile_mosaic` keeps only the fit zoom (`z = max(1, min(max_zoom, fit))`); with the
  OSM caller gone the zoom floor and tile budget had no purpose. Elevation output is
  unchanged and pinned by `test_elevation_always_uses_the_fit_zoom`. The per-call
  `headers` kwarg on `_tile_mosaic`/`_get` is gone; instead `_get` now sends a single
  module-level identifying `UA` on every request — found live, overpass-api.de answers
  requests' default User-Agent with a bare 406.

# Addendum 2026-08-06a: full-height level flight strip (approved)

The strip used to follow the terrain, sitting `groove_d_mm` into a shallow groove and
`proud_mm` above it — a red line that disappeared into every ridge it crossed. It is now
a **level wall**: one constant rectangle in cross-section, swept along the same
centreline, from `SLOT_FLOOR_MM = 1.0` (new module constant in `poster.py`, not a Param)
up to `max(surface sampled along the track) + proud_mm`. Both z values are scalars, which
is a straight simplification of `strip_mesh` — the centreline, `_offsets` and the winding
scheme are untouched, only the per-station z arrays became constants.

The slot matches: `compose_parts` now carves `green[gmask] = SLOT_FLOOR_MM` instead of
subtracting `groove_d_mm`, so the slot's **depth** varies with the terrain while its
**floor** does not. The 1.0mm floor keeps the relief plate connected under the slot;
`plate_mm` must exceed it, which `build_poster` validates in place of the old
`plate_mm > groove_d_mm` guard. Cap masks still exclude the slot, and the width fit
(`groove_w_mm − 2·clearance_mm`) is unchanged, so the seat invariant holds as before.

Consequence, accepted: `Params.groove_d_mm` (and its "Groove depth mm" UI slider) no
longer has any effect — slot depth is derived now. Left in place rather than removed;
drop both when convenient.

`check_output.py`'s single "strip z range" rule became two: bottom == `SLOT_FLOOR_MM`
±0.01, and top above `bottom + proud_mm` and no higher than the tallest relief body
+ `proud_mm`.
