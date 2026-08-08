import io
import json
import os
from dataclasses import asdict

import numpy as np
import pytest
from PIL import Image

import poster

KML = """<?xml version="1.0"?><kml xmlns:gx="http://www.google.com/kml/ext/2.2">
<gx:coord>8.55 47.46 430</gx:coord>
<gx:coord>8.60 47.50 900</gx:coord>
<gx:coord>8.70 47.60 1500</gx:coord></kml>"""

CSV = """Timestamp,UTC,Callsign,Position,Altitude,Speed,Direction
1717000000,2026-05-29T00:00:00Z,HB123,"47.46,8.55",1000,120,90
1717000060,2026-05-29T00:01:00Z,HB123,"47.50,8.60",2000,120,90
"""


def test_parse_kml():
    t = poster.parse_track("flight.kml", KML.encode())
    assert t.shape == (3, 3)
    assert t[0, 0] == 47.46 and t[0, 1] == 8.55 and t[0, 2] == 430


def test_parse_kml_linestring_fallback():
    xml = "<kml><coordinates>8.55,47.46,430 8.60,47.50,900</coordinates></kml>"
    t = poster.parse_track("x.kml", xml.encode())
    assert t.shape == (2, 3) and t[1, 0] == 47.50


def _fr24_ga_kml():
    """FR24 GA export shape: a straight Route line, single-point fixes, and a
    Trail folder of chaining 2-point segments that re-draw the same flight."""
    path = [(8.00 + i / 100, 47.00 + i / 100, 500.0 + 100 * i) for i in range(13)]
    singles = "".join(
        f"<Placemark><Point><coordinates>{lo},{la},0</coordinates></Point></Placemark>"
        for lo, la, _ in path)
    trail = "".join(
        f"<Placemark><LineString><coordinates>{a[0]},{a[1]},{a[2]} "
        f"{b[0]},{b[1]},{b[2]}</coordinates></LineString></Placemark>"
        for a, b in zip(path, path[1:]))
    return (f'<kml><Folder><name>Route</name><Placemark><LineString>'
            f'<coordinates>9.90,47.90,0 7.00,46.00,0</coordinates>'
            f'</LineString></Placemark>{singles}</Folder>'
            f'<Folder><name>Trail</name>{trail}</Folder></kml>'), path


def test_parse_kml_fr24_ga_picks_trail_only():
    xml, path = _fr24_ga_kml()
    t = poster.parse_track("ga.kml", xml.encode())
    assert t.shape == (13, 3)                                  # stitched trail, not doubled
    assert len(t) < 13 + 12 * 2                                # nowhere near concatenation
    assert (t[0, 0], t[0, 1]) == (path[0][1], path[0][0])
    assert (t[-1, 0], t[-1, 1]) == (path[-1][1], path[-1][0])
    assert (t[:, 2] > 0).all()                                 # real altitudes, not the 0-alt fixes
    for lat, lon in ((47.90, 9.90), (46.00, 7.00)):            # no Route endpoints
        assert not ((t[:, 0] == lat) & (t[:, 1] == lon)).any()


def test_parse_dedupes_consecutive_duplicates():
    xml = ("<kml><coordinates>8.55,47.46,430 8.55,47.46,430 "
           "8.60,47.50,900</coordinates></kml>")
    assert poster.parse_track("x.kml", xml.encode()).shape == (2, 3)


def test_parse_csv_fr24():
    t = poster.parse_track("flight.csv", CSV.encode())
    assert t.shape == (2, 3)
    assert t[0, 0] == 47.46
    assert abs(t[0, 2] - 1000 * 0.3048) < 1e-6  # feet -> meters


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        poster.parse_track("x.csv", b"Timestamp,Position\n")


def test_track_bounds_square_with_margin():
    t = np.array([[47.0, 8.0, 0], [47.5, 9.0, 0]])
    x0, y0, x1, y1 = poster.track_bounds(t, 15.0)
    assert abs((x1 - x0) - (y1 - y0)) < 1e-12          # square
    import math
    assert x0 < math.radians(8.0) and x1 > math.radians(9.0)  # margin outside track


def test_decode_terrarium():
    rgb = np.array([[[0, 0, 0], [128, 4, 128]]], dtype=np.uint8)
    e = poster.decode_terrarium(rgb)
    assert e[0, 0] == -32768
    assert abs(e[0, 1] - (128 * 256 + 4 + 128 / 256 - 32768)) < 1e-9


def _params(**kw):
    """Test params: every scaled field pinned to its 250mm base, so these tests
    measure geometry, not the auto-scaling (which resolve() is tested for below)."""
    return poster.Params(**{"size_mm": 40.0, "frame_mm": 4.0, "res_mm": 0.5,
                            "relief_mm": 20.0, "frame_height_mm": 9.96, "text_mm": 8.0,
                            "groove_w_mm": 2.0, "proud_mm": 0.96, **kw})


def test_resolve_at_250_is_the_legacy_defaults():
    """Backwards compat pin: the auto values at the reference size are exactly the
    concrete defaults every earlier print was made with."""
    p = poster.resolve(poster.Params(size_mm=250))
    assert p.frame_mm == 12.0
    assert p.relief_mm == 20.0
    assert p.frame_height_mm == 9.96     # was 10.0: whole 0.12 layers, ring top 14.00
    assert p.text_mm == 8.0
    assert p.groove_w_mm == 2.0
    assert p.proud_mm == 0.96            # was 1.0: 8 layers of 0.12
    assert p.snow_min_mm == 3.0


def test_resolve_scales_and_floors_at_80mm():
    p = poster.resolve(poster.Params(size_mm=80))
    assert p.frame_mm == 4.0            # 3.84 -> floor
    assert p.relief_mm == 6.4           # 20 * 80/250, above its 5.0 floor
    assert p.frame_height_mm == 3.19    # 9.96 * 80/250, above its 3.0 floor
    assert p.text_mm == 3.0             # 2.56 -> floor
    assert p.groove_w_mm == 1.2         # 0.64 -> floor
    assert p.proud_mm == 0.4            # 0.31 -> floor
    assert p.snow_min_mm == 1.5          # 0.96 -> floor
    # absolute params are untouched by size (printer properties, not visual scale)
    assert (p.base_mm, p.plate_mm, p.cap_mm, p.clearance_mm, p.fit_mm, p.res_mm,
            p.snow_line_m, p.layer_mm, p.smooth_px) == (4.04, 2.0, 0.96, 0.30, 0.2, 0.4,
                                                        2000.0, 0.12, 1.0)


def test_resolve_passes_explicit_values_through_and_is_idempotent():
    p = poster.resolve(poster.Params(size_mm=80, frame_mm=25.0, groove_w_mm=3.0))
    assert p.frame_mm == 25.0 and p.groove_w_mm == 3.0
    assert p.relief_mm == 6.4                      # the rest still auto
    assert poster.resolve(p) == p


def test_resolve_rejects_a_slot_too_narrow_to_print():
    """clearance eats groove_w from both sides; what is left must still be a
    printable strip core, or the path snaps off the spool."""
    with pytest.raises(ValueError, match="groove_w_mm"):
        poster.resolve(poster.Params(size_mm=250, groove_w_mm=0.8))
    with pytest.raises(ValueError, match="groove_w_mm"):   # wide gap, same squeeze
        poster.resolve(poster.Params(size_mm=250, groove_w_mm=1.2, clearance_mm=0.5))


