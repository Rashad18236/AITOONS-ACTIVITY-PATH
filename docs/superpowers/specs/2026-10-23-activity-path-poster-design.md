# Activity Path Poster — design

Date: 2026-10-23 · Status: draft, waiting for the owner's approval

This document lives in the flight repo until the new project exists, then moves there as
its first commit (see "Codebase").

Decisions are marked by who made them. **Owner** means the shop owner chose it during the
design conversation. **Design call** means the designer chose it and the owner should check
it while reading. Everything else is constraint inherited from the Flight Path Poster or is
left to the builder, and says so.

## 1. Intent

A sister product to the Flight Path Poster for runners, cyclists, hikers and triathletes.
The customer sends the recorded file of one activity: a race, a big ride, a mountain hike,
a triathlon. They get the same physical poster the flight product makes: a black frame with
a white caption, a green, blue and grey terrain relief, and a raised wall crossing it along
their route.

On the flight poster the wall's height is the altitude. An athlete is always on the ground,
so here the wall **stands on the terrain and its height above the ground is their heart
rate** (owner). The hard parts of the race stand tall and the easy kilometres stay low. A
climb reads twice: the ground rises, and the effort wall rises with it.

Why this product: the flight tool's pipeline is proven and printing, from the terrain, water
and roads through the frame and caption to ready-to-print OrcaSlicer projects. Endurance
athletes already carry the data on their watches, and the moment they want to keep is
usually a race they trained months for.

### The order, from the customer's side

- **One activity**: a road run or race, a trail run or hike, a ride, or a triathlon (owner:
  all four in the first version).
- **Its file(s), attached to the order** (owner). GPX, TCX or FIT from Strava, Garmin
  Connect, Polar, Suunto, Coros, Wahoo and the like. Apple Watch customers can send either
  a Strava or HealthFit export, or their full Apple Health export (owner: accept both).
- **A caption** of up to two lines, as on the flight poster.
- **A size**: 216, 170 or 120mm, as on the flight poster.
- **A wall colour** for single-sport activities, from the flight poster's list. Triathlon
  legs have fixed colours (owner).

The shop owner runs the files through the local tool and prints the result. Customers never
see or touch the tool.

## 2. Goals

1. Read GPX, TCX, FIT and an Apple Health `export.zip` into legs of points carrying position,
   time and heart rate.
2. Turn heart rate into wall height above the terrain on one fixed scale for everyone.
3. Print a low line where there is no heart rate.
4. Where a leg passes the same road more than once, print one clean wall at the average
   heart rate of the passes.
5. Print a triathlon as one map with three legs in three fixed colours, with legs that
   share a road running in side-by-side lanes.
6. Deliver the same physical product as the flight poster: same sizes, printer, print
   settings, frame and caption, as finished OrcaSlicer projects.

## 3. Non-goals for the first version

- **No Strava login, no customer-facing website.** Files arrive with the order (owner).
- **Heart rate only.** No pace, speed, power or heart-rate-zone walls (owner chose heart rate
  and a fixed bpm scale over zones).
- **No official race-course files.** The poster is the customer's own recorded track (owner).
- **No pool swims or indoor activities.** They have no GPS track to print.
- **No shop copy yet.** Listings, order-form instructions and the product name come after
  real prints exist to photograph (owner).
- **No start/finish or kilometre markers, no stats on the poster.** The caption is the
  customer's own text, as on the flight poster.
- **No trimming of the start or end to hide a home address.** The tool prints what the file
  contains; the customer chose to send it.

## 4. Anti-goals: failures even if it technically works

- A ragged double wall where a course repeats a road, or two passes printed at different
  heights on top of each other.
- A flat city course printed as hills.
- Heart-rate data, an uploaded file or an Apple Health export surviving the request: on
  disk, in a log, or in a cache. Heart rate is sensitive health data under Swiss and EU data
  law. Temporary files during the request are fine if they are gone when it ends.
- Two colours sharing layers on a path plate, which would mean a filament change per layer.
- A lane layout where a strip cannot be pushed into its groove and glued, or any strip
  narrower than 0.84mm, the two-extrusion floor.
- Silently printing the wrong workout out of an Apple Health export that holds hundreds.

## 5. Constraints inherited from the flight tool

Everything in the flight repo's `CLAUDE.md` holds unless this document says otherwise. In
particular:

- PLA on a Bambu Lab A1 with a 0.4 nozzle, 256×256 plate, poster in one piece.
- `SIZES_MM = (216, 170, 120)`, footprints checked against `USABLE_MM` (226), the
  `/generate` size whitelist, and the auto chin.
- The layer grid `0.2 + n*0.24`, `_snap` for absolute z, `_layers` for thicknesses.
- `SLOT_FLOOR_MM` 1.16, caps draped into the slot, the strip seated on the flat slot floor,
  strip width `groove_w_mm - 2*clearance_mm`, 0.84mm at the floor, 0.30mm clearance per side.
- Every output a finished OrcaSlicer 2.3.2 project from `write_3mf`, with the vendored
  profile chain, `COMMON`, `PLATES`, `PART_OVERRIDES` and `different_settings_to_system`.
  The path plate settings (`PLATES["path"]`) are reused for every path file.
- Local only, single user, no auth, no persistence of user data. Tiles and Overpass are
  cached in process only.
- Ponytail full mode: laziest working solution, heightmap ops over 3D booleans, no
  speculative features. Design decisions with Fable, implementation via Opus subagents.

## 6. How it gets made

### 6.1 Codebase

**A separate project that starts as a copy of the flight tool** (owner). The two products
change independently; a fix wanted in both is applied twice.

Design calls:

- The new folder is `Scripts/Activity Path Poster/`, next to the flight tool. The product
  name is chosen later with the shop copy.
- It is a `git clone` of the flight repo at the tip of `feature/colored-relief` (`c07f534`),
  not `main`: main is 39 commits behind and lacks the Orca-ready output, the 0.24 grid and
  the speed standard. The flight repo stays reachable as a remote named `flight`, so a
  shared fix can be cherry-picked instead of retyped. The GitHub `origin` is removed; a new
  remote is the owner's call.
- The first commits delete what is flight-only: FlightRadar24 KML/CSV parsing, the runway
  snap and its OurAirports fetch, the `snap_runways`/`takeoff_rwy`/`landing_rwy` params,
  the altitude-following strip and `FLIGHT_SPAN_M`'s upper clip. Runways stay in the OSM
  query, because they are part of the landscape. `CLAUDE.md` is rewritten for the new
  product; the flight-only sections go.

### 6.2 Input

Formats: `.gpx`, `.tcx`, `.fit`, and an Apple Health `export.zip`. One order can bring
several files, because a triathlon often arrives as three exports.

Every file parses to **legs**. A leg is a sport (swim, bike, run, or other) and its points:
latitude, longitude, time and heart rate, with heart rate `NaN` where the file has none. The
file's own elevation is ignored: the wall stands on the printed DEM terrain, not on GPS or
barometric height.

- **GPX**: standard library XML. Heart rate is the `hr` element of Garmin's
  TrackPointExtension, matched without depending on the namespace prefix, since exporters
  differ. Sport from `<type>` when present.
- **TCX**: standard library XML. `Trackpoint` position and `HeartRateBpm/Value`, sport from
  `Activity Sport`, legs from a multisport session when present.
- **FIT**: one FIT library is added, because FIT is a binary format not worth parsing by
  hand. Design call: Garmin's official Python FIT SDK. `record` messages give position in
  semicircles, `heart_rate` and `timestamp`; `session` messages give the sport and time
  window of each leg. Design call: a `transition` session is appended to the leg that
  follows it, so the printed path stays continuous from swim exit to bike to run.
- **Apple Health `export.zip`** (owner: accepted alongside Strava and HealthFit exports). It
  holds `apple_health_export/export.xml` and `workout-routes/*.gpx`. The route GPX files
  carry no heart rate, so the tool joins them by time with the export's
  `HKQuantityTypeIdentifierHeartRate` records.
  - The operator says which workout: a date, plus a start time when that day has more than
    one workout with a route. When the choice is ambiguous the tool refuses and lists the
    candidates with their start times and types. It never guesses.
  - `export.xml` can run to several GB. It is streamed (iterparse, clearing elements as it
    goes) and read straight from the zip, never extracted or loaded whole. Only the chosen
    workout's route and the heart-rate records inside its time window are kept.
  - A multisport Apple Watch workout splits into legs from the per-activity entries the
    export records for it. **This must be verified against a real export** before it is
    relied on. Until then, an Apple Watch triathlon is ordered as Strava or HealthFit
    files, which the GPX and FIT readers already handle. A Health export always yields
    exactly one workout.
  - Upload size: the route has to accept a multi-GB upload. Starlette spools uploads to a
    temporary file, which is fine as long as nothing survives the request.

