# Bambu Studio print settings — Flight Path Poster

Target: Bambu X1C / P1S / H2D class, 256×256 plate, 0.4 mm nozzle, AMS, PLA.
Three plates: `relief.3mf` (3 colours), `frame.3mf` (2 colours), `path.stl` (1 colour).

Written against Bambu Studio 1.10 / 2.x setting names. Where a name differs in
Orca Slicer it is noted.

---

## 0. Verdicts up front

| Question | Verdict |
|---|---|
| Layer height | **0.12 mm** ("0.12 mm Fine" preset, 0.4 nozzle). Not 0.2, not 0.08. |
| Nozzle | **Keep 0.4 mm.** A 0.2 mm nozzle is actively wrong for this print (see §4). |
| Adaptive / variable layer height | **OFF.** It destroys the layer-multiple quantisation the generator relies on, and it constrains the prime tower. |
| Ironing on the relief | **OFF.** Ironing only helps flat tops; a quantised heightmap is thousands of tiny terraces. |
| Ironing on the frame | **ON** (genuinely flat top surfaces). |
| Root cause of the "blotted grey" | The 0.6 mm conformal cap produces per-layer grey bands narrower than 2 extrusion widths on any slope steeper than ~35°. Those slivers get merged/dropped by MMU segmentation, and each one is smaller than the flush volume it needs — so what you see is *transition filament*, not grey. Geometry fix in §8, slicer fix in §3. |

Rough print-time expectations (250 mm plate, PLA, 0.4 nozzle, standard speed):

| Layer height | relief.3mf (3 colour) | frame.3mf (2 colour) |
|---|---|---|
| 0.20 mm | ~18–22 h | ~8–10 h |
| 0.16 mm | ~23–28 h | ~10–12 h |
| **0.12 mm** | **~30–36 h** | **~13–16 h** |
| 0.08 mm | ~50–60 h | ~22–26 h |
| 0.10 mm on a 0.2 nozzle | 4–5 days | — |

`path.stl` is ~1 h at any of these.

---

## 1. Quality / layer  (Process → Quality)

Applies to all three plates unless the per-part table (§5) overrides it.

| Setting (Bambu Studio) | Value | Why |
|---|---|---|
| Layer height | **0.12 mm** | 0.4 nozzle's usable range is 0.08–0.28 mm (20–70 % of nozzle Ø). 0.12 gives 1.67× the vertical quantisation levels of 0.2 over the same 20 mm relief amplitude — that alone fixes most of "not fine enough" — at ~1.7× the time of 0.2, vs ~3× for 0.08. 0.6 and 1.2 mm cap depths are exact multiples of 0.12; 0.6/0.16 is not. |
| Initial layer height | **0.2 mm** | Bambu's own rule: first layer = nozzle Ø × 50 %. Do **not** drop it to 0.12 on a 250 mm plate — you need the squish. Note the consequence for the generator (§8): absolute Z of every terrace is `0.2 + n×0.12`, not `n×0.12`. |
| Adaptive layer height / Variable layer height | **OFF** | Two hard reasons: (a) it re-heights layers, so a terrain surface quantised to whole layers stops landing on layer boundaries and you get the ragged sub-layer islands you already fixed; (b) with multi-colour, the prime tower can only be enabled if the variable layer height of *every* object on the plate is identical, and it is incompatible with organic supports. It is also the wrong tool here — it thins layers on *steep* geometry, and a relief poster's detail is on the shallow parts. |
| Precise Z height | **OFF** | It fine-tunes the **last 5 layers** of an object to hit an exact model height. On a heightmap that is 5 layers of non-0.12 terrain right where the highest peaks are. |
| Slice gap closing radius (Quality → Precision) | **0.01 mm** (default 0.049) | The default closes gaps up to 0.049 mm and is a known cause of small features and thin walls silently disappearing from sliced relief/lithophane geometry. |
| Wall generator | **Arachne** | Classic drops sub-line-width features to dots. Arachne varies extrusion width to keep them. Confirm it — regressions to Classic have shipped in Bambu profiles before. |
| Detect thin wall | **ON** | Keeps 1-line terrain features and the narrowest cap bands alive. |
| Wall loops | 3 (relief), 2 (frame), 2 (path) | See §5. |
| Order of walls / Wall printing order | **Inner/Outer/Inner** | Best outer-surface finish; matters on the frame ring and the poster edge. |
| Seam position | **Aligned** | Puts the seam on a predictable edge, not scattered over the relief. |
| Staggered inner seams | **ON** | |
| XY hole compensation / XY contour compensation | **0** | Any non-zero value erodes or inflates every terrain contour. |
| Elephant foot compensation | 0.15 mm (default) | Only affects the flat back. Leave. |
| Arc fitting | **OFF** | Fits arcs to polyline geometry; on a dense triangulated heightmap it rounds off real detail and can produce visible faceting. |
| Precise wall | ON | Dimensional accuracy on the frame/relief fit. |
| Avoid crossing wall | **ON** | This is an anti-smear setting. It keeps the nozzle from travelling across a freshly-laid cap on its way somewhere else — a direct contributor to "grey smeared over green". |
| Z hop type / Z hop height | **Auto**, **0.4 mm** | Same reason; also protects `path.stl`'s fin. |
| Reduce infill retraction | **OFF** | Trades retractions for ooze. Ooze on a 3-colour top surface is visible. |
| Fuzzy skin | **OFF** | |
| Spiral vase | **OFF** | |
| Timelapse | **Traditional** or off, **not Smooth** | Smooth mode forces a prime tower and parks the head every layer; on a 30 h multi-colour print it adds hundreds of extra travel/ooze events over the model. |

