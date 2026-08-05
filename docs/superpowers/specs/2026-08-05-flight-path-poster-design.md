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

Key invariant: both meshes derive from one heightmap → guaranteed fit (0.15mm clearance/side).

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
| Strip clearance | 0.15 mm |
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
  AMS multi-color export, FR24 API fetch, hosting, GPX. Add only when actually needed.
