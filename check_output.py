"""Check generated files against the Activity Path Poster spec.

    uv run python check_output.py frame.3mf relief.3mf path.3mf
    uv run python check_output.py frame.3mf relief.3mf path_swim.3mf path_bike.3mf \
        path_run.3mf --params '{"size_mm":170}'

frame.3mf (black frame + white text), relief.3mf (green/blue/grey) and every path file
(path.3mf, the red strip of a single sport, or one path_<sport>.3mf per leg) are
OrcaSlicer project 3MFs. Bodies are measured in their local frame: read_3mf ignores
the build item's bed placement.
--params takes the same JSON override format as the app: Params field names only,
unknown keys dropped. Exit 0 if every rule passes, 1 otherwise.

Deliberately NOT checked: pixel-level groove containment (does each wall fit the
carved groove along its whole length). That is proven at generation time by
test_a_wall_is_never_narrower_than_the_strip_floor_and_its_groove_holds_its_clearance,
against the masks both meshes are derived from; re-deriving it from two exported meshes adds no information, only
rasterisation error of its own. Nor is the assembly fit of plate-in-ring: the two
are exported in their own local frames, and _grid()'s pixel rounding is unit-tested
by test_relief_plate_clears_the_frame_ring.
"""
import argparse, json, sys
from dataclasses import fields
import numpy as np
import trimesh
from poster import (SLOT_FLOOR_MM, TEXT_EMBOSS_MM, USABLE_MM, Params, _grid, _snap,
                    read_3mf, resolve)

TEXT_MM = TEXT_EMBOSS_MM     # build_poster() white text body thickness
WALLS = ("strip", "swim", "bike", "run")   # a path file's one body: single sport, or a leg


