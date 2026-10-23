# Activity Path Poster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A copy of the Flight Path Poster that turns a runner's, cyclist's, hiker's or triathlete's recorded file into the same three-part printed poster, with the raised wall standing on the terrain at a height set by heart rate.

**Architecture:** A new `activity.py` reads GPX, TCX, FIT and Apple Health exports into `Leg`s (position, time, heart rate) and groups them into walls, one per sport. `poster.py` keeps the flight tool's terrain, frame, caption and Orca output, and replaces the altitude strip with a raster pipeline: legs become pixel stations, repeated passes collapse onto one line, other legs move into side-by-side lanes, and each wall is drawn on a grid four times finer than the terrain. Crossings, fragments and the groove are all mask operations on that grid. The groove is carved from the dilated wall masks, so every strip fits its groove by construction.

**Tech Stack:** Python ≥3.11 with uv, numpy, Pillow, trimesh, FastAPI, pytest. Garmin's `garmin-fit-sdk` is the one new dependency. GPX, TCX and Health XML use the standard library.

**Spec:** `docs/superpowers/specs/2026-10-23-activity-path-poster-design.md`, which Task 1 copies into the new repo. Read it before any task.

## Global Constraints

- Project folder: `/Users/rbissegger/Documents/AI Toons/Scripts/Activity Path Poster/`, on branch `main`. Every command runs from there.
- `uv run pytest -q` passes after every task. The Orca CLI test runs whenever `/Applications/OrcaSlicer.app` exists.
- One new dependency only: `garmin-fit-sdk>=21.218`, added in Task 3. Do not add scipy, gpxpy, fitdecode or defusedxml.
- These flight invariants stay unchanged: `SIZES_MM = (216, 170, 120)`, `USABLE_MM = 226`, the layer grid `0.2 + n*0.24` through `_snap`/`_layers`, `SLOT_FLOOR_MM = 1.16`, `clearance_mm = 0.30`, `write_3mf`'s embedded Orca settings, and one filament per path plate.
- Heart-rate scale is `HR_SCALE_BPM = (100.0, 200.0)`. The low line sits at `proud_mm`. `wall_mm` is auto: 12.0 at 250mm, floor 3.0, rounded up to whole layers. HR smoothing window is `HR_WINDOW_S = 30.0`.
- The terrain span floor is `SPAN_FLOOR_M = 300.0`.
- Colours are strip `#CC2222`, swim `#FFFFFF`, bike `#CC2222` and run `#F4EE2A`. Output files are `frame.3mf`, `relief.3mf`, plus either `path.3mf` for a single sport or `path_swim.3mf`, `path_bike.3mf`, `path_run.3mf`.
- Privacy: our code never writes uploaded data to disk and never logs, prints or caches it. Prints never include heart-rate values or coordinates. `/generate` closes every upload before returning.
- Ponytail full mode applies: raster and heightmap operations over 3D booleans, and a `ponytail:` comment on every deliberate ceiling.
- Each task updates the `Claude.md` paragraphs about what it changed. Commit messages use a conventional prefix and end with the session's `Co-Authored-By` trailer.

## Review Focus

1. **A single GPS spike**, one fix kilometres off, must be dropped, not printed as a spike in the wall. Covered by `test_a_gps_spike_is_dropped` in Task 5.
2. **A multisport FIT whose swim leg has no GPS** must still print the bike and run, and the status line must say the swim was not printed. Covered by `test_a_leg_without_gps_is_reported_and_not_printed` in Task 5.
3. **A planned-route GPX without timestamps**, sent instead of the recorded activity, must be refused with a message naming the problem. Covered by `test_parse_gpx_refuses_a_route_without_timestamps` in Task 2.
4. **The same activity sent twice**, say the GPX and the FIT of one run, must print as one wall, not two. Covered by `test_the_same_activity_sent_twice_is_one_wall` in Task 7.
5. **An Apple Health workout that runs past local midnight** must keep its heart rate after midnight. Covered by `test_health_export_keeps_hr_after_local_midnight` in Task 4.

## File Structure

| File | Responsibility |
|---|---|
| `activity.py` (new) | Customer files into `Leg`s: per-format readers, cleaning, sport rules, grouping into walls, the status note. No geometry. |
| `poster.py` | Geometry and outputs. Stations, collapsed passes, lanes, wall masks and tops, the groove, `compose_parts`, `build_poster`, `write_3mf`. Flight-only code removed. |
| `app.py` | `/generate` takes several files plus the workout date and time. `/dimensions` is unchanged. |
| `check_output.py` | Checks the frame, the relief and one or more path files. |
| `static/index.html` | Multi-file upload, Health date and time, preview and downloads per path file. |
| `test_activity.py` (new) | Fixture builders for every format, and the reader tests. |
| `test_poster.py` | Geometry, build, endpoint, checker and Orca tests. Flight-only tests removed. |
| `Claude.md`, `README.md`, `pyproject.toml`, `.gitignore` | Project docs and config. |

---

### Task 1: Create the project from the flight tool, without the runway snap

**Files:**
- Create: the folder `Activity Path Poster/` as a clone
- Move: `docs/superpowers/specs/2026-10-23-activity-path-poster-design.md` and `docs/superpowers/plans/2026-10-23-activity-path-poster.md` from the flight repo into the clone
- Modify: `poster.py`, `app.py`, `static/index.html`, `test_poster.py`, `Claude.md`, `README.md`, `pyproject.toml`, `.gitignore`
- Delete: `docs/store-listings.md`

**Interfaces:**
- Produces: a repo whose tests pass with no runway code. KML/CSV parsing and the altitude strip stay until Task 10 replaces them, so the app keeps working in between.

- [ ] **Step 1: Clone from the feature branch tip and set the remotes**

```bash
cd "/Users/rbissegger/Documents/AI Toons/Scripts"
git clone --branch feature/colored-relief "Flight Path Poster" "Activity Path Poster"
cd "Activity Path Poster"
git checkout -B main && git branch -D feature/colored-relief
git remote rename origin flight
git log --oneline -1    # expect c07f534
```

- [ ] **Step 2: Move the spec and this plan in, and drop the flight shop copy**

```bash
F="/Users/rbissegger/Documents/AI Toons/Scripts/Flight Path Poster/docs/superpowers"
mkdir -p docs/superpowers/specs docs/superpowers/plans
mv "$F/specs/2026-10-23-activity-path-poster-design.md" docs/superpowers/specs/
mv "$F/plans/2026-10-23-activity-path-poster.md" docs/superpowers/plans/
git rm -q docs/store-listings.md
```

- [ ] **Step 3: Remove the runway snap**

In `poster.py`, delete `_metres`, `_runway_table`, `_runways`, `_find_runway`, `_fit_end`, `snap_runways`, the runway-snap constants above them, and the `snap_runways`, `takeoff_rwy` and `landing_rwy` fields of `Params`. Keep `RUNWAY_M` and the `aeroway=runway` part of `fetch_osm_masks`, because runways are landscape.

In `app.py`, delete the snap block and the `"runways"` response key.

In `static/index.html`, delete the snap checkbox, both runway inputs, their `change` listener, their entries in `params`, and the `j.runways` status suffix.

In `test_poster.py`, delete `RUNWAYS_CSV`, `_g_cefm_landing`, every `test_snap_runways_*`, `test_generate_rejects_an_unknown_forced_runway`, and the `_runways` monkeypatch lines in `_fake_fetches` and `test_generate_refuses_a_poster_over_the_plate`.

- [ ] **Step 4: Rename the project**

- `pyproject.toml`: set `name = "activity-path-poster"`.
- `poster.py`: change `UA` to `"ActivityPathPoster/1.0 (local single-user 3D-print tool)"` and the module docstring to `"Activity Path Poster core: activity -> heightmap -> printable meshes."`.
- `README.md`: one line naming the product and the run command.
- `.gitignore`: add `samples/`, because the owner's real files are customer health data and never get committed.
- `Claude.md`: retitle it to "Activity Path Poster" and rewrite the intro paragraph from the spec's section 1. Delete the "Runway snap" section and the runway mentions in Architecture. Point `Spec:` at the new design.

