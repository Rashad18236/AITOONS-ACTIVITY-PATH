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

Consequence: `Params.groove_d_mm` had no effect once slot depth became derived, so the
field, its "Groove depth mm" UI slider and the slider's id-loop entry are **deleted**.
The surviving `groove_w_mm` is relabelled "Path slot width mm" in the UI. The
`plate_mm` guard pair is now `SLOT_FLOOR_MM` and `cap_mm` — both must be strictly less
than the plate thickness, for the same reason as before (the slot must not reach the
back of the plate, and a colour cap must not push the terrain negative).

`check_output.py`'s single "strip z range" rule became two: bottom == `SLOT_FLOOR_MM`
±0.01, and top above `bottom + proud_mm` and no higher than the tallest relief body
+ `proud_mm`.

# Addendum 2026-08-06b: frame text printed white (approved)

The 0.8mm text emboss was black-on-black — the frame's own filament — and unreadable.
It is now its own body in its own filament, at the same height as before.

- `compose_parts` no longer adds the emboss to the frame heightmap; it returns a
  `text_mask` (N,N bool) of the rendered glyph pixels, empty when no text was asked for.
- `build_poster` returns `frame_bodies`, a body list like the relief's:
  `[(frame_mesh, "frame", COLORS["frame"], 1)]` plus, when text is present,
  `(masked_slab_mesh(text_mask, frame_hm + 0.8, 0.8, res_mm), "text", COLORS["text"], 2)`.
  New `COLORS["text"] = "#FFFFFF"`. The glyphs stand exactly 0.8mm proud of the ring, as
  before, but on extruder 2.
- `write_3mf` already took any body list, so the first deliverable becomes **`frame.3mf`**
  (black + white, extruders 1/2). The `/generate` response key stays `"frame"`; its bytes
  are a 3MF now. UI: the download is `frame.3mf` (`model/3mf`) and the preview loads it
  with the same 3MF group loader, whose colour map gained `frame`/`text` and whose
  index-order fallback is now passed in per file (`FRAME_ORDER` / `RELIEF_ORDER`).
- `check_output.py` reads the frame as a 3MF: frame body watertight/winding/volume,
  footprint == `size_mm` and ≤256mm, flat back, and ring height == `base_mm +
  frame_height_mm` ±0.01 **exactly** — no emboss allowance, so the old "did you forget
  `--params text`?" hint is gone with it. Two new rules: a text body present **iff**
  `--params` carries non-empty text, and its z range == `[ring_top, ring_top + 0.8]`
  ±0.01. Usage is `check_output.py frame.3mf relief.3mf path.stl [--params ...]`.

# Addendum 2026-08-06c: visual parameters auto-scale with poster size (approved)

An 80mm poster used to print with the 250mm parameters: a 12mm frame ate 15% of the
plate per side (vs 5% at 250mm), the 2mm slot looked 3x fatter relative to the terrain,
and a 20mm relief on an 80mm plate was a tower. Visual parameters now scale with
`size_mm`; physical/print parameters stay absolute.

`Params`' six visual fields default to `None` ("auto"). `resolve(p) -> Params` (pure,
`dataclasses.replace`) fills each `None` with `max(floor, round(base * size_mm / 250, 2))`
and passes explicit values through untouched. `build_poster`'s first line is
`p = resolve(p)`, so every internal helper still sees concrete mm; `check_output.py`
resolves identically, so a checker run with the same `--params` computes the same
expectations. `resolve` is idempotent.

| Param | Kind | Base @250mm | Floor | Why the floor |
|---|---|---|---|---|
| `frame_mm` | scaled | 12 | 4.0 | ring must survive handling and hold the plate |
| `relief_mm` | scaled | 20 | 5.0 | terrain must stay readable |
| `frame_height_mm` | scaled | 10 | 3.0 | ring must still read as a frame |
| `text_mm` | scaled | 8 | 3.0 | glyph strokes need >=2px cells at res 0.4 |
| `groove_w_mm` | scaled | 2 | 1.2 | strip must print and not snap |
| `proud_mm` | scaled | 1.0 | 0.4 | line must clear the terrain visibly |
| `size_mm`, `margin_pct`, `exaggeration` | absolute | — | — | driver / already relative |
| `base_mm` 4, `plate_mm` 2, `cap_mm` 0.6, `clearance_mm` 0.30, `fit_mm` 0.2, `res_mm` 0.4, `snow_line_m` 2000 | absolute | — | — | stiffness / FDM tolerance / real-world metres |

`resolve` also asserts the strip core survives the clearance gaps:
`groove_w_mm - 2*clearance_mm >= 0.4`, else `ValueError`. The 1.2mm floor clears it at
the default 0.30mm clearance; the guard exists for explicit narrow overrides.

