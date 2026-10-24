# Themed reliefs, close-up detail, 4-slot relief and a closer preview

Repo: `/Users/rbissegger/Documents/AI Toons/Scripts/Activity Path Poster` (branch `main`, HEAD c2caff1). Execution: subagent-driven, Opus implementers, as before.

## Context

The Zermatt demo exposed two things the owner dislikes about the look:

1. **"The perspective comes from too high up."** On a 7 km box (≈36 m per printed mm) the relief draws only tertiary-and-up roads, water and the grey band, so it reads like a satellite view. The owner wants what a person on the ground sees: village streets, hiking trails, railway lines, buildings, and a web preview that looks at the poster from a lower, closer angle rather than straight down.
2. **One look for every event.** Green land / blue water / grey peaks is the "classic satellite" scheme. The owner wants reliefs that match the event: city marathons, Strava-style dark, Swiss hiking (key market), triathlon red/black, grand-tour cycling, trail/ultra, and whatever else fits. Answers given: a theme changes **colours and content**; a **4th AMS slot** is allowed for the relief (roads/buildings get their own colour), accepting that the prime tower must be re-measured in Orca; **any PLA colour** may be used.

Research outcome (web, 2026-10-24): official hex codes for races are mostly unpublished and the marks are trademarks (Ironman M-dot, UTMB, Boston unicorn, Strava logo). So themes are palettes *inspired by* an event, named generically, never using a brand or event name or logo. Reference hues used: Strava orange #FC4C02; Ironman red/black/white; Boston blue/yellow, NYC blue/orange, London/Chicago/Tokyo red; Swiss signpost yellow (RAL 1007, ≈#FFCC00), Bergweg white-red-white, Alpinweg white-blue-white; swisstopo pale greens/brown rock/white glacier; Tour yellow, Giro pink, Vuelta red; UTMB slate; Spartan red/black, HYROX yellow/black; Komoot green, Suunto/Polar red. 3D-print map art precedents: four-colour city maps (water, parks, buildings, base), dark monochrome terrain with one accent.

## Design decisions

- **One `Theme` dataclass + `THEMES` dict + `Params.theme = "classic"`** in poster.py. `COLORS` stays as the classic palette so every existing colour pin holds; `THEMES["classic"]` is built from it and must reproduce today's bodies and 3MF config exactly.
- **Relief slots per theme, fixed within a theme:** `relief_colours(t) = [land, water] + [band if band] + [detail if detail]`. Streets, trails, rail and buildings share the **last** slot ("detail"); the band is slot 3 when present. Classic has `detail=None` (roads share the band grey) → 3 slots, byte-identical. Claude.md's invariant becomes "slots never shift within a theme"; the status line prints the slot mapping per generate.
- **Theme content = permission, zoom = decision.** A theme lists which detail groups it *may* draw (`streets`, `trails`, `rail`, `buildings`); `fetch_osm_masks`'s m-per-mm tiers decide what is drawable. Honest consequence: a 42 km marathon box (~60 m/mm) still gets tertiary-plus only; the new detail lights up on short/close activities like Zermatt. **Buildings need ≤12 m/mm (a box under ~2.5 km at 216 mm)** — a 15 m house is 0.4 mm at Zermatt's scale, under the 0.84 mm colour floor — so Zermatt gets streets, trails and the Gornergrat railway but no buildings. Stated in the UI help and Claude.md.
- **All detail is one width (`ROAD_MM` 1.2 mm) and one colour.** No `TRAIL_MM`: 2 cells = 0.8 mm is under the floor. Density is kept in check by the existing `ROAD_MAX_FRAC` drop loop, finest class first (streets, then trails). Forests are **skipped** (no 5th slot; a band would lie about footprints), so the `landuse`-absent test pin stays.
- **Buildings = raised cap**: `surface += BUILDING_MM (0.48, 2 layers)` under building vertices (clamped to the relief ceiling), then the same conformal cap as roads, in the detail colour. Pure heightmap op; walls stand on roofs; `check_output` rule 8 passes unchanged. Sub-3×3 px footprints are dropped by the existing `MIN_RING_PX2`.
- **Detail draws over the band** (a yellow trail at 3000 m is the point of the hiking theme): drop the `lc != 2` guard, and in `compose_parts` set band vertices to `z_snow` **before** carving cap bottoms, so a cap meeting the band leaves no cavity. Classic changes only where a road or lake touches the grey band (invisible grey-in-grey caps); no existing fixture has that.
- **Snow line stays `Params.snow_line_m`** (UI field, 2000 m ≈ Swiss tree line); the theme carries only the band colour or `None` (band off).
- **Flush matrix:** classic keeps its hand-tuned 3×3 (moved into `CLASSIC.flush`); other themes use `_flush_matrix(colours)`: same hex → 0, to lighter (rec.709 luminance) → 550, to darker → 300, `ponytail:` starting values.
- **Frame per-filament temps/fans unchanged** (slot 2 is white in 9 of 10 themes).
- **Preview colours come from the `/generate` response** (`colours: {frame:[…], relief:[…], paths:{stem:[…]}}` built from the body tuples); the JS drops its hard-coded tables.
- **Trademark rule** goes into the spec and Claude.md: generic names, no brand/event names, no logo geometry.