- [ ] **Step 5: Run the suite and the leftovers grep**

Run: `uv sync && uv run pytest -q -k "not orca"`
Expected: all pass. The count is lower than the flight tool's 103 because the snap tests are gone.

Run: `grep -n "runway_table\|snap_runways\|takeoff_rwy\|landing_rwy\|_fit_end" *.py static/index.html`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: start Activity Path Poster from the flight tool, without the runway snap"
```

---

### Task 2: Legs, sport families, HR smoothing, and the GPX and TCX readers

**Files:**
- Create: `activity.py`, `test_activity.py`

**Interfaces:**
- Produces:
  - `@dataclass class Leg: sport: str; lat: np.ndarray; lon: np.ndarray; t: np.ndarray; hr: np.ndarray; source: str = ""`. `t` holds POSIX seconds, `hr` is bpm with NaN where absent, and `source` is the file name or `"Health: Running 2026-05-01 08:00"`.
  - `sport_family(raw: str) -> str` returns `"swim"`, `"bike"`, `"run"`, `"transition"`, `""` for missing or numeric, or else the raw name lower-cased.
  - `smooth_hr(t: np.ndarray, hr: np.ndarray, window_s: float = HR_WINDOW_S) -> np.ndarray`
  - `parse_gpx(data: bytes, name: str = "") -> list[Leg]`
  - `parse_tcx(data: bytes, name: str = "") -> list[Leg]`
  - Test helpers in `test_activity.py`, reused by later tasks: `T0`, `H`, `_pts`, `_gpx`, `_tcx` (see Step 1).

- [ ] **Step 1: Write the fixture builders and the failing tests**

Fixture builders, which the implementer writes in `test_activity.py`:
- `T0 = dt.datetime(2026, 7, 5, 6, 0, tzinfo=dt.timezone.utc)` and `H = dt.timedelta(hours=1)`.
- `_pts(n, hr=150, lat=47.0, lon0=8.0, step=1e-4, t0=T0)` returns `[(lat, lon, datetime, hr_or_None)]`, n fixes 1 s apart heading east. `hr` is a number, `None`, or a per-point list.
- `_gpx(tracks, ns="gpxtpx")` builds Strava-style GPX 1.1 bytes from `tracks = [(type_or_None, pts)]`. Heart rate goes in `<extensions><{ns}:TrackPointExtension><{ns}:hr>`, declared with the Garmin TrackPointExtension v1 namespace. A `None` time omits `<time>`.
- `_tcx(activities)` builds TrainingCenterDatabase v2 bytes from `activities = [(Sport, pts)]`. `<Position>` is omitted when the point's lat is `None`. `<HeartRateBpm><Value>` is present when hr is not `None`.

```python
@pytest.mark.parametrize("raw,fam", [
    ("running", "run"), ("Running", "run"), ("trail_running", "run"), ("hiking", "run"),
    ("walking", "run"), ("HKWorkoutActivityTypeRunning", "run"), ("cycling", "bike"),
    ("Biking", "bike"), ("mountain_biking", "bike"), ("e_biking", "bike"), ("Ride", "bike"),
    ("HKWorkoutActivityTypeCycling", "bike"), ("swimming", "swim"), ("transition", "transition"),
    ("", ""), ("9", ""), ("rowing", "rowing")])
def test_sport_family(raw, fam):
    assert activity.sport_family(raw) == fam

def test_smooth_hr_is_a_centred_time_window_mean():
    t = np.arange(120.0)
    s = activity.smooth_hr(t, np.where(t < 60, 100.0, 200.0))
    assert s[30] == 100 and s[90] == 200 and 100 < s[60] < 200

def test_smooth_hr_ignores_missing_samples_and_keeps_long_gaps_missing():
    t = np.arange(120.0)
    s = activity.smooth_hr(t, np.where(t < 60, np.nan, 180.0))
    assert np.isnan(s[10]) and s[50] == 180 and s[100] == 180

def test_parse_gpx_reads_position_time_and_hr():
    (leg,) = activity.parse_gpx(_gpx([("running", _pts(5, hr=[150, None, 152, 153, 154]))]), "run.gpx")
    assert leg.sport == "run" and leg.source == "run.gpx"
    assert leg.lat[0] == 47.0 and abs(leg.lon[4] - 8.0004) < 1e-9
    assert leg.t[0] == T0.timestamp() and leg.t[1] - leg.t[0] == 1.0
    assert leg.hr[0] == 150 and np.isnan(leg.hr[1])

def test_parse_gpx_finds_hr_under_any_namespace_prefix():
    (leg,) = activity.parse_gpx(_gpx([("cycling", _pts(3))], ns="ns3"))
    assert leg.sport == "bike" and list(leg.hr) == [150, 150, 150]

def test_parse_gpx_one_leg_per_track():
    legs = activity.parse_gpx(_gpx([("swimming", _pts(3)), (None, _pts(3, t0=T0 + H))]))
    assert [l.sport for l in legs] == ["swim", ""]

def test_parse_gpx_refuses_a_route_without_timestamps():
    pts = [(47.0, 8.0, None, None), (47.0, 8.001, None, None)]
    with pytest.raises(ValueError, match="no timestamps"):
        activity.parse_gpx(_gpx([("running", pts)]), "course.gpx")

def test_parse_tcx_reads_sport_position_and_hr():
    (leg,) = activity.parse_tcx(_tcx([("Biking", _pts(4, hr=140))]), "ride.tcx")
    assert leg.sport == "bike" and len(leg.lat) == 4 and (leg.hr == 140).all()

def test_parse_tcx_skips_trackpoints_without_position():
    pts = _pts(4)
    pts[1] = (None, None, pts[1][2], 150)
    (leg,) = activity.parse_tcx(_tcx([("Running", pts)]))
    assert len(leg.lat) == 3
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_activity.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'activity'`.

- [ ] **Step 3: Implement in `activity.py`**

- `sport_family`: case-insensitive substring checks, in this order. `"transition"` maps to transition. `"swimbikerun"` maps to `""`, because Task 4 refuses it. `"swim"` maps to swim. `"cycl"`, `"bik"` or `"ride"` map to bike. `"run"`, `"walk"` or `"hik"` map to run. An empty or all-digit string maps to `""`. Anything else returns lower-cased.
- `smooth_hr`: the mean of the finite samples with `|t_j - t_i| <= window_s / 2`, NaN when there are none. Use cumulative sums of the finite values and counts, with `np.searchsorted` for the window bounds, so it runs in O(n).
- Both parsers use `xml.etree.ElementTree` and match on the local tag name, `tag.rsplit('}', 1)[-1]`. Exporters differ in prefixes.
- Times go through `datetime.fromisoformat`. A naive time is UTC, so set `tzinfo` before calling `.timestamp()`.
- `parse_gpx` returns one `Leg` per `<trk>` with its segments concatenated. Sport comes from `trk/type`, and HR from any `trkpt` descendant named `hr`. It raises `ValueError(f"{name}: no track points")` when there are none. When any point lacks `<time>` it raises `ValueError(f"{name}: track points have no timestamps — this looks like a planned route, not a recorded activity")`.
- `parse_tcx` returns one `Leg` per `<Activity>`, with the sport from its `Sport` attribute. Trackpoints without `Position` are skipped.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest test_activity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add activity.py test_activity.py Claude.md
git commit -m "feat: read GPX and TCX activities into legs with smoothed heart rate"
```

---

### Task 3: FIT reader

**Files:**
- Modify: `activity.py`, `test_activity.py`, `pyproject.toml`, `uv.lock`

**Interfaces:**
- Consumes: `Leg` and `sport_family` from Task 2.
- Produces: `parse_fit(data: bytes, name: str = "") -> list[Leg]`, plus the test helper `_fit(sessions, t0=T0) -> bytes`.

- [ ] **Step 1: Add the dependency**

Run: `uv add "garmin-fit-sdk>=21.218"`
Expected: `pyproject.toml` lists it and `uv.lock` updates.

- [ ] **Step 2: Write `_fit` and the failing tests**

