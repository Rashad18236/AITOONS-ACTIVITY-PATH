# Bambu Studio print settings — Flight Path Poster

Target: Bambu X1C / P1S / H2D class, 256×256 plate, 0.4 mm nozzle, AMS, PLA.
Three plates: `relief.3mf` (3 colours), `frame.3mf` (2 colours), `path.3mf` (1 colour;
`path.stl` in the sections below, written before it became a project).

Written against Bambu Studio 1.10 / 2.x setting names. Where a name differs in
Orca Slicer it is noted.

---

## What the generator embeds (A1 0.4)

The target is now the **Bambu Lab A1, 0.4 nozzle, only**: an open bed-slinger with
the AMS lite, so every door / chamber row below does not apply. All three files are
finished OrcaSlicer 2.3.2 projects: open, slice, print. Each carries the full
flattened system chain (`Bambu Lab A1 0.4 nozzle` / `0.24mm Draft @BBL A1` / `Bambu PLA
Basic @BBL A1`, vendored as `orca_a1_pla.json`) with `COMMON`, `PLATES` and
`PART_OVERRIDES` from `poster.py` on top. Those tables are the truth; this file is the
why. Where they differ from the sections below:

- **Layer height 0.24 mm, not 0.12.** The user measured the 0.12 prints as far too
  long, and the decision is final. Sliced on the 216 order (D-EMFE) with the Orca 2.3.2
  CLI, the relief changes filament once per layer, because the roads drape into the
  slot, so halving the layer count halves the changes too. The terrain step becomes
  7.6 m instead of 3.8 m, which the user accepted. The generator's grid follows:
  every z is `0.2 + n*0.24` (slot floor 1.16, plate 2.12). Measured variants (Orca CLI
  estimate):

  | Plate | Variant | Time | Changes |
  |---|---|---|---|
  | frame | base (0.12, ironing on) | 8.29 h | 1 |
  | frame | no ironing | 3.92 h | 1 |
  | frame | no ironing + 0.24 | 3.46 h | 1 |
  | relief | base (0.12, walls 3 / top 5 / 15 %) | 18.84 h | 155 |
  | relief | walls 2 + top 3 | 16.36 h | 155 |
  | relief | flush × 0.6 | 18.00 h | 155 |
  | relief | flush into infill | 18.44 h | 155 |
  | relief | 0.24 | 11.29 h | 79 |
  | relief | 0.24 + walls 2 + top 3 | 9.72 h | 79 |

  Flushing is not where the time goes; layer count and ironing are.
- **Frame: ironing off, 7 % infill.** Ironing was over half the frame's time. Walls
  2, seam `nearest`.