### Line width (Process → Quality → Line width), 0.4 nozzle

| Setting | Value | Why |
|---|---|---|
| Default | 0.42 mm | Stock. Bambu's guidance is 0.75–1.5 × nozzle Ø; do not deviate without reason. |
| First layer | 0.5 mm | Adhesion on a 250 mm footprint. |
| Outer wall | **0.40 mm** | Slightly under nozzle Ø sharpens terrain contours and the frame's inner ring. |
| Inner wall | 0.45 mm | |
| Top surface | **0.40 mm** | Narrower top lines = more lines per terrace = less stripe, and lets a narrow cap band become 2 lines instead of 1. |
| Internal solid infill | 0.45 mm | |
| Sparse infill | 0.45 mm | |

---

## 2. Top surface  (Process → Strength / Quality)

The relief's top surface is not one flat plane — it is a staircase of terraces, each
one a separate "top surface" to the slicer. That changes what helps.

| Setting | Value | Why |
|---|---|---|
| Top shell layers | **5** | 5 × 0.12 = 0.6 mm roof. Community target for a clean top is ~1 mm of solid roof; on a relief the terrain body under the roof is nearly solid anyway, so 5 is enough and 8 would double solid-infill time over 250×225 mm. Frame: **6**. |
| Top shell thickness | **0** (let layer count rule) | Prevents Studio silently adding layers and desyncing the cap arithmetic. |
| Bottom shell layers | 4 | |
| Top surface pattern | **Monotonic line** | Monotonic prints top lines strictly in one direction so each new line is laid against the previous one's clean edge. This is *the* setting for "stripey vs uniform sheen" on large top areas. |
| Sparse infill pattern | **Grid** | Predictable, flat support under a roof that changes area every layer. Gyroid is fine too; avoid Lightning here — it under-supports a roof whose footprint moves every layer, which is exactly what causes pillowing on relief prints. |
| Sparse infill density | **15 %** | Bump to 20 % if you see pillowing between the terraces. |
| Infill/wall overlap | **25 %** | Bonds the top shell to the infill; too low leaves the roof unsupported at its edges. |
| Infill combination / Combine infill every | **OFF / 1** | Combining infill layers pushes the roof's support down and off-register with the terraces. |
| Detect narrow internal solid infill | **ON** | Terraces generate lots of narrow solid regions. |
| Only one wall on top surfaces | **ON** (Orca / BS 2.x, Quality → Walls and surfaces) | On a terrace 1–2 mm wide, two perimeters *are* the whole terrace — you get concentric wall texture, not monotonic top fill. One wall gives the monotonic pattern room. If your build doesn't expose it, skip it. |
| Ensure vertical shell thickness | Moderate (default) | |

### Ironing