def _mpx(p):
    """Relief-grid side M: full grid minus the frame ring and the fit gap, per side."""
    return poster._grid(p)[1]


def test_relief_plate_clears_the_frame_ring():
    """The relief plate must be at least fit_mm smaller than the ring opening per
    side, at every resolution — a gap that rounds down to zero is an interference
    fit and the plate will not drop into the frame."""
    for res in (0.2, 0.25, 0.3, 0.4, 0.5):
        p = _params(res_mm=res)
        N, M, fpx = poster._grid(p)
        opening = N - 2 * fpx                        # ring inner width, px
        gap = (opening - M) / 2 * res                # per side, mm
        assert gap >= p.fit_mm, f"res={res}: gap {gap:.2f}mm < fit_mm {p.fit_mm}"
        assert gap < p.fit_mm + res                  # not sloppily oversized either
    assert _mpx(_params(fit_mm=0.0)) == int(40.0 / 0.5) - 2 * int(4.0 / 0.5)  # opt out


def _synthetic():
    p = _params()
    N = int(p.size_mm / p.res_mm)              # 80
    fpx = int(p.frame_mm / p.res_mm)           # 8
    M = _mpx(p)                                # 62
    elev = np.tile(np.linspace(0, 1000, M), (M, 1))  # E-W gradient
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    bounds = poster.track_bounds(track, p.margin_pct)
    return p, N, fpx, elev, track, bounds