UI: the scaled numeric inputs (`relief_mm`, `groove_w_mm`) ship blank with
`placeholder="auto"` — the existing "blank field is not posted" loop already means
`None` server-side. Because the preview's assembly translation needs the frame width
and can no longer read it off a blank field, `/generate` returns a fourth key,
`"resolved"` (`asdict` of the resolved `Params`), and the JS insets the relief plate and
strip from that instead of from the form (`res_mm`/`fit_mm` constants deleted with it).

# Addendum 2026-08-06d: print quality + altitude path (approved)

Three print defects, one addendum.

**Ragged layer lines.** DEM noise wobbles the terrain by ~0.08mm against a 0.2mm layer,
so the slicer scattered single-layer islands over near-flat ground. The DEM is now
blurred once (`smooth_px` = 2px, separable box mean — PIL's `GaussianBlur` rejects mode
`F`) and the resulting `surface` is rounded to whole `layer_mm` (0.2, `0` disables)
*before* the caps and the slot are cut, so those keep their exact offsets. `plate_mm` 2.0,
`cap_mm` 0.6, `SLOT_FLOOR_MM` 1.0, `base_mm` 4.0, `frame_height_mm` 10.0 and the 0.8mm
text are already 0.2 multiples, so the frame needs no snapping. Both params are absolute
(printer properties, not visual scale); an unaligned `layer_mm` is the user's call, no guard.

**Speckled grey.** `_opened(elev >= snow_line_m, 3)` kept every ridge sliver, and the
cell-based cap slab turned 1px slivers into dots. `_snow_mask` now closes *then* opens at
`k = max(3, round(snow_min_mm / res_mm) | 1)`: the closing merges neighbouring ridges into
one massif, the opening drops whatever is still thinner than the minimum printed blob.
`snow_min_mm` is scaled (base 3.0 @250mm, floor 1.5). The threshold reads the *smoothed*
elevation — `build_poster` blurs once and hands the same array to `compose_parts`, so
nothing is blurred twice.

**Level path wall.** Altitude was parsed and thrown away. `compose_parts` now also returns
`alt_mm`, the per-track-point altitude mapped through the same `e0/e1 -> relief_mm *
exaggeration` scale as the terrain, and `strip_mesh(track_px, alt_mm, surface, p)`
resamples it onto the centerline's own arc-length stations. Per station
`z_top = max(alt, surface + proud_mm)`, snapped to `layer_mm`; `z_bot` stays the constant
`SLOT_FLOOR_MM`. The clamp means the wall never sinks into the relief — where the flight
crossed below the terrain the poster shows (or the altitude is a missing 0, ~2.7% of a
real FR24 file) it simply rides terrain + proud. Only the z arrays vary; the offsets and
the face/winding scheme are untouched.

`check_output.py`: the old "strip top is proud *and level*" ceiling is dropped — the top
now follows an altitude no exported mesh carries, and a high flight over low terrain
legitimately towers over the relief. In its place, every terrain and strip z must be a
multiple of `layer_mm` (3MF `%.3f` -> 1e-6, binary STL float32 -> 1e-4).

| Param | Kind | Default | Floor |
|---|---|---|---|
| `snow_min_mm` | scaled | 3.0 @250mm | 1.5 | *(deleted 2026-08-08, see the band addendum)* |
| `layer_mm` | absolute | 0.2 (0 = no snapping) | — |
| `smooth_px` | absolute | 2.0 (0 = no blur) | — |

---

# Addendum 2026-08-08: grey as an elevation band + 0.12mm print grid (approved)

## Grey is a band, not a conformal cap

Measured: the grey cap was a `cap_mm` = 0.6mm shell following the terrain. A horizontal
slice through it is a stripe `cap_mm / slope` wide; the median alpine slope on a 250mm
poster is 2.29mm rise per mm run, so the stripe surfaces at **0.26mm — narrower than one
0.42mm extrusion**. Slicers detect such non-printable segmented regions and merge them
into the neighbouring colour, so what printed was transition filament, not grey: the
"blotted grey".

The terrain solid is now **split at a horizontal plane**, not skinned:

- `z_snow` = `snow_line_m` mapped through the same elevation→mm scale `compose_parts`
  already uses for the surface and the flight altitude, then `_snap`ped to a layer
  boundary and clamped to `plate_mm` (a snow line below the whole DEM must not thin the
  plate). Above the DEM's top the band is simply empty.
