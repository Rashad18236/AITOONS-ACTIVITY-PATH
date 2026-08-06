# Flight Path Poster

Local web tool that turns a FlightRadar24 track export (KML/CSV) into three 3D-printable files:
`frame.3mf` (black backplate + ring, white text as its own body), `relief.3mf` (multi-body
green terrain / blue water / grey high-alpine caps, one AMS slot each) and `path.stl` (the flight-path strip:
a level red wall standing in a constant-floor slot).

## Rules

- Printed in PLA on a Bambu, 256×256mm plate, poster is one piece (default 250mm)
- Design decisions with Fable, implementation via Opus subagents
- Ponytail full mode during coding: laziest working solution, heightmap ops over 3D booleans, no speculative features
- Local only (localhost), single user, no auth, no persistence

## Run

```bash
uv run uvicorn app:app --reload
# open http://localhost:8000
```

## Architecture

- `app.py` — FastAPI: upload/generate routes, serves `static/`
- `poster.py` — core: parse track → fetch DEM (AWS Terrain Tiles, terrarium, no key) + water polygons (OSM via Overpass) → compose 2D heightmaps (frame + text mask, green/water/snow relief, slot) → mesh to `frame.3mf` + `relief.3mf` + `path.stl`
- `static/index.html` — upload form, parameter sliders, three.js preview, downloads
- `test_poster.py` — self-check: parse sample track, build small mesh, assert watertight + strip fits slot

Key invariant: every body comes off the same heightmap, so they always fit. The relief plate glues into the frame ring (fit clearance ceil-rounded up to a whole pixel, ≥0.2mm per side — rounding down gives an interference fit); the strip glues into the slot with 0.30mm per side. The slot is carved to a constant `SLOT_FLOOR_MM = 1.0` floor (depth varies with terrain, the floor does not), and the strip is a level wall from that floor to `proud_mm` above the highest terrain the track crosses.

Visual params (`frame_mm`, `relief_mm`, `frame_height_mm`, `text_mm`, `groove_w_mm`, `proud_mm`) default to `None` = auto: `poster.resolve(p)` scales them from their 250mm base by `size_mm` and floors them for printability, so an 80mm poster keeps the 250mm look. `build_poster` and `check_output.py` both resolve first; `/generate` returns the resolved dict for the preview.

Spec: `docs/superpowers/specs/2026-08-05-flight-path-poster-design.md`