- **Relief: walls 2, top 3, 10 % infill** (the user's numbers); MMU interlocking depth
  0.72 = 3 layers.
- **Shells as thickness**, so the change of layer height reads honestly. A bottom
  shell starts with the 0.2 first layer.

  | Plate | Top / bottom layers | Top | Bottom | Was at 0.12 |
  |---|---|---|---|---|
  | frame | 3 / 3 | 0.72 mm | 0.68 mm | 6 / 4 = 0.72 / 0.56 |
  | relief | 3 / 3 | 0.72 mm | 0.68 mm | 5 / 4 = 0.60 / 0.56 |
  | path | 2 / 2 | 0.48 mm | 0.44 mm | 3 / 3 = 0.36 / 0.44 |
- **Caption: 2 walls at 0.40 mm, 5 top layers, only one wall on top surfaces ON** (per
  part, text only), the user's own "AIToons Sopra" look. This **supersedes** the caption
  section below (2 loops at 0.36, only-one-wall-top OFF) and an interim 3 loops at 0.40:
  with only-one-wall-top OFF the 1.07–1.33 mm strokes were filled by beads alone, no top
  surface was ever generated, and Orca showed hollow outline letters on the 216 order.
  Now the top layer is one outline plus a monotonic top surface, so the letters read
  filled; measured gap area in the top layer is the same (7.4 vs 6.7 mm² for the whole
  caption). `inner wall/outer wall`, 100 % infill, no ironing on the text.
  `test_orca_slices_every_plate` asserts the frame's last layer has a top surface.
- **`flush_into_infill` OFF on the frame too.** The caption section wins over §3.
- **Prime tower 130 mm wide at x 63 / y 5**, behind which `write_3mf` centres the
  object (x centred, y centred in 20–256). Sliced at 0.24 on the 216 order, the frame's
  tower is 6.75 mm deep. That is Orca's height-based stability minimum, not purge
  volume: at 0.12 a 180 mm tower sliced the same depth, so it stays at 130. The tower's
  brim and stabilising cone reach y 16.8 (frame) / 17.3 (relief); the objects' brims
  start at y 20.4 / 36.0. `path.3mf` has one filament and no tower.
- **Path on the slinger:** outer wall 50, inner 80 mm/s, outer-wall acceleration
  1000 for a 28 × 1.1 mm fin on a moving bed; brim 8 mm.
- **Not embedded:** the per-layer filament print order (set it by hand if wanted).
  Thumbnails, `plate_1.json` and `slice_info.config` are left out because Orca
  regenerates them.

Orca also reports three warnings, and the unmodified system preset gives the same three:
"bed temperature higher than the filament's vitrification temperature" (PLA Basic 65 °C
textured plate vs 45 °C, a closed-door warning that does not apply to the open A1) and
two "traditional timelapse not supported". It also logs "precise wall ignored for
inner-outer-inner": `precise_outer_wall` only takes effect on the caption, whose
sequence is `inner wall/outer wall`.

Sliced, 216 order (D-EMFE), at 0.24 with these settings: frame 2.69 h / 131 g (1
change), relief 9.55 h / 156 g (77 changes), path 0.86 h / 9.4 g. At 0.12 it was
8.29 h / 147 g, 18.84 h / 210 g (155 changes) and 1.43 h / 9.6 g.

---

## 0. Verdicts up front

| Question | Verdict |
|---|---|
| Layer height | **0.12 mm** ("0.12 mm Fine" preset, 0.4 nozzle). Not 0.2, not 0.08. **Superseded — see the head section** (0.24 since the measured A1 print times). |
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
| Prime tower position | drag on the plate | front strip, ≥15 mm from the plate edge | Studio enforces a 15 mm keep-out around the plate edge. The generator now budgets for this instead of leaving it to the slicer: `poster.USABLE_MM` = 256 − 2×5 mm brim − 4 mm gap − 16 mm tower-plus-its-brim = **226 mm**, on *both* axes, and no size that busts it can be ordered. If your tower comes out deeper than 6 mm (more than 2 changes per layer), lower `USABLE_MM` and the sizes with it. |
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

### relief.3mf — terrain + water/road caps + grey band, 194.8 mm square at the 216 size, 3 extruders

| Setting | Value |
|---|---|
| Layer height | 0.12 mm |
| Wall loops | 3 |
| Top shell layers / Bottom shell layers | 5 / 4 |
| Sparse infill | Grid, 15 % |
| Top surface pattern | Monotonic line |
| Ironing | **No ironing** |
| Flush into objects' infill | **OFF** |
| Flush into this object (all bodies) | **OFF** |
| Brim type / width | Outer brim only, **5 mm** |
| Support | None |
| Orientation | Flat back on the plate. Leave the front strip free for the prime tower. |

### frame.3mf — black backplate + ring + white text, 215.6 × 226.0 mm, 13.9 mm, 2 extruders

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

### path.stl — 0.84–1.13 mm × up to 28 mm × up to 150 mm ribbon, 1 extruder

The ribbon follows a curved plan path, so it **cannot** be laid flat on its side —
a curved-in-plan vertical ribbon is not a planar shape. Print it standing, as designed.
(If you ever generate a straight-line path, laying it flat is strictly better: 14 layers
instead of 133, 10× the bed contact, and the height profile becomes a crisp XY outline.)

| Setting | Value | Why |
|---|---|---|
| Layer height | 0.12 mm | Matches the relief it's glued into; the layer lines are adjacent and visible. |
| Wall loops | **2** | The ribbon is `groove_w_mm - 2*clearance_mm` wide, and `groove_w_mm`'s floor was raised to 1.44 mm so that comes to **0.84 mm — exactly 2 × 0.42** at the 120 and 170 sizes. Pure perimeter: no infill, no gap fill, no under-extruded core. At 216 the core is 1.13 mm and Arachne widens the same two beads to ~0.57 mm, which is still inside the 0.75–1.5 × nozzle band. Do not use 1 or 3. *(Was "1.7 mm exactly" — that was measured before the sizes and the clearance moved, and at the 1.2 mm floor the fin was 0.60 mm, a single wobbly bead 16 mm tall.)* |
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

Recommendations only — no code. Defaults as they stood when this was written
(`layer_mm=0.2`, `cap_mm=0.6`, `res_mm=0.4`, `relief_mm=20.0`, `text_mm` scaled,
`snow_min_mm=3.0` at 250 mm). **Since implemented:** `layer_mm=0.12` on the
`0.2 + n*0.12` grid, `cap_mm=0.96`, and grey is now an elevation band, not a cap —
`snow_min_mm` and its morphology are gone (item 4 below no longer applies to grey);
then 0.24, see top.

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

8. **Slot clearance vs. wall arithmetic.** ~~`path.stl` at 1.7 mm is exactly 4 × 0.425 mm
   extrusions~~ — stale; the fin is `groove_w_mm - 2*clearance_mm`, which the sizes and
   the clearance have both moved since. **Done in part:** `groove_w_mm`'s floor is 1.44,
   so the fin is 0.84 mm = exactly 2 × 0.42 at the 120 and 170 sizes. It is 1.13 mm at
   216, which Arachne prints as two 0.57 mm beads — not gap-filled, but not the
   whole-bead ideal either. Snapping the fin to whole beads at *every* size is still
   open, and would widen the visible path line on the large poster.

9. ~~**Reserve plate space for the prime tower.**~~ **Done, and it was worse than this
   said.** The rule was never just the tower: a 240 mm poster's frame meshes 239.6 ×
   250.4 mm — inside the bare 256 plate, which is all `PLATE_MM` ever checked — and the
   5 mm brim alone takes it to 249.6 × **260.4 mm**, off the bed before the tower is
   placed. `poster.USABLE_MM` (226 mm) is now the budget every footprint is measured
   against, in the generator's guard, in `check_output.py` and in the live UI line, and
   `SIZES_MM` is `(216, 170, 120)` because 216 is the largest grid-exact size whose
   two-line frame lands inside it (215.6 × 226.0 mm exactly).

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

---

## Frame & caption — sharp text profile

Scope: `frame.3mf` only — one multi-part object, part **"frame"** (extruder 1, black) and
part **"text"** (extruder 2, white), 169.6 × 179.2 mm at `size_mm=170`, base 4.04 mm,
ring top z ≈ 10.81 mm, caption 0.84 mm proud (7 layers at 0.12). This section refines
§1, §2, §3 and §5 for the caption; where it contradicts §5's `frame.3mf` row, this
section wins, and the contradiction is called out.

**Since implemented** (items 1–3 of *Generator-side implications* below): the caption is
**1.20 mm** proud (10 layers), resolved Z dimensions are snapped to whole layers so the
ring top at `size_mm=170` is **10.88 mm** (`0.2 + 89 × 0.12`) and the caption spans
layers 89–99, and the caption is set in **Trebuchet MS Bold, 0.84 mm target,
topology-guarded**. Read 0.84 mm and 10.81 mm below as the numbers that motivated
the change, not as what the generator emits. Item 4 (cap-height floors) is **not**
implemented: at 170 mm the subtitle is still 3.5 mm, and the stroke floor thickens it
to the point where its letters touch — raise `size_mm`, `text_mm` or `SUB_RATIO` if
that shows.

### The two facts that drive everything here

1. **Glyph strokes are 0.6–0.9 mm — 1.5–2.2 extrusions wide.** At that scale a stroke is
   *entirely perimeter*. There is no infill, no top fill, nothing else. Every quality
   decision is therefore a wall-generator decision, and the goal is: **every stroke
   resolves to a whole number of beads, and that number never changes along the stroke.**
2. **Nothing black exists above z = 10.81.** The ring top is flat all round (the chin is
   9.6 mm taller in *plan*, not in Z), so the caption is the only geometry in the top
   7 layers. The plate therefore contains **exactly one filament change** (black → white,
   at the layer where the caption starts). That single fact makes purge essentially free
   and rewrites §3's cost model for this plate — see *Multi-colour* below.

### Settings table

`P` = **per-part override on the "text" part** (select the part in the Objects list,
gear icon → *Add settings*). `F` = per-part on the "frame" part. `O` = object-level
(whole `frame.3mf` object). `G` = whole plate / Process preset.

Scope caveat: line widths, wall loops, wall-generator parameters, ironing, shell counts
and feature speeds are *region*-scope in the PrusaSlicer lineage Bambu Studio inherits,
so they are offerable per part. **Seam position, layer height, brim and supports are
object-scope** — they cannot be set on one part only. If your Studio build does not
offer a given row on the part, set it plate-wide; every value below is harmless on the
black frame too.

#### Wall generator (Quality → Precision; Advanced mode. Orca: Quality → Walls and surfaces → Advanced)

| Setting (Bambu Studio) | Scope | Value | Why |
|---|---|---|---|
| **Wall generator** | G | **Arachne** | Not close. At 1.5–2.2× line width Classic must choose 1 or 2 fixed-width loops and dump the remainder into gap fill — that is the blob down the middle of a stem and the closed counter in an *e*. Arachne varies bead width continuously and prints a 0.7 mm stroke as one 0.7 mm bead or two 0.35 mm beads with **no gap fill at all**. Verify it after every Studio update; regressions to Classic have shipped in Bambu profiles before (§7). |
| **Wall transition filter margin** (`wall_transition_filter_deviation`) | P | **50 %** (0.20 mm; default 25 %) | **The most valuable knob in this whole section.** It is hysteresis on the bead-count decision. The text mesh is built on a 0.1 mm grid, so a nominally 0.70 mm stem actually wobbles ±0.05 mm along its length. At the default margin Arachne flips 2 beads → 1 bead → 2 beads over a few millimetres, and every flip is an extrusion stop/start: a nick on one edge and a bead of surplus on the other. 50 % makes the stroke commit to one bead count and hold it. |
| **Minimum wall width** (`min_bead_width`) | P | **85 %** (0.34 mm) — **leave it** | This is the width below which Arachne refuses to split into two beads, so it sets the 1-bead/2-bead crossover at 2 × 0.34 = **0.68 mm**. With strokes at 0.6–0.9 mm that puts 0.6 mm strokes on a single clean bead and 0.7–0.9 mm strokes on two — which is what you want. Do **not** lower it "to keep detail": beads under ~0.34 mm from a 0.4 mm nozzle wander inside the aperture and under-extrude. Do not raise it either — 100 % would push the crossover to 0.80 mm and force a 0.78 mm stroke through as a single 0.78 mm bead, 1.95× nozzle, past Bambu's own 1.5× ceiling. |
| **Minimum feature size** (`min_feature_size`) | P | **10 %** (0.04 mm; default 25 % = 0.10 mm) | Features thinner than this are discarded outright. The default is 0.10 mm — *exactly* the text mesh's grid pitch, so every one-cell facet on a curve sits on the coin-flip boundary. 10 % moves the threshold well clear of the geometry. Strokes are nowhere near this; what it protects is counters, serif junctions and the tips of *A*, *V*, *W*. |
| **Wall transition length** (`wall_transition_length`) | P | **100 %** (0.40 mm, default) — leave | The runway over which a 2-bead stroke tapers into a 1-bead one. Shortening it makes the change abrupt and deposits the surplus as a blob at the taper; lengthening it spreads a visible width ramp along a stroke only ~5 mm long. Default is right. |
| **Wall transitioning threshold angle** (`wall_transition_angle`) | P | **10°** (default) — leave | Wedges wider than this angle get *no* centre bead; lowering it removes more centre beads, raising it adds them. Letter terminals and stem/bowl junctions are wedges. At 0.7 mm stroke a centre bead is a third extrusion squeezed into two extrusions' worth of space — reliably a blob. **Uncertain**: one Bambu forum thread reports 59° working well for thin walls generally; that advice is for load-bearing thin walls, not 5 mm glyphs. If terminals print visibly hollow, step to 20–25° and re-check for blobbing. Do not start there. |
| **Wall distribution count** (`wall_distribution_count`) | P | **1** (default) — confirm | Number of beads, counted inward, allowed to vary in width. 1 pins the *outer* bead at exactly the outer-wall line width and dumps all variation on the inner one. The outer bead is the visible glyph edge; it must not breathe. |
| **Wall loops** | P | **2** | With outer/inner line width at 0.36 mm, 2 loops = 0.72 mm — a stroke is pure perimeter at every width in the 0.6–0.9 mm range. Same arithmetic as `path.stl` in §5. **1 loop** leaves a 0.1–0.2 mm remainder that becomes gap fill down the middle of every stem; **3 loops** cannot fit and Arachne discards the third anyway. |
| **Order of walls** | P | **Inner/Outer** | Not Inner/Outer/Inner — with only 2 loops there is no third pass, and Inner/Outer lays the visible bead last against a solid, already-cooled reference. |
| **Detect thin wall** | G | ON (no-op) | Classic-only in the PrusaSlicer lineage. Harmless under Arachne; leave as §1 has it. |
| **Slice gap closing radius** | G | **0.01 mm** | As §1. Critical here: the default 0.049 mm can weld a narrow counter shut on a 0.1 mm-grid mesh. |

#### Line widths (Quality → Line width)

| Setting | Scope | Value | Why |
|---|---|---|---|
| Outer wall | **P** | **0.36 mm** | 90 % of nozzle. Two effects: corner radius on the printed path is ≈ half the line width, so glyph corners sharpen from ~0.20 mm to ~0.18 mm; and 2 × 0.36 = 0.72 mm sits in the middle of the stroke-width band, so most strokes land on an exact 2-bead solution. |
| Inner wall | **P** | **0.36 mm** | Must match — the inner bead is half the stroke, not a hidden structural loop. |
| Top surface | **P** | **0.36 mm** | The glyph tops. See *Top surface* below. |
| Internal solid / sparse infill | **P** | 0.40 mm | Never used at this stroke width; set only so a fat glyph junction cannot invent a wide fill line. |
| All frame line widths | F/G | unchanged from §1 (0.42 default, 0.40 outer, 0.40 top) | The frame is not the problem. |
| **Minimum practical line width, 0.4 nozzle** | — | **0.30 mm hard floor, 0.34 mm practical** | Bambu's guidance is 0.75–1.5 × nozzle Ø = 0.30–0.60 mm, and Studio's own `min_bead_width` clamp is 85 % = 0.34 mm — set the outer wall to 0.30 and the wall generator will widen thin beads back to 0.34 anyway. **Cost of going below ~0.34:** the extrudate is stretched thinner than the aperture it left, so it wanders laterally within ±0.4 mm regardless of the commanded width — you buy path noise, not precision. Plus under-extrusion, weak layer bonding on a 7-layer part, and ~15 % more print time for the extra beads. **0.36 mm is the sweet spot; 0.32 mm is the floor worth trying if 0.36 leaves counters closed.** |

#### Seams (Quality → Seam — object scope, cannot be set per part)

Yes, a 0.84 mm-tall letter gets conventional seams: **one per closed loop, per layer**.
An *R* is 2 loops (outline + counter) × 7 layers = 14 seams. They land on the 0.84 mm
vertical side wall of the glyph, invisible from straight on, obvious in raking light.

| Setting | Scope | Value | Why |
|---|---|---|---|
| **Seam position** | O | **Sharpest corner** | Overrides §1's *Aligned* for this plate. Letters are almost entirely corners — stem ends, stem/bowl junctions, counter corners — and *Sharpest corner* tucks the start/stop into a concave corner where the geometry already breaks. *Aligned* stacks 7 seams into one vertical zip on an arbitrary point of each letter, which on an *O* lands mid-curve; *Random* gives you 7 scattered pockmarks per letter, which is strictly worse than one line. The frame ring loses nothing — its seam moves into a rectangle corner, which is where you'd want it anyway. |
| **Staggered inner seams** | O | **ON** | With 2 loops it offsets the inner bead's seam from the outer's, so the two do not stack into a through-channel across the stroke. |
| **Scarf joint seam** / *Smart scarf seam* / *Seam slope* | O | **OFF — all of it** | A scarf ramps flow up and down over a taper length of ~10 mm. A glyph counter perimeter is 3–8 mm total; the ramp cannot develop, so you get an under-extruded loop instead of a hidden seam. Documented limitation: scarf seams are not for perimeters shorter than the taper distance. This is a "must be off" (see below). |
| Seam gap | O | default (10 %) | Do not zero it on loops this short — the anti-blob gap matters more than the notch at this scale. |
| **Avoid crossing wall** | G | **ON** | Each letter is an island. On 7 layers with ~20 islands the head travels between letters constantly; every crossing is a chance to drag white over black. |
| Z hop type / height | G | **Auto / 0.4 mm** | Same reason. |
| Retraction / Wipe while retracting | G | default ON | Stringing white filament between letters across a black ring is the single most visible failure mode on this plate. Do not disable retraction on travel between islands. |
| Reduce infill retraction | G | **OFF** | As §1. |

#### Multi-colour (Project Filaments panel + Process → Others)

**Recalculated for this plate.** Because the caption is the only thing above z = 10.81,
the plate has **one** black→white change, not one per layer. Purge is therefore a
rounding error and should be maximised, not economised.

| Setting | Scope | Value | Why |
|---|---|---|---|
| Prime tower | G | **ON** | Mandatory. It is the only place the transition filament can go, and it re-stabilises nozzle pressure before the first white bead. Height only needs to reach 11.65 mm here, so it is cheap. |
| Prime tower width | G | 60 mm is plenty | A 170 mm poster leaves room; §5's 130 mm long-and-shallow trick is a large-plate problem. **Scope note:** `poster.USABLE_MM` budgets 16 mm of plate for the tower, which is the *130 mm-wide* tower plus its brim. A 60 mm tower is ~2× deeper for the same purge, so on the 216 mm size use the wide one — that budget is what makes the largest poster fit at all. |
| **Flushing volume black → white** | G | **999 mm³ (the maximum)** | Overrides §5's 700. It happens **once**, so the entire cost is ≈ 1.0 cm³ ≈ **1.24 g** of PLA. There is no reason to tune it: black→white is the worst direction (a trace of black pigment tints white grey immediately, while the reverse is invisible), community-recommended range is 500–800 mm³, and users chasing black-into-white bleed routinely max the field at 999. Spend the gram. |
| Flushing volume white → black | G | 150 mm³ | Never occurs on this plate (white is last), but keep it sane. |
| Flushing multiplier | G | **1.0** | Do not reduce. |
| Filament change volume / prime volume (per filament, BS 2.0+) | G | **60 mm³ for the white** | Same argument — once. |
| Flush into objects' infill | G | inert here — leave **OFF** | §5 sets this ON for `frame.3mf` on the reasoning that black infill hides purge. That reasoning does not apply: the change happens *above* all black geometry, so there is no black infill left to absorb it. Enabling it can only put purge somewhere you don't want. |
| **Flush into this object** | **P** | **OFF, explicitly** | Non-negotiable. Purge inside a white part 0.7 mm wide would be the whole part. |
| Flow Dynamics Calibration (print dialog) | G | **ON** | Per-filament pressure advance. See *Speed & cooling*. |

**How many layers are contaminated (Q5), quantified.**

Two independent mechanisms, and they have very different answers:

- **Contamination.** With the prime tower ON and 999 mm³ of flush, **N ≈ 0** — the dirty
  filament is spent on the tower before the head returns to the model, and there is only
  one change to get wrong. Without a prime tower (or at a stock ~300 mm³ flush) expect
  **N ≈ 2–4 layers**, i.e. one third to more than half of a 7-layer caption printed in
  grey. That is the whole risk, and 999 mm³ + tower retires it for 1.24 g.
- **Opacity / show-through.** This is the mechanism that 0.84 mm does *not* solve. White
  PLA over black needs thickness before it stops reading warm-grey: §3's own finding is
  **0.6 mm minimum, 1.0 mm where it reliably stops showing the substrate**, and Bambu's
  0.2 mm profiles push colour ~3 layers deep for the same reason. **0.84 mm is inside the
  marginal band** — it will read white in diffuse light and slightly grey under a raking
  lamp, which is exactly the lighting a wall-hung poster gets.

**Verdict: 0.84 mm is not enough. The generator should raise the caption to 1.08 mm
(9 layers) minimum, 1.20 mm (10 layers) preferred.** It costs no extra colour change,
about 0.1 g of white, and roughly 3 minutes of print time.

#### Precision (Quality → Precision)

| Setting | Scope | Value | Why |
|---|---|---|---|
| **Precise Z height** | G | **OFF** | Already off per §1, but here the reason is far sharper: it rescales the **last 5 layers** of an object to hit an exact model height. The caption is **7 layers**. It would rescale 5 of them — the entire visible top of every letter — off the layer grid. |
| **Precise wall** | G | **ON** (with a test) | Forces the outer wall to exactly one line width instead of letting the slicer fudge it to close gaps, which is what gives crisp glyph edges and correctly-sized counters. Caveat: Bambu issue #8030 reports Precise wall shifting walls inward and shrinking parts. On a 0.72 mm stroke, a 0.05 mm inward shift per side is a 14 % thinner letter. **Print a 30 × 30 mm tile of the caption first and measure a stem**; if letters come out thin, turn it off rather than compensating elsewhere. |
| **Elephant foot compensation** | G | **0.15 mm** (default) | First-layer only. It touches the black base plate on the bed and cannot reach the caption at z = 10.81. Leave it. Do **not** add a per-part elephant-foot value to the text part hoping to sharpen its base — that setting does not apply there. |
| **XY hole compensation** | P | **0** to start | Positive values grow holes. Counters (B, R, E, A, O) are the small holes here. If the test tile shows counters closing, go to **+0.05 mm** — but prefer fixing it in the generator (below), because slicer compensation also thins the strokes around the counter. |
| **XY contour compensation** | P | **0** to start | Negative values erode contours. **−0.03 mm** only if letters print visibly fat after flow calibration. A blanket negative value on a 0.7 mm stroke removes 8 % of it. |
| Slice resolution (`resolution`) | G | 0.008 mm (default 0.012) | The glyph outlines are 0.1 mm-grid polylines; a slightly finer G-code simplification tolerance keeps the curves curved. Marginal gain, zero cost. |
| **Arc fitting** | G | **OFF** | As §1 and §7. |
| Adaptive / variable layer height | G | **OFF** | As §1. Would knock the 7-layer caption off its own arithmetic. |
| Slow down for curled overhangs | G | OFF | No overhangs on this plate; it only introduces speed changes mid-glyph. |
| Bambu Studio has **no** "Small perimeters" speed | — | — | That is an Orca/PrusaSlicer setting (`small_perimeter_speed`, `small_perimeter_threshold`). In Bambu Studio use the per-part outer-wall speed below instead. If you slice in Orca: small perimeter speed **50 %**, threshold **3 mm**. |

#### Top surface of the letters (Quality / Strength)

| Setting | Scope | Value | Why |
|---|---|---|---|
| **Ironing type** | **P** | **No ironing** | Decisive. A glyph top is 0.6–0.9 mm wide; §5's ironing inset of 0.4 mm leaves 0.1 mm or nothing to iron, and ironing works by dragging a barely-extruding hot nozzle sideways across a surface. On a 0.7 mm-wide white island that means dragging molten white **onto the black ring on both sides of every stroke**. The bow-wave build-up Bambu's own wiki warns about at every ironed region boundary would land, in white, on black, at every letter edge. Off. |
| Ironing type | **F** | **All top surfaces** (as §5) — with a caveat | The ring top is ironed on the layer where it becomes a top surface, which happens *before* any white is laid, so there is no white-drag risk from ironing the frame. But the letter footprints are not top surface (something is above them), so the ironed region has ~20 letter-shaped holes in it and each gets an inset halo. Raise **Ironing inset to 0.5 mm**. Expect a faint matte outline around each letter on an otherwise glossy ring. **Real trade-off:** if that halo bothers you more than the sheen helps, set the frame part to **No ironing** too — monotonic top fill at 0.12 mm on black already looks good, and it removes the last mechanism that can put material where it shouldn't be. |
| Top shell layers | **P** | **3** | Moot in practice — two beads *are* the whole stroke, so there is no top-fill region to build. Set anyway so a wide junction (where two stems meet) does not get treated as sparse. |
| Bottom shell layers | **P** | **1** | The caption sits on solid black. There is nothing to bridge. |
| Top surface pattern | **P** | **Monotonic line** | Free; applies only at wide junctions. |
| **Only one wall on top surfaces** | **P** | **OFF** | §2 turns this ON for the relief. On the caption it is destructive: it drops the top layer of every glyph to a single bead and tries to fill the remaining ~0.35 mm with top infill, which at that width is gap fill — a ragged, blobby last layer on exactly the surface you look at. |
| Only one wall on first layer | G | OFF | |
| Sparse infill density | **P** | 100 % (or irrelevant) | There is no sparse region. Setting 100 % guarantees a wide junction is solid rather than a 3-line grid. |

#### Speed, temperature & cooling

| Setting | Scope | Value | Why |
|---|---|---|---|
| Outer wall speed | **P** | **50 mm/s** | Stock is ~200. On a 5 mm letter the head never reaches 200 anyway — it spends the whole stroke accelerating — so a commanded 200 just means the motion planner is permanently in a transient. 50 mm/s makes the commanded and actual speed agree, which is what makes extrusion consistent around corners. |
| Inner wall speed | **P** | 80 mm/s | |
| Top surface speed | **P** | 40 mm/s | |
| **Outer wall acceleration** | G | **1000 mm/s²** (stock ~5000) | This, not speed, is what rounds small corners and bulges them. Acceleration is plate-scope in Bambu Studio; the frame does not care, so set it globally for this plate. |
| Outer wall jerk | G | 5 mm/s | Same reason. |
| **Flow Dynamics Calibration / pressure advance** | G | **run it, per filament** | Under-tuned PA is *the* cause of bulged corners and a gap on the far side of every corner, and a glyph is nothing but corners. Bambu's per-print flow-dynamics calibration handles this automatically — make sure it is not disabled in the send-to-printer dialog. If you use a filament profile you edited, re-run the calibration for it. |
| Flow ratio (white filament) | G | calibrated; **−2 %** if counters close | Over-extrusion is what fills in the hole in an *e*. This is a filament setting, not a print setting. |
| Nozzle temperature, **white** | filament | **210 °C** (other layers), 220 first layer | Lower end of PLA. Less ooze between the ~20 letter islands, less corner bulge, crisper edges. It is also the lever that reduced black-into-white bleed in the community threads. |
| Nozzle temperature, **black** | filament | 220 °C (stock) | Nothing on the black needs babying. |
| Part cooling fan, white | filament | **100 %**, min fan 100 % | The caption layers are tiny. Each glyph loop must be rigid before the next one lands on it. |
| **Slow down for layers with short print time** | G | **ON, minimum layer time 8 s** | The 7 caption layers are a few seconds of extrusion each. Without a minimum layer time the nozzle returns to a letter that is still soft and smears it. |
| Minimum print speed | G | **20 mm/s** | Floor for the above, so the slowdown never drops to a crawl that over-extrudes. |
| Keep fan always on | filament | ON | |

### 0.2 mm nozzle for the frame plate — no

Estimated cost, this plate: §1's 250 mm frame is 13–16 h; at 170 mm the area scales by
(170/250)² = 0.46, so **~6–7.5 h on the 0.4 mm nozzle**. A 0.2 mm nozzle forces roughly
half the layer height and half the line width, and the frame is an area-dominated part
(169.6 × 179.2 mm of base plate and ring top), so the path length roughly quadruples
while volumetric flow drops: expect **4–6×, i.e. 28–45 h.**

Estimated gain: printed corner radius falls from ~0.18 mm to ~0.10 mm, and a 0.7 mm
stroke resolves as 3–4 beads instead of 2. Real, but it is ~0.08 mm on a 5.4 mm cap
height — about 1.5 % of the letter.

**Verdict: keep the 0.4 mm nozzle.** The same sharpness is available for free by fixing
the stroke width in the generator (below): going from a 0.7 mm stroke to a 1.1 mm stroke
buys more legibility than going from 2 beads to 4 beads on a 0.7 mm stroke, and costs
zero print time. Spending 30 extra hours to render a stroke that is *below the accepted
minimum for embossed text anyway* is optimising the wrong end.

**One exception:** on an **H2D**, which runs two nozzles of different diameters, assign
the 0.2 mm nozzle to the white text and keep 0.4 mm on the black frame. That is the only
configuration where the fine nozzle costs only the caption's print time (minutes) instead
of the whole plate's. On a single-nozzle X1C/P1S/A1 it is not an option, since the AMS
feeds one hotend.

### Settings that specifically RUIN small embossed text — must be off

| Setting | What it does to a 0.7 mm × 5 mm glyph |
|---|---|
| **Classic wall generator** | Forces fixed-width loops; the 0.1–0.3 mm remainder becomes gap fill down the centre of every stem and closes the counters. |
| **Precise Z height** | Rescales the last 5 layers — 5 of the caption's 7. |
| **Scarf joint seam / smart scarf / seam slope** | Taper length exceeds the perimeter length; you get an under-extruded loop instead of a hidden seam. |
| **Ironing on the "text" part** | Drags molten white sideways off a 0.7 mm island onto the black ring. |
| **"Only one wall on top surfaces" on the "text" part** | Replaces the top layer of every stroke with gap fill. |
| **"Flush into this object" on the "text" part** | Fills a white letter with black-tinted purge. |
| **Prime tower OFF** | 2–4 of 7 caption layers print in transition grey. |
| **Fuzzy skin** | Obviously. Check it in inherited profiles. |
| **Arc fitting** | Refits 0.1 mm-grid glyph curves as arcs; visible faceting on bowls. |
| **Slice gap closing radius at the 0.049 default** | Welds narrow counters shut. |
| **Adaptive / variable layer height** | Moves the caption off its 7-layer arithmetic and blocks the prime tower. |
| **Negative XY contour compensation "for sharpness"** | −0.05 mm removes 14 % of a 0.72 mm stroke. Sharpness comes from line width and acceleration, not from shrinking the model. |
| **Seam position: Random** | 7 scattered pockmarks per letter instead of one tucked corner. |
| **Retraction disabled / "only retract when crossing perimeters"** | White strings between ~20 letter islands, across black. |
| **Flow ratio > 1.0 / uncalibrated over-extrusion** | Fills in counters and rounds every corner. Calibrate before blaming the slicer. |
| **Spiral vase, timelapse Smooth mode** | As §7. |

### Generator-side implications

Numbers are for `size_mm=170` at `layer_mm=0.12`, `FIRST_LAYER_MM=0.2`. Items 1–3 are
**implemented**; each carries a note on what shipped where it differs from the
recommendation. 4–6 are recommendations only.

1. **`TEXT_EMBOSS_MM` 0.84 → 1.08 mm (9 layers), prefer 1.20 mm (10 layers).**
   0.84 mm sits inside the marginal band for white-over-black opacity (0.6 mm minimum,
   1.0 mm reliable — §3's own finding, and it is the same physics for a proud letter as
   for a cap). Both candidates are whole layer counts at 0.12 (1.08 = 9, 1.20 = 10), so
   the existing whole-layer invariant is preserved. Cost: ~0.1 g and ~3 min. There is no
   argument for staying at 0.84.
   *Shipped: 1.20 mm.*

2. **The ring top is off the layer grid — fix `resolve()`.** At `size_mm=170` the resolved
   `frame_height_mm` is 9.96 × 0.68 = **6.7728 mm**, which is 56.44 layers, not a whole
   number. Ring top = 4.04 + 6.77 = **10.81 mm**, and `(10.81 − 0.2) / 0.12 = 88.42` — the
   caption's base plane sits **0.05 mm above layer boundary 88** (10.76 mm). Consequences:
   the ring's top layer is 42 % filled in Z, and the slice plane in the 10.76–10.88 band
   catches *both* the black ring top and the white caption bottom, so the black/white
   boundary is decided by a rounding accident rather than by geometry. That is precisely
   the failure §3 spent pages on, reproduced at the one colour boundary on this plate.
   **Fix: snap the resolved `frame_height_mm` (and any other scaled Z dimension) with the
   existing `_snap` helper so `base_mm + frame_height_mm` always lands on
   `FIRST_LAYER_MM + n × layer_mm`.** At 170 mm that means a ring top of **10.76 mm**
   (n = 88) and a caption spanning layers 89–97 at 1.08 mm. `base_mm` 4.04 is already on
   grid (n = 32); `frame_height_mm` 9.96 is a whole layer count only at `size_mm=250` and
   loses that property at every other size. Worth a test alongside
   `test_the_text_grid_is_registered_to_the_frame_grid` — the same class of bug, in Z.
   *Shipped: `resolve()` snaps `frame_height_mm`, `proud_mm` and `relief_mm` (through
   the exaggeration, which is what reaches the relief ceiling) with `_layers()`, the
   delta form of `_snap`. Rounded **up**, not to nearest: each of these has a
   printability floor that rounding down can cross — so the 170 mm ring top is
   **10.88 mm** (n = 89), not 10.76, and the caption spans layers 89–99. In-plane
   params are deliberately left alone. Test:
   `test_resolve_snaps_z_heights_to_the_layer_grid`, at 250/200/170/120 mm.*

3. **Minimum glyph stroke width: floor it at 0.80 mm, target 1.10 mm.** Current 0.6–0.9 mm
   is *below* the accepted guideline for embossed text on a 0.4 mm nozzle, which is
   **nozzle Ø × 2.5 = 1.0 mm minimum, 1.5 mm recommended**. Two levers, use both:
   - **Increase the mask dilation from 1 fine pixel to 2** (the text grid is `TEXT_SUB=4`,
     so a fine pixel is 0.1 mm). That adds 0.1 mm per side = **+0.2 mm on every stroke**:
     0.6 → 0.8 mm, 0.9 → 1.1 mm. Exactly the target band, and it is a one-parameter change
     to machinery that already exists.
   - **Guard the counters.** Dilation shrinks holes by the same 0.1 mm per side. Add a
     check that the smallest counter after dilation is **≥ 0.80 mm** (2 × 0.40 outer wall);
     if it is not, the point size is too small for the face rather than the dilation being
     too big. A closed counter is a worse failure than a slightly thin stem.

   *Shipped, both levers plus the face: `FONT_PATHS` tries the bold faces first (Arial
   Bold, Helvetica.ttc index 1, DejaVuSans-Bold) before the regular ones, which is
   worth ~40 % of stroke width for free; then `_stroke_mm()` measures each line's
   rendered mask by successive erosion and `_thicken()` dilates it until the stroke
   clears `MIN_STROKE_MM = 1.0`, capped at a quarter of the cap height so a counter
   cannot be welded shut (it says so on stdout when the cap engages).
   **Superseded (round 3):** the face is now Trebuchet MS Bold — Arial Bold's g ear,
   t hook and i-dot sit under 0.2 mm from their stems and any dilation welded them —
   with "→" borrowed per glyph from Arial Bold; `MIN_STROKE_MM` is a 0.84 mm *target*,
   and `_dilation_px` only grows a line while its blob/hole topology is unchanged and
   every counter survives 0.4 mm (`MIN_COUNTER_MM`) more growth. The quarter-cap cap
   is gone. Measured: 1.07 mm on both lines at 216 and 170 mm. Per line, since
   line 2 is the smaller face and needs the most. Measured at 170 mm: line 1
   1.07 → 1.33 mm, line 2 0.80 → 1.33 mm. Note the erosion stops at three quarters of
   the ink gone, not at an empty mask — eroding to empty measures the fattest feature
   on the line, which on this caption is the head of the "→" (1.60 mm) and would have
   left every stem unthickened.*

4. **Floor the cap heights.** Guideline minimum character height for embossed text is
   **4 mm, 6 mm recommended**. At `size_mm=170` the title is 5.4 mm (marginal) and the
   subtitle is **3.5 mm — below the minimum**. Since `text_mm` auto-scales from its 250 mm
   base, add floors on the *resolved* values: **title ≥ 6.0 mm, subtitle ≥ 4.5 mm.** With
   `SUB_RATIO = 0.65` a 6 mm title gives a 3.9 mm subtitle, so either raise `SUB_RATIO`
   to **0.75** or floor the subtitle independently. Both floors grow the caption block,
   which grows the auto chin — that is the correct behaviour, and the existing
   `check_output.py` per-axis footprint rule will catch it if the poster outgrows the plate.

5. **Face selection matters more than any slicer setting.** Sources converge on bold
   grotesques for printed text — **Roboto Bold, Open Sans Bold, Arial Bold, Overpass** —
   and explicitly against serif, script and light weights. A Bold weight at 5.4 mm cap
   height has a ~0.85 mm stem where a Regular has ~0.55 mm; that alone moves the caption
   from "below minimum" to "acceptable" with no geometry change. If a face must stay small,
   **set it in all caps** — simpler shapes, no descenders, no tight counters.

6. **Leave the caption as a butt joint at the ring top; do not sink it in.** Sinking the
   text body one layer into the ring would put black and white on the same layer and add a
   second tool change (+~1.2 g of purge) in exchange for adhesion the flat black top
   surface already provides. Keep the single colour change — it is the reason purge on
   this plate is free. (Once item 2 is fixed and the joint is exactly on a layer boundary,
   there is nothing left for interlocking to solve.)

7. **State the assumptions in the filename, as §8.10 already recommends** — the caption
   height and the ring-top Z are now slicer-visible invariants, so
   `frame_0.12mm_1.08emboss.3mf` (or a one-line README) makes a mis-set profile obvious
   before the plate is started.

### Sources

- [Introduction to wall generator | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/wall-generator) — Classic vs Arachne; minimum wall width clamped to 85 % of nozzle Ø (0.34 mm on a 0.4), automatic widening of too-thin features
- [Wall Generator — OrcaSlicer Wiki](https://www.orcaslicer.com/wiki/print_settings/quality/quality_settings_wall_generator) — `wall_transition_length`, `wall_transition_angle`, `wall_transition_filter_deviation`, `wall_distribution_count`, `min_bead_width`, `min_feature_size`: definitions, units (% of nozzle Ø) and scope
- [quality_settings_wall_generator · OrcaSlicer Wiki (GitHub)](https://github.com/OrcaSlicer/OrcaSlicer/wiki/quality_settings_wall_generator) — same parameters, plus wall maximum resolution/deviation
- [Arachne perimeter generator | Prusa Knowledge Base](https://help.prusa3d.com/article/arachne-perimeter-generator_352769) — "features smaller than minimum feature size won't be printed"; transition filter margin "prevents transitioning back and forth"; wedge-angle semantics
- [Wall Generator Settings — Orca Slicer](https://orcaslicer3d.org/wiki/wall-generator-settings/) and [Wall Generator Settings in Orca Slicer](https://orca-slicer.dev/wiki/wall-generator-settings-in-orca-slicer/) — wall distribution count constrains variation to inner walls; filter margin as hysteresis
- [Bambu Studio — Arachne Wall Generator — Minimum Wall Length Option?](https://forum.bambulab.com/t/bambu-studio-arachne-wall-generator-minimum-wall-length-option/188995) and [Minimum Wall Length — Arachne Generator (BambuStudio #9006)](https://github.com/bambulab/BambuStudio/issues/9006)
- [Small features not printing — minimum wall width adjustment | Bambu forum](https://forum.bambulab.com/t/small-features-not-printing-minimum-wall-width-adjustment/197248) — `min_feature_size` 0 behaves as "disabled"; features under ~0.3 mm are at the technology limit; the 59° transition-angle anecdote
- [Arachne generates LINE_WIDTH up to 57 mm (BambuStudio #9731)](https://github.com/bambulab/BambuStudio/issues/9731) — Bambu Studio Arachne defaults: `min_bead_width` 85 %, `min_feature_size` 25 %, `wall_transition_length` 100 %, `wall_transition_angle` 10°, `wall_transition_filter_deviation` 25 %
- [Line width | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/parameter/line-width) — 0.75–1.5 × nozzle Ø guidance, per-feature line widths
- [Line Width and Nozzle Size: How They Actually Interact — 3DProfileFix](https://www.3dprofilefix.com/guides/line-width-and-nozzle-size-guide.html) — why sub-aperture extrusion wanders rather than gaining precision
- [Precise Wall moves outer wall inward, incorrectly shrinks printed model (BambuStudio #8030)](https://github.com/bambulab/BambuStudio/issues/8030) — the Precise wall caveat
- [Precise wall — OrcaSlicer Wiki](https://github.com/SoftFever/OrcaSlicer/wiki/Precise-wall) — what Precise wall changes about the outer/inner wall gap
- [Scarf Seam Settings for OrcaSlicer, Bambu & Prusa — SpoolHound](https://spoolhound.com/seam-guide) — seam position options; scarf taper length; "if the perimeter is shorter than the taper distance, the ramp cannot develop properly"
- [The Scarf Seam function in Bambu Studio — 3DJake](https://www.3djake.ie/info/guide/get-rid-of-z-seams-how-to-get-smooth-surfaces-with-scarf-seam) — how the scarf flow ramp works
- [Black to White Outer Wall Bleed | Bambu forum](https://forum.bambulab.com/t/black-to-white-outer-wall-bleed-i-dont-think-its-a-purging-issue/96483) — black→white flush maxed at 800–999 mm³, lowering nozzle temp, dragging/ooze as a distinct mechanism from purge
- [How to fix black filament bleeding into white | Bambu forum](https://forum.bambulab.com/t/how-to-fix-black-filament-bleeding-into-white/44081) and [Multi-Color Bleed Through](https://forum.bambulab.com/t/multi-color-bleed-through/3980)
- [Flushing Volumes in Bambu Studio & OrcaSlicer: Complete Guide](https://www.3dprofilefix.com/guides/flushing-volumes-guide.html) — black→white 500–800 mm³, white→black 100–200 mm³, multiplier 1.0, "never flush into infill on a white or clear model"
- [Making better use of Flush-into object in Bambu Studio | Bambu forum](https://forum.bambulab.com/t/making-better-use-of-flush-into-object-in-bambu-studio/29422) — per-object flush target must be at least as tall as the last colour change
- [Reduce Waste during Filament Change | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/reduce-wasting-during-filament-change) — flush vs prime volume, and the 0.2 mm nozzle flushing-speed penalty
- [Text and Engravings: Best Practices for Readable 3D Printed Text — Mandarin3D](https://mandarin3d.com/blog/text-and-engravings-best-practices-for-readable-3d-printed-text) — embossed text: line width ≥ 1.0 mm (1.5 mm recommended), height ≥ 0.5 mm (0.8 mm recommended), character height ≥ 4 mm (6 mm recommended); "nozzle Ø × 2.5 for minimum feature width"; recommended faces (Roboto Bold, Open Sans Bold, Arial Bold, Overpass), avoid serif/script/thin; all-caps at small sizes
- [Printing small letters | UltiMaker community](https://community.ultimaker.com/topic/16535-printing-small-letters/) — practical floor for legible FDM lettering
- [Letters embedded depth when printing signs causing problems | Bambu forum](https://forum.bambulab.com/t/letters-embedded-depth-when-printing-signs-causing-problems/18797) — emboss/embed depth interacting with the layer grid
- [Small Perimeter speed is not applied to specific short perimeters in Arachne (OrcaSlicer #8973)](https://github.com/OrcaSlicer/OrcaSlicer/issues/8973) — `small_perimeter_speed` / `small_perimeter_threshold` semantics, and that they are Orca-side
- [Other layers speed — OrcaSlicer Wiki](https://www.orcaslicer.com/wiki/print_settings/speed/speed_settings_other_layers_speed) — small-perimeter speed as a percentage of outer wall speed
- [Ironing | Bambu Lab Wiki](https://wiki.bambulab.com/en/software/bambu-studio/parameter/ironing) — ironing inset, bow wave at every ironed-region boundary, lateral force