def test_compose_parts_frame_and_relief_levels():
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    assert parts["frame"].shape == (N, N)
    assert parts["green"].shape == (M, M) and parts["surface"].shape == (M, M)
    assert parts["frame"][0, 0] == p.base_mm + p.frame_height_mm   # frame ring is flat
    assert parts["frame"][N // 2, N // 2] == p.base_mm             # backplate under relief
    assert abs(parts["green"][M // 2, 0] - p.plate_mm) < p.relief_mm  # relief starts at plate
    assert parts["green"].max() <= p.plate_mm + p.relief_mm * p.exaggeration + 1e-6


def test_compose_parts_slot_floor_is_constant():
    """The slot is carved to a constant floor, so the level strip seats on a flat
    seat regardless of the terrain it crosses (depth varies, floor does not)."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    tpx = parts["track_px"]
    mid = (tpx[0] + tpx[-1]) / 2      # len(tpx)//2 was the endpoint, not the middle
    x, y = int(round(mid[0])), int(round(mid[1]))
    assert 0 <= x < M and 0 <= y < M                       # track inside the relief plate
    gmask = poster._groove_mask(tpx, (M, M), p)
    assert gmask[y, x]
    assert (parts["green"][gmask] == poster.SLOT_FLOOR_MM).all()
    assert 0 < poster.SLOT_FLOOR_MM < p.plate_mm           # plate stays connected under it
    # the elevation ramp means the slot really does vary in depth along the track
    depth = parts["surface"][gmask] - parts["green"][gmask]
    assert depth.max() - depth.min() > 1.0


def test_compose_parts_shapes_and_caps():
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    p = _params(snow_line_m=400.0)                         # under the ramp's high end
    lc = np.zeros((M, M), np.uint8)
    lc[5:15, 5:15] = 1                                     # water square, away from track
    lc[30:40, 30:40] = 2                                   # snow square
    lc[0, 20:30] = 1                                       # water touching the plate edge
    parts = poster.compose_parts(track, elev, lc, bounds, p)
    assert parts["frame"].shape == (N, N) and parts["green"].shape == (M, M)
    assert parts["frame"][0, 0] == p.base_mm + p.frame_height_mm
    assert parts["green"].min() >= min(poster.SLOT_FLOOR_MM, p.plate_mm - p.cap_mm) - 1e-6
    w, c = parts["water"], parts["snow"]
    assert w[10, 10] and not w[0, 0]                       # inside square, outside it
    assert not w[0, 25]                                    # 1px border excluded
    assert c[35, 35] and not c[10, 10]
    # water is a conformal cap: green is exactly cap_mm below surface inside it
    assert abs(parts["surface"][10, 10] - parts["green"][10, 10] - p.cap_mm) < 1e-9
    # grey is a band: green stops at the flat z_snow plane, however high the ground is
    assert abs(parts["green"][35, 35] - parts["z_snow"]) < 1e-9
    assert parts["surface"][35, 35] - parts["z_snow"] > p.cap_mm      # a body, not a skin
    # groove cells are never cap cells — a cap slab there would fight the strip
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert gmask[30:40, 30:40].any()      # the groove really does cross the snow square
    assert not (w | c)[gmask].any()
    # so outside the slot and the band every cell drops by at most cap_mm
    band = poster._cell_verts(parts["snow_cells"])
    drop = (parts["surface"] - parts["green"])[~gmask & ~band]
    assert drop.max() <= p.cap_mm + 1e-9
    assert not (w & c).any()


# --- layer snapping + DEM smoothing ------------------------------------------

def test_surface_snaps_to_layer_multiples():
    """Every terrain height lands on a layer boundary, so the slicer emits whole
    uniform layers instead of ragged single-layer islands."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    rng = np.random.default_rng(3)
    noisy = poster._smooth(elev + rng.normal(0, 3.0, (M, M)), p.smooth_px)
    s = poster.compose_parts(track, noisy, np.zeros((M, M), np.uint8), bounds, p)["surface"]
    assert np.abs(s - poster._snap(s, p)).max() < 1e-9
    assert len(np.unique(s.round(9))) > 5              # a real hill keeps its levels
    off = poster.compose_parts(track, noisy, np.zeros((M, M), np.uint8), bounds,
                               _params(layer_mm=0.0))["surface"]
    assert np.abs(off - poster._snap(off, p)).max() > 1e-3      # 0 = opt out


def test_sub_layer_noise_collapses_to_a_flat_plane():
    """DEM noise smaller than a layer must not survive as scattered islands, while
    the surrounding relief keeps every level it had."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    e = elev.copy()
    e[5:20, 5:20] = 500.0                              # a flat plateau in the ramp...
    rng = np.random.default_rng(0)
    noisy = e + rng.normal(0, 3.0, (M, M))             # ...under ~0.09mm of wobble
    lc = np.zeros((M, M), np.uint8)
    raw = poster.compose_parts(track, noisy, lc, bounds, _params(layer_mm=0.0))["surface"]
    got = poster.compose_parts(track, poster._smooth(noisy, p.smooth_px), lc, bounds,
                               p)["surface"]
    box = (slice(8, 17), slice(8, 17))                 # well inside the plateau
    assert len(np.unique(raw[box].round(9))) > 50      # every pixel its own level
    assert len(np.unique(got[box].round(9))) <= 2      # one plane (two at a boundary)
    assert len(np.unique(got.round(9))) > 5            # the ramp is not flattened


def test_smooth_is_an_identity_at_zero():
    e = np.arange(25.0).reshape(5, 5)
    assert (poster._smooth(e, 0.0) == e).all()
    assert poster._smooth(e, 2.0).shape == e.shape
    assert abs(poster._smooth(e, 2.0).mean() - e.mean()) < 1.0   # edge-clamped, no drift


def _groove_widths(p):
    """Contiguous perpendicular carved width, in mm, at every station along a 90° arc."""
    M = _mpx(p)
    a = np.linspace(0, np.pi / 2, 40)                    # arc sweeps 90° of heading
    trk = np.stack([47.0 + 0.3 * np.sin(a), 8.0 + 0.3 * (1 - np.cos(a)),
                    np.zeros_like(a)], 1)
    bounds = poster.track_bounds(trk, p.margin_pct)
    elev = np.tile(np.linspace(0, 1000, M), (M, 1))
    parts = poster.compose_parts(trk, elev, np.zeros((M, M), np.uint8), bounds, p)
    groove = (parts["surface"] - parts["green"]) > 0
    C, nrm = poster._offsets(parts["track_px"])[:2]
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm   # strip half-width, px
    step = np.arange(0, 3 * half, 0.25)                      # march out from centreline

    def reach(sign):                                         # contiguous carved px
        q = C[:, None] + sign * nrm[:, None] * step[None, :, None]
        ok = groove[q[..., 1].round().astype(int).clip(0, M - 1),
                    q[..., 0].round().astype(int).clip(0, M - 1)]
        return (np.where(ok.all(1), len(step), ok.argmin(1)) - 1) * 0.25

    return (reach(1.0) + reach(-1.0))[2:-2] * p.res_mm, parts   # skip the square ends


def test_strip_seats_in_groove_at_every_angle():
    """Fit invariant: the carved groove is never narrower than the strip.

    Rasterisation puts each edge within half a pixel of nominal, so absolute
    per-pixel containment is a sub-pixel stricter than the physical fit — the
    strip is slid in, not pinned to the centreline. Contiguous perpendicular
    width per station is the criterion. line(width=) fails this at ~45°.

    Swept over resolutions: at res_mm=0.5 the groove is only 4px wide and the
    seat margin (1.4mm strip in a 2.0mm groove) is thinner than one pixel, so a
    single resolution decides this on rasterisation luck rather than mechanism."""
    for res in (0.5, 0.4, 0.25):
        p = _params(res_mm=res)
        w, parts = _groove_widths(p)
        # ...and it seats on the slot floor exactly, not on the terrain under it
        strip = poster.strip_mesh(parts["track_px"], parts["alt_mm"], parts["surface"], p)
        assert abs(strip.bounds[0][2] - poster.SLOT_FLOOR_MM) < 1e-6
        assert (parts["green"][parts["surface"] > parts["green"]] ==
                poster.SLOT_FLOOR_MM).all()
        assert w.min() >= p.groove_w_mm - 2 * p.clearance_mm, \
            f"res={res}: groove pinches to {w.min():.2f}mm, " \
            f"strip is {p.groove_w_mm - 2 * p.clearance_mm}mm"
        # and it holds its *nominal* width to within one pixel of rasterisation
        # slack — the seat margin above is too thin to catch a mechanism that
        # narrows the groove by 1/sqrt(2) on the diagonal.
        assert w.min() >= p.groove_w_mm - res, \
            f"res={res}: groove pinches to {w.min():.2f}mm, nominal {p.groove_w_mm}mm"


def test_compose_parts_text_is_a_mask_not_an_emboss():
    """Text is printed white as its own body, so the frame heightmap stays flat —
    the glyph pixels come back as a mask instead."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    lc = np.zeros((M, M), np.uint8)
    parts = poster.compose_parts(track, elev, lc, bounds, _params(text="TEST", text_mm=3.0))
    frame, tm = parts["frame"], parts["text_mask"]
    assert frame.max() == p.base_mm + p.frame_height_mm    # ring is flat, nothing embossed
    assert tm.shape == (N, N) and tm.dtype == bool
    assert tm.any() and tm[:N - fpx, :].sum() == 0         # glyphs live on the bottom bar
    assert not poster.compose_parts(track, elev, lc, bounds, _params())["text_mask"].any()


def test_heightmap_mesh_watertight():
    rng = np.random.default_rng(0)
    hm = 4.0 + rng.random((20, 30)) * 5
    m = poster.heightmap_mesh(hm, 0.5)
    assert m.is_watertight
    assert m.is_winding_consistent   # normals all outward, or slicers choke
    assert m.volume > 0
    assert abs(m.bounds[1][0] - 29 * 0.5) < 1e-6   # x extent = (W-1)*res
    assert abs(m.bounds[1][2] - hm.max()) < 1e-6   # top = max height
    assert m.bounds[0][2] == 0                     # flat back at z=0


def test_strip_mesh_geometry():
    p = _params()
    M = _mpx(p)
    surface = np.full((M, M), p.plate_mm + 8.0)            # relief top, plate_mm z-base
    track_px = np.array([[10.0, 40.0], [40.0, 40.0], [55.0, 45.0]])
    m = poster.strip_mesh(track_px, np.zeros(3), surface, p)   # ground-level flight
    assert m.is_watertight
    assert m.is_winding_consistent   # watertight alone passes inside-out meshes
    assert m.volume > 0              # outward normals, not inverted
    zmin, zmax = m.bounds[0][2], m.bounds[1][2]
    assert abs(zmax - poster._snap(surface[0, 0] + p.proud_mm, p)) < 1e-6
    assert abs(zmin - poster.SLOT_FLOOR_MM) < 1e-6
    # width across a straight section = groove - 2*clearance
    xs = m.vertices[np.abs(m.vertices[:, 0] - 25 * p.res_mm) < p.res_mm]
    width = xs[:, 1].max() - xs[:, 1].min()
    assert abs(width - (p.groove_w_mm - 2 * p.clearance_mm)) < 0.2


def _strip_tops(m, track_px):
    """Per-station top z of a strip mesh (vertex block 3 of 4: L_bot R_bot R_top L_top)."""
    n = len(poster._offsets(track_px)[0])
    return m.vertices[2 * n:3 * n, 2]


def _sampled_surface(surface, track_px):
    C = poster._offsets(track_px)[0]
    H, W = surface.shape
    return surface[np.clip(C[:, 1].round().astype(int), 0, H - 1),
                   np.clip(C[:, 0].round().astype(int), 0, W - 1)]


def test_strip_follows_the_flight_altitude_over_flat_terrain():
    """The wall is the flight profile: a steady climb over level ground rises with
    it, layer-snapped (so a staircase, never a dip), and clears the terrain."""
    p = _params()
    M = _mpx(p)
    surface = np.full((M, M), p.plate_mm + 2.0)
    track_px = np.stack([np.linspace(5, M - 6, 40), np.full(40, M // 2.0)], 1)
    alt = np.linspace(p.plate_mm + 1.0, p.plate_mm + 20.0, 40)          # the climb
    m = poster.strip_mesh(track_px, alt, surface, p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    top = _strip_tops(m, track_px)
    assert (np.diff(top) >= -1e-9).all()                   # never sinks along the climb
    assert top[-1] - top[0] > 15.0                         # and really does climb
    assert (top > surface[0, 0]).all()                     # above terrain everywhere
    assert abs(m.bounds[0][2] - poster.SLOT_FLOOR_MM) < 1e-6
    assert np.abs(top - poster._snap(top, p)).max() < 1e-9


def test_strip_clamps_onto_a_peak_the_flight_crosses_below():
    """A low level flight over a ramp: where the terrain outclimbs the aircraft the
    wall rides terrain + proud instead of sinking into the relief."""
    p = _params()
    M = _mpx(p)
    surface = p.plate_mm + np.tile(np.linspace(0, 12.0, M), (M, 1))     # W-E ramp
    track_px = np.stack([np.linspace(5, M - 6, 40), np.full(40, M // 2.0)], 1)
    alt = np.full(40, p.plate_mm + 1.0)                                 # level, low
    m = poster.strip_mesh(track_px, alt, surface, p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    top, zc = _strip_tops(m, track_px), _sampled_surface(surface, track_px)
    assert (alt[0] < zc + p.proud_mm).all()                # the clamp really engages
    want = poster._snap(zc + p.proud_mm, p)
    assert np.abs(top - want).max() < 1e-9                 # == surface + proud, snapped
    assert (top > zc).all()                                # never sinks into the terrain
    assert len(np.unique(top.round(6))) > 2                # and it is no longer level


def test_compose_parts_maps_altitude_through_the_terrain_scale():
    """Flight altitude rides the same vertical scale as the relief, so a flight
    above the highest terrain visibly stands above it."""
    p, N, fpx, elev, track, bounds = _synthetic()          # terrain 0-1000m, flight 0-3000m
    M = _mpx(p)
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    alt = parts["alt_mm"]
    assert alt.shape == (len(track),)
    e0, e1 = float(elev.min()), float(elev.max())
    want = p.plate_mm + (track[:, 2] - e0) / (e1 - e0) * p.relief_mm * p.exaggeration
    assert np.allclose(alt, want)
    assert alt[0] == p.plate_mm                            # on the deck = plate level
    assert alt[-1] > parts["surface"].max()                # 3000m clears 1000m terrain


def test_strip_is_capped_at_the_relief_ceiling(capsys):
    """An airliner would print a 722mm wall: 12000m over 500m terrain runs straight
    off the poster. Above the relief's own ceiling the wall goes level instead."""
    p, N, fpx, _, _, bounds = _synthetic()                 # bounds of the same track
    M = _mpx(p)
    elev = np.tile(np.linspace(0, 500, M), (M, 1))         # 500m of terrain...
    track = np.array([[47.0, 8.0, 0.0], [47.5, 9.0, 12000.0]])   # ...under a jet
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    assert abs(parts["alt_mm"].max() - 722.0) < 1e-6       # the raw, unprintable height
    m = poster.strip_mesh(parts["track_px"], parts["alt_mm"], parts["surface"], p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    top = _strip_tops(m, parts["track_px"])
    ceiling = p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm      # 32.96mm
    assert abs(top.max() - ceiling) < 1e-9                 # capped, not 722mm
    assert np.abs(top - poster._snap(top, p)).max() < 1e-9
    assert "ceiling" in capsys.readouterr().out            # and it says so, once
    # (a flight below the ceiling is untouched — test_strip_follows_the_flight_
    # altitude_over_flat_terrain tops out at 22.0mm against the same 33.0mm cap)


TRACK3 = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])


def _fake_fetches(monkeypatch, water=False, elev_top=500.0):
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, elev_top, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_water_mask",
                        lambda b, px: np.full((px, px), water, bool))


def test_build_poster_v2(monkeypatch):
    _fake_fetches(monkeypatch)
    frame_bodies, bodies, path_stl = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in frame_bodies] == ["frame"]            # no text asked for
    assert frame_bodies[0][2] == poster.COLORS["frame"] and frame_bodies[0][3] == 1
    assert frame_bodies[0][0].is_watertight and frame_bodies[0][0].volume > 0
    names = [b[1] for b in bodies]
    assert names == ["terrain"]                  # dry, below the snow line -> no caps
    assert bodies[0][2] == poster.COLORS["green"] and bodies[0][3] == 1
    assert bodies[0][0].is_watertight and bodies[0][0].volume > 0
    assert path_stl[:5] != b"solid" and len(path_stl) > 84


def test_build_poster_text_is_its_own_white_body(monkeypatch):
    """Text prints white on the black frame: a second body sitting exactly
    TEXT_EMBOSS_MM proud of the ring, not an emboss in the frame's own filament."""
    _fake_fetches(monkeypatch)
    p = _params(text="HB-EZE")
    frame_bodies, _, _ = poster.build_poster(TRACK3, p)
    assert [b[1] for b in frame_bodies] == ["frame", "text"]
    text = frame_bodies[1]
    assert text[2] == poster.COLORS["text"] == "#FFFFFF" and text[3] == 2
    m = text[0]
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    ring = p.base_mm + p.frame_height_mm
    assert abs(m.bounds[0][2] - ring) < 1e-6                   # sits on the ring...
    assert abs(m.bounds[1][2] - (ring + poster.TEXT_EMBOSS_MM)) < 1e-6   # ...proud of it
    frame = frame_bodies[0][0]
    assert abs(frame.bounds[1][2] - ring) < 1e-6               # frame itself stays flat


def test_build_poster_emits_water_cap(monkeypatch):
    _fake_fetches(monkeypatch, water=True)       # whole plate is water
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain", "water"]
    cap = bodies[1][0]
    assert bodies[1][2] == poster.COLORS["water"] and bodies[1][3] == 2
    assert cap.is_watertight and cap.is_winding_consistent and cap.volume > 0



def test_build_poster_rejects_oversized_grid():
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(size_mm=2500.0))   # typo, not a request
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(res_mm=0.01))
    with pytest.raises(ValueError):   # slot floor would reach the back of the relief plate
        poster.build_poster(track, _params(plate_mm=1.0))


def test_build_poster_rejects_cap_thicker_than_plate(monkeypatch):
    """cap_mm >= plate_mm silently produced negative green heights (API-only path)."""
    _fake_fetches(monkeypatch)
    with pytest.raises(ValueError):
        poster.build_poster(TRACK3, _params(plate_mm=2.0, cap_mm=3.0))


def test_generate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    _fake_fetches(monkeypatch, water=True)     # water everywhere -> relief has 2 bodies
    client = TestClient(appmod.app)
    params = '{"size_mm": 40, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files={"file": ("f.kml", KML.encode())},
                    data={"params": params})
    assert r.status_code == 200
    import base64
    j = r.json()
    assert set(j) == {"frame", "relief", "path", "resolved"}
    assert j["resolved"]["frame_mm"] == 4 and j["resolved"]["text"] == "ZRH-GVA"
    frame, relief, path = (base64.b64decode(j[k]) for k in ("frame", "relief", "path"))
    assert path[:5] != b"solid" and len(path) > 84
    assert frame[:2] == b"PK" and relief[:2] == b"PK"      # both 3MFs are zips
    assert [b[0] for b in poster.read_3mf(frame)] == ["frame", "text"]
    assert [b[0] for b in poster.read_3mf(relief)] == ["terrain", "water"]


def test_generate_endpoint_auto_scales_at_80mm(monkeypatch):
    """Empty scaled params at 80mm: the ring really is the resolved 4mm, not 12mm,
    and the response carries the resolved values for the preview's assembly maths."""
    from fastapi.testclient import TestClient
    import app as appmod
    _fake_fetches(monkeypatch)
    r = TestClient(appmod.app).post(
        "/generate", files={"file": ("f.kml", KML.encode())},
        data={"params": '{"size_mm": 80, "res_mm": 0.5}'})
    assert r.status_code == 200
    j = r.json()
    assert j["resolved"]["frame_mm"] == 4.0 and j["resolved"]["relief_mm"] == 6.4
    import base64
    V = poster.read_3mf(base64.b64decode(j["relief"]))[0][1]
    ext = V[:, 0].max() - V[:, 0].min()
    # 80 - 2*(4.0 ring + 0.5 ceil'd fit) = 71, less one grid pixel = 70.5.
    # At the old fixed 12mm ring this would be 54.5.
    assert abs(ext - 70.5) < 0.5


def test_generate_bad_file():
    from fastapi.testclient import TestClient
    import app as appmod
    r = TestClient(appmod.app).post(
        "/generate", files={"file": ("x.csv", b"junk")}, data={"params": "{}"})
    assert r.status_code == 400


def test_generate_bad_params_json():
    from fastapi.testclient import TestClient
    import app as appmod
    client = TestClient(appmod.app)
    files = {"file": ("f.kml", KML.encode())}
    assert client.post("/generate", files=files,
                       data={"params": "not-json"}).status_code == 400
    assert client.post("/generate", files=files,   # valid JSON, not an object
                       data={"params": "5"}).status_code == 400




def test_masked_slab_mesh_geometry():
    rng = np.random.default_rng(1)
    top = 10.0 + rng.random((30, 30)) * 3
    mask = np.zeros((30, 30), bool)
    mask[5:15, 5:25] = True                        # rectangle blob
    mask[20:28, 3:9] = True                        # second blob
    m = poster.masked_slab_mesh(mask, top, 0.6, 0.5)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    # thickness: z-extent at any x,y column is exactly 0.6 below local top
    assert abs(m.bounds[1][2] - top[mask].max()) < 1e-6
    assert abs(m.bounds[0][2] - (top[np.where(mask)].min() - 0.6)) < 1e-6
    # volume ~ cell_area * thickness (cells = all-4-corner-masked)
    cells = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    assert abs(m.volume - cells.sum() * 0.5 * 0.5 * 0.6) / m.volume < 0.01


def test_masked_slab_mesh_corner_touch_is_watertight():
    """Blobby real-world masks have diagonal pinch points; two cells that meet at
    only a corner share one vertical wall edge between four wall quads, which is
    not manifold. Caught by the live e2e, invisible to rectangular test blobs."""
    top = np.full((6, 6), 10.0)
    mask = np.zeros((6, 6), bool)
    mask[0:2, 0:2] = True                                  # cell (0,0)
    mask[1:3, 1:3] = True                                  # cell (1,1), corner-touching
    m = poster.masked_slab_mesh(mask, top, 0.6, 1.0)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    # the other diagonal, and a staircase of them
    mask2 = np.zeros((8, 8), bool)
    for i in range(4):
        mask2[i:i + 2, 6 - 2 * i - 2:6 - 2 * i] = True     # anti-diagonal staircase
    m2 = poster.masked_slab_mesh(mask2, np.full((8, 8), 10.0), 0.6, 1.0)
    assert m2.is_watertight and m2.is_winding_consistent and m2.volume > 0


def test_masked_slab_mesh_empty():
    assert poster.masked_slab_mesh(np.zeros((5, 5), bool), np.ones((5, 5)), 0.6, 0.5) is None


def test_3mf_roundtrip():
    a = poster.heightmap_mesh(np.full((4, 4), 2.0), 1.0)
    b = poster.heightmap_mesh(np.full((3, 3), 1.0), 1.0)
    data = poster.write_3mf([(a, "terrain", "#4CAF50", 1), (b, "water", "#2196F3", 2)])
    import zipfile, io as _io
    z = zipfile.ZipFile(_io.BytesIO(data))
    assert "3D/3dmodel.model" in z.namelist() and "Metadata/model_settings.config" in z.namelist()
    got = poster.read_3mf(data)
    assert [g[0] for g in got] == ["terrain", "water"]
    assert got[0][1].shape == (len(a.vertices), 3) and got[0][2].shape == (len(a.faces), 3)
    assert np.allclose(got[0][1], a.vertices, atol=1e-3)
    cfg = z.read("Metadata/model_settings.config").decode()
    assert 'value="1"' in cfg and 'value="2"' in cfg


CORE_NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def _three_body_3mf():
    import zipfile, io as _io
    meshes = [poster.heightmap_mesh(np.full((4, 4), 2.0), 1.0),
              poster.heightmap_mesh(np.full((3, 3), 1.0), 1.0),
              poster.heightmap_mesh(np.full((3, 3), 3.0), 1.0)]
    bodies = list(zip(meshes, ["terrain", "water", "snow"],
                      ["#4CAF50", "#2196F3", "#9E9E9E"], [1, 2, 3]))
    return bodies, zipfile.ZipFile(_io.BytesIO(poster.write_3mf(bodies)))


def test_3mf_is_one_multi_part_object():
    """Bambu Studio drops every <item> to the bed and auto-arranges it, so N items
    means N scattered bodies and the co-registration is destroyed. Exactly one item,
    pointing at a container object that holds every body as an identity component."""
    import xml.etree.ElementTree as ET
    bodies, z = _three_body_3mf()
    root = ET.fromstring(z.read("3D/3dmodel.model"))

    items = root.findall("m:build/m:item", CORE_NS)
    assert len(items) == 1, [i.get("objectid") for i in items]
    objs = {o.get("id"): o for o in root.findall("m:resources/m:object", CORE_NS)}
    assert sorted(objs, key=int) == ["1", "2", "3", "4"]
    cid = items[0].get("objectid")
    assert cid == "4"                                   # container is n+1, after the bodies

    container = objs[cid]
    assert container.get("type") == "model" and container.find("m:mesh", CORE_NS) is None
    comps = container.findall("m:components/m:component", CORE_NS)
    assert [c.get("objectid") for c in comps] == ["1", "2", "3"]   # every body, exactly once
    for c in comps:      # bodies already share the world origin — nothing to transform
        assert c.get("transform") == "1 0 0 0 1 0 0 0 1 0 0 0"
    for oid in ("1", "2", "3"):
        assert objs[oid].get("type") == "model"
        assert objs[oid].find("m:mesh", CORE_NS) is not None
    # display colours stay per body, so non-Bambu viewers still show them
    assert len(root.findall("m:resources/m:basematerials", CORE_NS)) == 3


def test_3mf_config_maps_every_part_to_its_extruder():
    """The old object-level extruder key left the slots unassigned in Bambu; a
    multi-part object carries them per <part>, and each part is a real object id."""
    import xml.etree.ElementTree as ET
    bodies, z = _three_body_3mf()
    ids = {o.get("id") for o in
           ET.fromstring(z.read("3D/3dmodel.model")).findall("m:resources/m:object", CORE_NS)}
    cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    objs = cfg.findall("object")
    assert len(objs) == 1 and objs[0].get("id") == "4"
    assert objs[0].find('metadata[@key="name"]') is not None
    parts = objs[0].findall("part")
    assert [pt.get("id") for pt in parts] == ["1", "2", "3"]
    assert all(pt.get("id") in ids for pt in parts)          # no dangling part -> object ref
    assert all(pt.get("subtype") == "normal_part" for pt in parts)
    assert [(pt.find('metadata[@key="name"]').get("value"),
             pt.find('metadata[@key="extruder"]').get("value")) for pt in parts] == \
        [("terrain", "1"), ("water", "2"), ("snow", "3")]


def test_3mf_roundtrip_skips_the_container():
    """read_3mf feeds the tests and check_output.py: the mesh-less container must
    not show up as a body, and body order must survive."""
    bodies, _ = _three_body_3mf()
    got = poster.read_3mf(poster.write_3mf([b for b in bodies]))
    assert [g[0] for g in got] == ["terrain", "water", "snow"]
    for (m, name, _, _), (_, V, F) in zip(bodies, got):
        assert np.allclose(V, m.vertices, atol=1e-3) and (F == m.faces).all()


def _text_body(**kw):
    """The shipped 250mm text case, without paying for a whole build_poster."""
    p = poster.resolve(poster.Params(**{"size_mm": 250.0, "text": "HB-EZE", **kw}))
    M = poster._grid(p)[1]
    track = np.array([[47.0, 8.0, 0.0], [47.5, 9.0, 3000.0]])
    parts = poster.compose_parts(track, np.zeros((M, M), np.float32),
                                 np.zeros((M, M), np.uint8),
                                 poster.track_bounds(track, p.margin_pct), p)
    t = poster.TEXT_EMBOSS_MM
    return p, parts, poster.masked_slab_mesh(parts["text_mask"], parts["frame"] + t,
                                             t, p.res_mm)


def _assert_text_meshes(p, parts, text, min_verts):
    """The meshability bars, shared by the TrueType and the load_default paths."""
    assert text is not None
    assert len(text.vertices) >= min_verts, f"only {len(text.vertices)} verts — still slivers"
    assert text.is_watertight and text.is_winding_consistent and text.volume > 0
    tm = parts["text_mask"]
    # constant-thickness slab: volume / thickness IS the meshed footprint area
    foot = text.volume / poster.TEXT_EMBOSS_MM
    # Bar is the *glyph* area the dilation exists to protect: erode the mask back and
    # require the mesh to cover all of it, i.e. no lettering was eaten by the cell rule.
    from PIL import ImageFilter
    eroded = Image.fromarray(tm.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))
    glyphs = (np.asarray(eroded) > 0).sum() * p.res_mm ** 2
    assert foot >= glyphs, f"meshed {foot:.1f}mm2 of {glyphs:.1f}mm2 of glyphs"
    # ...and most of the dilated mask. Its outer 1px rim is where the loss sits (a cell
    # wants four corners), concentrated at tight joints and counters — 75% is a
    # no-big-chunk-missing tripwire, not the real invariant above.
    assert foot >= 0.75 * tm.sum() * p.res_mm ** 2
    # z semantics unchanged: bottom on the ring top, TEXT_EMBOSS_MM proud
    ring = p.base_mm + p.frame_height_mm
    assert abs(text.bounds[0][2] - ring) < 1e-6
    assert abs(text.bounds[1][2] - (ring + poster.TEXT_EMBOSS_MM)) < 1e-6
    assert parts["frame"].max() == ring                       # ring still flat


def test_frame_text_meshes_into_readable_glyphs():
    """Regression: load_default's ~1px strokes never filled a whole 4-corner cell,
    so masked_slab_mesh ate the glyphs and left 840 vertices of slivers. A real
    TrueType face plus a 1px dilation makes every glyph pixel cell-interior."""
    p, parts, text = _text_body()
    _assert_text_meshes(p, parts, text, 2500)


def test_frame_text_meshes_without_a_truetype_font(monkeypatch):
    """The load_default fallback is the path every box without one of FONT_PATHS
    takes, so it has to clear the same bars — it is the dilation, not the face,
    that satisfies the cell rule."""
    monkeypatch.setattr(poster, "FONT_PATHS", ("/nonexistent/no-such-font.ttf",))
    p, parts, text = _text_body()
    _assert_text_meshes(p, parts, text, 2500)


def test_frame_text_shrinks_to_fit_the_bar():
    """TrueType glyphs run ~40% wider than the old bitmap, so a long string has to
    shrink to fit the ring's bottom bar instead of silently clipping off the edge."""
    long_text = "ZURICH KLOTEN TO GENEVA COINTRIN VIA THE ALPS"
    p, parts, text = _text_body(text=long_text)
    N, _, fpx = poster._grid(p)
    tm = parts["text_mask"]
    cols, rows = np.where(tm.any(0))[0], np.where(tm.any(1))[0]
    assert fpx <= cols.min() and cols.max() < N - fpx      # inside the bar, off the corners
    assert N - fpx <= rows.min() and rows.max() < N        # still on the bottom bar
    _assert_text_meshes(p, parts, text, 2500)








@pytest.mark.parametrize("text", ["HB-EZE", ""])
def test_check_output_passes_on_freshly_built_files(monkeypatch, tmp_path, text):
    """The shipped checker agrees with the shipped builder, text body or not."""
    import check_output
    _fake_fetches(monkeypatch, water=True)
    p = _params(text=text)
    frame_bodies, bodies, path_stl = poster.build_poster(TRACK3, p)
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.stl").write_bytes(path_stl)
    params = json.dumps(asdict(p))   # the checker is handed exactly what was built
    assert check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                              str(tmp_path / "path.stl"), "--params", params]) == 0


def test_check_output_passes_on_a_relief_with_a_grey_band(monkeypatch, tmp_path):
    """The all-water case above never builds a grey body, so the band's own rules
    (flat bottom on one plane, top under the relief ceiling) go unchecked there."""
    import check_output
    _fake_fetches(monkeypatch, elev_top=4000.0)              # dry ramp through 2000m
    p = _params()
    frame_bodies, bodies, path_stl = poster.build_poster(TRACK3, p)
    assert [b[1] for b in bodies] == ["terrain", "snow"]
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.stl").write_bytes(path_stl)
    assert check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                              str(tmp_path / "path.stl"),
                              "--params", json.dumps(asdict(p))]) == 0