`_fit(sessions, t0=T0)` takes `sessions = [(sport, n, hr)]` laid out back to back. Each record is 1 s after the last and heads east 1e-4°. `n=0` gives a session with no positioned records. An `hr` of `None` omits `heart_rate`. Build the file with the SDK's encoder, as verified against 21.218.0:

```python
from garmin_fit_sdk import Encoder, Profile
M = Profile["mesg_num"]
e = Encoder()
e.on_mesg(M["FILE_ID"], {"type": "activity", "manufacturer": "development", "product": 0,
                         "time_created": t0, "serial_number": 1})
e.on_mesg(M["RECORD"], {"timestamp": ts, "position_lat": int(lat / 180 * 2**31),
                        "position_long": int(lon / 180 * 2**31), "heart_rate": 150})
e.on_mesg(M["SESSION"], {"timestamp": end, "start_time": start, "total_elapsed_time": secs,
                         "sport": "running", "message_index": i})
data = e.close()   # bytes
```

```python
def test_parse_fit_splits_a_multisport_file_and_attaches_transitions_to_the_next_leg():
    legs = activity.parse_fit(_fit([("swimming", 5, None), ("transition", 2, 120),
                                    ("cycling", 6, 140), ("transition", 2, 130),
                                    ("running", 4, 160)]), "tri.fit")
    assert [l.sport for l in legs] == ["swim", "bike", "run"]
    assert [len(l.lat) for l in legs] == [5, 8, 6]
    assert np.isnan(legs[0].hr).all() and legs[1].hr[0] == 120 and legs[2].hr[-1] == 160
    assert abs(legs[0].lat[0] - 47.0) < 1e-6 and legs[0].source == "tri.fit"

def test_parse_fit_keeps_a_session_without_gps_as_an_empty_leg():
    legs = activity.parse_fit(_fit([("swimming", 0, None), ("cycling", 3, 140)]))
    assert [l.sport for l in legs] == ["swim", "bike"] and len(legs[0].lat) == 0

def test_parse_fit_refuses_a_non_fit_file():
    with pytest.raises(ValueError, match="not a FIT file"):
        activity.parse_fit(b"hello", "x.fit")
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest test_activity.py -q -k fit`
Expected: FAIL with `AttributeError: module 'activity' has no attribute 'parse_fit'`.

- [ ] **Step 4: Implement `parse_fit`**

- Decode with `Decoder(Stream.from_byte_array(bytearray(data)))`. When `is_fit()` is false, raise `ValueError(f"{name}: not a FIT file")`. Decoder errors raise `ValueError` with the first error.
- Keep the records that have a `timestamp` and both position fields. Convert semicircles to degrees with `v * 180 / 2**31`.
- Sort the sessions by `start_time`. Each record belongs to the last session whose `start_time` is at or before its timestamp.
- A `transition` session's records go to the next non-transition session and are dropped if none follows.
- Return one `Leg` per non-transition session, including sessions with no records, which give empty arrays. With no sessions at all, return one leg with sport `""`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest test_activity.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add activity.py test_activity.py pyproject.toml uv.lock Claude.md
git commit -m "feat: read FIT activities, multisport sessions become legs"
```

---

### Task 4: Apple Health export reader

**Files:**
- Modify: `activity.py`, `test_activity.py`

**Interfaces:**
- Consumes: `Leg`, `sport_family` and `parse_gpx` from Task 2.
- Produces: `parse_health_zip(f: BinaryIO, workout_date: str, workout_time: str = "", name: str = "") -> Leg`, the constant `HR_GAP_S = 15.0`, and the test helper `_health_zip(workouts, hr, pad_cda=4096) -> bytes`.

- [ ] **Step 1: Write `_health_zip` and the failing tests**

`_health_zip(workouts, hr, pad_cda=4096)` takes `workouts = [(type, start "YYYY-MM-DD HH:MM:SS +ZZZZ", n)]`, where `n` is the number of route points 1 s apart, or 0 for a workout without a route. `hr = [(date string, bpm)]` gives the records. The zip lays out the way an iPhone export does:
- `apple_health_export/export.xml`
- `apple_health_export/workout-routes/route_<i>.gpx`, laid out as `_pts(n, hr=None, t0=start)`, with UTC `Z` times and no heart rate
- `apple_health_export/export_cda.xml` of `pad_cda` bytes, stored uncompressed and larger than `export.xml`

`export.xml` looks like this, DOCTYPE included:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [<!ELEMENT HealthData ANY>]>
<HealthData locale="en_CH">
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min"
   creationDate="2026-05-01 08:00:07 +0200" startDate="2026-05-01 08:00:05 +0200"
   endDate="2026-05-01 08:00:05 +0200" value="150"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="1" durationUnit="min"
   sourceName="Watch" startDate="2026-05-01 08:00:00 +0200" endDate="2026-05-01 08:01:00 +0200">
  <WorkoutRoute sourceName="Watch" startDate="2026-05-01 08:00:00 +0200" endDate="2026-05-01 08:01:00 +0200">
   <FileReference path="/workout-routes/route_0.gpx"/>
  </WorkoutRoute>
 </Workout>
</HealthData>
```

```python
RUN_0800 = ("Running", "2026-05-01 08:00:00 +0200", 60)
EVERY_5S = [(f"2026-05-01 08:00:{s:02d} +0200", 150) for s in range(0, 60, 5)]

def test_health_export_takes_the_workout_and_joins_hr_by_time():
    leg = activity.parse_health_zip(io.BytesIO(_health_zip([RUN_0800], EVERY_5S)), "2026-05-01")
    assert leg.sport == "run" and len(leg.lat) == 60 and np.allclose(leg.hr, 150)
    assert leg.source == "Health: Running 2026-05-01 08:00"

def test_health_export_never_guesses_between_two_workouts():
    z = _health_zip([("Running", "2026-05-01 08:00:00 +0200", 30),
                     ("Cycling", "2026-05-01 17:45:00 +0200", 30)], [])
    with pytest.raises(ValueError) as e:
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")
    assert "08:00" in str(e.value) and "17:45" in str(e.value)
    assert activity.parse_health_zip(io.BytesIO(z), "2026-05-01", "17:40").sport == "bike"

def test_health_export_refuses_a_day_without_a_route():
    z = _health_zip([("Running", "2026-05-01 08:00:00 +0200", 0)], [])
    with pytest.raises(ValueError, match="no workout with a route"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")

def test_health_export_leaves_hr_gaps_missing():
    recs = [(f"2026-05-01 08:00:{s:02d} +0200", 150) for s in (0, 5, 10, 55)]
    leg = activity.parse_health_zip(io.BytesIO(_health_zip([RUN_0800], recs)), "2026-05-01")
    assert np.isfinite(leg.hr[:15]).all() and np.isnan(leg.hr[30])

def test_health_export_keeps_hr_after_local_midnight():
    recs = [(f"2026-05-01 23:5{m}:00 +0200", 140) for m in range(10)] + [("2026-05-02 00:05:00 +0200", 140)]
    z = _health_zip([("Walking", "2026-05-01 23:50:00 +0200", 1200)], recs)
    leg = activity.parse_health_zip(io.BytesIO(z), "2026-05-01")
    assert leg.hr[900] == 140          # 00:05:00, the next calendar day

def test_health_export_refuses_an_apple_watch_triathlon():
    z = _health_zip([("SwimBikeRun", "2026-05-01 08:00:00 +0200", 30)], [])
    with pytest.raises(ValueError, match="Strava or HealthFit"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")

def test_health_export_needs_the_workout_date():
    with pytest.raises(ValueError, match="workout date"):
        activity.parse_health_zip(io.BytesIO(_health_zip([], [])), "")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_activity.py -q -k health`
Expected: FAIL with `AttributeError: ... 'parse_health_zip'`.

- [ ] **Step 3: Implement `parse_health_zip`**