Bambu's own wiki: *"Ironing is only effective when the top surface is flat. On the
curved top surface, ironing will not be able to smooth out the lines between layers,
so it may not necessarily achieve better results than not ironing, but rather increase
printing time."* It also warns that ironing exerts extra lateral force on the part —
on a 250 mm plate that is an adhesion risk — and that edge material build-up ("bow
wave") shows at the boundary of every ironed region.

On a quantised heightmap, *every terrace is a separate ironed region with its own two
edges*. That is thousands of bow-wave ridges. **Ironing off on `relief.3mf`.**

| Setting | relief.3mf | frame.3mf | Why |
|---|---|---|---|
| Ironing type | **No ironing** | **All top surfaces** | Frame has real flat tops (backplate, ring, text). |
| Ironing pattern | — | Rectilinear | |
| Ironing flow | — | **15 %** | Bambu's failure modes: too low = not smooth, too high = over-extrusion. 15 % is the PLA start point; raise in 5 % steps to a max of ~25 %. |
| Ironing line spacing | — | **0.10 mm** | Wiki: keep it below nozzle Ø so the same area is ironed repeatedly. 0.10 for display work, 0.15 as the general default. |
| Ironing speed | — | **30 mm/s** | |
| Ironing inset | — | **0.4 mm** | Keeps the bow wave off the ring edges and off the white text boundary, where it would push black over white. |
| Ironing direction (needs Develop mode) | — | 45° | 45° to the top pattern gives the best result per the wiki. |

If you insist on ironing the lakes: don't set it globally. Ironing is per-region and
per-extruder, so a global "All top surfaces" will iron every terrain terrace too.
There is no per-body ironing toggle worth the setup — accept unironed lakes; monotonic
top fill at 0.12 mm already looks good and the lakes are flat multi-layer regions.

---

## 3. Multi-colour  (Project Filaments panel + Process → Others)

### How Bambu actually spends filament on a colour change

From the Bambu wiki: `Flushing volume = volume flushed into the excess chute + volume
flushed into support/infill/objects`, and *separately* the **prime volume** is what
gets laid on the prime tower after that, to re-stabilise nozzle pressure. Two different
knobs. If your flush goes into the object instead of the chute, the dirty filament is
inside your print.

### Settings

| Setting | Location | Value | Why |
|---|---|---|---|
| Prime tower | Process → Others | **ON** | Non-negotiable. Without it the first millimetres of every new colour land on the model. It is also a hard prerequisite: *"flush into object" and "flush into infill" are unavailable when the prime tower is disabled.* |
| Prime tower **Width** | Process → Others | **130 mm** | This is the fix for "the tower doesn't fit next to a 250×225 poster". Tower depth = `(turns × line width) × changes per layer`, where `turns = (prime volume ÷ (layer height × line width)) ÷ width`. At 45 mm³ prime, 0.12 mm layers, 0.42 mm lines and 2 changes/layer: 893 mm of path ÷ 130 mm ≈ 7 turns ≈ 2.9 mm depth per change ≈ **5.8 mm total depth**. A long, shallow tower fits the ~30 mm strip left in front of the poster; a default square one does not. |
| Prime tower **Brim width** | Process → Others | **5 mm** | A 130 × 6 mm tower 32 mm tall is tippy. |
| Prime tower position | drag on the plate | front strip, ≥15 mm from the plate edge | Studio enforces a 15 mm keep-out around the plate edge. If the tower still won't place, drop `size_mm` from 250 → 240. |
| Filament change volume ("Prime volume" pre-2.0) | Filament settings, **per filament** (BS 2.0+) | **45 mm³** default, **60 mm³ for grey** | Grey is the light colour being contaminated by two darker ones. |
| Flushing volumes → **Multiplier** | Project Filaments → Flushing volumes | **1.0** while diagnosing | Bambu's auto values are deliberately conservative. Do not reduce until the grey is clean. Once clean, 0.8–0.9 saves a lot (see waste note below). |
| Flushing volumes → per-pair | same dialog | see table below | |
| **Flush into objects' infill** | Process → Others | **OFF on relief.3mf**, **ON on frame.3mf** | Wiki warning is explicit: lighter and transparent filaments let contaminated infill show through, and the fewer walls/shells, the worse. Grey and blue are the light colours in the relief — turn it off there. The frame is black with 2 walls and a black roof: dumping white purge into its infill is invisible and saves real money. |
| **Flush into this object** (per-object, Process → Objects) | | **OFF for the relief body and both caps** | Same reason. |
| Flush into objects' support | Process → Others | ON (default, no supports anyway) | |
| Interlocking depth of a segmented region | Process → Others → Advanced | **0.6 mm** (≈5 layers at 0.12) | Interlocks the colour boundary instead of butt-joining it. Helps the cap edges read as a line rather than a fringe. Orca additionally exposes **Maximum width of a segmented region** (`mmu_segmented_region_max_width`) — leave it 0 unless you slice in Orca. |
| Interface shells | Process → Others (Orca: Multimaterial) | **OFF** | Forces a solid shell between adjacent materials. Sounds helpful; in practice it adds a full solid wall around every cap band, i.e. more colour changes and more purge, and the caps are already surface features. |
| Filament printing sequence for layers | right sidebar, per-layer filament order | **Fix a deterministic order: green → blue → grey** | Two wins: grey (the light one that shows contamination) always follows the *same* predecessor, so you only have one flush pair to tune instead of two; and grey is laid last on the layer, so nothing travels over it afterwards. |

### Flushing volume table (green E1, blue E2, grey E3)

Start here, then adjust the *→ grey* rows only.

| From → To | mm³ |
|---|---|
| green → blue | 400 |
| blue → green | 350 |
| green → **grey** | **550** |
| blue → **grey** | **600** |
| grey → green | 250 |
| grey → blue | 300 |

Rule of thumb behind these (community consensus, matches Bambu's own algorithm's
shape): light→dark 100–200 mm³, mid-tone→mid-tone 200–400 mm³, dark→light
500–800 mm³, anything→transparent 700+ mm³.

### Why the grey is blotted — and how thick a colour region must be

Three mechanisms stack, in order of how much they matter:

1. **The grey region per layer is smaller than the purge it needs.** A 0.6 mm-deep
   conformal cap intersected by a horizontal slice is a band whose plan width is
   `cap_depth / tan(slope)`. On a 45° slope that's **0.6 mm — 1.4 extrusion widths**.
   On a 60° slope it's 0.35 mm, i.e. *less than one line*. Slicers detect such
   non-printable segmented regions and **merge them into the neighbouring region,
   changing its colour** (documented Orca/PrusaSlicer MMU segmentation behaviour;
   Bambu Studio inherits it). Result: partly green-where-it-should-be-grey, partly a
   1-line grey squiggle printed entirely out of transition filament. That reads exactly
   as "blotted". **This is the primary cause.**
2. **Contaminated filament is landing in the model.** Any of: prime tower off/absent,
   "flush into objects' infill" on, or flush volume into grey set too low. Fix per the
   table above.
3. **Translucency.** 3 layers (0.6 mm) of PLA over green is not fully opaque, especially
   for a light grey. Community consensus for colour features that must read as solid:
   **0.6 mm is the minimum, 1.0 mm is where it reliably stops showing the substrate**,
   and Bambu's own 0.2 mm profiles push colour ~3 layers deep for this reason.

**Minimum colour-region rules to design to:**

- **≥ 5 layers deep** (0.6 mm at 0.12) for opacity — and prefer 8–10 layers (~1.0–1.2 mm).
- **Every in-plane colour feature ≥ 2 line widths = 0.84 mm wide**, ideally ≥ 1.5 mm.
  Anything below that is a coin flip.
- Consequence for a conformal cap: `cap_depth ≥ 2 × line_width × tan(θ_max)`.
  For 0.42 mm lines and terrain up to 60°, that's **≥ 1.45 mm**; use **2.4 mm** (20
  layers) for margin. See §8.