def test_check_output_flags_a_missing_text_body(monkeypatch, tmp_path, capsys):
    """Text asked for but no white body in the frame 3MF is a real failure now,
    not a hint — the body is recoverable from the mesh, unlike the old emboss."""
    import check_output
    _fake_fetches(monkeypatch)
    frame_bodies, bodies, path_stl = poster.build_poster(TRACK3, _params())   # no text
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.stl").write_bytes(path_stl)
    rc = check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                            str(tmp_path / "path.stl"),
                            "--params", json.dumps(asdict(_params(text="HB-EZE")))])
    assert rc == 1 and "text body" in capsys.readouterr().out


def test_elevation_always_uses_the_fit_zoom(monkeypatch):
    """_tile_mosaic must never silently coarsen the DEM: over four decades of span,
    up to the largest legal grid (256mm / 0.2mm), it picks exactly the fit zoom,
    capped only at max_zoom. Pinned across the drop of the OSM zoom-floor/budget
    logic — that simplification must not move a single elevation tile."""
    import math
    seen = []
    png = io.BytesIO()
    Image.new("RGB", (256, 256), (128, 0, 0)).save(png, "PNG")
    monkeypatch.setattr(poster, "_get",
                        lambda url, **kw: seen.append(url) or png.getvalue())
    for span in (0.0005, 0.005, 0.05, 0.5):
        seen.clear()
        poster.fetch_elevation((0.1, 0.9, 0.1 + span, 0.9 + span), 1280)
        fit = math.ceil(math.log2(1280 * 2 * math.pi / (span * 256)))
        assert int(seen[0].split("/")[-3]) == min(12, fit), (span, seen[0])