## Findings from the rendered previews (binding corrections to the design above)

1. **Trails = signposted hiking routes.** Drawing every `highway=path|footway|track` turned the Zermatt plate solid yellow (>30 % of the plate). The `trails` tier therefore means the member ways of `relation["route"="hiking"]` (the Swiss yellow network, `osmc:symbol`), fetched in the same Overpass call; Zermatt's network alone is 11 % of the plate, under the cap.
2. **In a city the buildings make the streets.** At 1.2 mm width `residential|service|…` covered 26 % of the 8.5 m/mm city plate and the 15 % cap dropped them. Buildings as raised blocks define the streets as gaps on their own. Keep the rule as designed (cap drops streets first); do not widen the cap for cities.
3. **Buildings need a short route.** ≤ 12 m/mm (a box under ~2.5 km at 216). Zermatt (33 m/mm) gets streets, hiking routes and the Gornergrat railway, no buildings. Say so in the UI help line.
4. **Thresholds used in the previews:** streets ≤ 35 m/mm (not 30: Zermatt is 32.7), trails ≤ 40, rail ≤ 150, buildings ≤ 12. Start there.
5. **32 themes, five groups** (events, rooms, industrial, nature, running), all approved by the owner from the rendered previews at https://claude.ai/artifact/6w2MaE4g7UQTx8c3Y91EqU. 22 use four relief slots, 9 use three, `gallery` uses two (land + water, no band, no detail). The UI `<select>` groups them with `<optgroup>` by group, label text exactly as below.
6. **Slot rule covers the 2-slot case:** `relief_colours(t) = [land, water] + ([band] if band) + ([detail] if detail)`; the flush matrix is n×n for n in {2, 3, 4}; `SLOTS["relief"]` is informational only (classic).

## Theme table (binding starting values; each line carries a `ponytail:` "tune against real spools")