Several files: legs are ordered by start time. Sport comes from each file's metadata. A
three-file order without sports is taken as swim, bike, run in time order. Legs of one
sport merge, and an order with one sport or none is single-sport (see 6.6).

### 6.3 Heart rate becomes wall height

Owner decisions:

- **One fixed scale, 100 to 200 bpm, the same for every customer.** A relaxed run prints low,
  a race prints tall, and two posters can be compared.
- **The height is measured above the ground under the wall.** The wall rides over every hill.
- **Missing heart rate prints as the low line**, the same height as 100 bpm or less. An
  open-water swim usually looks like this, because watches rarely record heart rate in water.
  That is expected, not an error.

The mapping, per station along the path:

```
height = proud_mm + clip((hr - 100) / 100, 0, 1) * wall_mm      # hr NaN -> 0
z_top  = _snap(surface_under_station + height)
```

The strip still runs from `SLOT_FLOOR_MM` up to `z_top`. `proud_mm` is the flight strip's
existing clamp, 0.96mm at 250mm, so the low line is exactly what a flight poster's strip
does where the aircraft flew below the terrain.

Design calls:

- **`wall_mm` is a new visual param**, auto-scaled like the others in `_SCALED`: 12.0mm at
  the 250mm base, so 10.4mm at 216, with a 3.0mm floor, rounded up to whole layers by
  `resolve()`. It is a starting value, tuned on the first test print.
- **Heart rate is smoothed over time before mapping**, starting at a 30s rolling window.
  Optical sensors spike and drop out, and a raw signal would print as a saw-tooth top.
  The window is a builder knob.
- A gap inside a leg's heart-rate data prints as the low line for that stretch.

### 6.4 Terrain vertical scale

Design call: with no flight altitude, the terrain span is `max(e1 - e0, 300m)`. The 300m
floor is the old `FLIGHT_SPAN_M` lower clip, and it is what keeps a flat city course flat.
Mountains keep their own range, so an alpine trail run looks exactly as it would on a
flight poster. The heart-rate wall has its own scale in mm and does not touch this one.

### 6.5 The same road twice inside one leg

**Owner: average the passes.** Laps and out-and-back sections print as one clean wall at the
average heart rate of every pass over that stretch. No single lap is shown, by choice.

Required result: one wall of normal width there and one groove that fits it, never two
walls offset by GPS drift. The wall is one strip wide, `groove_w_mm - 2*clearance_mm`, plus
at most the couple of fine-grid pixels of rasterisation pad the plan allows so the strip
never meshes under 0.84mm. Passes
without heart rate do not dilute the average; a stretch where no pass has heart rate is the
low line.

How "the same road" is detected, the tolerance, and how the passes collapse onto one
centreline are left to the builder (see 6.9).

### 6.6 Triathlon

Owner decisions:

- **One map, legs in colours.** All legs share one relief and one frame; each leg is its
  own wall.
- **A fixed set of leg colours.** Design call, taken from the example the owner picked:
  swim white, bike red, run yellow. The water is blue, so the swim is never blue.
- **Legs that share a road run in side-by-side lanes.** Where two legs come within lane
  tolerance of each other, each leg's centreline is offset sideways so it runs in its own
  groove next to the other's. The adjacent grooves merge into one wide groove holding both
  strips. Every strip keeps the standard width and clearance. Three legs on one road make
  three lanes.

- **Where walls of two legs cross, one wall has a gap** (owner). Two separately printed
  strips cannot both fill the groove at a crossing. The **later leg runs straight through**
  (owner): run over bike, bike over swim, every time. The earlier leg's wall stops on
  either side of it, `clearance_mm` clear of the through wall's sides, so each crossing
  splits it into one more piece to glue. The same rule covers a crossing forced by a lane
  change. A leg crossing itself is one body and needs nothing. Whether a fragment too short
  to handle is dropped or kept is the builder's.

Order of operations: repeated passes inside a leg collapse first (6.5), giving one wall per
leg per road. Lanes then separate different legs, and crossings cut the earlier leg last.

Design calls:

- Each leg prints as its **own file, in one colour**: `path_swim.3mf`, `path_bike.3mf`,
  `path_run.3mf`. No filament changes and no prime tower load on the path plates. A
  single-sport activity keeps one `path.3mf`.
- Lane order stays the same along a shared stretch, and the sideways offset is eased in and
  out so the wall never kinks. Which leg takes which side is the builder's.