# --- vector water (Overpass) -------------------------------------------------

def _wbounds(lat0, lon0, lat1, lon1):
    """Mercator bounds tuple for a lat/lon box (x0, y0, x1, y1)."""
    x0, y0 = poster._merc(lat0, lon0)
    x1, y1 = poster._merc(lat1, lon1)
    return x0, y0, x1, y1


def _rc(bounds, lat, lon, n):
    """(row, col) of a lat/lon inside an n*n mask over bounds; row 0 = north."""
    x, y = poster._merc(lat, lon)
    x0, y0, x1, y1 = bounds
    return int((y1 - y) / (y1 - y0) * n), int((x - x0) / (x1 - x0) * n)


def _ring(lat0, lon0, lat1, lon1):
    return [(lat0, lon0), (lat0, lon1), (lat1, lon1), (lat1, lon0), (lat0, lon0)]


def _way(coords, **kw):
    return dict(type="way", geometry=[{"lat": la, "lon": lo} for la, lo in coords], **kw)


def _rel(members):
    """members: [(role, coords), ...]"""
    return dict(type="relation", members=[
        dict(type="way", role=role, geometry=[{"lat": la, "lon": lo} for la, lo in c])
        for role, c in members])


B = _wbounds(47.0, 8.0, 47.1, 8.1)      # ~7.5 km box; at 100 px, 1 px ~ 75 m