| key | group | label | frame | text | land | water | band | detail | path | swim/bike/run | groups |
|---|---|---|---|---|---|---|---|---|---|---|---|
| classic | events | Classic green terrain | #222222 | #FFFFFF | #4CAF50 | #2196F3 | #9E9E9E | None | #CC2222 | #FFFFFF/#CC2222/#F4EE2A | – |
| city_marathon | events | City marathon — asphalt | #222222 | #FFFFFF | #CFCBC2 | #3F8FD2 | None | #4A4A4A | #E53935 | #FFFFFF/#CC2222/#F4EE2A | buildings, rail, streets |
| dark_orange | events | Dark terrain — orange route | #111111 | #FC4C02 | #2B2B2B | #355C7D | None | #6E6E6E | #FC4C02 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| alpine_hiking | events | Alpine hiking — signpost-yellow trails | #3E2A1E | #FFFFFF | #CFE3B4 | #6FA8DC | #B9A58B | #FFCC00 | #D62828 | #FFFFFF/#D62828/#FF8C42 | rail, streets, trails |
| alpine_winter | events | Alpine winter — snow and slate | #1A1A2E | #FFFFFF | #B8C7D6 | #4A90C2 | #FFFFFF | #4B5563 | #E63946 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| triathlon | events | Triathlon — red/black | #111111 | #FFFFFF | #2B2B2B | #2A6FB5 | #666666 | None | #ED1C24 | #FFFFFF/#ED1C24/#FFC300 | streets |
| grand_tour | events | Grand-tour cycling — yellow/pink/red | #222222 | #FFFFFF | #6B8E23 | #2196F3 | #9E9E9E | #4A4A4A | #FFD400 | #FFFFFF/#F08CAE/#D52B1E | streets |
| trail_slate | events | Trail / ultra — slate and amber | #1C1F26 | #FFFFFF | #4F5B66 | #2F6690 | #8A949E | #E0E0E0 | #F2C14E | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| mono_dark | events | Dark mode — one accent | #111111 | #FFFFFF | #1E1E1E | #2C3E50 | None | #3A3A3A | #00E5A0 | #FFFFFF/#CC2222/#F4EE2A | streets |
| forest | events | Forest — deep greens | #1B2A1B | #F4EAD5 | #2F5D3A | #5B9BD5 | #C9D1C8 | #D9B36B | #FF8C42 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| scandi_oak | rooms | Scandinavian — oak and linen | #C9A97A | #2B2B2B | #EFE9DD | #9DB8C8 | #D8D1C3 | #8C8577 | #2F3A45 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| japandi | rooms | Japandi — clay and charcoal | #3A3A38 | #EAE3D6 | #D9C9B3 | #7A9AA6 | #B9B0A2 | #5B5651 | #B5543A | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| bauhaus | rooms | Bauhaus — primaries on white | #111111 | #FFFFFF | #F2F0EB | #1F4FBF | None | #111111 | #E63312 | #FFFFFF/#E63312/#F2C300 | buildings, streets |
| concrete | rooms | Brutalist — raw concrete | #6E6E6A | #F4F4F2 | #B8B6B0 | #52606D | #D5D3CD | #3C3C3A | #FF4F1F | #FFFFFF/#CC2222/#F4EE2A | buildings, streets |
| gallery | rooms | Gallery white — sculpture relief | #F7F7F5 | #1A1A1A | #FFFFFF | #E6E6E3 | None | None | #1A1A1A | #FFFFFF/#CC2222/#F4EE2A | – |
| chalk | rooms | Chalk and charcoal | #2B2B2B | #F2F2F0 | #F2F2F0 | #BFC7CC | #DADAD6 | #2B2B2B | #2B2B2B | #2B2B2B/#6B6B6B/#A6A6A6 | streets, trails |
| rams | industrial | Greige and signal orange | #D7D2C8 | #222222 | #E8E4DC | #8FA3AD | #C8C3B9 | #4A4845 | #F26419 | #FFFFFF/#CC2222/#F4EE2A | rail, streets |
| steel_brass | industrial | Blackened steel and brass | #1C1C1C | #C9A961 | #3B3D40 | #23303A | #6B6E72 | #8A8D91 | #C9A961 | #FFFFFF/#CC2222/#F4EE2A | streets |
| verdigris | industrial | Copper and verdigris | #2E2A26 | #E6D2B8 | #4F8A7B | #2C5F6E | #9FB9AE | #B87333 | #E07A3F | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| workshop | industrial | Workshop — plywood and safety yellow | #D9B77E | #1E1E1E | #E7DCC3 | #6E8FA6 | #C9BFA7 | #2B2B2B | #FFC400 | #FFFFFF/#CC2222/#F4EE2A | buildings, rail, streets |
| sandstone | nature | Desert sandstone | #5A3E2B | #F5E9D6 | #E2B98A | #4F8FB0 | #A96F4B | #7A5236 | #1F3A5F | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| ocean | nature | Ocean and coral | #0B2A3A | #F3F6F7 | #1E5F74 | #58C1D3 | #E4E9EC | #0B2A3A | #FF6F61 | #FFFFFF/#CC2222/#F4EE2A | streets |
| larch | nature | Autumn larch | #2E2419 | #F3E5C8 | #6B6F3F | #4A7C9B | #D9A441 | #3C2F23 | #C73E1D | #FFFFFF/#CC2222/#F4EE2A | trails |
| glacier | nature | Glacier ice | #DDE7EE | #0E2A3F | #CFE0EA | #4A8FB8 | #F6FBFD | #7E96A6 | #FF3B30 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| moss_slate | nature | Moss and slate | #2F3A34 | #DDE6D9 | #5C7A5A | #3F6B86 | #7E8686 | #B9C0B4 | #F2E394 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| blue_hour | nature | Blue hour — sodium lights | #141A2E | #F7D5A8 | #2B3A5C | #0F1E3A | #8B9BC4 | #52648C | #F7A541 | #FFFFFF/#CC2222/#F4EE2A | streets |
| volcanic | nature | Volcanic — basalt and ember | #0D0D0D | #FFB37A | #262323 | #3A4A55 | #5E5957 | #8A7F79 | #FF4D00 | #FFFFFF/#CC2222/#F4EE2A | streets, trails |
| track | running | Running track — oxide red | #1A1A1A | #FFFFFF | #B33A2E | #2C6FAA | None | #F2E7D5 | #FFFFFF | #FFFFFF/#F2E7D5/#FFD60A | buildings, streets |
| neon_kit | running | Race kit — volt on black | #0A0A0A | #CCFF00 | #171717 | #1C2B3A | None | #3A3A3A | #CCFF00 | #FF2D95/#CCFF00/#00E0FF | streets |
| retro_70s | running | Retro seventies stripes | #F4E3C1 | #2B2118 | #E9D8B4 | #4C86A8 | #C9A86A | #A6553D | #C8102E | #C8102E/#F28C28/#2E6B5E | streets, trails |
| night_run | running | Night run — reflective silver | #0F1115 | #E8E8E8 | #1B1F26 | #0B2540 | None | #C0C0C0 | #FFD60A | #FFFFFF/#CC2222/#F4EE2A | streets |
| medal | running | Finisher medal — bronze on navy | #0F2238 | #CD7F32 | #16304D | #0A1A2E | #345E85 | #5C7FA3 | #CD7F32 | #FFFFFF/#CC2222/#F4EE2A | streets |
Triathlon legs default to `#FFFFFF / #CC2222 / #F4EE2A` unless the row says otherwise. `detail=None` means detail shares the band colour (3 slots) or, with `band=None` too, is not drawn (`gallery`). Groups are the detail classes the theme MAY draw; zoom decides what is drawn.