- **Legs of the same sport merge into one wall**, so there is one wall and one file per
  sport. A duathlon's two runs, a ride split over two files after a watch restart, or a
  hike sent in several files each become one wall, and roads they repeat average as in
  6.5. Two walls of one colour side by side would be the double wall the owner rejected.
- **An order whose legs are all one sport, or carry no sport, is single-sport**: one
  `path.3mf`, wall colour the filament the operator loads, as on the flight tool.
- Sports map by family: swimming and open water to swim; cycling, mountain biking and
  e-bike to bike; running, trail running, walking and hiking to run. A multisport order
  with a leg outside those three is refused with a message naming the sport, never guessed.

### 6.7 Output

`frame.3mf` and `relief.3mf` are unchanged in kind. The path is one file per leg, as above.
Every file is a finished project with the embedded settings, and every footprint fits
`USABLE_MM`. The single-sport wall colour stays what it is on the flight tool: the filament
the operator loads. The 3MF declares the default red.

### 6.8 The local web page

The flight tool's single page, adapted:

- The file input takes several files: `.gpx`, `.tcx`, `.fit`, `.zip`.
- A workout date and optional start time, used only for a Health export.
- The status line reports what was read, per leg: the sport, the share of the track with
  heart rate, and for a Health export which workout was taken. For example
  `swim: no HR, low line · bike: HR 98% · run: HR 100%`. A file with no heart rate at all
  still prints, and the status line says so plainly, so the operator can ask the customer
  for a better file before printing.
- The three.js preview shows each leg's wall in its colour.
- One download link per output file.

### 6.9 Left to the builder

- Detecting repeated passes and shared roads: tolerances, method, and how passes collapse
  onto one centreline.
- Lane assignment and easing.
- **Whether the strip stays a swept mesh or becomes a fine-grid heightmap body.** Suggested:
  the caption's approach, a masked slab on a grid `TEXT_SUB` times finer than the terrain.
  Overlaps, crossings, averaging and lanes then become raster operations, which is what the
  "heightmap ops over 3D booleans" rule asks for. The groove must still be carved from the
  same geometry the strip comes from, as `_groove_mask` and `strip_mesh` share `_offsets`
  today.
- The heart-rate smoothing window.
- Parsing details, within "standard library XML plus one FIT library".
- The page layout.

## 7. Checks

The flight tool's habit carries over: one self-check file, small synthetic fixtures, the
real Orca CLI when installed. It must fail if any of these breaks:

- Each format parses to the right legs, sports and heart rate: a GPX with heart rate, a TCX,
  a multisport FIT with swim, transition, bike, transition and run sessions, and a tiny
  Health export zip with two workouts on one day.
- Heart rate maps to height correctly at 90, 100, 150, 200 and 230 bpm and when missing.
- An out-and-back leg gives one wall at the average heart rate.
- Two legs sharing a road give two lanes, each strip fitting its groove with 0.30mm
  clearance, the strips not overlapping each other.
- Two legs crossing leave the later leg whole and the earlier one split, with
  `clearance_mm` between them, and no two strips overlap anywhere on the poster.
- Every strip is watertight and at least 0.84mm wide.
- Every output file fits `USABLE_MM`, and Orca slices every plate.
- An ambiguous Health export day is refused with the candidate list.
- Nothing from the request is left in the temporary directory afterwards.

## 8. Needed from the owner before the first print

Real files, the way the flight tool was tuned on a real G-CEFM flight: one run with heart
rate exported from Strava as GPX, one ride as FIT, one triathlon as a multisport FIT or
three exports, and one Apple Health `export.zip`. The synthetic fixtures prove the code;
only real files show how the walls look.

## 9. Design calls for the owner to check

1. The folder name `Activity Path Poster`, and cloning from `feature/colored-relief` rather
   than `main`.
2. Triathlon colours swim white, bike red, run yellow.
3. Each triathlon leg printed as its own single-colour path file.
4. Transitions drawn as part of the leg that follows them.
5. `wall_mm` at 12mm for a 250mm poster, so 10.4mm at 216, before the first test print.
6. Heart rate smoothed over 30 seconds.
7. A flat-terrain span floor of 300m, kept from the flight tool.
8. Garmin's official FIT SDK as the one new library.
9. An Apple Watch triathlon ordered as Strava or HealthFit files until a real multisport
   Health export has been checked.
10. Legs of the same sport merged into one wall, and a multisport order with a sport other
    than swim, bike or run refused rather than guessed.
