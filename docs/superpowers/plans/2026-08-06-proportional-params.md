# Proportional Parameters Implementation Plan

> **For agentic workers:** single-task plan; execute with one implementer + task review.

**Goal:** Small posters keep the same visual proportions as big ones: visual parameters scale with `size_mm` (anchored at the 250mm defaults), physical/print parameters stay absolute, and every scaled parameter has a printability floor.

**Problem:** All Params are absolute mm. At size_mm=80 the 12mm frame eats 15% of the poster per side (vs 5% at 250mm), the 2mm path slot looks 3× fatter relative to terrain, text dominates the bar, and relief height stays 30mm tall on an 80mm plate (a tower).

## Design

**Mechanism — "auto unless set":** scaled fields become `float | None = None` in `Params`. A new pure function `resolve(p) -> Params` returns a fully-concrete copy: `None` fields get `round(base_250 * size_mm / 250, 2)` clamped to `max(floor, ...)`; explicit values pass through untouched. `build_poster` calls `resolve` first (single entry point); `check_output.py` resolves identically so expected dims match. The UI's existing blank-field-skips-key behavior already routes "not set" → `None`: change the scaled inputs' `value=` defaults to empty with `placeholder="auto"`.

**Scaling table (base @250mm → floor):**

| Param | Kind | Base @250 | Floor | Why floor |
|---|---|---|---|---|
| frame_mm | scaled | 12 | 4.0 | ring must survive + hold plate |
| relief_mm | scaled | 20 | 5.0 | visible terrain |
| frame_height_mm | scaled | 10 | 3.0 | ring must read as frame |
| text_mm | scaled | 8 | 3.0 | glyph strokes need ≥2px cells at res 0.4 |
| groove_w_mm | scaled | 2 | 1.2 | strip must print + not snap |
| proud_mm | scaled | 1.0 | 0.4 | line must clear terrain visibly |
| size, margin_pct, exaggeration | absolute | — | — | driver / already relative |
| base_mm 4, plate_mm 2, cap_mm 0.6, clearance 0.30, fit 0.2, res 0.4, snow_line_m 2000 | absolute | — | — | stiffness / FDM tolerance / real-world meters |

Guards after resolve must still hold (plate>slot floor, plate>cap; groove floor 1.2 > 2·clearance 0.6 + printable core — sanity-assert `groove_w > 2*clearance_mm + 0.4` in resolve, clear ValueError otherwise).

## Changes

- `poster.py`: Params scaled fields → `None` defaults (type `float | None`); module consts `_SCALED = {"frame_mm": (12.0, 4.0), "relief_mm": (20.0, 5.0), "frame_height_mm": (10.0, 3.0), "text_mm": (8.0, 3.0), "groove_w_mm": (2.0, 1.2), "proud_mm": (1.0, 0.4)}`; `resolve(p)` (dataclasses.replace); `build_poster` first line `p = resolve(p)`; internal helpers unchanged (they receive concrete values).
- `app.py`: none (Params introspection unchanged; None defaults fine — JSON numbers override).
- `check_output.py`: resolve the params object the same way before computing expectations.
- `static/index.html`: scaled fields get `value=""` + `placeholder="auto"`; label hint "(auto-scales with size)" on one of them or a single footnote line. Absolute fields keep values.
- Tests: `_params()` helper passes explicit values everywhere → untouched. New tests: resolve() scales at 80mm (frame 3.84→floor 4.0, groove 0.64→floor 1.2, relief 6.4, text 3.0 floor…) — assert exact numbers; explicit override passes through; 250mm resolves to legacy defaults exactly (backwards compat); guard fires when explicit groove_w < printable core; endpoint with empty params JSON at size 80 → 200 and smaller frame in the actual STL footprint (frame ring width check via checker or bounds).
- Docs: spec addendum table gains Base@250/floor columns; Claude.md one line.

## Verification

1. `uv run pytest -q` green (+~4 tests).
2. Live: generate HB-EZE at size 80 AND 250 with empty scaled params → checker PASS on both (checker resolving identically); report frame/groove resolved values both sizes.
3. User: preview at 80mm — frame/path/text visually proportional to the 250mm look.

## Risks

- Any test or checker path that reads `Params().frame_mm` directly now gets None → resolve first; grep for bare `Params()` uses.
- 3MF/preview JS constants: index.html assembly translation uses frame+fit — JS reads the frame field; when blank it must fall back to the resolved value. Lazy fix: server response gains `"resolved": {…}` dict (5 lines in app.py) and the JS uses it for the translation instead of reading form fields.
