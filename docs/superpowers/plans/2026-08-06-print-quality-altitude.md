# Print Quality + Altitude Path Implementation Plan

**Goal:** (A) kill ragged layer lines on near-flat terrain, (B) turn speckled grey caps into coherent massifs, (C) make the path wall follow real flight altitude.

**Root causes:** (A) DEM noise wobbles heights by ~0.08mm against 0.2mm layers → the slicer emits scattered single-layer islands. (B) `_opened(elev>=2000, 3)` keeps every ridge sliver; caps are cell-based so 1px slivers become dots. (C) altitude is parsed (`parse_track` col 2; real file: 1498 pts, 0–1806m) but discarded — Task 8 made the strip top a single scalar.

## Global constraints

- Ponytail; no new deps (PIL/numpy only); fix_normals/networkx unavailable — winding correct at construction, every mesh test keeps watertight+winding+volume.
- `resolve()` (Task 9) is the single param entry point; new visual params join `_SCALED`.
- TDD; never weaken existing tests; suite `uv run pytest -q` (currently 52 passed + 1 live-skip).

---

## A. Smooth + snap to layer multiples

**New Params:** `layer_mm: float = 0.2` (0 = disable snapping), `smooth_px: float = 2.0` (0 = disable). Both absolute (printer properties, not visual scale).

**In `compose_parts`, before anything else consumes elevation:**
1. Smooth: gaussian blur `elev` at radius `smooth_px`. Try `Image.fromarray(elev.astype("float32"), "F").filter(ImageFilter.GaussianBlur(p.smooth_px))`; if mode-F blur misbehaves, fall back to a separable numpy box blur (cumsum, ~8 lines) — pick whichever passes the test, note which in the report.
2. Scale to relief as today → `surface`.
3. Snap: `surface = np.round(surface / p.layer_mm) * p.layer_mm` when `layer_mm > 0`.

Snap `surface` (pre-cap, pre-slot) so caps/slot keep exact offsets. Verify the existing constants stay layer-aligned at the default: `plate_mm 2.0`, `cap_mm 0.6`, `SLOT_FLOOR_MM 1.0`, `base_mm 4.0`, `frame_height_mm 10.0`, text emboss `0.8` are all multiples of 0.2 → frame needs no snapping. If `layer_mm` is set to a value that leaves those unaligned, that's the user's call — no guard.

**Test:** synthetic noisy ramp → every value of `parts["surface"]` is a multiple of `layer_mm` (within 1e-9); noise amplitude below one layer collapses to a single flat plane; a real hill still spans multiple distinct levels (smoothing must not flatten features).

## B. Grey caps as coherent massifs

**New Param:** `snow_min_mm` — **scaled** (`_SCALED` base `3.0` @250mm, floor `1.5`): minimum grey blob width on the printed poster.

**Re-add `_closed(mask, k)`** (MaxFilter then MinFilter — the mirror of the existing `_opened`; it was deleted in Task 7).

**In `build_poster`,** replace `_opened(elev >= p.snow_line_m, 3)` with:
```
k = max(3, int(round(p.snow_min_mm / p.res_mm)) | 1)
snow = _opened(_closed(elev >= p.snow_line_m, k), k)   # close merges ridges, open drops dots
```
Use the **smoothed** elevation for the threshold (same array compose_parts uses — pass it or smooth once in build_poster and hand it down; single smoothing call, don't blur twice).

**Test:** synthetic elevation with two ridges 2mm apart plus one isolated 0.8mm speck → ridges merge into one region, speck gone; a genuine 5mm massif survives intact.

## C. Altitude-following path wall

**`compose_parts`** additionally returns `alt_mm`: per original track point, the flight altitude mapped through the **same** vertical scale as terrain —
`alt_mm = plate_mm + (alt_m − e0) / max(e1 − e0, 1e-9) * relief_mm * exaggeration`, with `e0, e1` the terrain min/max already used for `surface` (so a 1800m flight over 900m terrain visibly rides above it).

**`strip_mesh(track_px, alt_mm, surface, p)`** (one new arg): after the existing arc-length resample of the centerline, resample altitude the same way (`np.interp` on the same cumulative-distance array — mirror the `cx`/`cy` lines). Then per station:
```
z_top[i] = max(alt_mm_resampled[i], surface_sampled[i] + p.proud_mm)   # never sinks into terrain
z_top = snap to layer_mm (when > 0)
z_bot = SLOT_FLOOR_MM                                                   # unchanged, constant
```
Per-station `z_top` restores the varying-z ribbon that existed pre-Task-8; the winding/offset/cap logic is unchanged and must stay untouched — only the z arrays vary again.

Altitude 0 (missing, ~2.7% of the real file) simply loses the max() and rides terrain+proud — acceptable, no interpolation.

**Tests:** flight climbing over flat terrain → strip top strictly increasing, above terrain everywhere; flight at constant low altitude crossing a peak → clamp engages, top == surface+proud there, never below terrain; watertight/winding/volume hold on a varying-z strip; slot-width seat invariant unchanged.

## Wiring

- `static/index.html`: add "Layer height mm" (`layer_mm`, value 0.2) and "Grey min size mm" (`snow_min_mm`, blank + placeholder auto). Keep the rest.
- `check_output.py`: new rule — when `layer_mm > 0`, every relief terrain-body z is a multiple of `layer_mm` (±1e-6). Strong regression catch, ~4 lines.
- Docs: spec addendum bullet (smoothing/snapping, massif merging, altitude wall + clamp); Claude.md one line.

## Verification

1. `uv run pytest -q` green (+~6 tests).
2. Live HB-EZE at 250mm: report grey region count before/after merging, strip top min/max (expect the alpine section on the clamp since max flight alt 1806m < terrain max 3853m), checker all-PASS incl. the new layer rule.
3. User: slice in Bambu Studio — flat areas should show clean uniform layers, grey as few solid regions, path wall rising/falling with altitude.