1. An empty `workout_date` raises `ValueError("Apple Health export: give the workout date")`.
2. Open `zipfile.ZipFile(f)` in place and never extract. The export XML is the largest member ending in `.xml` whose name does not contain `cda`. Export names vary by locale, which is why it goes by size.
3. Make one `ET.iterparse` pass with `("start", "end")` events and track the depth. At the end of each depth-1 element, handle it and then `root.clear()`, so memory stays flat on a multi-GB export.
   - Keep a heart-rate `Record` when its `startDate[:10]` is within one calendar day of `workout_date`.
   - Keep a `Workout` when its `startDate[:10] == workout_date` and it has a `WorkoutRoute/FileReference`.
4. Pick the workout.
   - None found raises `"no workout with a route on {date}"`.
   - With `workout_time` given, take the candidate whose `startDate[11:16]` is within 30 minutes. If none qualifies, raise and list the candidates.
   - Without a time and more than one candidate, raise with every candidate listed as `"HH:MM Type"`.
   - A type containing `SwimBikeRun` raises `"Apple Watch triathlon: send the Strava or HealthFit files for each leg instead"`.
5. Load the route through `parse_gpx`, matching the zip member whose name ends with the `FileReference` path. Parse dates with `"%Y-%m-%d %H:%M:%S %z"`. Each route point's heart rate is `np.interp` over the records, set to NaN where the nearest record is more than `HR_GAP_S` away.
6. Set `sport = sport_family(type)` and `source = f"Health: {type without 'HKWorkoutActivityType'} {date} {HH:MM}"`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest test_activity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add activity.py test_activity.py Claude.md
git commit -m "feat: read one workout from an Apple Health export, heart rate joined by time"
```

---

### Task 5: Reading an order, sport rules, walls and the status note

**Files:**
- Modify: `activity.py`, `test_activity.py`

**Interfaces:**
- Consumes: the parsers from Tasks 2–4.
- Produces:
  - `read_activity(files: list[tuple[str, BinaryIO]], workout_date: str = "", workout_time: str = "") -> list[Leg]` returns all legs, empty ones included, cleaned and sorted by start time, with sports assigned.
  - `group_walls(legs: list[Leg]) -> list[tuple[str, list[Leg]]]` returns `[("strip", legs)]` for a single sport, or one `(sport, legs)` per sport ordered by first appearance. Legs with fewer than 2 points are left out.
  - `legs_note(legs: list[Leg]) -> str`
  - `MAX_SPEED_MS = 60.0`

- [ ] **Step 1: Write the failing tests**

```python
_file = lambda name, data: (name, io.BytesIO(data))

def test_read_activity_dispatches_by_extension_and_refuses_others():
    legs = activity.read_activity([_file("a.gpx", _gpx([("running", _pts(5))])),
                                   _file("b.tcx", _tcx([("Running", _pts(5, t0=T0 + H))]))])
    assert [l.source for l in legs] == ["a.gpx", "b.tcx"]
    with pytest.raises(ValueError, match="unsupported"):
        activity.read_activity([_file("flight.kml", b"<kml/>")])

def test_three_files_without_sport_are_swim_bike_run_in_time_order():
    fs = [_file(f"{i}.gpx", _gpx([(None, _pts(5, t0=T0 + i * H))])) for i in (2, 0, 1)]
    assert [l.sport for l in activity.read_activity(fs)] == ["swim", "bike", "run"]

def test_a_file_without_sport_next_to_files_with_one_is_refused():
    fs = [_file("a.gpx", _gpx([("running", _pts(5))])), _file("b.gpx", _gpx([(None, _pts(5, t0=T0 + H))]))]
    with pytest.raises(ValueError, match="b.gpx"):
        activity.read_activity(fs)

def test_a_multisport_order_with_an_unknown_sport_is_refused():
    fs = [_file("a.gpx", _gpx([("rowing", _pts(5))])), _file("b.gpx", _gpx([("running", _pts(5, t0=T0 + H))]))]
    with pytest.raises(ValueError, match="rowing"):
        activity.read_activity(fs)

def test_one_sport_in_several_files_is_one_strip_wall():
    fs = [_file(f"{i}.gpx", _gpx([("cycling", _pts(5, t0=T0 + i * H))])) for i in (0, 1)]
    assert [(n, len(ls)) for n, ls in activity.group_walls(activity.read_activity(fs))] == [("strip", 2)]

def test_a_duathlon_groups_by_sport_in_order_of_first_appearance():
    fs = [_file(f"{i}.gpx", _gpx([(s, _pts(5, t0=T0 + i * H))]))
          for i, s in enumerate(("running", "cycling", "running"))]
    assert [(n, len(ls)) for n, ls in activity.group_walls(activity.read_activity(fs))] == [("run", 2), ("bike", 1)]

def test_a_gps_spike_is_dropped():
    pts = _pts(10)
    pts[5] = (47.5, pts[5][1], pts[5][2], 150)          # one fix 55 km north
    (leg,) = activity.read_activity([_file("a.gpx", _gpx([("running", pts)]))])
    assert len(leg.lat) == 9 and leg.lat.max() < 47.01

def test_a_leg_without_gps_is_reported_and_not_printed():
    legs = activity.read_activity([_file("tri.fit", _fit([("swimming", 0, None), ("cycling", 5, 140), ("running", 5, 160)]))])
    assert [n for n, _ in activity.group_walls(legs)] == ["bike", "run"]
    assert "swim: no GPS track, not printed" in activity.legs_note(legs)

def test_files_without_any_gps_are_refused():
    with pytest.raises(ValueError, match="no GPS"):
        activity.read_activity([_file("pool.fit", _fit([("swimming", 0, None)]))])

def test_legs_note_reports_hr_coverage_per_leg():
    legs = activity.read_activity([_file("tri.fit", _fit([("swimming", 5, None), ("cycling", 4, 140), ("running", 4, 160)]))])
    assert activity.legs_note(legs) == "swim: no HR, low line · bike: HR 100% · run: HR 100%"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_activity.py -q`
Expected: the new tests FAIL with `AttributeError: ... 'read_activity'`.

- [ ] **Step 3: Implement**

`read_activity`:
1. Dispatch on the lower-cased extension. `.gpx`, `.tcx` and `.fit` read the bytes. `.zip` passes the file object itself to `parse_health_zip` and is never read whole. Anything else raises `ValueError(f"{name}: unsupported file type, send GPX, TCX, FIT or an Apple Health export.zip")`.
2. Clean each leg:
   - Drop non-finite points, sort by `t`, and drop consecutive duplicate positions.
   - Then the spike rule. Drop interior points whose speed both from the previous point and to the next exceeds `MAX_SPEED_MS`. Then drop an endpoint whose speed to its new neighbour exceeds it. Use an equirectangular distance and `dt = max(dt, 1)`. Mark it `# ponytail: isolated spikes only; two bad fixes in a row survive`.
3. When no leg has 2 or more points, raise `ValueError("no GPS track in these files — indoor or pool activity?")`.
4. Sort legs by first timestamp, with empty legs placed by their file order.
5. Assign sports from the non-empty legs.
   - If every sport is `""` and there are exactly 3 legs, they become swim, bike, run.
   - If every sport is `""` otherwise, they stay `""`, which means single sport.
   - If some sports are `""` and some are not, raise naming each sport-less leg's `source`.
   - If there is more than one distinct sport and one of them is outside swim, bike and run, raise naming that sport.

`group_walls`: one distinct sport among the non-empty legs gives `[("strip", legs)]`. More than one gives `[(sport, legs_of_that_sport)]` ordered by each sport's first leg.