def test_water_mask_fills_a_closed_way():
    m = poster._water_mask_from_elements([_way(_ring(47.02, 8.02, 47.08, 8.08))], B, 100)
    assert m.shape == (100, 100) and m.dtype == bool
    assert m[_rc(B, 47.05, 8.05, 100)]                     # inside the lake
    assert not m[_rc(B, 47.005, 8.005, 100)]               # outside it
    assert 0.25 < m.mean() < 0.45                          # ~0.6 x 0.6 of the box


def test_stitch_rings_joins_reversed_fragments():
    a = [(47.02, 8.02), (47.02, 8.08), (47.08, 8.08)]
    b = [(47.02, 8.02), (47.08, 8.02), (47.08, 8.08)]      # same ring, wound backwards
    rings, broken = poster._stitch_rings([a, b])
    assert broken == 0 and len(rings) == 1
    r = rings[0]
    assert r[0] == r[-1] and len(r) == 5                   # closed, no duplicated joints


def test_water_mask_relation_outer_split_with_island():
    """Real multipolygon shape: outer split across two ways (one reversed), plus an
    inner ring that must be punched back out of the fill."""
    rel = _rel([("outer", [(47.02, 8.02), (47.02, 8.08), (47.08, 8.08)]),
                ("outer", [(47.02, 8.02), (47.08, 8.02), (47.08, 8.08)]),
                ("inner", _ring(47.04, 8.04, 47.06, 8.06))])
    m = poster._water_mask_from_elements([rel], B, 100)
    assert m[_rc(B, 47.03, 8.03, 100)]                     # lake body
    assert not m[_rc(B, 47.05, 8.05, 100)]                 # island hole
    assert not m[_rc(B, 47.005, 8.005, 100)]               # dry land outside