def _load_3mf(path, first):
    """3MF -> [(name, Trimesh), ...] in build order, or raise. `first` names the bodies
    allowed to come first."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"PK":
        raise ValueError("not a zip, expected 3MF")
    bodies = [(n, trimesh.Trimesh(V, F, process=False)) for n, V, F in read_3mf(data)]
    if not bodies or bodies[0][0] not in first:
        raise ValueError(f"expected a {'/'.join(first)} body first, got {[b[0] for b in bodies]}")
    return bodies


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frame_3mf")
    ap.add_argument("relief_3mf")
    ap.add_argument("path_3mf", nargs="+", help="every path file of the order")
    ap.add_argument("--params", default="{}", help="JSON overrides, Params field names")
    a = ap.parse_args(argv)
    allowed = {f.name for f in fields(Params)}
    # same resolve() the generator ran: omitted visual params auto-scale with size_mm
    p = resolve(Params(**{k: v for k, v in json.loads(a.params).items() if k in allowed}))

    rows = []

    def chk(name, ok, got, want):
        rows.append((bool(ok), name, str(got), str(want)))

    # 1. every file loads; each path file is one wall, labelled by its body's name
    strips = []
    for path in a.path_3mf:
        try:
            name, m = _load_3mf(path, WALLS)[0]
            strips.append((name, m))
            chk(f"{name} loads", True, f"{len(m.faces)} faces", f"3MF, {'/'.join(WALLS)} first")
        except Exception as e:
            chk(f"{path} loads", False, f"{type(e).__name__}: {e}", "loadable")
    bodies = frame_bodies = []
    for label, path, first in (("frame", a.frame_3mf, ("frame",)),
                               ("relief", a.relief_3mf, ("terrain",))):
        try:
            got = _load_3mf(path, first)
            if label == "frame":
                frame_bodies = got
            else:
                bodies = got
            chk(f"{label} loads", True, ", ".join(n for n, _ in got), f"3MF, {got[0][0]} first")
        except Exception as e:
            chk(f"{label} loads", False, f"{type(e).__name__}: {e}", "loadable")

    if frame_bodies and strips and bodies:
        frame = frame_bodies[0][1]
        text = dict(frame_bodies[1:]).get("text")
        terrain = bodies[0][1]
        caps = bodies[1:]

        # 2. printable solids (every body is its own object in a 3MF)
        solids = [("frame", frame), *strips, ("terrain", terrain)]
        solids += [(f"body {n}", m) for n, m in frame_bodies[1:]]
        solids += [(f"cap {n}", m) for n, m in caps]
        for label, m in solids:
            chk(f"{label} watertight", m.is_watertight, m.is_watertight, True)
            chk(f"{label} winding consistent", m.is_winding_consistent,
                m.is_winding_consistent, True)
            chk(f"{label} volume > 0", m.volume > 0, f"{m.volume:.1f}mm3", "> 0")

        lo, hi = frame.bounds
        rlo, rhi = terrain.bounds

        # 3. frame footprint and plate fit. size_mm is the poster's WIDTH and the
        # square relief area; the chin is extra height hung below it, so y is
        # size_mm + chin_mm and the two axes need their own rule — a poster that
        # fits the plate in x can now overflow it in y, and this is what says so.
        # ponytail: flat +-0.5mm absorbs the (N-1)*res_mm grid off-by-one-pixel
        # (249.6mm at defaults). Spuriously FAILs for res_mm > 0.5 — compare against
        # (int(size_mm/res_mm)-1)*res_mm if a coarse-res preset ever ships.
        for i, (axis, want) in enumerate((("x", p.size_mm),
                                          ("y", p.size_mm + p.chin_mm))):
            ext = hi[i] - lo[i]
            # ...and against USABLE_MM, not the bare 256 plate: a 240mm frame measured
            # 250.4mm in y, passed a 256 rule, and could not be sliced — the mandatory
            # 5mm brim alone put it 4.4mm off the bed. See poster.USABLE_MM.
            chk(f"frame {axis} footprint",
                abs(ext - want) <= 0.5 and ext <= USABLE_MM,
                f"{ext:.2f}mm", f"{want}mm +-0.5, <= {USABLE_MM}mm printable")

        # 4. flat back at z=0 (bounds min is the lowest vertex, so nothing is below it)
        chk("frame flat back", abs(lo[2]) <= 0.01, f"z_min {lo[2]:.4f}mm", "0 +-0.01")

        # 5. ring height: base + frame_height, flat — the text is a separate body now
        ring = p.base_mm + p.frame_height_mm
        chk("frame ring height", abs(hi[2] - ring) <= 0.01,
            f"{hi[2]:.3f}mm", f"{ring:.2f}mm +-0.01")

        # 6. white text body: present iff a caption was asked for, sitting on the ring.
        # EITHER line counts — a text2-only caption is valid and builds a body.
        caption = bool(p.text or p.text2)
        chk("text body present", (text is not None) == caption,
            "yes" if text is not None else "no", "yes" if caption else "no")
        if text is not None:
            tlo, thi = text.bounds
            chk("text body z range",
                abs(tlo[2] - ring) <= 0.01 and abs(thi[2] - ring - TEXT_MM) <= 0.01,
                f"[{tlo[2]:.3f}, {thi[2]:.3f}]mm",
                f"[{ring:.2f}, {ring + TEXT_MM:.2f}]mm +-0.01")
            # 6b. and staying on the ring's bottom bar in xy. The glyphs are TrueType
            # now, ~40% wider than the bitmap they replaced, so a long string that
            # overflows and clips off the poster edge must not pass silently.
            # The mesh flips y, so the bottom bar is the ring's own band plus the chin
            # — measured in grid rows, the way the mesher lays them out, not in nominal
            # mm (frame_mm truncates to fpx, and rows N-fpx..H-1 span one pixel less).
            _, _, fpx, chin_px = _grid(p)
            bar = lo[1] + (fpx + chin_px - 1) * p.res_mm
            chk("text body on the bottom bar",
                tlo[0] >= lo[0] - 0.5 and thi[0] <= hi[0] + 0.5
                and tlo[1] >= lo[1] - 0.5 and thi[1] <= bar + 0.5,
                f"x[{tlo[0]:.1f}, {thi[0]:.1f}] y[{tlo[1]:.1f}, {thi[1]:.1f}]mm",
                f"in x[{lo[0]:.1f}, {hi[0]:.1f}] y[{lo[1]:.1f}, {bar:.1f}]mm +-0.5")

        # 7. relief plate footprint == the ring opening less the fit gap. Taken from
        # _grid(), not re-derived: frame_mm/res_mm truncates (12/0.4 -> 29 px, not 30),
        # so a params-only formula is off by a pixel or two before anything is wrong.
        M = _grid(p)[1]
        want = (M - 1) * p.res_mm
        for i, axis in enumerate("xy"):
            ext = rhi[i] - rlo[i]
            chk(f"relief {axis} footprint", abs(ext - want) <= 0.5,
                f"{ext:.2f}mm", f"{want:.2f}mm +-0.5 (size-2*frame-2*fit, gridded)")
        chk("relief flat back", abs(rlo[2]) <= 0.01, f"z_min {rlo[2]:.4f}mm", "0 +-0.01")

        # 8. colour bodies sit on the terrain: inside its footprint, and vertically
        # bounded by the relief. The water cap is still a conformal slab, so its top
        # is terrain + cap_mm (tight: the terrain is carved down by exactly cap_mm
        # under it). The grey body is a BAND — a solid from a horizontal z_snow plane
        # up to the surface — so it reaches the relief's own ceiling, and the thing
        # to check instead is that its bottom really is that one flat plane.
        relief_hi = p.plate_mm + p.relief_mm * p.exaggeration + 0.01
        for name, m in caps:
            clo, chi = m.bounds
            chk(f"cap {name} inside relief xy",
                all(clo[i] >= rlo[i] - 0.5 and chi[i] <= rhi[i] + 0.5 for i in (0, 1)),
                f"x[{clo[0]:.1f},{chi[0]:.1f}] y[{clo[1]:.1f},{chi[1]:.1f}]",
                f"in x[{rlo[0]:.1f},{rhi[0]:.1f}] y[{rlo[1]:.1f},{rhi[1]:.1f}] +-0.5")
            if name == "snow":
                z = m.vertices[:, 2]
                flat = int((np.abs(z - clo[2]) <= 1e-6).sum())
                chk("snow band flat bottom", flat == len(z) // 2,
                    f"{flat} of {len(z)} verts on z={clo[2]:.3f}mm", f"{len(z) // 2} (half)")
                chk("snow band above the plate, under the relief top",
                    clo[2] >= p.plate_mm - 0.01 and chi[2] <= relief_hi,
                    f"[{clo[2]:.3f}, {chi[2]:.3f}]mm",
                    f"in [{p.plate_mm:.2f}, {relief_hi:.3f}]mm")
            else:
                cap_hi = rhi[2] + p.cap_mm + 0.01
                chk(f"cap {name} z range", clo[2] >= rlo[2] - 0.01 and chi[2] <= cap_hi,
                    f"[{clo[2]:.3f}, {chi[2]:.3f}]mm", f"in [{rlo[2]:.3f}, {cap_hi:.3f}]mm")

        # The walls are all in the relief's own local frame, so 9 and 10 run per wall.
        # The top is the terrain under the wall plus its heart-rate height, so the
        # ceiling is a full-scale peak plus the tallest wall: proud_mm + wall_mm.
        ceiling = p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm + p.wall_mm
        for name, strip in strips:
            slo, shi = strip.bounds
            # 9. the wall stays inside the relief plate it drops into
            for i, axis in enumerate("xy"):
                chk(f"{name} inside relief {axis}",
                    slo[i] >= rlo[i] - 0.5 and shi[i] <= rhi[i] + 0.5,
                    f"[{slo[i]:.2f}, {shi[i]:.2f}]mm",
                    f"in [{rlo[i]:.2f}, {rhi[i]:.2f}]mm +-0.5")
            # 10. it seats on the constant slot floor, stands proud of it, stays under
            chk(f"{name} seats on slot floor", abs(slo[2] - SLOT_FLOOR_MM) <= 0.01,
                f"{slo[2]:.3f}mm", f"{SLOT_FLOOR_MM:.2f}mm +-0.01")
            chk(f"{name} top is proud of the floor", shi[2] > slo[2] + p.proud_mm,
                f"{shi[2]:.3f}mm", f"> {slo[2] + p.proud_mm:.3f}mm")
            chk(f"{name} top under the relief ceiling", shi[2] <= ceiling + 0.01,
                f"{shi[2]:.3f}mm", f"<= {ceiling:.2f}mm (plate + relief*exag + proud + wall)")

        # 11. layer snapping: every relief z lands on a printable layer boundary, so
        # flat ground slices as uniform layers instead of ragged single-layer islands.
        # The grid is first_layer + n*layer_mm (the printer's first layer is thicker),
        # plus z=0, which is the plate itself. 3MF writes %.3f, so a snapped z is exact.
        if p.layer_mm > 0:
            for label, m, tol in ([("terrain", terrain, 1e-6)]
                                  + [(n, c, 1e-6) for n, c in caps]
                                  + [(n, m, 1e-6) for n, m in strips]):
                z = m.vertices[:, 2]
                z = z[np.abs(z) > tol]                    # z=0 is the build plate
                off = float(np.abs(z - _snap(z, p)).max()) if len(z) else 0.0
                chk(f"{label} z on layer boundaries", off <= tol,
                    f"max off {off:.1e}mm", f"0.2 + n*{p.layer_mm}mm +-{tol:g}")

    wn = max(len(r[1]) for r in rows)
    wg = max(len(r[2]) for r in rows)
    print(f"      {'RULE':<{wn}}  {'MEASURED':<{wg}}  EXPECTED")
    for ok, name, got, want in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{wn}}  {got:<{wg}}  {want}")
    bad = sum(not r[0] for r in rows)
    print(f"\n{len(rows) - bad}/{len(rows)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