`legs_note`: one part per leg in order, joined with `" · "`. The label is the sport, or `"activity"` when blank.
- A leg with fewer than 2 points reads `"{label}: no GPS track, not printed"`.
- A leg with 0% finite HR reads `"{label}: no HR, low line"`.
- Otherwise it reads `"{label}: HR {round(100 * share)}%"`.
- If any source starts with `"Health:"`, that source and `" · "` go in front.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest test_activity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add activity.py test_activity.py Claude.md
git commit -m "feat: read a whole order into legs, sport rules, walls and the status note"
```

---

### Task 6: Wall height, wall dimensions and leg stations

**Files:**
- Modify: `poster.py`, `test_poster.py`

**Interfaces:**
- Consumes: `activity.Leg` and `activity.smooth_hr`. `poster.py` now does `import activity`, and `activity` never imports `poster`.
- Produces:
  - `Params.wall_mm: float | None = None`, with `_SCALED["wall_mm"] = (12.0, 3.0)`. `resolve()` applies `_layers(p.wall_mm, p)`.
  - `HR_SCALE_BPM = (100.0, 200.0)` and `WALL_SUB = 4`. `WALL_PAD_PX = 2` is the number of fine pixels added to the drawn strip width.
  - `wall_height(hr: np.ndarray, p: Params) -> np.ndarray` gives mm above the ground.
  - `_wall_dims(p: Params) -> tuple[float, float, int, float]` returns `(res_f, W_mm, dil_px, lane_mm)`:
    - `res_f = res_mm / WALL_SUB`
    - `W_mm = groove_w_mm - 2*clearance_mm + WALL_PAD_PX*res_f`, the drawn strip width
    - `dil_px = ceil(clearance_mm / res_f)`
    - `lane_mm = W_mm + (dil_px + 1)*res_f`, centre to centre
  - `legs_bounds(legs: list[Leg], margin_pct: float) -> tuple` wraps `track_bounds` over every point.
  - `leg_stations(leg: Leg, bounds, M: int) -> tuple[np.ndarray, np.ndarray]` returns `(P (k,2)` relief-plate pixels about 1 px apart, `hr (k,)` smoothed bpm with NaN where none`)`.
  - Test helper `_leg(sport, n, hr, t0=0.0, lat0=47.0, lon0=8.0, dlon=1e-4)` builds an `activity.Leg` heading east, 1 s per point. `hr` is a number or a callable of the index.

- [ ] **Step 1: Write the failing tests**

Add `"wall_mm": 12.0` to `_params`, and pin the auto value in `test_resolve_at_250_is_the_legacy_defaults` with `assert p.wall_mm == 12.0`.

```python
def test_wall_mm_auto_scales_in_whole_layers():
    for size, want in ((250, 12.0), (216, 10.56), (120, 5.76)):
        assert poster.resolve(poster.Params(size_mm=size)).wall_mm == want

def test_wall_height_follows_the_fixed_bpm_scale():
    h = poster.wall_height(np.array([90, 100, 150, 200, 230, np.nan]), _params())
    assert np.allclose(h, [0.96, 0.96, 6.96, 12.96, 12.96, 0.96])

def test_wall_dims_keep_neighbouring_lanes_clear_of_the_crossing_cut():
    for res in (0.5, 0.4, 0.25):
        p = _params(res_mm=res)
        res_f, W, dil, lane = poster._wall_dims(p)
        assert W >= p.groove_w_mm - 2 * p.clearance_mm
        assert lane - W > dil * res_f