def test_water_mask_role_empty_counts_as_outer():
    rel = _rel([("", _ring(47.02, 8.02, 47.08, 8.08))])
    assert poster._water_mask_from_elements([rel], B, 100)[_rc(B, 47.05, 8.05, 100)]


def test_water_mask_broken_ring_warns_and_keeps_the_rest(capsys):
    """An unclosed outer chain is skipped with one warning; every other polygon
    in the same response still gets painted."""
    broken = _rel([("outer", [(47.02, 8.02), (47.02, 8.08)]),      # a bare open chain
                   ("outer", [(47.03, 8.03), (47.04, 8.04)])])     # not touching it
    good = _way(_ring(47.05, 8.05, 47.09, 8.09))
    m = poster._water_mask_from_elements([broken, good], B, 100)
    assert m[_rc(B, 47.07, 8.07, 100)]                     # the good lake survived
    assert not m[_rc(B, 47.025, 8.025, 100)]               # the broken chain painted nothing
    out = capsys.readouterr().out
    assert "water" in out and "2" in out                   # one line, both chains counted


def test_water_mask_clips_a_polygon_crossing_the_bbox():
    """Overpass does not clip geometry to the bbox — the rasteriser must."""
    m = poster._water_mask_from_elements([_way(_ring(46.5, 7.5, 47.05, 8.05))], B, 100)
    assert m[_rc(B, 47.01, 8.01, 100)]                     # the part inside is painted
    assert not m[_rc(B, 47.09, 8.09, 100)]                 # the far corner stays dry
    assert 0.15 < m.mean() < 0.4                           # ~half the box, not all of it


def test_water_mask_skips_sub_pixel_ponds():
    pond = _way(_ring(47.05, 8.05, 47.052, 8.052))         # ~2 px across -> ~5 px2
    lake = _way(_ring(47.05, 8.05, 47.06, 8.06))           # ~11 px across -> ~120 px2
    assert not poster._water_mask_from_elements([pond], B, 100).any()
    assert poster._water_mask_from_elements([lake], B, 100).any()


def test_fetch_water_mask_uses_the_mirror_when_the_first_fails(monkeypatch, capsys):
    calls = []

    def fake_get(url, timeout=20):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise RuntimeError("overpass busy")
        return b'{"elements": []}'

    monkeypatch.setattr(poster, "_get", fake_get)
    m = poster.fetch_water_mask(B, 16)
    assert m.shape == (16, 16) and not m.any()
    assert len(calls) == 2
    assert calls[0][0].startswith(poster.OVERPASS_URLS[0])
    assert calls[1][0].startswith(poster.OVERPASS_URLS[1])
    assert calls[0][1] == 180                               # Overpass is slow, not 20s
    assert "natural" in calls[0][0] and "8.1" in calls[0][0]  # query + bbox in the URL
    assert "mirror" in capsys.readouterr().out.lower()


def test_fetch_water_mask_skips_transoceanic_spans(monkeypatch, capsys):
    monkeypatch.setattr(poster, "_get",
                        lambda *a, **k: pytest.fail("must not query Overpass"))
    m = poster.fetch_water_mask(_wbounds(40.0, -70.0, 50.0, 10.0), 32)
    assert m.shape == (32, 32) and not m.any()
    assert "water" in capsys.readouterr().out.lower()


def test_build_poster_soft_fails_to_terrain_when_overpass_is_down(monkeypatch, capsys):
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, 500, px), (px, 1)))

    def boom(url, timeout=20):
        raise RuntimeError("overpass down")

    monkeypatch.setattr(poster, "_get", boom)
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain"]           # a water-less poster, not a 502
    assert "water" in capsys.readouterr().out.lower()


def test_get_sends_an_identifying_user_agent(monkeypatch):
    """overpass-api.de answers requests' default User-Agent with a bare 406."""
    seen = {}

    class R:
        content = b"x"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(poster.requests, "get",
                        lambda url, **kw: seen.update(kw) or R())
    assert poster._get("https://example.invalid/x") == b"x"
    assert "FlightPathPoster" in seen["headers"]["User-Agent"]