**Does a narrow diagonal band inherently print badly?** Yes. There is no slicer setting
that makes a sub-extrusion-width colour band print cleanly. Mitigations in order of
effectiveness: (1) make the cap deeper so the band is wider — geometry, not settings;
(2) `Interlocking depth of a segmented region` so the boundary meshes instead of
butting; (3) Arachne + Detect thin wall so what survives is printed as a variable-width
line rather than dropped; (4) Avoid crossing wall + Z hop so the band isn't smeared
after it's laid.

### Purge waste — budget for it

267 layers × up to 2 colour changes × ~(500 mm³ flush + 45 mm³ prime) ≈ **250–330 cm³
≈ 320–420 g of purge** on the relief plate alone. That is not a bug, it's what a
per-layer 3-colour print costs. Reduce it, *after* the colour is clean, by: dropping
the Multiplier to 0.8–0.9, and by making the caps deeper (deeper caps means the same
number of changes buys far more visible colour per change).

---

## 4. Nozzle: keep the 0.4

A 0.2 mm nozzle is the wrong call here, and the reason is not just print time:

- **Time.** Community consensus is roughly **4× the print time** of a 0.4 for the same
  part. The relief goes from ~33 h to ~5 days.
- **Multi-colour makes it much worse.** Bambu's own wiki: purge is extruded at max
  volumetric speed, which is dominated by nozzle size, so *"a 0.2 mm nozzle may take
  significantly longer to complete the Flushing step than a standard 0.4 mm nozzle,
  noticeably increasing filament change time and overall multimaterial print duration."*
  With ~500 colour changes, that is hours of pure purging.