## Tasks (ordered, each independently testable)

### 1. Theme model and colour plumbing (no content change)
`poster.py`: `Theme` dataclass + `THEMES` after `COLORS` (:90-95); `relief_colours(t)`, `_flush_matrix(colours)`; `Params.theme: str = "classic"` (:518-541); `build_poster` (:1577, bodies :1642-1666) resolves `THEMES[p.theme]` (unknown → `ValueError` listing the keys, which `/generate` already turns into a 400), colours bodies from the theme, roads slot = `len(relief_colours(t))`, skips `lc = 2` when `band is None`; `_project_settings(plate, theme=CLASSIC)` (:1751) builds `colours` from the theme and sets the relief flush matrix (hand table moves from `PLATES["relief"]` :1717 into `CLASSIC.flush`); `write_3mf(bodies, plate=None, theme=CLASSIC)` (:1789). `SLOTS["path"]` → `("path",)`.
`app.py`: pass the theme to `write_3mf`; add `colours` to the response.
Tests: all existing colour/slot pins stay untouched (that is the classic identity check). New: `test_classic_theme_is_todays_output`, `test_a_four_slot_theme_declares_four_filaments` (4 colours, 16-entry matrix, zero diagonal, 550/300 by luminance, `different_settings_to_system` length 6), `test_unknown_theme_is_refused` (ValueError + 400), `test_generate_returns_the_theme_colours`. Update :1604, :1661, :1663 to `relief_colours(THEMES["classic"])`.

### 2. Zoom tiers for streets, trails and rail
`poster.py`: `ROAD_TIERS` (:102) → `(name, limit_m_per_mm, highway_regex)` with new finest tiers `("streets", 30, "residential|unclassified|living_street|service|pedestrian")`, `("trails", 40, "path|footway|track|steps|bridleway|cycleway")`; `DETAIL_GROUPS = {"streets","trails"}` need theme permission; `RAIL_MAX_M_PER_MM = 150`. `fetch_osm_masks(bounds, px_out, res_mm, groups=frozenset())` (:466-514): classes filtered by zoom and permission; `kind()` maps highway → tier via a `tier_of` dict and `railway=rail` → "rail"; `road_items` keyed by tier so the `ROAD_MAX_FRAC` loop pops streets first, then trails; rail query member appended into the `{roads}` placeholder (so `OVERPASS_QL` and the classic query string are unchanged → same cache key, `landuse` pin holds). `build_poster` passes `t.groups`.
Tests: `_fake_fetches` (:1073) gains `groups=`; new `test_fine_classes_need_both_zoom_and_theme` (coarse bbox → no residential even with all groups; ~10 m/mm bbox with no groups → none; with groups → residential/footway/railway in the query, drawn at `ROAD_MM`, tunnel footway skipped, drop loop pops streets before trails with the note).