@pytest.mark.skipif(not os.environ.get("LIVE"), reason="hits the live Overpass API")
def test_live_lake_zug_water_mask():
    m = poster.fetch_water_mask(_wbounds(47.08, 8.42, 47.20, 8.55), 256)
    assert 0.05 < m.mean() < 0.6, m.mean()


# --- elevation snow caps -----------------------------------------------------

def test_build_poster_snow_caps_above_the_snow_line(monkeypatch):
    _fake_fetches(monkeypatch, elev_top=4000.0)            # W-E ramp through 2000 m
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain", "snow"]
    cap = bodies[1][0]
    assert bodies[1][2] == poster.COLORS["snow"] and bodies[1][3] == 3
    assert cap.is_watertight and cap.is_winding_consistent and cap.volume > 0
    # ...and the threshold is the parameter, not a constant
    _, bodies, _ = poster.build_poster(TRACK3, _params(snow_line_m=5000.0))
    assert [b[1] for b in bodies] == ["terrain"]


def test_snow_speckle_is_opened_away(monkeypatch):
    def elev(b, px):
        e = np.full((px, px), 500.0)
        e[px // 2, px // 2] = 3000.0                       # a single spiky DEM pixel
        return e

    monkeypatch.setattr(poster, "fetch_elevation", elev)
    monkeypatch.setattr(poster, "fetch_water_mask", lambda b, px: np.zeros((px, px), bool))
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain"]


def test_snow_mask_merges_ridges_into_massifs_and_drops_specks():
    """Grey caps print as coherent massifs: closing at the minimum printed blob width
    bridges ridge slivers, the following opening removes what stayed thin."""
    p = _params(res_mm=0.5, snow_min_mm=3.0)               # k = 7px = 3.5mm
    e = np.zeros((60, 60))
    e[12:48, 12:15] = 3000.0                               # ridge A, 1.5mm wide
    e[12:48, 19:22] = 3000.0                               # ridge B, 2mm away
    e[12:15, 40:43] = 3000.0                               # an isolated 1.5mm speck
    e[30:40, 35:45] = 3000.0                               # a genuine 5mm massif
    m = poster._snow_mask(e, p)
    assert m[30, 15:19].all()                              # the 2mm gap is bridged...
    assert m[12:48, 12:22].all()                           # ...both ridges, one region
    assert not m[12:15, 40:43].any()                       # the speck is gone
    assert m[32:38, 37:43].all()                           # the massif survives intact
    old = poster._opened(e >= p.snow_line_m, 3)            # what Task 7 produced
    assert not old[30, 16] and old[13, 41]                 # split ridges, speck kept


def test_water_beats_snow(monkeypatch):
    """High Alpine lakes sit above the snow line — they must still be blue."""
    _fake_fetches(monkeypatch, water=True, elev_top=4000.0)
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain", "water"]


# --- grey elevation band -----------------------------------------------------

def _banded(snow_line_m=600.0, lc_all=False, **kw):
    """Synthetic E-W ramp (0-1000m) with the ground above `snow_line_m` marked grey."""
    p = _params(snow_line_m=snow_line_m, **kw)
    M = _mpx(p)
    elev = np.tile(np.linspace(0, 1000, M), (M, 1))
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    bounds = poster.track_bounds(track, p.margin_pct)
    lc = np.zeros((M, M), np.uint8)
    lc[np.ones_like(elev, bool) if lc_all else (elev >= snow_line_m)] = 2
    return p, M, elev, poster.compose_parts(track, elev, lc, bounds, p)


def test_snap_lands_on_the_first_layer_grid():
    """The printer lays a 0.2mm first layer and 0.12mm ones after it, so a printable
    height is 0.2 + n*0.12 — not n*0.12, which is what round(z/layer) gave."""
    p = _params()
    z = np.array([0.21, 0.25, 0.26, 1.0, 5.0, 31.7])
    s = poster._snap(z, p)
    n = (s - poster.FIRST_LAYER_MM) / p.layer_mm
    assert np.abs(n - np.round(n)).max() < 1e-9
    assert np.abs(s - z).max() <= p.layer_mm / 2 + 1e-9        # nearest boundary
    exact = poster.FIRST_LAYER_MM + 7 * p.layer_mm
    assert abs(poster._snap(exact, p) - exact) < 1e-12         # a boundary is a fixed point
    assert (poster._snap(z, _params(layer_mm=0.0)) == z).all()  # 0 = opt out


def test_z_snow_is_the_snow_line_on_the_relief_scale():
    p, M, elev, parts = _banded()
    e0, e1 = float(elev.min()), float(elev.max())
    want = p.plate_mm + (p.snow_line_m - e0) / (e1 - e0) * p.relief_mm * p.exaggeration
    assert abs(parts["z_snow"] - poster._snap(want, p)) < 1e-9
    assert abs(parts["z_snow"] - poster._snap(parts["z_snow"], p)) < 1e-12   # on a boundary
    assert p.plate_mm <= parts["z_snow"] < parts["surface"].max()


def test_grey_is_a_band_with_a_flat_bottom_not_a_conformal_skin():
    """The cap was a 0.6mm shell conformal to terrain: on a 2.3mm/mm alpine slope it
    surfaces as a 0.26mm stripe, narrower than one extrusion, and the slicer merges it
    into the neighbouring colour. A band from a horizontal plane has no such stripe."""
    p, M, elev, parts = _banded()
    m = poster.band_mesh(parts, p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    z = m.vertices[:, 2]
    assert abs(z.min() - parts["z_snow"]) < 1e-9                # flat bottom on the plane
    assert (np.abs(z - z.min()) < 1e-9).sum() == len(z) // 2    # exactly the bottom half
    assert parts["z_snow"] < z.max() <= parts["surface"].max() + 1e-9
    skin = poster.masked_slab_mesh(parts["snow"], parts["surface"], p.cap_mm, p.res_mm)
    assert m.volume > 3 * skin.volume                           # a body, not a skin


def test_green_and_grey_meet_exactly_at_the_snow_plane():
    p, M, elev, parts = _banded()
    verts = poster._cell_verts(parts["snow_cells"])
    assert verts.sum() > 100
    assert np.abs(parts["green"][verts] - parts["z_snow"]).max() < 1e-9  # no gap, no overlap


def test_the_band_does_not_change_the_assembled_surface():
    """Colour-volume change, not a shape change: green top union grey top is still
    exactly the surface heightmap the single body had."""
    p, M, elev, parts = _banded()
    verts = poster._cell_verts(parts["snow_cells"])
    top = np.where(verts, parts["surface"], parts["green"])
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert np.abs(top - parts["surface"])[~gmask].max() < 1e-9
    assert verts.any() and gmask.any()


def test_snow_line_above_the_dem_leaves_no_band():
    p, M, elev, parts = _banded(snow_line_m=5000.0, lc_all=True)
    assert not parts["snow_cells"].any()
    assert poster.band_mesh(parts, p) is None
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert (parts["green"][~gmask] == parts["surface"][~gmask]).all()


def test_snow_line_below_the_dem_leaves_no_green_above_the_plate():
    p, M, elev, parts = _banded(snow_line_m=-100.0, lc_all=True)
    assert abs(parts["z_snow"] - p.plate_mm) < 1e-9        # clamped to the plate, not under
    verts = poster._cell_verts(parts["snow_cells"])
    assert verts.mean() > 0.8
    assert np.abs(parts["green"][verts] - p.plate_mm).max() < 1e-9