- **You don't need it.** Your terrain source resolution is 0.4 mm/px (`res_mm=0.4`) and
  the DEM is blurred by 2 px before quantisation. There is no XY detail below 0.4 mm in
  the model to resolve. A finer nozzle would print the blur, not new terrain.
- The detail you are missing is **vertical** (quantisation steps), and that is bought by
  layer height, which costs 1.7× — not by nozzle diameter, which costs 4×.

Get fine detail from a 0.4 by: outer wall and top surface line width **0.40 mm**,
layer height **0.12 mm**, Arachne, and slice gap closing radius **0.01**.

---

## 5. Per-part overrides

### relief.3mf — terrain body + 2 caps, 250×225 mm, 3 extruders

| Setting | Value |
|---|---|
| Layer height | 0.12 mm |
| Wall loops | 3 |
| Top shell layers / Bottom shell layers | 5 / 4 |
| Sparse infill | Grid, 15 % |
| Top surface pattern | Monotonic line |
| Ironing | **No ironing** |
| Flush into objects' infill | **OFF** |
| Flush into this object (all three bodies) | **OFF** |
| Brim type / width | Outer brim only, **5 mm** |
| Support | None |
| Orientation | Long axis (250) along X, flat back on the plate. Leave the front strip free for the prime tower. |

### frame.3mf — black backplate + ring + white text, 250 mm, 14 mm, 2 extruders

| Setting | Value |
|---|---|
| Layer height | 0.12 mm (match the relief — they sit side by side and the layer lines must line up visually) |
| Wall loops | 2 |
| Top shell layers | 6 |
| Ironing type | **All top surfaces**, flow 15 %, spacing 0.10 mm, speed 30 mm/s, **inset 0.4 mm** |
| Sparse infill | Grid, 12 % |
| Flush into objects' infill | **ON** (black body, invisible) |
| Flushing volume black → white | **700 mm³** (worst-case dark→light) |
| Flushing volume white → black | 150 mm³ |
| Brim type / width | Outer brim only, 5 mm |

### path.stl — 1.7 mm × 5–16 mm × ~250 mm ribbon, 1 extruder

The ribbon follows a curved plan path, so it **cannot** be laid flat on its side —
a curved-in-plan vertical ribbon is not a planar shape. Print it standing, as designed.
(If you ever generate a straight-line path, laying it flat is strictly better: 14 layers
instead of 133, 10× the bed contact, and the height profile becomes a crisp XY outline.)

| Setting | Value | Why |
|---|---|---|
| Layer height | 0.12 mm | Matches the relief it's glued into; the layer lines are adjacent and visible. |
| Wall loops | **2** | 2 loops × 2 sides × 0.425 mm = **1.7 mm exactly**. The ribbon becomes pure perimeter — no infill, no gap fill, maximum strength, no under-extruded core. Do not use 1 or 3. |
| Wall generator | Arachne | Absorbs the ±0.05 mm the slot clearance leaves. |
| Sparse infill density | 0 % (nothing left to fill) | |
| Top / bottom shell layers | 3 / 3 | |
| Detect thin wall | ON | |
| Brim type / width / gap | **Outer brim only**, **8 mm**, gap **0** | Footprint is only ~425 mm². Standing thin parts want 10–15 mm brim; 8 mm plus the ribbon's own length is enough, and it snaps off cleanly. |
| Z hop | Normal, 0.4 mm | Nothing should touch the fin on a travel move. |
| Support | **None** | It is a vertical wall; there are no overhangs. |
| Print sequence | Its own plate | Don't share a plate with a 30 h multi-colour print. |
| Reduce fan / min layer time | leave default | Each layer is ~1000 mm of extrusion (~7 s) — no minimum-layer-time slowdown needed and no heat build-up. |

---

## 6. Plate & adhesion (250 mm flat PLA)