### 3. Buildings as raised caps (lc 4)
`poster.py`: `BUILDING_MM = 0.48` beside `SLOT_CAP_MM` (:121) and in `test_fixed_constants_sit_on_the_default_layer_grid`; `BUILDING_MAX_M_PER_MM = 12`; `fetch_osm_masks` returns `(water, sea, roads, buildings)` using `_water_mask_from_elements(pick("building"))`, query member `way["building"]` only when permitted and close enough, transoceanic guard → 4 masks, `ponytail:` multipolygon buildings skipped. `build_poster` lc: `2` (if band), `1` water, `3` roads (guard dropped), `4 = buildings & (lc == 0)`. `compose_parts` (:895-973): raise `surface` under `lc==4` by `BUILDING_MM` clamped to the relief ceiling right after the snap (:928); `building_cells`; **reorder** carve (:965-967) band-to-`z_snow` first, then cap bottoms; return the new cells. `build_poster` adds a `"buildings"` cap body in the detail slot/colour.
Tests: `test_buildings_are_a_two_layer_roof_in_the_detail_colour` (roof on the grid, ≤ ceiling at a summit, bottom = roof − cap_mm, terrain carved, check_output passes); `test_a_trail_over_the_band_cuts_the_band_not_a_void` (band cells exclude road cells, `green >= cap_bot` under every cap vertex, all bodies watertight); update :2103 unpacking and :2043 tuple length.

### 4. Tower depth, USABLE_MM, docs
Extend `test_orca_slices_every_plate` (:1643) with an `alpine_hiking` relief where all four slots carry bodies on shared layers (`_fake_fetches(water=True, roads=True, buildings=True, elev_top=4000)`): it slices, 4 filament colours, and the prime tower + brim stays inside the 20 mm front strip (parse the tower moves from the G-code). Expectation: 3 changes × ~1.4 mm ≈ 4.3 mm, under the measured 6.75 mm minimum, so `USABLE_MM` likely holds — **measure, don't assume**. Manual: open the sliced 4-slot relief in Orca, record tower depth and change count in `docs/print-settings.md` (head table "relief, 4 colours"; §3 :228-230 and the flush rule). If the tower exceeds 6 mm: raise `TOWER_MM`, recompute `USABLE_MM`, re-run `test_every_offered_size_fits_the_plate`, and the 216 two-line caption is the likely casualty. Claude.md: themes + trademark rule, slot rule, detail tiers, buildings, carve order.

### 5. UI: theme select, status line, closer preview
`static/index.html`: `<select id="theme">` with the ten labels (+ one help line: fine detail appears on short routes; buildings under ~2.5 km); `params.theme`. Delete `COLORS`/`RELIEF_ORDER`/`FRAME_ORDER` (:81-86); `threeMFGroup(bytes, colours)` colours by index from `j.colours`; status line prints `relief.3mf on slots 1–N`. Camera (:62-72): after placing the frame, fit distance from its `Box3` for the 45° fov, elevation ~35°, looking at the frame centre; warm raking key light from upper left, cool soft fill, neutral hemisphere, background #e8e4dc; shadows off. ~12 lines.

### 6. Manual verification
Run the server, generate `~/Desktop/zermatt-trail-run/Zermatt_Trail_Run.gpx` with `alpine_hiking` (expect yellow trails and village lanes, the Gornergrat railway, brown band above 2000 m with trails cut into it, red wall, no buildings at 36 m/mm) and `~/Desktop/activity-poster-demo/zurich-triathlon.fit` with `triathlon` (3 slots, dark land). `check_output.py` on both; slice both reliefs in Orca and screenshot the tower. Tune the 30 / 40 / 12 m/mm thresholds against what Zermatt shows.

## Verification summary
- `uv run pytest -q` (incl. the real Orca test) green after every task; classic output byte-identical (Task 1 test).
- Task 4's tower measurement recorded in `docs/print-settings.md` before any 4-slot theme is offered.
- Task 6's two demo orders pass `check_output.py` and slice.

## Open items (decide during execution or after the first prints)
- Tier thresholds (30 / 40 / 12 m/mm) are reasoned, not measured — tune on Zermatt.
- Whether the 4-slot tower stays ≤ 6 mm (only Orca answers).
- Orca's handling of the small green sliver inside the band after the carve-order flip — confirm once on the sliced preview.
- Every palette is a starting point; the owner tunes hexes against the spools actually bought.
