# Flight Path Poster

Local web tool that turns a FlightRadar24 track export (KML/CSV) into three 3D-printable files:
`frame.3mf` (black backplate + ring, white text as its own body), `relief.3mf` (multi-body
green terrain / blue water / grey high-alpine band, one AMS slot each) and `path.stl` (the flight-path strip:
a red wall following the flight altitude, standing in a constant-floor slot).

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

Key invariant: every body comes off the same heightmap, so they always fit. The relief plate glues into the frame ring (fit clearance ceil-rounded up to a whole pixel, ≥0.2mm per side — rounding down gives an interference fit); the strip glues into the slot with 0.30mm per side. The slot is carved to a constant `SLOT_FLOOR_MM = 1.04` floor (depth varies with terrain, the floor does not), and the strip runs from that floor up to the flight altitude on the terrain's own vertical scale, clamped to at least `proud_mm` above the terrain under each station.

The DEM is blurred once (`smooth_px` = 1px) and the terrain surface is snapped to a printable layer boundary before caps and slot are cut, so flat ground slices as uniform layers. The grid is `FIRST_LAYER_MM + n*layer_mm` (0.2 + n*0.12), *not* `n*layer_mm` — the printer's first layer is thicker than the rest. One helper, `_snap(z, p)`, does it for the terrain, the strip top and the `z_snow` plane, and every fixed thickness is a whole layer count (`SLOT_FLOOR_MM` 1.04, water `cap_mm` 0.96, text 0.84, `base_mm` 4.04, `frame_height_mm` 9.96, `proud_mm` 0.96).

**Grey is an elevation band, not a cap.** The terrain solid is split at the horizontal plane `z_snow` (= `snow_line_m` on the relief's own mm scale, snapped): green below, a grey solid from that flat plane up to the surface above. A conformal 0.6mm grey cap surfaced as a 0.26mm stripe on median alpine slope — under one extrusion width, which the slicer merges into the neighbouring colour ("blotted grey"). The two bodies meet exactly at `z_snow` and their union is still the same surface heightmap, so this changes colour volume, not shape. The footprint is the bare `elev >= snow_line_m` threshold intersected with `surface > z_snow` — no morphology: an opening dropped small peaks from grey while leaving them in green, so green towered above the plane and the two colours shared layers. A small peak is a solid band volume that prints fine, and cell-based meshing already drops sub-2-cell blobs. Water stays a conformal `cap_mm` cap — lakes are flat.

**The caption bar is a chin, and the text has its own grid.** `size_mm` is the poster's **width** and the square relief area; `chin_mm` is extra frame hung *below* it, so the frame grid is `(N + chin_px, N)` while `N`, `M` and `fpx` keep their formulas — the ring opening and the relief are unchanged by construction (byte-identical, and pinned by a test). A poster therefore measures `size_mm` × `size_mm + chin_mm`, and **both** must fit the 256 plate; `check_output.py`'s footprint rule is per axis for that reason. `chin_mm` is auto: it is whatever `text`/`text2` need beyond the ring's own bottom bar, `block + 2*TEXT_MARGIN_MM - gridded_ring` rounded up to a pixel, so no caption means no chin and every earlier poster is unchanged. Line 2 is a subtitle at `SUB_RATIO` (0.65) of line 1 with `GAP_RATIO` (0.35) between them.

The text body is meshed on its **own** grid, `TEXT_SUB` (4) times finer than the frame's — 0.1mm at defaults. It sits on the flat ring, so it needs only a constant top array, not the frame heightmap, and that is what decouples the two grids. On the terrain's 0.4mm grid an 8mm capital was ~20px tall with 0.4mm stair-steps and a 0.4mm dilation fattening every stroke; at 4× the edge pitch and the dilation both cost 0.1mm (250mm "HB-EZE": 2796 → 27304 verts, ink area 175.7 → 124.5mm²). 6× buys 0.6% more fidelity for 2.2× the vertices, so 4× it is.

Visual params (`frame_mm`, `relief_mm`, `frame_height_mm`, `text_mm`, `groove_w_mm`, `proud_mm`) default to `None` = auto: `poster.resolve(p)` scales them from their 250mm base by `size_mm` and floors them for printability, so an 80mm poster keeps the 250mm look. `build_poster` and `check_output.py` both resolve first; `/generate` returns the resolved dict for the preview.

Spec: `docs/superpowers/specs/2026-08-05-flight-path-poster-design.md`
