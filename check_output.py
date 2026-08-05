"""Check generated STLs against the Flight Path Poster spec.

    uv run python check_output.py poster.stl path.stl
    uv run python check_output.py poster.stl path.stl --params '{"size_mm":200}'

--params takes the same JSON override format as the app: Params field names only,
unknown keys dropped. Exit 0 if every rule passes, 1 otherwise.

Deliberately NOT checked: pixel-level groove containment (does the strip fit the
carved groove along its whole length). That is proven at generation time by
test_strip_seats_in_groove_at_every_angle, against the heightmap both meshes are
derived from; re-deriving it from two exported STLs adds no information, only
rasterisation error of its own.
"""
import argparse, json, sys
from dataclasses import fields
import trimesh
from poster import Params

PLATE_MM = 256.0
EMBOSS_MM = 0.8   # compose() text emboss height


def _load(path):
    """Binary STL -> Trimesh, or raise."""
    with open(path, "rb") as f:
        if f.read(5) == b"solid":
            raise ValueError("ASCII STL, expected binary")
    m = trimesh.load(path, file_type="stl")
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise ValueError(f"no mesh loaded ({type(m).__name__})")
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("poster_stl")
    ap.add_argument("path_stl")
    ap.add_argument("--params", default="{}", help="JSON overrides, Params field names")
    a = ap.parse_args(argv)
    allowed = {f.name for f in fields(Params)}
    p = Params(**{k: v for k, v in json.loads(a.params).items() if k in allowed})

    rows = []

    def chk(name, ok, got, want):
        rows.append((bool(ok), name, str(got), str(want)))

    # 1. both files load as meshes
    mesh = {}
    for label, path in (("poster", a.poster_stl), ("strip", a.path_stl)):
        try:
            mesh[label] = _load(path)
            chk(f"{label} loads", True, f"{len(mesh[label].faces)} faces", "binary STL")
        except Exception as e:
            chk(f"{label} loads", False, f"{type(e).__name__}: {e}", "binary STL")

    if len(mesh) == 2:
        # 2. both printable solids
        for label, m in mesh.items():
            chk(f"{label} watertight", m.is_watertight, m.is_watertight, True)
            chk(f"{label} winding consistent", m.is_winding_consistent,
                m.is_winding_consistent, True)
            chk(f"{label} volume > 0", m.volume > 0, f"{m.volume:.1f}mm3", "> 0")

        lo, hi = mesh["poster"].bounds
        slo, shi = mesh["strip"].bounds

        # 3. footprint == size_mm and fits the plate
        # ponytail: flat +-0.5mm absorbs the (N-1)*res_mm grid off-by-one-pixel
        # (249.6mm at defaults). Spuriously FAILs for res_mm > 0.5 — compare against
        # (int(size_mm/res_mm)-1)*res_mm if a coarse-res preset ever ships.
        for i, axis in enumerate("xy"):
            ext = hi[i] - lo[i]
            chk(f"poster {axis} footprint",
                abs(ext - p.size_mm) <= 0.5 and ext <= PLATE_MM,
                f"{ext:.2f}mm", f"{p.size_mm}mm +-0.5, <= {PLATE_MM}mm plate")

        # 4. flat back at z=0 (bounds min is the lowest vertex, so nothing is below it)
        chk("poster flat back", abs(lo[2]) <= 0.01, f"z_min {lo[2]:.4f}mm", "0 +-0.01")

        # 5. peak = base + whichever stands taller, relief or frame ring, plus the
        # text emboss (text sits on the frame, so it rides the max either way)
        zmax = (p.base_mm + max(p.relief_mm * p.exaggeration, p.frame_height_mm)
                + EMBOSS_MM)
        chk("poster max z", hi[2] <= zmax + 0.01, f"{hi[2]:.3f}mm", f"<= {zmax:.3f}mm")

        # 6. strip sits in the relief area: poster footprint inset by the frame
        for i, axis in enumerate("xy"):
            in_lo, in_hi = lo[i] + p.frame_mm, hi[i] - p.frame_mm
            chk(f"strip inside relief {axis}",
                slo[i] >= in_lo - 0.5 and shi[i] <= in_hi + 0.5,
                f"[{slo[i]:.2f}, {shi[i]:.2f}]mm",
                f"in [{in_lo:.2f}, {in_hi:.2f}]mm +-0.5")

        # 7. strip spans groove floor to proud of the highest terrain
        z_lo = p.base_mm - p.groove_d_mm - 0.01
        z_hi = hi[2] + p.proud_mm + 0.01
        chk("strip z range", slo[2] >= z_lo and shi[2] <= z_hi,
            f"[{slo[2]:.3f}, {shi[2]:.3f}]mm", f"in [{z_lo:.3f}, {z_hi:.3f}]mm")

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
