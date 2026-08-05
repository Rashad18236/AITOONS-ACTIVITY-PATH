# Flight Path Poster

Local web tool that turns a FlightRadar24 track export (KML/CSV) into two 3D-printable STLs:
a terrain-relief poster with frame, embossed text, and a groove along the flight path —
plus a separate path strip that glues into the groove.

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
- `poster.py` — core: parse track → fetch DEM (AWS Terrain Tiles, terrarium, no key) → compose one 2D heightmap (terrain + frame + text + groove) → mesh to `poster.stl` + `path.stl`
- `static/index.html` — upload form, parameter sliders, three.js preview, downloads
- `test_poster.py` — self-check: parse sample track, build small mesh, assert watertight + strip fits groove

Key invariant: poster and path strip are both derived from the same heightmap, so they always fit (strip gets 0.15mm glue clearance).

Spec: `docs/superpowers/specs/2026-08-05-flight-path-poster-design.md`