def test_leg_stations_resample_one_per_pixel_and_carry_smoothed_hr():
    p = _params()
    leg = _leg("run", 300, lambda i: 120.0 if i < 150 else np.nan)
    P, hr = poster.leg_stations(leg, poster.legs_bounds([leg], p.margin_pct), _mpx(p))
    assert len(P) > 8 and abs(np.hypot(*np.diff(P, axis=0).T).mean() - 1.0) < 0.05
    assert np.allclose(hr[: len(hr) // 3], 120) and np.isnan(hr[-1])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_poster.py -q -k "wall or leg_stations or legacy"`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'wall_mm'`.

- [ ] **Step 3: Implement**

- `wall_height` is `proud_mm + clip((hr - 100) / 100, 0, 1) * wall_mm`, with NaN treated as 0.
- `leg_stations`:
  - Project with `_to_px(zip(leg.lat, leg.lon), bounds, M)` and resample with `C, _, d, t = _offsets(px)`.
  - Smooth with `s = activity.smooth_hr(leg.t, leg.hr)` and let `v = np.interp(t, d, isfinite(s))`.
  - Where `v >= 0.5`, `hr = np.interp(t, d, nan_to_num(s)) / v`. Elsewhere it is NaN.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest -q -k "not orca"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py Claude.md
git commit -m "feat: heart rate to wall height on the fixed 100-200 bpm scale, leg stations"
```

---

### Task 7: Collapse repeated passes inside one wall

**Files:**
- Modify: `poster.py`, `test_poster.py`

**Interfaces:**
- Consumes: station pieces shaped like Task 6's `leg_stations` output.
- Produces:
  - `collapse_passes(pieces: list[tuple[np.ndarray, np.ndarray]], r_px: float, ramp: int) -> list[tuple[np.ndarray, np.ndarray]]` takes one wall's pieces in time order and returns the same shapes with positions snapped and heart rate averaged.
  - `_nearest_on_segments(Q: np.ndarray, A: np.ndarray, B: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]` returns `(feet (m,2), dist (m,), segment index (m,))`. A segment with `A == B` is a point.
  - `_ramp(mask: np.ndarray, piece: np.ndarray, k: int) -> np.ndarray`. Inside each piece, `alpha = min(1, d / k)`, where `d` is the index distance to the nearest False station in the same piece, or infinite if there is none. False stations get 0. Piece ends are not False, so a pass that starts or ends on a shared road needs no ramp there.
  - Test helpers: `_line(x0, x1, y, hr)` and `_vline(x, y0, y1, hr)` give pieces stepping 1 px. `_arc(cx, cy, R, hr)` gives one circle lap 1 px apart, starting at angle 0. `_cat(*pieces)` concatenates pieces.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_out_and_back_collapses_onto_one_line_at_the_average_hr():
    (P, hr), = poster.collapse_passes([_cat(_line(10, 90, 50.0, 120), _line(90, 10, 50.6, 160))], r_px=4, ramp=4)
    back, xb = P[81:], P[81:, 0]
    assert np.all(back[(xb >= 12) & (xb <= 75), 1] == 50.0)
    xo = P[:81, 0]
    assert np.allclose(hr[:81][(xo >= 16) & (xo <= 74)], 140)

def test_passes_without_hr_do_not_dilute_the_average():
    (P, hr), = poster.collapse_passes([_cat(_line(10, 90, 50.0, 120), _line(90, 10, 50.6, np.nan))], r_px=4, ramp=4)
    xo = P[:81, 0]
    assert np.allclose(hr[:81][(xo >= 16) & (xo <= 74)], 120)

def test_a_stretch_without_hr_on_any_pass_stays_missing():
    (_, hr), = poster.collapse_passes([_line(10, 90, 50.0, np.nan)], r_px=4, ramp=4)
    assert np.isnan(hr).all()

def test_roads_further_apart_than_r_stay_separate():
    piece = _cat(_line(10, 90, 50.0, 120), _line(90, 10, 58.0, 160))
    (P, hr), = poster.collapse_passes([piece], r_px=4, ramp=4)
    assert np.array_equal(P, piece[0]) and np.allclose(hr, piece[1])

def test_the_same_activity_sent_twice_is_one_wall():
    a, b = _line(10, 90, 50.0, 130), _line(10, 90, 50.3, 130)
    (Pa, _), (Pb, hb) = poster.collapse_passes([a, b], r_px=4, ramp=4)
    assert np.array_equal(Pa, a[0]) and np.allclose(Pb, Pa) and np.allclose(hb, 130)

def test_three_laps_collapse_onto_the_first_at_the_mean_hr():
    laps = [_arc(30, 30, 20 + 0.3 * k, hr) for k, hr in enumerate((120, 150, 180))]
    (P, hr), = poster.collapse_passes([_cat(*laps)], r_px=4, ramp=4)
    n = len(laps[0][0])
    assert poster._nearest_on_segments(P[n:], P[:n - 1], P[1:n])[1].max() < 1e-6
    assert np.allclose(hr[12:n - 12], 150, atol=3)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_poster.py -q -k "collapse or passes or laps or twice or apart"`
Expected: FAIL with `AttributeError: ... 'collapse_passes'`.

- [ ] **Step 3: Implement `collapse_passes`, following these rules exactly**

1. Concatenate every piece's stations into `P (n,2)` and `hr (n,)`, with the piece id `g` and the index within the piece `a`.
2. `repeat[i]` is true when some earlier station `j < i` lies within `r_px` (strictly less), and either `g[j] != g[i]` or `a[i] - a[j] > 3 * r_px`. Compare against every earlier station's raw position, repeats included.
3. The canonical polyline is every segment `(j, j+1)` within one piece where neither end is a repeat. A canonical station with no canonical neighbour enters as a point segment.
4. For each repeat, `foot` is `_nearest_on_segments` onto the canonical polyline. With `alpha = _ramp(repeat, g, ramp)`, the new position is `P + alpha[:, None] * (foot - P)`. Non-repeats stay put.
5. The new `hr[i]` is the mean of finite `hr[j]` over every station `j` whose new position lies within `r_px` of `i`'s new position, or NaN when there are none.
6. Split back into pieces.

Compute pairwise distances in row chunks, and mark it `# ponytail: O(n^2) in chunks; grid buckets if a wall ever passes ~20k stations`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest -q -k "not orca"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py Claude.md
git commit -m "feat: repeated passes collapse onto one line at their average heart rate"
```

---

### Task 8: Side-by-side lanes between walls

**Files:**
- Modify: `poster.py`, `test_poster.py`

**Interfaces:**
- Consumes: `_nearest_on_segments`, `_ramp` and the Task 7 helpers.
- Produces: `assign_lanes(walls: list[list[tuple[np.ndarray, np.ndarray]]], lane_px: float, r_px: float, ramp: int) -> list[list[tuple[np.ndarray, np.ndarray]]]`. Walls come earliest first, each already collapsed. Positions are shifted and heart rate is left unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_shared_road_gets_its_own_lane_beside_the_earlier_wall():
    a, b = _line(10, 90, 50.0, 120), _line(10, 90, 50.5, 160)
    [[(Pa, _)], [(Pb, hb)]] = poster.assign_lanes([[a], [b]], lane_px=4, r_px=4, ramp=4)
    assert np.array_equal(Pa, a[0]) and np.allclose(Pb[:, 1], 54.0) and np.allclose(hb, 160)

def test_three_walls_on_one_road_take_three_lanes():
    out = poster.assign_lanes([[_line(10, 90, y, 120)] for y in (50.0, 50.5, 50.2)], lane_px=4, r_px=4, ramp=4)
    assert [w[0][0][:, 1].mean() for w in out] == pytest.approx([50.0, 54.0, 58.0])

def test_the_lane_side_does_not_flip_with_the_direction_of_travel():
    [_, [(Pb, _)]] = poster.assign_lanes([[_line(10, 90, 50.0, 120)], [_line(90, 10, 50.5, 160)]], lane_px=4, r_px=4, ramp=4)
    assert np.allclose(Pb[:, 1], 54.0)

def test_a_wall_leaving_the_shared_road_is_left_alone_off_it():
    b = _cat(_line(10, 50, 50.5, 160), _vline(50, 51, 90, 160))
    [_, [(Pb, _)]] = poster.assign_lanes([[_line(10, 90, 50.0, 120)], [b]], lane_px=4, r_px=4, ramp=4)
    off = b[0][:, 1] >= 59
    assert np.array_equal(Pb[off], b[0][off]) and np.allclose(Pb[:30, 1], 54.0)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_poster.py -q -k lane`
Expected: FAIL with `AttributeError: ... 'assign_lanes'`.

- [ ] **Step 3: Implement `assign_lanes`, following these rules exactly**

1. Each wall's reference is its input polyline. Lanes are always measured against these pre-lane lines.
2. Wall 0 is returned unchanged.
3. For each station of wall `i > 0`, an earlier wall `j < i` is present when the station lies within `r_px` (strictly) of `j`'s reference. The station's `lane` is the number of present earlier walls, and `ref` is the earliest of them.
4. Where `lane > 0`, take `(foot, _, seg)` from `_nearest_on_segments` onto `ref`. Let `u` be that segment's unit direction and `n = (-u_y, u_x)`. The target is `foot + lane * lane_px * n`.
5. The new position is `P + _ramp(lane > 0, piece, ramp)[:, None] * (target - P)`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest -q -k "not orca"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py Claude.md
git commit -m "feat: walls sharing a road take side-by-side lanes"
```

---

### Task 9: Wall masks, crossings, the groove and the wall mesh

**Files:**
- Modify: `poster.py`, `test_poster.py`

**Interfaces:**
- Consumes: `_wall_dims`, `wall_height`, `_snap`, `_dilate`, `_slab_cells`, `_cell_verts` and `_slab_mesh`.
- Produces:
  - `MIN_PIECE_MM = 3.0`
  - `wall_masks(walls, M: int, p) -> list[np.ndarray]` returns fine vertex masks of shape `((M-1)*WALL_SUB+1,)*2`, after crossings and fragments.
  - `groove_from_masks(masks: list[np.ndarray], M: int, p) -> np.ndarray` returns the coarse `(M, M)` vertex groove.
  - `wall_tops(walls, surface: np.ndarray, p) -> list[np.ndarray]` returns fine float tops in mm.
  - `wall_mesh(mask: np.ndarray, top: np.ndarray, p) -> trimesh.Trimesh | None`
  - `_components(mask: np.ndarray) -> list[np.ndarray]` returns the 4-connected components as bool masks.
  - Test helpers: `_flat(p)` is an `(M, M)` surface at `_snap(3.0, p)`. `_ray(M, deg)` is a straight piece through the plate centre at heading `deg`, spaced 1 px. `_figure8(cx, cy, R, hr)` is a self-crossing piece. `_min_width_mm(mask, C, nrm, res)` is the contiguous perpendicular width, refactored out of `_groove_widths`'s `reach`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_wall_mesh_is_watertight_seated_and_on_the_layer_grid():
    p = _params(); s = _flat(p); P = _ray(s.shape[0], 30)
    walls = [[(P, np.full(len(P), 150.0))]]
    (mask,), (top,) = poster.wall_masks(walls, s.shape[0], p), poster.wall_tops(walls, s, p)
    m = poster.wall_mesh(mask, top, p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    assert abs(m.bounds[0][2] - poster.SLOT_FLOOR_MM) < 1e-9
    assert abs(m.bounds[1][2] - poster._snap(s[0, 0] + 6.96, p)) < 1e-9

@pytest.mark.parametrize("res", [0.5, 0.4, 0.25])
def test_a_wall_is_never_narrower_than_the_strip_floor_and_its_groove_holds_its_clearance(res):
    p = _params(res_mm=res, groove_w_mm=1.44)
    M, S = _mpx(p), poster.WALL_SUB
    res_f, _, dil, _ = poster._wall_dims(p)
    for deg in range(0, 91, 15):
        P = _ray(M, deg)
        (mask,) = poster.wall_masks([[(P, np.full(len(P), 150.0))]], M, p)
        C, nrm = poster._offsets(P * S)[:2]
        assert _min_width_mm(poster._cell_verts(poster._slab_cells(mask)), C, nrm, res_f) >= 0.84
        g = poster.groove_from_masks([mask], M, p)
        R, Cc = np.nonzero(poster._slab_cells(poster._dilate(mask, dil)))
        r, c = R // S, Cc // S
        assert (g[r, c] & g[r + 1, c] & g[r, c + 1] & g[r + 1, c + 1]).all()

def test_a_later_wall_runs_through_and_the_earlier_one_is_cut_clear_of_it():
    p = _params(); M, S = _mpx(p), poster.WALL_SUB
    ma, mb = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_vline(30, 5, 55, 150)]], M, p)
    assert len(poster._components(mb)) == 1 and len(poster._components(ma)) == 2
    win = lambda m: np.argwhere(m[25 * S:36 * S, 25 * S:36 * S])
    A, B = win(ma), win(mb)
    gap = np.sqrt(((A[:, None] - B[None]) ** 2).sum(-1)).min() * p.res_mm / S
    assert gap >= p.clearance_mm

def test_walls_in_neighbouring_lanes_are_not_cut():
    p = _params(); M = _mpx(p); lane = poster._wall_dims(p)[3] / p.res_mm
    ma, mb = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_line(5, 55, 30.0 + lane, 150)]], M, p)
    assert len(poster._components(ma)) == len(poster._components(mb)) == 1 and not (ma & mb).any()

def test_a_fragment_too_short_to_handle_is_dropped(capsys):
    p = _params(); M = _mpx(p)
    ma, _ = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_vline(10, 5, 55, 150)]], M, p)
    assert len(poster._components(ma)) == 1 and "dropped" in capsys.readouterr().out

def test_a_wall_crossing_itself_stays_one_piece():
    p = _params(); M = _mpx(p)
    (m,) = poster.wall_masks([[_figure8(31, 31, 20, 150)]], M, p)
    assert len(poster._components(m)) == 1
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_poster.py -q -k "wall_mesh or narrower or cut or fragment or itself"`
Expected: FAIL with `AttributeError: ... 'wall_masks'`.

- [ ] **Step 3: Implement**

Fine coordinates are coarse pixels times `WALL_SUB`. Fine vertex `r*WALL_SUB` is coarse vertex `r`, the same registration the caption grid uses.

`wall_masks`:
1. For each wall, draw every segment of every piece as a quad of width `W_mm / res_f` fine pixels into an `"L"` image, using the per-segment quad construction from `_groove_mask`.
2. Crossings: for every pair `i < j`, apply `mask_i &= ~_dilate(mask_j, dil_px)`. The later wall runs through.
3. Fragments: for each component from `_components`, the length is `pixels * res_f**2 / W_mm`. Drop any component shorter than `MIN_PIECE_MM`, printing `f"path: dropped a {length:.1f}mm wall fragment at a crossing"`. `_components` labels by `ImageDraw.floodfill` on an `"I"` image, as `_sea_mask` does.

`groove_from_masks`: let `D` be the union of `_dilate(mask, dil_px)`. A coarse cell `(r, c)` is needed when any vertex of `D` falls in its fine block `[r*S, (r+1)*S] x [c*S, (c+1)*S]`. The groove is `_cell_verts(needed)`. That makes the floor-level opening contain every strip plus its clearance by construction.

`wall_tops`:
- For each station, `z = _snap(surface[nearest coarse vertex] + wall_height(hr, p), p)`.
- Draw each segment's quad into an `"F"` image with the mean `z` of its two ends, at the same width as the mask.

`wall_mesh`: `_slab_mesh(_slab_cells(mask), top, np.full(top.shape, SLOT_FLOOR_MM), p.res_mm / WALL_SUB)`.

The drawn width `W_mm` runs up to `WALL_PAD_PX` fine pixels over the nominal strip. That is what lets the four-corner cell rule still mesh at least 0.84mm. The spec's "never wider than one strip" rules out a doubled wall, not this pad, and the groove is built from the padded width.

If the width test fails at some angle, raise `WALL_PAD_PX` and re-run Task 6's `_wall_dims` test. Never lower the assertion.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest -q -k "not orca"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add poster.py test_poster.py Claude.md
git commit -m "feat: raster walls on a 4x grid, crossings cut the earlier wall, groove from the walls"
```

---

### Task 10: Activities replace the flight, end to end

**Files:**
- Modify: `poster.py`, `app.py`, `check_output.py`, `test_poster.py`

**Interfaces:**
- Consumes: everything from Tasks 5–9.
- Produces:
  - `SPAN_FLOOR_M = 300.0` replaces `FLIGHT_SPAN_M`.
  - `compose_parts(gmask: np.ndarray, elev, lc, p) -> dict` returns the old keys minus `track_px` and `alt_mm`.
  - `build_poster(legs: list[activity.Leg], p=Params()) -> tuple[list, list, list[tuple[str, list]]]`. The third element is `[(file_stem, bodies)]`, either `[("path", [(mesh, "strip", COLORS["strip"], 1)])]` or one `("path_<sport>", [(mesh, sport, COLORS[sport], 1)])` per wall.
  - `COLORS` gains `swim #FFFFFF`, `bike #CC2222` and `run #F4EE2A`. `SLOTS` gains `path_swim`, `path_bike` and `path_run`, each holding its own sport. `PLATES` gains the same three keys, each set to `PLATES["path"]`. `write_3mf`'s default plate maps body names `swim`, `bike` and `run` to `path_<sport>`.
  - `/generate` takes `files: list[UploadFile]`, `params: str = Form("{}")`, `workout_date: str = Form("")` and `workout_time: str = Form("")`. It returns `{"frame", "relief", "paths": {stem: b64}, "resolved", "legs"}`.
  - `check_output.main([frame, relief, path, *more_paths, "--params", json])`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_flat_city_is_scaled_to_the_300m_span_floor():
    p = _params(); M = _mpx(p); full = p.relief_mm * p.exaggeration
    none, dry = np.zeros((M, M), bool), np.zeros((M, M), np.uint8)
    flat = poster.compose_parts(none, np.tile(np.linspace(0, 30, M), (M, 1)), dry, p)
    assert abs(flat["surface"].max() - poster._snap(p.plate_mm + 30 / 300 * full, p)) < 1e-9
    alps = poster.compose_parts(none, np.tile(np.linspace(0, 3000, M), (M, 1)), dry, p)
    assert abs(alps["surface"].max() - poster._snap(p.plate_mm + full, p)) < 1e-9

def test_build_poster_prints_a_single_sport_as_one_red_path(monkeypatch):
    _fake_fetches(monkeypatch); p = _params()
    _, _, paths = poster.build_poster([_leg("run", 400, 150), _leg("run", 400, 170, t0=3600, lat0=47.001)], p)
    assert [n for n, _ in paths] == ["path"]
    (m, name, colour, slot), = paths[0][1]
    assert (name, colour, slot) == ("strip", poster.COLORS["strip"], 1)
    assert m.is_watertight and abs(m.bounds[0][2] - poster.SLOT_FLOOR_MM) < 1e-9
    assert m.bounds[1][2] <= p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm + p.wall_mm + 1e-6

def test_build_poster_prints_a_triathlon_as_one_file_per_leg(monkeypatch):
    _fake_fetches(monkeypatch)
    legs = [_leg("swim", 200, np.nan), _leg("bike", 400, 140, t0=3600, lat0=47.01),
            _leg("run", 300, 160, t0=7200, lat0=47.02)]
    _, _, paths = poster.build_poster(legs, _params())
    assert [(n, b[0][1], b[0][2]) for n, b in paths] == [
        ("path_swim", "swim", "#FFFFFF"), ("path_bike", "bike", "#CC2222"), ("path_run", "run", "#F4EE2A")]

def test_generate_returns_one_path_per_leg_and_the_legs_note(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    from test_activity import _fit
    _fake_fetches(monkeypatch)
    fit = _fit([("swimming", 60, None), ("cycling", 120, 140), ("running", 90, 160)])
    r = TestClient(appmod.app).post("/generate", files=[("files", ("tri.fit", fit, "application/octet-stream"))],
                                    data={"params": json.dumps({"size_mm": 120.0})})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["paths"]) == ["path_bike", "path_run", "path_swim"]
    assert r.json()["legs"] == "swim: no HR, low line · bike: HR 100% · run: HR 100%"

def test_generate_refuses_an_unsupported_file():
    from fastapi.testclient import TestClient
    import app as appmod
    r = TestClient(appmod.app).post("/generate", files=[("files", ("x.kml", b"<kml/>", "text/xml"))])
    assert r.status_code == 400 and "unsupported" in r.json()["detail"]

def test_generate_leaves_nothing_behind(monkeypatch, tmp_path):
    import tempfile
    from fastapi.testclient import TestClient
    import app as appmod
    from test_activity import _health_zip
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    _fake_fetches(monkeypatch)
    z = _health_zip([("Running", "2026-05-01 08:00:00 +0200", 300)],
                    [(f"2026-05-01 08:0{m}:00 +0200", 150) for m in range(6)], pad_cda=2_000_000)
    r = TestClient(appmod.app).post("/generate", files=[("files", ("export.zip", z, "application/zip"))],
                                    data={"params": json.dumps({"size_mm": 120.0}), "workout_date": "2026-05-01"})
    assert r.status_code == 200, r.text
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest test_poster.py -q -k "span_floor or single_sport or triathlon or generate"`
Expected: FAIL with `TypeError` from the old `compose_parts`/`build_poster` signatures.

- [ ] **Step 3: Rewire `poster.py`**

- `compose_parts(gmask, elev, lc, p)`:
  - `span = max(e1 - e0, SPAN_FLOOR_M)`.
  - The groove is the `gmask` argument.
  - Delete the track projection, `alt_mm`, and `track_px`.
- `build_poster(legs, p)`, in this order:
  1. Resolve `p` and keep the existing guards.
  2. `walls = activity.group_walls(legs)`, raising `ValueError` when empty, and `bounds = legs_bounds(...)`.
  3. Fetch the elevation and the OSM masks, then flatten the sea and smooth, unchanged.
  4. Take `res_f, W, dil, lane_mm = _wall_dims(p)`, `r = lane_mm / res_mm` and `ramp = ceil(2 * r)`. For each wall, collapse its stations with `collapse_passes([leg_stations(l, bounds, M) for l in wall_legs], r, ramp)`. Then run `assign_lanes(collapsed, r, r, ramp)`.
  5. `masks = wall_masks(...)`, then `parts = compose_parts(groove_from_masks(masks, M, p), elev, lc, p)`, then `tops = wall_tops(..., parts["surface"], p)`.
  6. Make one `wall_mesh` per wall and skip a wall whose mesh is `None`. The file stem is `"path"` when the wall's name is `"strip"`, and `f"path_{name}"` otherwise.
- Delete `parse_track`, `_parse_kml`, `_parse_csv`, `strip_mesh`, `_groove_mask` and `FLIGHT_SPAN_M`.

- [ ] **Step 4: Rewire `app.py`**

- `legs = activity.read_activity([(f.filename or "", f.file) for f in files], workout_date, workout_time)`. A `ValueError` becomes a 400.
- The size whitelist is unchanged. A build failure is a 502.
- The response is `paths = {stem: b64(write_3mf(bodies)) for stem, bodies in path_files}` and `legs = activity.legs_note(legs)`.
- Close every upload in a `finally`: `for f in files: await f.close()`.

- [ ] **Step 5: Rewire `check_output.py`**

- `path_3mf` takes `nargs="+"`, and `_load_3mf` accepts a tuple of first-body names, `("strip", "swim", "bike", "run")`.
- Every rule that used `strip` now runs once per path file, labelled with the body's name.
- The ceiling is `plate_mm + relief_mm*exaggeration + proud_mm + wall_mm`.
- Update the docstring usage lines.

- [ ] **Step 6: Port the remaining tests**

Every `compose_parts(track, elev, lc, bounds, p)` call becomes `compose_parts(_band(M), elev, lc, p)`. `_band(M)` is a horizontal groove band on rows `M//2-2 .. M//2+2`. `TRACK3` becomes `LEGS3 = [_leg("run", 300, 150)]`, and `frame_bodies, bodies, strip = build_poster(...)` becomes `..., paths = ...`.

Delete these tests, whose subjects are gone: the `test_parse_*` flight parsers, `test_strip_*`, `test_compose_parts_maps_altitude_*`, `test_flat_land_under_a_circuit_*`, and the old groove-at-every-angle test with its `_groove_widths`. Keep `_min_width_mm`.

`test_orca_slices_every_plate` iterates `frame`, `relief` and each path file of the triathlon build. It asserts `filament_colour` against `COLORS` for that plate's `SLOTS`.

The `test_check_output_*` tests pass every path file.

- [ ] **Step 7: Run everything, the slicer included**

Run: `uv run pytest -q`
Expected: all pass. The Orca test is skipped only if Orca isn't installed.

Run: `grep -n "parse_track\|strip_mesh\|FLIGHT_SPAN_M\|alt_mm\|_groove_mask" *.py`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: activities replace the flight track end to end, one path file per leg"
```

---

### Task 11: The web page and the project notes

**Files:**
- Modify: `static/index.html`, `Claude.md`

**Interfaces:**
- Consumes: Task 10's `/generate` contract.

- [ ] **Step 1: Update the page**

- The file input becomes `<input type="file" id="file" multiple accept=".gpx,.tcx,.fit,.zip">`, labelled "Activity files (GPX, TCX, FIT, or an Apple Health export.zip)".
- Add `<input type="date" id="workout_date">` and `<input type="time" id="workout_time">`, labelled "Apple Health export only: workout date / start time".
- Add a number input `wall_mm` with placeholder `auto`, labelled "Wall height at 200 bpm, mm". It joins the numeric params loop.
- Submit with `fd.append('files', f)` for each file, plus `workout_date` and `workout_time`.
- The JS `COLORS` gains `strip: 0xcc2222, swim: 0xffffff, bike: 0xcc2222, run: 0xf4ee2a`. Place each `j.paths` entry at the relief offset `at`.
- Replace the static `dlPath` link with one link per path file, created in a container.
- The status line shows `j.legs` and names the files to print: frame on AMS slots 1 and 2, relief on 1, 2 and 3, and each path file alone.

- [ ] **Step 2: Finish `Claude.md` for the new product**

- **Architecture:** `activity.py`, then the `poster.py` pipeline order from Task 10's `build_poster`.
- **New section, "The wall is heart rate":**
  - the fixed 100–200 bpm scale and the low line
  - the 30 s smoothing
  - collapsed passes, and their rule that a repeat must be closer than one lane
  - lanes, and their spacing from `_wall_dims`
  - crossings, where the later wall runs through
  - fragments under `MIN_PIECE_MM`
  - the 4× wall grid
  - the groove built from the dilated walls
- **Replace** the "vertical scale is the terrain or the flight" section with the 300m span floor.
- **Remove** any remaining altitude-strip text.

- [ ] **Step 3: Check the page in a browser**

```bash
uv run python -c "import test_activity as t; open('/tmp/run.gpx','wb').write(t._gpx([('running', t._pts(600))]))"
uv run uvicorn app:app --reload
```

Open http://localhost:8000, upload `/tmp/run.gpx` at 120mm and generate. This needs network access for the terrain tiles and Overpass.
Expected:
- the status line reads `run: HR 100%`
- the preview shows one red wall standing on the terrain
- there are three download links: `frame.3mf`, `relief.3mf` and `path.3mf`

- [ ] **Step 4: Commit**

```bash
git add static/index.html Claude.md
git commit -m "feat: page takes several activity files and a Health workout date, one download per path file"
```

---

### Task 12: First run on the owner's real files

**Files:**
- Read only: `samples/`, which is git-ignored

**Interfaces:**
- Consumes: the finished tool.

- [ ] **Step 1: Check the files are there**

Run: `ls samples/`
Expected: a run GPX with heart rate from Strava, a ride FIT, a triathlon as a multisport FIT or three exports, and an Apple Health `export.zip`. **If `samples/` is missing or incomplete, stop here and report that the owner's files are needed.** This step cannot be faked with fixtures.

- [ ] **Step 2: Generate and check each order at 216mm**

Use the page or a short `uv run python` script calling `activity.read_activity`, `poster.build_poster` and `poster.write_3mf`. Write the outputs to `samples/out/<order>/`. Then run:

```bash
uv run python check_output.py samples/out/<order>/frame.3mf samples/out/<order>/relief.3mf samples/out/<order>/path*.3mf --params '{"size_mm": 216}'
```

Expected: every rule passes.

- [ ] **Step 3: Slice each plate with the Orca CLI**

Use the same command `test_orca_slices_every_plate` runs. Expected: exit code 0 for every plate. Note the print time and the filament changes from each gcode header.

- [ ] **Step 4: Check the Health export's multisport structure**

Run: `unzip -p samples/export.zip '*export.xml' | grep -m5 -o '<WorkoutActivity[^>]*>'`
Report whether multisport workouts carry per-leg activities. This is the open item in the spec's section 6.2.

- [ ] **Step 5: Report**

The report covers:
- the legs note per order
- the tallest wall in mm
- any `dropped` fragments
- the print times
- anything that looked wrong in the preview

The owner decides from it whether `wall_mm` or `HR_WINDOW_S` need tuning before the first physical print. Do not commit anything from `samples/`.
