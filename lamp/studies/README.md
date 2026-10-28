# Activity Path Poster: the whole pipeline, and where everything lives

Written 28 Oct 2026. Everything below is on this Mac only: neither repository has an online
remote, so a Time Machine backup or a private GitHub repository is the only protection
against losing the disk.

## 1. The poster tool

**Folder:** `~/Documents/AI Toons/Scripts/Activity Path Poster`, a git repository.

It turns sport files into three ready-to-print OrcaSlicer projects for the Bambu A1 0.4.

1. **Read the activity** (`activity.py`). GPX, TCX, FIT and Apple Health `export.zip`, one or
   several files. A triathlon splits into swim, bike and run legs, and each leg carries its
   points, times and heart rate.
2. **Fetch the ground** (`poster.py`). The map area comes from the route. Elevation comes from
   AWS terrain tiles. Water, coastline, roads and, in the themes branch, streets, trails, rail
   and buildings come from OpenStreetMap through Overpass, with fallback mirrors and a cache.
3. **Build heightmaps.** All heights snap to the print's layer grid, 0.2 mm then 0.24 mm per
   layer. The pieces are:
   - a black frame with a white caption;
   - the relief, with land, water, a grey high-alpine band and roads in their own colours;
   - one heart-rate wall per leg, in lanes so that overlapping legs don't collide.
4. **Mesh and write.** Each body becomes a watertight mesh and goes into an OrcaSlicer 2.3.2
   project with the full A1 and PLA settings built in: `frame.3mf`, `relief.3mf`, and a path
   file per leg.
5. **Web page** (`app.py`, `static/index.html`). Run `uv run uvicorn app:app` and open
   localhost:8000. You upload, set parameters, see a 3D preview and download.
6. **Checks.** `check_output.py` checks finished files. `test_poster.py` and `test_activity.py`
   are the tests, and one of them slices the files in the real Orca.

**Branches:**

- **`main`:** the finished Activity Path Poster (commit c2caff1).
- **`feature/themes-and-detail`:** 32 colour themes, finer map detail and buildings, in five
  commits. It is paused after Task 3. Two review rulings are open: detail drawn over the grey
  band, and buildings thinner than 0.84 mm. Tasks 4 to 6 have not started: the prime-tower
  measurement, the theme picker in the page with a closer preview, and a manual test. It is
  not merged.

**Documents:**

- `docs/superpowers/specs/`: the design specs.
- `docs/superpowers/plans/`: the build plans. The themes plan holds the 32-theme table.
- `docs/print-settings.md`: why the print settings are what they are.
- `Claude.md`: the project rules.
- `.superpowers/sdd/`: the build ledgers with every review and ruling. This folder is on disk
  but not in git.

## 2. The lithophane lid

**Folder:** `~/Desktop/lid-test-print`.

A white disc that glows on the 84 mm puck lamp. Thin plastic glows and thick plastic stays
dark, so the picture is the thickness.

1. **The map** around the route is drawn in one of two recipes, chosen 25 Oct:
   - **Recipe 5, contour lines,** for mountain and hill runs. Even glow with dark lines; the
     spacing is a round number, at least 2 mm apart on the steepest ground.
   - **Recipe 7, city map,** for city runs. Streets dark, buildings half dark, water bright.
     Streets and buildings only appear when the map covers under about 2.5 km.
2. **Shared rules.** The route is the brightest line, 1.1 mm wide with a 0.8 mm dark edge.
   Lakes are bright. The caption glows in a dark band around the edge.
3. **Thickness** runs from 0.6 mm (brightest) to 3.2 mm (dark), snapped to 0.1 mm layers.
   The disc prints flat, solid and white.
4. **The tube** (`lid_ring.3mf`, black) stands on the table and hides the lamp's 20 mm of
   height. It has no lip over the lamp. The disc floats 6 mm above the lamp on a post on the
   centre button, so pressing the map switches the light. A narrow step under the disc's dark
   rim stops each press.
5. **Posts** (`lid_spacers.3mf`, white, 3.6 to 6.4 mm). You pick the one that clicks.

**Files in that folder:**

- `make_lid_test.py`: the generator. Run `python3 ~/Desktop/lid-test-print/make_lid_test.py`
  from any folder. It works on either branch of the repository.
- `lid_A_contours.3mf`, `lid_B_city.3mf`: the discs as printed.
- `lid_*_v2.3mf`: an alternative layout with everything inside the lamp's glow. Not chosen.
- `README.md`: printing and test steps.
- `map_cache/`, `sliced/`: map data and Orca's sliced copies.

**Still open:** the lamp's exact height, a charging port on its side, which post clicks, and
the final disc size.

## 3. The design studies

**Folder:** this one. The studies were copied here from a temporary session folder.

- **`previews/`:** the 32 theme palettes on Zermatt and Zürich (`render_previews.py`,
  `render_more.py`, `index.html`, `theme_table.md`).
- **`previews/forms/`:** 11 relief forms, among them the medal, hexagons, fins and lithophane
  (`render_forms.py`, `index.html`, and the map caches).
- **`previews/litho/`:** the lithophane concepts, the seven recipes and the tests of the chosen
  two (`render_litho.py`, `render_recipes.py`, `render_choice.py`, `index.html`, `lid.html`).
- **`demo-generators/`:** the scripts that made the synthetic Zermatt trail run and the
  Zürich triathlon.
- **`lamp-photos/`:** your lamp photo and the crops used to read the button.
- **`lid-generator-history/`:** the two earlier ring versions of the lid generator.

To rerun a study, from the repository folder:

```bash
PYTHONPATH="$PWD" uv run python "../Activity Path Poster Studies/previews/litho/render_choice.py"
```

## 4. Published pages, private on claude.ai

| Page | Link |
|---|---|
| 32 relief themes | https://claude.ai/artifact/6w2MaE4g7UQTx8c3Y91EqU |
| 11 relief forms | https://claude.ai/artifact/ArXuszyBfwnXBbDMgYdMUn |
| Lithophane lamp concepts | https://claude.ai/artifact/EtRd5SCjSJfqg5yXXVw9r8 |
| Lithophane lid recipes and your picks | https://claude.ai/artifact/QFVXabrTwVwiJPxborn4ts |

Their HTML sources are the `index.html` and `lid.html` files in `previews/`.

## 5. Everything else

- **Demo prints on the Desktop:**
  - `zermatt-trail-run/`: the GPX and its three files.
  - `activity-poster-demo/`: the triathlon FIT and its five files.
- **The Flight Path Poster:** `~/Documents/AI Toons/Scripts/Flight Path Poster`, on branch
  `feature/colored-relief`. It has four changed files that are not committed: `Claude.md`,
  `docs/print-settings.md`, `poster.py` and `test_poster.py`.
- **Claude's notes on this project:**
  - Memory notes: `~/.claude/projects/-Users-rbissegger-Documents-AI-Toons-Scripts-Flight-Path-Poster/memory/`.
  - The themes plan as approved: `~/.claude/plans/velvety-cooking-widget.md`.
