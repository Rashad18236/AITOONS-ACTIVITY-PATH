"""Check generated files against the Flight Path Poster spec.

    uv run python check_output.py frame.stl relief.3mf path.stl
    uv run python check_output.py frame.stl relief.3mf path.stl --params '{"size_mm":200}'

frame.stl and path.stl are binary STLs, relief.3mf is the multi-body coloured 3MF.
--params takes the same JSON override format as the app: Params field names only,
unknown keys dropped. Exit 0 if every rule passes, 1 otherwise.

Deliberately NOT checked: pixel-level groove containment (does the strip fit the
carved groove along its whole length). That is proven at generation time by
test_strip_seats_in_groove_at_every_angle, against the heightmap both meshes are
derived from; re-deriving it from two exported meshes adds no information, only
rasterisation error of its own. Nor is the assembly fit of plate-in-ring: the two
are exported in their own local frames, and _grid()'s pixel rounding is unit-tested
by test_relief_plate_clears_the_frame_ring.
"""
import argparse, json, sys
from dataclasses import fields
import trimesh
from poster import SLOT_FLOOR_MM, Params, _grid, read_3mf

PLATE_MM = 256.0
EMBOSS_MM = 0.8   # compose_parts() text emboss height


def _load(path):
    """Binary STL -> Trimesh, or raise."""
    with open(path, "rb") as f:
        if f.read(5) == b"solid":
            raise ValueError("ASCII STL, expected binary")
    m = trimesh.load(path, file_type="stl")
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise ValueError(f"no mesh loaded ({type(m).__name__})")
    return m