| Setting | Value | Why |
|---|---|---|
| Build plate type | **Textured PEI Plate** — and it must match the physical sheet | Bambu's most common warping cause is slicing for Cool Plate while printing on Textured PEI: the bed runs far too cold. |
| Bed temperature (other layers / first layer) | **60 / 65 °C** | +5 °C over stock for a 250 mm footprint. |
| Brim type | **Outer brim only** | |
| Brim width | **5 mm** (relief, frame), **8 mm** (path) | |
| Brim-object gap | **0** | |
| Initial layer height | 0.2 mm | |
| Initial layer speed | 50 mm/s | |
| Initial layer line width | 0.5 mm | |
| Door / top glass | **Open** for PLA | Bambu's warping advice to close the chamber is for ABS/ASA/PC/PA. PLA on an enclosed machine suffers heat creep and soft, glossy overhangs instead; a big flat PLA plate does not need chamber heat. |
| Before you start | Wash the plate with dish soap and water; re-run auto bed levelling; check Z-offset — the first layer must be squished | Standard Bambu warping checklist; on 250 mm there is no margin. |
| If corners still lift | Add brim ears / mouse ears at the four corners, and drop first-layer speed to 30 mm/s | |

---

## 7. Settings that specifically ruin heightmap/relief prints — turn these OFF

| Setting | Why it wrecks a relief |
|---|---|
| **Adaptive / variable layer height** | Re-heights layers, so quantised terrain no longer lands on layer boundaries → the ragged sub-layer islands come back. Also blocks the prime tower unless every object shares the identical profile. |
| **Precise Z height** | Silently rescales the last 5 layers to hit exact model height. Your peaks are those 5 layers. |
| **Slice gap closing radius at the 0.049 default** | Documented cause of missing walls and vanished small features in fine models. Set 0.01. |
| **Classic wall generator** | Renders sub-line-width terrain features as isolated dots. Use Arachne. |
| **Arc fitting** | Approximates dense heightmap polylines with arcs; visible faceting on organic contours. |
| **Infill combination / Combine infill every N layers** | The roof footprint changes every layer on a relief; combined infill leaves it unsupported → pillowing between terraces. |
| **Lightning infill** | Same reason, worse. |
| **Flush into objects' infill / Flush into this object (on the relief)** | Puts purge inside the part; shows through the light grey and blue. |
| **Ironing "All top surfaces" on the relief** | Every terrace edge gets a bow-wave ridge; adds many hours for no gain on a non-flat top. |
| **Reduce infill retraction** | Ooze onto a multi-colour top surface. |
| **Timelapse → Smooth mode** | Parks the head and re-primes every single layer for 267 layers. |
| **Non-zero XY hole/contour compensation** | Uniformly erodes or inflates every contour on the map. |
| **Spiral vase, Fuzzy skin** | Obviously, but check they're off in an inherited profile. |

---

## 8. Generator-side implications

Recommendations only — no code. Current defaults referenced from `poster.py`
(`layer_mm=0.2`, `cap_mm=0.6`, `res_mm=0.4`, `relief_mm=20.0`, `text_mm` scaled,
`snow_min_mm=3.0` at 250 mm).

1. **`layer_mm` default → 0.12.** Everything below assumes it. This single change
   multiplies the terrain's vertical quantisation levels by 1.67 over the same relief
   amplitude, which is most of "not fine enough".