- **green body** = the terrain heightmap with its top clamped to `z_snow` under the band.
- **grey body** = a solid from the flat `z_snow` plane up to `surface`, only where
  `surface > z_snow`. Same mesher as the caps: `masked_slab_mesh` was split into
  `_slab_cells` (mask → meshable cells) and `_slab_mesh(cells, top, bot, res)`, which
  now takes a bottom *surface* instead of a constant thickness. `band_mesh` passes the
  constant `z_snow` plane. Winding and the pinch-drop rule are untouched.
- The two bodies meet exactly at `z_snow`: green's top is clamped on
  `_cell_verts(snow_cells)` — the vertices the grey mesh actually covers, not the raw
  mask. Clamping on the mask would drop the green top along a one-cell rim the grey does
  not reach and gash the assembled surface.
- The assembled surface is therefore **unchanged**: green-top ∪ grey-top reconstructs the
  same heightmap the single body had. This is a colour-volume change, not a shape change.
- **No morphology.** The mask is the bare `elev >= snow_line_m` threshold; `_snow_mask`,
  `_opened`, `_closed` and `snow_min_mm` are deleted. Keeping the merge was a mistake
  carried over from the cap design: the *opening* dropped small peaks from grey but not
  from the terrain, so they stayed green and towered above `z_snow` — 225 of 266 layers
  on the real HB-EZE trio held more than one colour, green reaching 31.52mm against a
  16.88mm plane. The *closing* was a no-op here, since it only adds pixels below the
  threshold and `surface > z_snow` filters them straight back out. In a band a small peak
  is a solid volume that prints fine, and `_slab_cells` already drops sub-2-cell blobs.
  Band footprint = (`elev >= snow_line_m`) ∩ (`surface > z_snow`).
- Water stays a conformal cap — lakes are flat, so its slices are lake-wide already.
  `cap_mm` is now a water-only parameter (0.96mm, 8 layers).

Consequence for `check_output.py`: the grey body no longer sits within `cap_mm` of the
terrain top. Its rules are now "flat bottom" (exactly half the vertices share the lowest
z, i.e. one plane, not a conformal underside) and "above `plate_mm`, under the relief
ceiling". The water cap keeps the old tight `terrain + cap_mm` bound.

## 0.12mm layers, snapped to the printer's real grid

`layer_mm` 0.2 → **0.12** (0.4 nozzle, "Fine" preset; see `docs/print-settings.md`).

The snap was `round(z / layer) * layer`, which assumes every layer is `layer_mm` thick.
The printer's **first layer is 0.2mm** (`FIRST_LAYER_MM`, Bambu's nozzle Ø × 50% rule)
and the rest are `layer_mm`, so a printable height is `0.2 + n*0.12`. One helper,
`_snap(z, p, rnd=np.round)`, now does it for the terrain surface, the strip top, the
strip's relief ceiling (`rnd=floor`, so the cap cannot land above the ceiling) and the
`z_snow` plane. `layer_mm = 0` still opts out. z = 0 is the build plate and is exempt.

Every constant that has to land on that grid moved:

| Constant | Was | Now | Why |
|---|---|---|---|
| `layer_mm` | 0.2 | **0.12** | 1.67× the vertical quantisation over the same relief |
| `smooth_px` | 2.0 | **1.0** | half the layer height needs half the blur; crisper terrain |
| `cap_mm` (water) | 0.6 | **0.96** | 8 layers, and past the ~1mm opacity threshold |
| text emboss | 0.8 | **0.84** (`TEXT_EMBOSS_MM`) | 7 layers above the ring top |
| `SLOT_FLOOR_MM` | 1.0 | **1.04** | `0.2 + 7*0.12`: the boundary nearest 1.0. *Not* 0.96 — 0.96 is 8×0.12 of material but lands mid-layer once the 0.2 first layer is counted, which is the bug this change exists to fix |
| `base_mm` | 4.0 | **4.04** | `0.2 + 32*0.12` |
| `frame_height_mm` @250 | 10.0 | **9.96** | a whole 83 layers, so the ring top `base + frame_height` = 14.00 is itself a boundary |
| `proud_mm` @250 | 1.0 | **0.96** | 8 layers above an already-snapped terrain sample |
| `plate_mm` | 2.0 | 2.0 | already `0.2 + 15*0.12` |

Guards unchanged and still hold: `plate_mm` (2.0) > `SLOT_FLOOR_MM` (1.04) and > `cap_mm`
(0.96). `frame_height_mm` and `proud_mm` are scaled params, so only their 250mm base is
grid-exact; at other sizes the strip top is snapped anyway and the frame is a flat
two-level body the slicer quantises on its own.

`check_output.py`'s layer rule now measures against `_snap` (the same helper the generator
uses) and covers the colour bodies as well as the terrain and the strip.