def _load_3mf(path):
    """3MF -> [(name, Trimesh), ...] in build order, or raise."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"PK":
        raise ValueError("not a zip, expected 3MF")
    bodies = [(n, trimesh.Trimesh(V, F, process=False)) for n, V, F in read_3mf(data)]
    if not bodies or bodies[0][0] != "terrain":
        raise ValueError(f"expected a 'terrain' body first, got {[b[0] for b in bodies]}")
    return bodies


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frame_stl")
    ap.add_argument("relief_3mf")
    ap.add_argument("path_stl")
    ap.add_argument("--params", default="{}", help="JSON overrides, Params field names")
    a = ap.parse_args(argv)
    allowed = {f.name for f in fields(Params)}
    p = Params(**{k: v for k, v in json.loads(a.params).items() if k in allowed})

    rows = []

    def chk(name, ok, got, want):
        rows.append((bool(ok), name, str(got), str(want)))

    # 1. all three files load
    frame = strip = None
    bodies = []
    for label, path, load in (("frame", a.frame_stl, _load),
                              ("strip", a.path_stl, _load),
                              ("relief", a.relief_3mf, _load_3mf)):
        try:
            got = load(path)
            if label == "relief":
                bodies = got
                chk("relief loads", True, ", ".join(n for n, _ in got), "3MF, terrain first")
            else:
                if label == "frame":
                    frame = got
                else:
                    strip = got
                chk(f"{label} loads", True, f"{len(got.faces)} faces", "binary STL")
        except Exception as e:
            chk(f"{label} loads", False, f"{type(e).__name__}: {e}", "loadable")

    if frame is not None and strip is not None and bodies:
        terrain = bodies[0][1]
        caps = bodies[1:]

        # 2. printable solids (caps included — each is its own object in the 3MF)
        solids = [("frame", frame), ("strip", strip), ("terrain", terrain)]
        solids += [(f"cap {n}", m) for n, m in caps]
        for label, m in solids:
            chk(f"{label} watertight", m.is_watertight, m.is_watertight, True)
            chk(f"{label} winding consistent", m.is_winding_consistent,
                m.is_winding_consistent, True)
            chk(f"{label} volume > 0", m.volume > 0, f"{m.volume:.1f}mm3", "> 0")

        lo, hi = frame.bounds
        rlo, rhi = terrain.bounds
        slo, shi = strip.bounds

        # 3. frame footprint == size_mm and fits the plate
        # ponytail: flat +-0.5mm absorbs the (N-1)*res_mm grid off-by-one-pixel
        # (249.6mm at defaults). Spuriously FAILs for res_mm > 0.5 — compare against
        # (int(size_mm/res_mm)-1)*res_mm if a coarse-res preset ever ships.
        for i, axis in enumerate("xy"):
            ext = hi[i] - lo[i]
            chk(f"frame {axis} footprint",
                abs(ext - p.size_mm) <= 0.5 and ext <= PLATE_MM,
                f"{ext:.2f}mm", f"{p.size_mm}mm +-0.5, <= {PLATE_MM}mm plate")

        # 4. flat back at z=0 (bounds min is the lowest vertex, so nothing is below it)
        chk("frame flat back", abs(lo[2]) <= 0.01, f"z_min {lo[2]:.4f}mm", "0 +-0.01")

        # 5. ring height: base + frame_height, plus the text emboss if text was asked for
        ring = p.base_mm + p.frame_height_mm
        want = f"{ring:.2f}mm +-0.01" + (f" (+{EMBOSS_MM}mm emboss)" if p.text else "")
        # the emboss is not recoverable from the mesh, so an exact EMBOSS_MM overshoot
        # on a no-text run is almost always a forgotten --params text, not a bad print
        if not p.text and abs(hi[2] - ring - EMBOSS_MM) <= 0.01:
            want += "  (hint: if generated with text, pass the same text in --params)"
        chk("frame ring height",
            ring - 0.01 <= hi[2] <= ring + (EMBOSS_MM if p.text else 0) + 0.01,
            f"{hi[2]:.3f}mm", want)

        # 6. relief plate footprint == the ring opening less the fit gap. Taken from
        # _grid(), not re-derived: frame_mm/res_mm truncates (12/0.4 -> 29 px, not 30),
        # so a params-only formula is off by a pixel or two before anything is wrong.
        M = _grid(p)[1]
        want = (M - 1) * p.res_mm
        for i, axis in enumerate("xy"):
            ext = rhi[i] - rlo[i]
            chk(f"relief {axis} footprint", abs(ext - want) <= 0.5,
                f"{ext:.2f}mm", f"{want:.2f}mm +-0.5 (size-2*frame-2*fit, gridded)")
        chk("relief flat back", abs(rlo[2]) <= 0.01, f"z_min {rlo[2]:.4f}mm", "0 +-0.01")

        # 7. caps sit on the terrain: inside its footprint, and no higher than the
        # terrain top plus cap_mm (the terrain is carved down by exactly cap_mm
        # under a cap, so surface = terrain + cap_mm there — that bound is tight)
        cap_hi = rhi[2] + p.cap_mm + 0.01
        for name, m in caps:
            clo, chi = m.bounds
            chk(f"cap {name} inside relief xy",
                all(clo[i] >= rlo[i] - 0.5 and chi[i] <= rhi[i] + 0.5 for i in (0, 1)),
                f"x[{clo[0]:.1f},{chi[0]:.1f}] y[{clo[1]:.1f},{chi[1]:.1f}]",
                f"in x[{rlo[0]:.1f},{rhi[0]:.1f}] y[{rlo[1]:.1f},{rhi[1]:.1f}] +-0.5")
            chk(f"cap {name} z range", clo[2] >= rlo[2] - 0.01 and chi[2] <= cap_hi,
                f"[{clo[2]:.3f}, {chi[2]:.3f}]mm", f"in [{rlo[2]:.3f}, {cap_hi:.3f}]mm")

        # 8. strip stays inside the relief plate it drops into (same local frame)
        for i, axis in enumerate("xy"):
            chk(f"strip inside relief {axis}",
                slo[i] >= rlo[i] - 0.5 and shi[i] <= rhi[i] + 0.5,
                f"[{slo[i]:.2f}, {shi[i]:.2f}]mm",
                f"in [{rlo[i]:.2f}, {rhi[i]:.2f}]mm +-0.5")

        # 9. strip is a level wall seated on the constant slot floor: bottom exactly
        # SLOT_FLOOR_MM, top proud of the highest terrain the track crosses (which is
        # at most the highest point of the whole relief).
        z_hi = max(m.bounds[1][2] for _, m in bodies) + p.proud_mm + 0.01
        chk("strip seats on slot floor", abs(slo[2] - SLOT_FLOOR_MM) <= 0.01,
            f"{slo[2]:.3f}mm", f"{SLOT_FLOOR_MM:.2f}mm +-0.01")
        chk("strip top is proud and level", slo[2] + p.proud_mm < shi[2] <= z_hi,
            f"{shi[2]:.3f}mm", f"in ({slo[2] + p.proud_mm:.3f}, {z_hi:.3f}]mm")

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