2. **Quantise to `first_layer + n × layer_mm`, not `n × layer_mm`.** With the 0.12 mm
   preset the first layer is 0.2 mm (Bambu's nozzle Ø × 50 % rule). Absolute Z of every
   printed layer boundary is therefore `0.2 + n×0.12`. Offset the snapping grid by the
   first-layer height, or the whole terrain sits half a layer off every boundary and
   you get exactly the ragged islands the snapping was added to prevent. Expose
   `first_layer_mm` (default 0.2) alongside `layer_mm`.

3. **`cap_mm` 0.6 → 2.4 mm.** This is the fix for the blotted grey. A conformal cap's
   per-layer plan band is `cap_mm / tan(slope)`; at 0.6 mm it is under two extrusion
   widths (0.84 mm) for anything steeper than 36°, and under one line past 55°, at
   which point the slicer merges it into the neighbouring colour. 2.4 mm keeps the band
   ≥ 0.84 mm out to 71° of slope. It is also 20 layers at 0.12, comfortably past the
   ~1.0 mm opacity threshold. Cost: more blue/grey filament, but *less* purge per gram
   of visible colour, because the number of tool changes per layer is unchanged.
   - Keep the "must be a whole number of layers" invariant: **`cap_mm` should be
     `round(cap_mm / layer_mm) * layer_mm`**, computed rather than hard-coded, and
     validated (2.4 / 0.12 = 20 ✓; 0.6 / 0.16 = 3.75 ✗).
   - Better still where filament cost allows: make the water and snow bodies
     **full-depth prisms** (colour extends from the terrain surface down to the base
     plate) instead of conformal slabs. Then the per-layer colour region is a large
     plan area with no narrow bands anywhere, and the print quality problem disappears
     entirely rather than being mitigated.

4. **Add a minimum in-plane feature size to the cap masks, expressed in line widths.**
   `snow_min_mm` already opens/closes the grey mask at 3.0 mm — good, keep it, and
   apply the same treatment to the **water** mask (currently unfiltered), where a
   0.5 mm alpine tarn will print as a blue smear. Floor for both: **≥ 1.5 mm**
   (≈ 3.5 extrusion widths), never below 0.84 mm (2 × line width) at any `size_mm`.
   The existing `_SCALED` floor of 1.5 mm for `snow_min_mm` is right; water needs one.

5. **`res_mm` stays 0.4.** It already equals one extrusion width; finer sampling adds
   triangles and slicing time but no printable detail — and `smooth_px=2.0` blurs over
   2 px = 0.8 mm anyway. If you want genuinely finer terrain, **reduce `smooth_px` to
   1.0–1.5 at `layer_mm=0.12`**: the blur exists to kill sub-layer noise, and halving
   the layer height halves how much blur is needed. That, not `res_mm`, is where the
   perceived softness comes from.

6. **Maximise use of the 20 mm relief amplitude.** With `layer_mm=0.12`, 20 mm gives
   167 steps. If a given track's elevation range under-fills that (flat regions), the
   effective step count collapses and the terrain reads as plateaus. Consider
   auto-setting `exaggeration` so the DEM's actual min–max maps to the full
   `relief_mm`, with a cap so alpine tracks don't become spikes.

7. **`text_mm` / proud text height must be a whole number of layers too.** 0.8 mm at
   0.12 is 6.67 layers — the top of the text lands mid-layer and the last row is either
   dropped or fuzzy. Snap it: **0.72 mm (6 layers)** or **0.84 mm (7 layers)**. Same
   treatment for `proud_mm` and `SLOT_FLOOR_MM` (1.0 mm is 8.33 layers → use 0.96 mm).

8. **Slot clearance vs. wall arithmetic.** `path.stl` at 1.7 mm is exactly 4 × 0.425 mm
   extrusions, which is why it prints as pure perimeter. Keep the ribbon width an
   **even multiple of ~0.42 mm** (1.68, 2.10, 2.52 mm) as `size_mm` scales, rather than
   a round number — an odd remainder forces gap-fill down the centre of the fin and
   halves its strength.

9. **Reserve plate space for the prime tower.** A 250 × 225 mm relief plus a prime tower
   is tight on 256 × 256 with Studio's 15 mm edge keep-out. Either document "set prime
   tower width to 130 mm and place it in the front strip", or default `size_mm` to
   **240** so a conventional tower fits without fuss.

10. **Emit the recommended profile alongside the files.** Since the geometry now encodes
    `layer_mm` and `cap_mm` assumptions, the download should state them (a one-line
    README or a comment in the 3MF name, e.g. `relief_0.12mm.3mf`) so a mis-set slicer
    profile is obvious before 30 hours are spent.

---

## Sources

- [Layer height | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/layer-height) — usable range 20–70 % of nozzle Ø, first layer = nozzle Ø × 50 %, layer rounding logic, Precise Z height (last 5 layers)
- [Variable Layer Height | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/adaptive-layer-height) — adaptive mode, and the prime-tower / organic-support restrictions
- [Ironing | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/parameter/ironing) — ironing types, flow, spacing "smaller than nozzle diameter", inset, direction, and "only effective when the top surface is flat"
- [Prime tower | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/parameter/prime-tower) — width/prime volume/brim, the tower-depth formula, flushing volume vs prime volume, BS 2.0 per-filament prime volume
- [Reduce Waste during Filament Change | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/reduce-wasting-during-filament-change) — flush/wipe/prime stages, flushing multiplier, flush into objects' infill/support/this object, and the 0.2 mm nozzle flushing-speed penalty
- [Multi-Color Printing | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/multi-color-printing) — why flushing volume exists
- [Line width | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/parameter/line-width) — per-feature line widths, 0.75–1.5 × nozzle Ø guidance
- [Model Warping, Falling Off, or Collapsing | Bambu Lab Wiki](https://wiki.bambulab.com/en/filament-acc/filament/print-quality/warping-falling-off-collapsing) — plate-type matching, bed temp, brim/brim ears, chamber guidance
- [Multimaterial Advanced — OrcaSlicer Wiki](https://www.orcaslicer.com/wiki/print_settings/multimaterial/multimaterial_settings_advanced) — `interface_shells`, `mmu_segmented_region_max_width`, `mmu_segmented_region_interlocking_depth`
- [Multi material painting | Prusa Knowledge Base](https://help.prusa3d.com/article/multi-material-painting_262620) — "thin non-printable regions created during segmentation are detected and merged with the neighbouring region, changing its colour" (the mechanism behind the blotted grey)
- [Flushing Volumes in Bambu Studio & OrcaSlicer: Complete Guide](https://www.3dprofilefix.com/guides/flushing-volumes-guide.html) — per-pair mm³ ranges by colour direction, multiplier guidance, "never flush into infill on a white or clear model"
- [How to Fix Ugly Top Surfaces on Bambu Lab Printers](https://www.3dprofilefix.com/guides/how-to-fix-top-surface.html) — 5→6–7 top shell layers, ~1 mm roof target, infill density bump
- [Ironing in Bambu Studio: How to Get a Perfectly Smooth Top Layer — 3DBite](https://3dbite.com/bambu-studio-ironing-settings-guide/) — flow 15 % start (15–30 % PLA), spacing 0.15 → 0.10 for display work, speed 40 mm/s, inset 0.2 mm
- [Reduce Prime Tower Waste in Bambu Studio — 3DBite](https://3dbite.com/reduce-prime-tower-waste-bambu-studio/) — tower width/placement, 15 mm plate keep-out
- [BambuStudio issue #1573 — Multi-colour goes multiple layers "deep"](https://github.com/bambulab/BambuStudio/issues/1573) — colour regions extending 4–5 layers below the intended one
- [BambuStudio issue #5618 — "Flush into object"/"flush into infill" unavailable if prime tower is disabled](https://github.com/bambulab/BambuStudio/issues/5618)
- [BambuStudio issue #1953 — monotonic applied only to the topmost layer](https://github.com/bambulab/BambuStudio/issues/1953)
- [Forum: Colour layer showing in multiple layers](https://forum.bambulab.com/t/color-layer-showing-in-multiple-layers/36715) — 0.2 mm profiles enforcing ~3 layers of colour penetration
- [Forum: Multi-Color Bleed Through](https://forum.bambulab.com/t/multi-color-bleed-through/3980) and [Multicolor Bleeding](https://forum.bambulab.com/t/multicolor-bleeding/144969) — thin colour regions and complex geometry defeat the slicer's colour-thickness optimisation
- [Forum: Best practice for printing logo (2 colours)](https://forum.bambulab.com/t/best-practice-for-printing-logo-in-first-layer-2-colors/17554) — 0.6 mm minimum, 1 mm better, for a colour to read solid
- [Forum: Slicer ignores small cuts in the part](https://forum.bambulab.com/t/slicer-ignores-small-cuts-in-the-part/112082) — slice gap closing radius default 0.049 destroying detail
- [Forum: Bambu Studio 1.7.3.50 slicing issues](https://forum.bambulab.com/t/bambu-studio-1-7-3-50-slicing-issues/23673) — Classic vs Arachne wall generator and lost thin-wall detail
- [Forum: First time I used 0.2 mm nozzle](https://forum.bambulab.com/t/first-time-i-used-0-2mm-nozzle-unbelievable-print-quality/45696) and [Confused over nozzle size/print time](https://forum.bambulab.com/t/confused-over-nozzle-size-print-time/83455) — ~4× print time, only worth it for genuinely small features
- [Forum: Large print keeps warping at corners](https://forum.bambulab.com/t/large-print-keeps-warping-at-corners-tried-liquid-glue-and-brims/44024) and [Warping — PLA — Textured PEI Gold Plate](https://forum.bambulab.com/t/warping-pla-textured-pei-gold-plate/60067)
- [Forum: Prime tower on edge of build plate?](https://forum.bambulab.com/t/prime-tower-on-edge-of-build-plate/66471) — plate keep-out and tower placement
- [ScienceInsights: How to 3D print tall thin objects](https://scienceinsights.org/how-to-3d-print-tall-thin-objects-without-them-falling-over/) — brim 10–15 mm, Z-hop, reduced speeds for tall thin parts
