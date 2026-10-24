import contextlib
import io
import json
import os
import re
from dataclasses import asdict, replace

import numpy as np
import pytest
from PIL import Image, ImageDraw

import activity
import poster


@pytest.fixture(autouse=True)
def _fresh_overpass_cache():
    """_overpass caches per query string, and the tests reuse one bbox with different
    fake responses — without this the second test reads the first one's elements."""
    poster._overpass.cache_clear()


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
    measure geometry, not the auto-scaling (which resolve() is tested for below).

    Resolved, because chin_mm is derived from the caption and compose_parts/_grid
    are only ever handed resolved params (build_poster and check_output both resolve)."""
    return poster.resolve(poster.Params(**{
        "size_mm": 40.0, "frame_mm": 4.0, "res_mm": 0.5, "relief_mm": 20.0,
        "frame_height_mm": 9.96, "text_mm": 8.0, "groove_w_mm": 2.0,
        "proud_mm": 0.96, "wall_mm": 12.0, **kw}))


def test_resolve_at_250_is_the_legacy_defaults():
    """Backwards compat pin: the auto values at the reference size are exactly the
    concrete defaults every earlier print was made with."""
    p = poster.resolve(poster.Params(size_mm=250))
    assert p.frame_mm == 12.0
    assert p.relief_mm == 20.0
    assert p.frame_height_mm == 10.08    # 9.96 up to 42 whole 0.24 layers, ring top 14.12
    assert p.text_mm == 8.0
    assert p.groove_w_mm == 2.0
    assert p.proud_mm == 0.96            # was 1.0: 4 layers of 0.24
    assert p.wall_mm == 12.0             # 50 layers: the 100-200 bpm range of the wall
    assert p.chin_mm == 0.0              # no caption -> the frame stays square


def test_resolve_scales_and_floors_at_80mm():
    p = poster.resolve(poster.Params(size_mm=80))
    assert p.frame_mm == 4.0            # 3.84 -> floor
    assert p.relief_mm == 6.4           # 20 * 80/250, above its 5.0 floor
    assert p.frame_height_mm == 3.36    # 9.96 * 80/250 = 3.19, up to 14 whole layers
    assert p.text_mm == 3.0             # 2.56 -> floor
    assert p.groove_w_mm == 1.44        # 0.64 -> floor (2 x 0.42 of strip core)
    assert p.proud_mm == 0.48           # 0.31 -> 0.4 floor, up to 2 whole layers
    # absolute params are untouched by size (printer properties, not visual scale)
    assert (p.base_mm, p.plate_mm, p.cap_mm, p.clearance_mm, p.fit_mm, p.res_mm,
            p.snow_line_m, p.layer_mm, p.smooth_px) == (4.04, 2.12, 0.96, 0.30, 0.2, 0.4,
                                                        2000.0, 0.24, 1.0)


def test_resolve_snaps_z_heights_to_the_layer_grid():
    """Every z the frame stacks up must land on a printable layer boundary.

    Regression: at 170mm frame_height_mm scaled to 6.7728 and rounded to 6.77, so the
    ring top came out 10.81mm — 0.05mm above boundary 88. Which layer the black/white
    colour boundary lands on was then decided by the slicer's rounding, not by us.
    In-plane params (frame_mm, text_mm, groove_w_mm, chin_mm) must NOT be snapped:
    the layer grid is a z grid and means nothing in xy."""
    # 5 layers: white PLA over black only stops reading warm-grey at ~1.0mm
    assert poster.TEXT_EMBOSS_MM == 1.2
    for size in (250, 200, 170, 120):
        p = poster.resolve(poster.Params(size_mm=size, text="ZURICH", text2="HB-EZE"))
        ring_top = p.base_mm + p.frame_height_mm
        for label, z in (("ring top", ring_top),
                         ("text top", ring_top + poster.TEXT_EMBOSS_MM),
                         ("relief ceiling",
                          p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm)):
            off = abs(z - poster._snap(z, p))
            assert off < 1e-9, f"{size}mm {label} {z:.4f}mm is {off:.4f}mm off the grid"
        # xy is not snapped — a frame width forced onto 0.24mm steps would be nonsense
        assert p.frame_mm == max(4.0, round(12.0 * size / 250, 2))
        assert p.text_mm == max(3.0, round(8.0 * size / 250, 2))


def test_fixed_constants_sit_on_the_default_layer_grid():
    """The literals that are not resolve()d — slot floor, the green under a slot cap,
    base and plate — must be absolute layer boundaries (0.2 + n*layer), and the slab
    thicknesses stacked on them whole layers, or a layer_mm change silently leaves
    them between layers. They are literals on purpose; this is what pins them."""
    p = poster.resolve(poster.Params())
    for v in (poster.SLOT_FLOOR_MM, poster.SLOT_FLOOR_MM - poster.SLOT_CAP_MM,
              p.base_mm, p.plate_mm):
        assert abs(v - poster._snap(v, p)) < 1e-6, v
    for v in (p.cap_mm, poster.SLOT_CAP_MM, poster.TEXT_EMBOSS_MM):
        n = v / p.layer_mm
        assert abs(n - round(n)) < 1e-6, v


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


def _leg(sport, n, hr, t0=0.0, lat0=47.0, lon0=8.0, dlon=1e-4):
    """An activity.Leg heading east, 1 s per point; hr is a bpm or a callable of the index."""
    i = np.arange(n)
    hr = np.array([hr(k) for k in i], float) if callable(hr) else np.full(n, float(hr))
    return activity.Leg(sport, np.full(n, lat0), lon0 + i * dlon, t0 + i.astype(float), hr)


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
        assert lane - W > 2 * dil * res_f


def test_leg_stations_resample_one_per_pixel_and_carry_smoothed_hr():
    p = _params()
    leg = _leg("run", 300, lambda i: 120.0 if i < 150 else np.nan)
    P, hr = poster.leg_stations(leg, poster.legs_bounds([leg], p.margin_pct), _mpx(p))
    assert len(P) > 8 and abs(np.hypot(*np.diff(P, axis=0).T).mean() - 1.0) < 0.05
    assert np.allclose(hr[: len(hr) // 3], 120) and np.isnan(hr[-1])


def _line(x0, x1, y, hr):
    """A station piece stepping 1 px along x from x0 to x1 inclusive, at height y."""
    x = np.linspace(x0, x1, abs(x1 - x0) + 1)
    return np.stack([x, np.full(len(x), y)], 1), np.full(len(x), float(hr))


def _arc(cx, cy, R, hr):
    """One lap of a circle from angle 0, stations 1 px apart along it."""
    th = np.arange(int(np.ceil(2 * np.pi * R))) / R
    return np.stack([cx + R * np.cos(th), cy + R * np.sin(th)], 1), np.full(len(th), float(hr))


def _cat(*pieces):
    return np.concatenate([P for P, _ in pieces]), np.concatenate([h for _, h in pieces])


def _vline(x, y0, y1, hr):
    """_line turned upright: column x, stepping 1 px from y0 to y1 inclusive."""
    P, h = _line(y0, y1, x, hr)
    return P[:, ::-1], h


def test_ramp_grades_each_piece_on_its_own():
    w = poster._ramp(np.array([0, 1, 1, 1, 1, 0, 1, 1, 1, 1], bool), np.array([0] * 6 + [1] * 4), 4)
    assert np.allclose(w, [0, .25, .5, .5, .25, 0, 1, 1, 1, 1])


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


def _foot_on(Q, wall):
    """(feet, dist, seg) of each Q on a wall's polyline (stations joined within a piece only)."""
    A = np.concatenate([P[:-1] for P, _ in wall]); B = np.concatenate([P[1:] for P, _ in wall])
    return poster._nearest_on_segments(Q, A, B)


def _dist_to(Q, wall):
    return _foot_on(Q, wall)[1]


def test_a_wall_leaving_the_shared_road_never_dips_toward_it():
    a = _line(10, 90, 50.0, 120)
    b = _cat(_line(10, 50, 50.5, 160), _vline(50, 51, 90, 160))
    [_, [(Pb, _)]] = poster.assign_lanes([[a], [b]], lane_px=4, r_px=4, ramp=4)
    assert _dist_to(Pb, [a]).min() >= 4 - 1e-6


@pytest.mark.parametrize("late_y, back_y", [(50.4, None), (49.6, None), (50.0, 49.6)])
def test_an_out_and_back_earlier_wall_keeps_the_later_wall_on_one_side(late_y, back_y):
    # The later wall runs on the lane side, on the far side (the mirror), or is itself an
    # out-and-back drifting 0.4 px to the far side on its way back (two out-and-backs
    # sharing a turnaround). One side, and 4 px off wherever the lane is fully eased in.
    # A turnaround is a 180 deg corner, inside assign_lanes' ceiling, and on the lane side
    # (50.4) the last station lands across: there, as in the corner sweep, stations whose
    # foot on the earlier wall lies within 3 lanes of the turnaround are not checked. The
    # other two hold at every station, which pins that no target clip comes back.
    early0 = poster.collapse_passes([_cat(_line(10, 90, 50.0, 120), _line(90, 10, 50.6, 160))], r_px=4, ramp=4)
    late0 = _line(10, 90, late_y, 150)
    if back_y is not None:
        (late0,) = poster.collapse_passes([_cat(late0, _line(90, 10, back_y, 150))], r_px=4, ramp=4)
    turn = np.array([90.0, 50.0])
    for deg in (0, 33, 71):
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        rot = lambda Q: (Q - 50) @ np.array([[c, s], [-s, c]]) + 50   # +deg about (50, 50)
        early = [(rot(Q), h) for Q, h in early0]
        L = rot(late0[0])
        [_, [(P, _)]] = poster.assign_lanes([early, [(L, late0[1])]], lane_px=4, r_px=4, ramp=4)
        keep = np.hypot(*(_foot_on(P, early)[0] - rot(turn)).T) > 3 * 4 if late_y == 50.4 else np.ones(len(P), bool)
        a1 = poster._ramp(_dist_to(L, early) < 4, np.zeros(len(L), int), 4) == 1
        side = np.sign(c * (P[:, 1] - 50) - s * (P[:, 0] - 50))     # road direction x P
        assert np.ptp(side[keep]) == 0, deg
        assert np.allclose(_dist_to(P[keep & a1], early), 4, rtol=0, atol=1e-6), deg
    # unrotated, |y - 50| = 4 mid-stretch, where the collapsed road is y = 50
    [_, [(P, _)]] = poster.assign_lanes([early0, [late0]], lane_px=4, r_px=4, ramp=4)
    keep = np.hypot(*(_foot_on(P, early0)[0] - turn).T) > 3 * 4
    assert np.allclose(abs(P[keep, 1] - 50), 4, rtol=0, atol=1e-6)


@pytest.mark.parametrize("lane_inside, off", [(False, 0.4), (False, -0.4), (True, 0.4), (True, -0.4)])
def test_lanes_round_a_sharp_corner_stay_clear_of_the_earlier_wall(lane_inside, off):
    road = _cat(_line(5, 30, 30.0, 120), _vline(30, 29, 5, 120))   # the lane side is outside
    early = (road[0][::-1], road[1]) if lane_inside else road
    late = (early[0] + off, early[1])                               # +0.4 outside, -0.4 inside
    [_, [(P, _)]] = poster.assign_lanes([[early], [late]], lane_px=4, r_px=4, ramp=4)
    S = (P[:-1] + np.linspace(0, 1, 10)[:, None, None] * (P[1:] - P[:-1])).reshape(-1, 2)
    assert _dist_to(S, [early]).min() >= 0.9 * 4
    assert np.hypot(*np.diff(P, axis=0).T).max() <= 1.5 * 4


def _bend(deg, left=0.0, n=30):
    """A road n px along +x to a corner at index n, then n px on a heading turned deg
    (positive toward +y), 1 px stations around (50, 50); left shifts it to its +y side
    (leg 1's left), the corner mitred."""
    d2 = np.array([np.cos(np.radians(deg)), np.sin(np.radians(deg))])
    n1, n2 = np.array([0, 1.0]), np.array([-d2[1], d2[0]])
    ends = [left * n1, n * np.array([1, 0]) + left * (n1 + n2) / (1 + d2[0]), n * (np.array([1, 0]) + d2) + left * n2]
    legs = [a + np.linspace(0, 1, int(np.ceil(np.hypot(*(b - a)) - 1e-9)) + 1)[:, None] * (b - a)
            for a, b in zip(ends, ends[1:])]
    P = np.concatenate([legs[0], legs[1][1:]]) + 50
    return P, np.full(len(P), 120.0)


@pytest.mark.parametrize("deg, cut, lane_px, ramp", [
    (sgn * deg, cut, lane_px, ramp)
    for deg in (90, 120, 135) for sgn in (1, -1) for cut in (-0.4, 0.4, 0.8, 2.0)
    for lane_px, ramp in ((4, 4), (5.075, 11))
] + [(-120, None, 4, 4)])   # the re-review's repro: later wall = road - 1.6
def test_a_sharp_corner_never_switches_the_lane_side_for_the_rest_of_the_run(deg, cut, lane_px, ramp):
    # cut: how far the later track runs inside the corner (-0.4 = outside). Clearance is
    # not asserted past 90 deg or for a cut-in track, and stations whose foot is within
    # 3 lanes of the corner are not checked: that is assign_lanes' ceiling. What must
    # hold is the side after the corner being the side before it.
    road = _bend(deg)
    late = (road[0] - 1.6, road[1]) if cut is None else _bend(deg, cut * np.sign(deg))
    [_, [(P, _)]] = poster.assign_lanes([[road], [late]], lane_px=lane_px, r_px=lane_px, ramp=ramp)
    a1 = poster._ramp(_dist_to(late[0], [road]) < lane_px, np.zeros(len(P), int), ramp) == 1
    A, B = road[0][:-1], road[0][1:]
    F, _, k = poster._nearest_on_segments(P, A, B)
    u = B[k] - A[k]
    side = np.sign(u[:, 0] * (P - F)[:, 1] - u[:, 1] * (P - F)[:, 0])
    keep = a1 & (np.hypot(*(F - road[0][30]).T) > 3 * lane_px)
    assert np.ptp(side[keep]) == 0 and side[keep][0] != 0


def test_a_push_out_that_gives_up_says_so_in_one_line_without_coordinates(capsys):
    poster.assign_lanes([[_bend(150)], [_bend(150, 0.4)]], lane_px=4, r_px=4, ramp=4)   # a 30 deg wedge
    assert re.fullmatch(r"path: lane push-out did not converge at \d+ stations\n", capsys.readouterr().out)


def test_lanes_are_counted_against_the_earlier_walls_lines_before_they_moved():
    # wall 2 is 1 px from wall 1's input line but 4.5 px from where wall 1 moved to
    out = poster.assign_lanes([[_line(10, 90, y, 120)] for y in (50.0, 50.5, 49.5)], lane_px=4, r_px=4, ramp=4)
    assert np.allclose(out[2][0][0][:, 1], 58.0)


def test_the_lane_move_is_eased_per_piece():
    # r_px > lane_px, so the stations eased in sit outside the lane and are not pushed
    b = [_cat(_line(10, 50, 50.5, 160), _vline(50, 51, 70, 160)), _line(60, 90, 57.0, 160)]
    [_, [(P0, _), (P1, _)]] = poster.assign_lanes([[_line(10, 90, 50.0, 120)], b], lane_px=4, r_px=8, ramp=4)
    assert P0[b[0][0][:, 1] == 57, 1] == pytest.approx([56.25])   # 1/4 of the way at the edge
    assert np.allclose(P1[:, 1], 54.0)          # a piece that starts on the road is not eased


def test_relief_plate_clears_the_frame_ring():
    """The relief plate must be at least fit_mm smaller than the ring opening per
    side, at every resolution — a gap that rounds down to zero is an interference
    fit and the plate will not drop into the frame."""
    for res in (0.2, 0.25, 0.3, 0.4, 0.5):
        p = _params(res_mm=res)
        N, M, fpx, chin_px = poster._grid(p)
        assert chin_px == 0                          # no caption -> no chin, ever
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
    # groove cells are never band cells; water caps drape into the slot instead
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert gmask[30:40, 30:40].any()      # the groove really does cross the snow square
    assert not c[gmask].any()
    assert (parts["cap_top"][gmask] == poster.SLOT_FLOOR_MM).all()
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
    the glyph pixels come back as a mask instead, on its own finer grid."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    S = poster.TEXT_SUB
    lc = np.zeros((M, M), np.uint8)
    q = _params(text="TEST", text_mm=3.0)
    parts = poster.compose_parts(track, elev, lc, bounds, q)
    frame, tm = parts["frame"], parts["text_mask"]
    H = N + poster._grid(q)[3]
    assert frame.max() == p.base_mm + p.frame_height_mm    # ring is flat, nothing embossed
    assert tm.shape == ((H - 1) * S + 1, (N - 1) * S + 1) and tm.dtype == bool
    assert parts["text_res"] == q.res_mm / S
    assert tm.any() and tm[:(N - fpx) * S, :].sum() == 0   # glyphs live on the bottom bar
    assert not poster.compose_parts(track, elev, lc, bounds, _params())["text_mask"].any()


# --- the chin: extra frame height at the bottom, for the caption ----------------

def _chinned(**kw):
    """(bare parts, chinned parts, chin_px) over the same synthetic terrain."""
    p, N, fpx, elev, track, bounds = _synthetic()
    lc = np.zeros((_mpx(p), _mpx(p)), np.uint8)
    q = _params(**kw)
    return (poster.compose_parts(track, elev, lc, bounds, p),
            poster.compose_parts(track, elev, lc, bounds, q), poster._grid(q)[3])


def test_the_chin_extends_the_frame_downward_and_leaves_the_opening_alone():
    """The chin is extra ring at the bottom only: the inner opening keeps its exact
    indices and values, so the relief plate that drops into it is untouched."""
    p, N, fpx, elev, track, bounds = _synthetic()
    bare, chinned, chin_px = _chinned(text="ZURICH", text2="HB-EZE")
    M = _mpx(p)
    assert chin_px > 0
    assert bare["frame"].shape == (N, N)                   # no caption -> square, as before
    assert chinned["frame"].shape == (N + chin_px, N)      # taller than wide, downward
    # byte-identical opening at byte-identical indices — this is the gate
    op = (slice(fpx, N - fpx), slice(fpx, N - fpx))
    assert (chinned["frame"][op] == bare["frame"][op]).all()
    assert (chinned["frame"][op] == p.base_mm).all()
    assert (chinned["frame"][:N] == bare["frame"]).all()   # the whole square is unchanged
    assert (chinned["frame"][N:] == p.base_mm + p.frame_height_mm).all()   # chin is all ring
    # ...and the relief the opening holds is not even aware of it
    for k in ("green", "surface", "water", "snow"):
        assert chinned[k].shape == (M, M) and (chinned[k] == bare[k]).all()


def test_chin_auto_sizes_to_hold_the_caption():
    """Two lines plus TEXT_MARGIN_MM top and bottom decide the chin, so the bar is
    always exactly as tall as the caption needs and never taller."""
    q = _params(text="ZURICH", text2="HB-EZE", text_mm=6.0)
    block = 6.0 + 0.35 * 6.0 + poster.SUB_RATIO * 6.0      # line1 + gap + line2
    N, _, fpx, chin_px = poster._grid(q)
    # frame rows N-fpx..H-1, measured the way heightmap_mesh maps them to y
    bar = (fpx + chin_px - 1) * q.res_mm
    assert bar >= block + 2 * poster.TEXT_MARGIN_MM - 1e-9
    assert bar < block + 2 * poster.TEXT_MARGIN_MM + q.res_mm   # pixel rounding, no more
    # one line needs less chin than two, no caption needs none
    assert 0 == _params().chin_mm < _params(text="ZURICH", text_mm=6.0).chin_mm < q.chin_mm
    # the glyphs really do sit inside those margins
    p, N, fpx, elev, track, bounds = _synthetic()
    parts = poster.compose_parts(track, elev, np.zeros((_mpx(q), _mpx(q)), np.uint8),
                                 bounds, q)
    tm, tres = parts["text_mask"], parts["text_res"]
    rows = np.where(tm.any(1))[0]
    top = (N - fpx) * poster.TEXT_SUB                      # first fine row of the bar
    # 0.2mm of slack: _fit_line rounds the em to a whole px, so rendered ink lands
    # within a fraction of the nominal line height it was asked for
    assert (rows.min() - top) * tres >= poster.TEXT_MARGIN_MM - 0.2
    assert (tm.shape[0] - 1 - rows.max()) * tres >= poster.TEXT_MARGIN_MM - 0.2


def test_explicit_chin_mm_overrides_the_auto_size():
    q = _params(text="ZURICH", text2="HB-EZE", chin_mm=3.0)
    assert q.chin_mm == 3.0
    assert poster._grid(q)[3] == int(3.0 / q.res_mm)
    assert poster.resolve(q) == q                          # still idempotent


def test_second_line_renders_smaller_than_the_first():
    p, N, fpx, elev, track, bounds = _synthetic()
    q = _params(text="MMMM", text2="MMMM", text_mm=6.0)
    tm = poster.compose_parts(track, elev, np.zeros((_mpx(q), _mpx(q)), np.uint8),
                              bounds, q)["text_mask"]
    rows = np.where(tm.any(1))[0]
    blank = np.where(~tm.any(1)[rows.min():rows.max() + 1])[0]   # the gap between the lines
    assert len(blank), "the two lines ran together"
    split = rows.min() + blank[len(blank) // 2]
    h1 = tm[:split].any(1).sum()
    h2 = tm[split:].any(1).sum()
    assert 0 < h2 < h1                                     # line 2 is the smaller subtitle
    assert abs(h2 / h1 - poster.SUB_RATIO) < 0.15
    # both lines live inside the ring opening's x range, off the corners
    cols = np.where(tm.any(0))[0]
    assert fpx * poster.TEXT_SUB <= cols.min() and cols.max() < (N - fpx) * poster.TEXT_SUB


def _split_lines(tm):
    """(line 1 rows, line 2 rows) of a two-line mask, split on the blank gap."""
    rows = np.where(tm.any(1))[0]
    blank = np.where(~tm.any(1)[rows.min():rows.max() + 1])[0]
    assert len(blank), "the two lines ran together"
    split = rows.min() + blank[len(blank) // 2]
    return tm[:split], tm[split:]


def test_caption_strokes_clear_the_printable_stroke_floor(capsys):
    """A 0.4mm nozzle cannot hold a stroke under ~0.8mm (0.84 target, two 0.42
    extrusions): at 1.5-2.2 extrusion widths a glyph is pure perimeter, and Arachne
    flips between one and two beads along the stroke, nicking one edge and blobbing
    the other (docs/print-settings.md). The rendered strokes were 0.6-0.9mm, so the
    mask is dilated toward MIN_STROKE_MM — per line, because line 2 is the smaller
    face and needs the most — unless that would shut a counter, which it says."""
    p, N, fpx, elev, track, bounds = _synthetic()
    q = _params(text="ZURICH", text2="HB-EZE", text_mm=6.0)
    parts = poster.compose_parts(track, elev, np.zeros((_mpx(q), _mpx(q)), np.uint8),
                                 bounds, q)
    tm, res = parts["text_mask"], parts["text_res"]
    floor = 0.6 if "keeps" in capsys.readouterr().out else poster.MIN_STROKE_MM
    for label, band in zip(("line 1", "line 2"), _split_lines(tm)):
        stroke = poster._stroke_mm(band, res)
        assert stroke >= floor - 1e-9, f"{label}: {stroke:.2f}mm strokes"
    # ...and the counters survived. A dilation that welds the hole in an R or a B
    # shut turns the bowl into a blob, which is worse than a thin stroke — hence the
    # topology guard. R and the two B counters must still be open.
    assert _counter_mm2(tm, res) > 1.0, "the dilation closed the letter counters"


def _counter_mm2(mask, res):
    """Area of the enclosed background (letter counters), mm2.

    Flood the background in from a corner; whatever background survives is walled in
    by ink. No labelling, so no scipy — the total area is enough of a tripwire."""
    # .copy(): a fromarray() image shares the numpy buffer and floodfill's writes
    # never show up in the array we read back — the fill silently does nothing
    img = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).copy()
    ImageDraw.floodfill(img, (0, 0), 128)
    return int((np.array(img) == 0).sum()) * res ** 2


def test_the_caption_keeps_its_counters_and_dots(monkeypatch):
    """Arial Bold at 7mm caps sets the g's ear, the t's hook and the i-dot under 0.2mm
    from their stems, and its 1.33mm dilation welded all three: (17 blobs, 3 holes) in,
    (17, 6) out on "First Solo Flight". The dilated line must have exactly the raw
    render's topology — no dot welded on, no counter shut, no new hole pinched off."""
    raws = []
    real = poster._dilation_px
    monkeypatch.setattr(poster, "_dilation_px",
                        lambda render, res: raws.append(render(0)) or real(render, res))
    for size in (216.0, 170.0):
        raws.clear()
        p = poster.resolve(poster.Params(size_mm=size, text="First Solo Flight",
                                         text2="11th October 2026"))
        N, _, fpx, chin_px = poster._grid(p)
        tm, _ = poster._text_mask(N + chin_px, N, fpx, chin_px, p)
        for raw, band in zip(raws, _split_lines(tm)):
            assert poster._topology(band) == poster._topology(raw), size


def test_the_stroke_floor_does_not_merge_the_caption_letters():
    """The dilation that clears MIN_STROKE_MM also eats the gaps between the letters:
    it grows every glyph by n fine pixels on all sides, so a gap narrower than 2n
    closes. At 170mm the subtitle takes n=2 and "HB-EZE · 02.08.2026" came out as 7
    blobs where it has 17 letters — thickening strokes for readability while welding
    the words shut. So each line is now TRACKED by 2n as well: the advance between
    two characters grows by exactly what the two facing edges gained, and the
    designed gap survives the dilation intact.

    ">=", not "==": a glyph is allowed to be more than one blob (an accented capital,
    a dotted i at this size). Nothing in a plain sans caption is, so this reads 17/17
    in practice, but the invariant asserted is "no two letters merged", not a count."""
    p = poster.resolve(poster.Params(size_mm=170.0, text="ZURICH → ALTENRHEIN",
                                     text2="HB-EZE · 02.08.2026"))
    N, _, fpx, chin_px = poster._grid(p)
    tm, _ = poster._text_mask(N + chin_px, N, fpx, chin_px, p)
    for s, band in zip((p.text, p.text2), _split_lines(tm)):
        ink = sum(not c.isspace() for c in s)
        blobs = poster._topology(band)[0]
        assert blobs >= ink, f"{s!r}: {blobs} blobs for {ink} letters"


CAPTION_MAX = {"text": 30, "text2": 45}   # characters, advertised in docs/store-listings.md


def test_the_advertised_caption_maxima_print_at_full_size():
    """The shop promises 30 characters on line 1 and 45 on line 2. That is a promise
    about geometry, so it is checkable: past what the ring opening can hold, _fit_line
    shrinks the font to fit, and a shrunk line has thinner strokes than it was designed
    with. At the advertised length every offered size must still render its designed
    cap height and clear MIN_STROKE_MM, or 0.6mm where _dilation_px says it held the
    dilation back to keep a counter open.

    Measured headroom when this shipped: line 1 fits 33-35 characters at full size and
    line 2 fits 52-58, so 30/45 is the safe round number under the tightest of them."""
    long = "ZURICH ALTENRHEIN GENEVA LUGANO SAMEDAN BERN SION MEIRINGEN"
    for size in poster.SIZES_MM:
        for field, n in CAPTION_MAX.items():
            s = long[:n].rstrip()
            assert len(s) >= n - 1
            p = poster.resolve(poster.Params(size_mm=size, **{field: s}))
            N, _, fpx, chin_px = poster._grid(p)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                tm, res = poster._text_mask(N + chin_px, N, fpx, chin_px, p)
            ys = np.where(tm)[0]
            drawn = (ys.max() - ys.min() + 1) * res
            want = p.text_mm * (poster.SUB_RATIO if field == "text2" else 1.0)
            assert drawn > want - 0.25, f"{size}mm {field}: {drawn:.2f}mm caps, want {want:.2f}"
            # the stroke target gives way to an open counter, and says so
            floor = 0.6 if "keeps" in out.getvalue() else poster.MIN_STROKE_MM
            assert poster._stroke_mm(tm, res) >= floor - 1e-9, out.getvalue()


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
    """An airliner would print a 362mm wall: 12000m over 500m terrain runs straight
    off the poster even on the clipped 1000m flight span. Above the relief's own ceiling the wall goes level instead."""
    p, N, fpx, _, _, bounds = _synthetic()                 # bounds of the same track
    M = _mpx(p)
    elev = np.tile(np.linspace(0, 500, M), (M, 1))         # 500m of terrain...
    track = np.array([[47.0, 8.0, 0.0], [47.5, 9.0, 12000.0]])   # ...under a jet
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    assert abs(parts["alt_mm"].max() - 362.12) < 1e-6      # 2.12 + 12000/1000*30, unprintable
    m = poster.strip_mesh(parts["track_px"], parts["alt_mm"], parts["surface"], p)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    top = _strip_tops(m, parts["track_px"])
    ceiling = p.plate_mm + p.relief_mm * p.exaggeration + p.proud_mm      # 33.08mm
    assert abs(top.max() - ceiling) < 1e-9                 # capped, not 362mm
    assert np.abs(top - poster._snap(top, p)).max() < 1e-9
    assert "ceiling" in capsys.readouterr().out            # and it says so, once
    # (a flight below the ceiling is untouched — test_strip_follows_the_flight_
    # altitude_over_flat_terrain tops out at 22.12mm against the same 33.08mm cap)


def test_flat_land_under_a_circuit_is_scaled_to_the_flight():
    """Blackpool: 30m of coast stretched over the whole relief read as hills and put
    the 335m circuit on the strip ceiling as a flat fence. The span is the terrain
    range or the flight's height over the lowest ground clipped to 300..1000m."""
    p = _params()
    M = _mpx(p)
    elev = np.tile(np.linspace(0, 30, M), (M, 1))
    full = p.relief_mm * p.exaggeration

    def parts(alts):
        t = TRACK3.copy()
        t[:, 2] = alts
        return poster.compose_parts(t, elev, np.zeros((M, M), np.uint8),
                                    poster.track_bounds(t, p.margin_pct), p)

    q = parts([0, 335, 0])                                 # span 335m: the flight
    assert abs(q["alt_mm"].max() - (p.plate_mm + full)) < 1e-6
    assert q["surface"].max() < p.plate_mm + 0.12 * full    # flat land stays flat
    q = parts([0, 3000, 0])                                # span clipped to 1000m
    assert abs(q["alt_mm"].max() - (p.plate_mm + 3 * full)) < 1e-6
    q = parts([0, 0, 0])                                   # span clipped up to 300m
    assert abs(q["surface"].max() - poster._snap(p.plate_mm + 30 / 300 * full, p)) < 1e-9


TRACK3 = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])


def _fake_fetches(monkeypatch, water=False, elev_top=500.0, roads=False):
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, elev_top, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_osm_masks",
                        lambda b, px, res: (np.full((px, px), water, bool),
                                            np.zeros((px, px), bool),
                                            np.full((px, px), roads, bool)))


def test_build_poster_v2(monkeypatch):
    _fake_fetches(monkeypatch)
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in frame_bodies] == ["frame"]            # no text asked for
    assert frame_bodies[0][2] == poster.COLORS["frame"] and frame_bodies[0][3] == 1
    assert frame_bodies[0][0].is_watertight and frame_bodies[0][0].volume > 0
    names = [b[1] for b in bodies]
    assert names == ["terrain"]                  # dry, below the snow line -> no caps
    assert bodies[0][2] == poster.COLORS["green"] and bodies[0][3] == 1
    assert bodies[0][0].is_watertight and bodies[0][0].volume > 0
    assert [b[1:] for b in strip] == [("strip", poster.COLORS["strip"], 1)]
    assert strip[0][0].is_watertight and strip[0][0].volume > 0


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


def test_build_poster_rejects_a_frame_taller_than_the_plate():
    """The chin is height the plate has to find, and only check_output.py said so.

    250mm with two caption lines is 249.6 x 260.0mm — 4mm of overhang nobody saw
    until the files were sliced. The refusal names both axes and the size that fits."""
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    p = poster.Params(size_mm=250.0, text="ZURICH", text2="HB-EZE")
    with pytest.raises(ValueError) as e:
        poster.build_poster(track, p)
    msg = str(e.value)
    assert "249.6 x 260.0mm" in msg and "256mm plate" in msg
    assert "one caption line" in msg          # the concrete way out of a two-liner
    mx = float(re.search(r"<=([\d.]+)mm", msg).group(1))
    # the suggestion is the real ceiling: it fits, and one 0.1mm step up does not
    fits = lambda s: max(poster.footprint_mm(poster.resolve(replace(p, size_mm=s))))
    assert fits(mx) <= poster.USABLE_MM < fits(round(mx + 0.1, 1))
    # and a one-line caption at 250mm is still fine (2.4mm of chin, not 10.4)
    assert poster.footprint_mm(poster.resolve(replace(p, text2=""))) == (249.6, 252.0)


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
    # 120 is the smallest size the shop sells; frame_mm/res_mm are pinned coarse so
    # the endpoint test stays fast. Any other size_mm is a 400 (see the test below).
    params = '{"size_mm": 120, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files={"file": ("f.kml", KML.encode())},
                    data={"params": params})
    assert r.status_code == 200
    import base64
    j = r.json()
    assert set(j) == {"frame", "relief", "path", "resolved"}
    assert j["resolved"]["frame_mm"] == 4 and j["resolved"]["text"] == "ZRH-GVA"
    frame, relief, path = (base64.b64decode(j[k]) for k in ("frame", "relief", "path"))
    assert frame[:2] == relief[:2] == path[:2] == b"PK"     # all three are 3MF zips
    assert [b[0] for b in poster.read_3mf(frame)] == ["frame", "text"]
    assert [b[0] for b in poster.read_3mf(relief)] == ["terrain", "water"]
    assert [b[0] for b in poster.read_3mf(path)] == ["strip"]


def test_generate_endpoint_auto_scales_at_the_small_size(monkeypatch):
    """Empty scaled params at the 120mm size: the ring really is the resolved 5.76mm,
    not 12mm, and the response carries the resolved values for the preview's maths."""
    from fastapi.testclient import TestClient
    import app as appmod
    _fake_fetches(monkeypatch)
    r = TestClient(appmod.app).post(
        "/generate", files={"file": ("f.kml", KML.encode())},
        data={"params": '{"size_mm": 120, "res_mm": 0.5}'})
    assert r.status_code == 200
    j = r.json()
    assert j["resolved"]["frame_mm"] == 5.76 and j["resolved"]["relief_mm"] == 9.6
    import base64
    V = poster.read_3mf(base64.b64decode(j["relief"]))[0][1]
    ext = V[:, 0].max() - V[:, 0].min()
    # 120 - 2*(11px ring + 1px ceil'd fit) = 216px, less one grid pixel = 107.5mm.
    # At the old fixed 12mm ring this would be 93.5.
    assert abs(ext - 107.5) < 0.5


def test_generate_only_sells_the_three_offered_sizes():
    """The shop's size list is enforced server-side, not just by the <select>.

    No monkeypatched fetches: the check fires before any network call or meshing."""
    from fastapi.testclient import TestClient
    import app as appmod
    client = TestClient(appmod.app)
    post = lambda params: client.post("/generate", files={"file": ("f.kml", KML.encode())},
                                      data={"params": params})
    r = post('{"size_mm": 250}')      # the old default, over the plate with two lines
    assert r.status_code == 400 and "216, 170, 120mm" in r.json()["detail"]
    assert post('{"size_mm": 200}').status_code == 400
    # A params-less POST falls back to the dataclass default, so that has to be one
    # of the three. An offered size getting all the way through is test_generate_endpoint.
    assert poster.Params.size_mm in poster.SIZES_MM


def test_every_offered_size_fits_the_plate():
    """Why SIZES_MM[0] is 240 and not 245 or 250 — the two rules that pick the sizes.

    1. It prints with every caption it can be ordered with (the two-line chin is what
       overflows). 2. It is a whole number of res_mm pixels, or _grid()'s truncation
       shaves a further part-pixel and the poster comes out under nominal: 245mm is
       612.5px and measures 244.4mm, which check_output.py's +-0.5 rule FAILs."""
    for size in poster.SIZES_MM:
        assert round(size / poster.Params.res_mm, 6).is_integer(), f"{size}mm off-grid"
        for kw in ({}, {"text": "ZURICH → GENEVA"},
                   {"text": "ZURICH → GENEVA", "text2": "HB-EZE · 12.07.2026"}):
            p = poster.resolve(poster.Params(size_mm=size, **kw))
            w, h = poster.footprint_mm(p)
            assert max(w, h) <= poster.USABLE_MM, f"{size}mm {kw}: {w} x {h}mm"
            assert size - w == pytest.approx(p.res_mm), f"{size}mm: width {w}mm"
    assert max(poster.footprint_mm(poster.resolve(poster.Params(
        size_mm=250.0, text="ZURICH", text2="HB-EZE")))) > poster.USABLE_MM


def test_generate_refuses_a_poster_over_the_plate():
    """The whole refusal has to reach the UI: the front end prints `detail` verbatim.

    An offered size can no longer overflow on its own (that is what SIZES_MM buys),
    so the remaining way in is an explicit chin — the guard still has to catch it.
    No monkeypatched DEM/water on purpose — it fires before those network calls."""
    from fastapi.testclient import TestClient
    import app as appmod
    r = TestClient(appmod.app).post(
        "/generate", files={"file": ("f.kml", KML.encode())},
        data={"params": '{"size_mm": 216, "text": "ZURICH", "text2": "HB-EZE",'
                        ' "chin_mm": 20}'})
    assert r.status_code == 502          # same generic handler the other guards use
    detail = r.json()["detail"]
    assert "215.6 x 235.6mm" in detail and "prime tower" in detail and "<=" in detail


def test_dimensions_endpoint():
    """The live UI line: resolve + _grid, no meshing, so it answers instantly."""
    from fastapi.testclient import TestClient
    import app as appmod
    client = TestClient(appmod.app)
    get = lambda **q: client.get("/dimensions", params=q).json()

    over = get(size_mm=250, text="ZURICH", text2="HB-EZE")
    assert (over["width"], over["height"], over["chin_mm"]) == (249.6, 260.0, 10.4)
    assert over["fits"] is False
    assert over["max_size_mm"] < 250     # and it is a size that actually fits
    assert max(poster.footprint_mm(poster.resolve(poster.Params(
        size_mm=over["max_size_mm"], text="ZURICH", text2="HB-EZE")))) <= poster.USABLE_MM

    ok = get(size_mm=170, text="ZURICH", text2="HB-EZE")
    assert (ok["width"], ok["height"], ok["fits"]) == (169.6, 179.2, True)

    bare = get(size_mm=250)              # no caption -> no chin, still square
    assert (bare["width"], bare["height"], bare["chin_mm"]) == (249.6, 249.6, 0.0)
    assert bare["fits"] is False         # ...and 249.6 is still over USABLE_MM: the
    # budget is the plate less the brim and the prime tower, so "fits" means "slices",
    # not "is under 256mm". A caption is no longer what decides it at this size.

    big = get(size_mm=216, text="ZURICH", text2="HB-EZE")   # the largest offered size
    assert (big["width"], big["height"], big["fits"]) == (215.6, 226.0, True)


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


def test_3mf_is_a_finished_orca_project():
    """Each file opens in OrcaSlicer as a finished A1 0.4 project: the whole flattened
    system config (a partial one blanks the start G-code), the plate's overrides, the
    caption's own walls per part, and the bed placement on the build item alone."""
    import zipfile, io as _io, xml.etree.ElementTree as ET
    m = poster.heightmap_mesh(np.full((5, 3), 2.0), 1.0)              # 2 x 4mm, z from 0
    lifted = m.copy()
    lifted.apply_translation([0, 0, poster.SLOT_FLOOR_MM])           # the strip's own floor
    for plate, bodies, walls in (
            ("relief", [(m, "terrain", "#4CAF50", 1)], "2"),
            ("frame", [(m, "frame", "#222222", 1), (m, "text", "#FFFFFF", 2)], "2"),
            ("path", [(lifted, "strip", "#CC2222", 1)], "2")):
        z = zipfile.ZipFile(_io.BytesIO(poster.write_3mf(bodies)))
        cfg = json.loads(z.read("Metadata/project_settings.config"))
        n = len(poster.SLOTS[plate])                     # relief: 3 even with 1 body used
        assert cfg["printer_settings_id"] == poster.PRINTER and cfg["layer_height"] == "0.24"
        assert "machine: A1 =" in cfg["machine_start_gcode"]           # the flatten got there
        assert len(cfg["filament_colour"]) == n == len(cfg["flush_volumes_matrix"]) ** 0.5
        assert len(cfg["filament_type"]) == n                          # filament lists tiled
        assert cfg["wall_loops"] == walls and cfg["prime_tower_width"] == "130"
        assert cfg["wipe_tower_x"] == ["63"] and cfg["wipe_tower_y"] == ["5"]
        assert cfg["top_surface_speed"] == "50"                        # the user's standard
        if plate != "path":   # Draft's 200/230 less 50; the path keeps its own slower walls
            assert (cfg["outer_wall_speed"], cfg["inner_wall_speed"]) == ("150", "180")
        # Orca's GUI keeps only the keys listed as modified: [print, filament 1..n, printer].
        # Missing, a GUI edit + save reverted every override to the bare system preset.
        mod = cfg["different_settings_to_system"]
        assert len(mod) == n + 2 and cfg["inherits_group"] == [""] * (n + 2)
        assert {"prime_tower_width", "wall_generator"} <= set(mod[0].split(";"))
        if plate == "frame":
            assert "nozzle_temperature" in mod[2].split(";")   # the white text, 210 not 220
        model = z.read("3D/3dmodel.model").decode()
        assert "BambuStudio:3mfVersion" in model
        tx, ty, tz = map(float, re.search(r'<item [^>]*transform="1 0 0 0 1 0 0 0 1 '
                                          r'(\S+) (\S+) ([^"]+)"', model).groups())
        w, h = m.extents[:2]
        assert (tx, ty, tz) == (128 - w / 2, 138 - h / 2, -bodies[0][0].bounds[0][2])
        obj = ET.fromstring(z.read("Metadata/model_settings.config")).find("object")
        assert obj.find('metadata[@key="flush_into_objects"]').get("value") == "0"
        if plate == "frame":
            text = {e.get("key"): e.get("value") for e in obj.findall("part")[1]}
            assert text["extruder"] == "2" and text["wall_loops"] == "2"
            assert text["only_one_wall_top"] == "1"   # the caption gets a filled top surface
            assert text["ironing_type"] == "no ironing"
        # placement is the item's alone: the meshes still read back in their local frame
        assert np.allclose(poster.read_3mf(z.fp.getvalue())[0][1], bodies[0][0].vertices,
                           atol=1e-3)


ORCA = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"


@pytest.mark.skipif(not os.path.exists(ORCA), reason="OrcaSlicer not installed")
def test_orca_slices_every_plate(monkeypatch, tmp_path):
    """The real slicer, headless: every project slices with the settings it carries."""
    import subprocess, zipfile
    _fake_fetches(monkeypatch, water=True)
    p = _params(text="HB", text_mm=3.0)
    for plate, bodies in zip(("frame", "relief", "path"), poster.build_poster(TRACK3, p)):
        f, out = tmp_path / f"{plate}.3mf", tmp_path / plate
        f.write_bytes(poster.write_3mf(bodies))
        out.mkdir()
        r = subprocess.run([ORCA, "--debug", "1", "--slice", "0", "--export-3mf", "sliced.3mf",
                            "--outputdir", str(out), str(f)], capture_output=True, timeout=600)
        assert r.returncode == 0, r.stdout[-2000:]
        g = zipfile.ZipFile(out / "sliced.3mf").read("Metadata/plate_1.gcode").decode()
        cfg = dict(re.findall(r"^; (\w+) = (.*)$", g, re.M))
        assert cfg["layer_height"] == "0.24" and cfg["prime_tower_width"] == "130"
        # Orca switches the tower off itself for a one-filament plate (path)
        assert cfg["enable_prime_tower"] == ("1" if len(poster.SLOTS[plate]) > 1 else "0")
        assert cfg["wall_loops"] == poster.PLATES[plate]["wall_loops"]
        assert cfg["filament_colour"] == ";".join(poster.COLORS[k] for k in poster.SLOTS[plate])
        if plate == "frame":   # bead-only caption tops read as hollow outline letters in Orca
            assert "; FEATURE: Top surface" in g.split("; CHANGE_LAYER")[-1]


def _text_body(**kw):
    """The shipped 250mm text case, without paying for a whole build_poster."""
    p = poster.resolve(poster.Params(**{"size_mm": 250.0, "text": "HB-EZE", **kw}))
    M = poster._grid(p)[1]
    track = np.array([[47.0, 8.0, 0.0], [47.5, 9.0, 3000.0]])
    parts = poster.compose_parts(track, np.zeros((M, M), np.float32),
                                 np.zeros((M, M), np.uint8),
                                 poster.track_bounds(track, p.margin_pct), p)
    t = poster.TEXT_EMBOSS_MM
    tm = parts["text_mask"]
    top = np.full(tm.shape, p.base_mm + p.frame_height_mm + t)
    return p, parts, poster.masked_slab_mesh(tm, top, t, parts["text_res"])


def _assert_text_meshes(p, parts, text, min_verts):
    """The meshability bars, shared by the TrueType and the load_default paths."""
    assert text is not None
    assert len(text.vertices) >= min_verts, f"only {len(text.vertices)} verts — still slivers"
    assert text.is_watertight and text.is_winding_consistent and text.volume > 0
    tm, res = parts["text_mask"], parts["text_res"]
    # constant-thickness slab: volume / thickness IS the meshed footprint area
    foot = text.volume / poster.TEXT_EMBOSS_MM
    # Bar is the *glyph* area the dilation exists to protect: erode the mask back and
    # require the mesh to cover all of it, i.e. no lettering was eaten by the cell rule.
    from PIL import ImageFilter
    eroded = Image.fromarray(tm.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))
    glyphs = (np.asarray(eroded) > 0).sum() * res ** 2
    assert foot >= glyphs, f"meshed {foot:.1f}mm2 of {glyphs:.1f}mm2 of glyphs"
    # ...and most of the dilated mask. Its outer 1px rim is where the loss sits (a cell
    # wants four corners), concentrated at tight joints and counters — 75% is a
    # no-big-chunk-missing tripwire, not the real invariant above.
    assert foot >= 0.75 * tm.sum() * res ** 2
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
    _assert_text_meshes(p, parts, text, 20000)


def test_frame_text_meshes_without_a_truetype_font(monkeypatch):
    """The load_default fallback is the path every box without one of FONT_PATHS
    takes, so it has to clear the same bars — it is the dilation, not the face,
    that satisfies the cell rule."""
    monkeypatch.setattr(poster, "FONT_PATHS", (("/nonexistent/no-such-font.ttf", 0),))
    p, parts, text = _text_body()
    _assert_text_meshes(p, parts, text, 20000)


def test_text_is_meshed_on_its_own_fine_grid():
    """The readability fix. On the terrain's 0.4mm grid an 8mm glyph is ~20px tall
    and every curve stair-steps by 0.4mm, then a 1px dilation blurs it further.
    The text body has its own grid: TEXT_SUB times finer, so an edge steps by 0.1mm
    and the dilation costs 0.1mm — at the cost of nothing but vertices."""
    p, parts, text = _text_body()
    N, _, fpx, chin_px = poster._grid(p)
    S = poster.TEXT_SUB
    assert parts["text_res"] == p.res_mm / S
    assert parts["text_mask"].shape == ((N + chin_px - 1) * S + 1, (N - 1) * S + 1)
    # glyph edges land on the fine pitch, not the frame's
    xs = np.unique(text.vertices[:, 0].round(6))
    assert abs(np.diff(xs).min() - parts["text_res"]) < 1e-6
    # ...and the same glyphs on the coarse grid are an order of magnitude cruder
    coarse = poster.masked_slab_mesh(
        parts["text_mask"][::S, ::S],                      # exactly the frame's own rows
        np.full((N + chin_px, N), p.base_mm + p.frame_height_mm + poster.TEXT_EMBOSS_MM),
        poster.TEXT_EMBOSS_MM, p.res_mm)
    assert len(text.vertices) > 4 * len(coarse.vertices)


def test_the_text_grid_is_registered_to_the_frame_grid():
    """The fine mask must span the frame's EXACT extent, or the caption prints offset.

    Regression: heightmap_mesh and _slab_mesh both map row -> (rows-1-row)*res, and
    that -1 is a vertex count — it does not scale with TEXT_SUB. An (H*TEXT_SUB,
    N*TEXT_SUB) mask therefore sat (1 - 1/TEXT_SUB)*res_mm = 0.3mm north of the frame
    at defaults, on every row, and the error grows with res_mm. Nothing caught it
    because every other geometric test measures inside ONE grid; this one is the only
    test that puts the two meshes side by side."""
    p, parts, text = _text_body()
    frame = poster.heightmap_mesh(parts["frame"], p.res_mm)
    tm, tres = parts["text_mask"], parts["text_res"]
    # two corner cells are enough to pin all four edges of the fine grid's extent
    probe = np.zeros(tm.shape, bool)
    probe[:2, :2] = probe[-2:, -2:] = True
    m = poster.masked_slab_mesh(probe, np.full(tm.shape, 1.0), 0.5, tres)
    assert np.allclose(m.bounds[:, :2], frame.bounds[:, :2], atol=1e-9), \
        f"text grid {m.bounds[:, :2].tolist()} vs frame {frame.bounds[:, :2].tolist()}"
    # ...and the real glyphs land inside the caption bar, measured by heightmap_mesh's
    # own row -> y mapping. Exact, not check_output's +-0.5mm, which absorbed the bug.
    N, _, fpx, chin_px = poster._grid(p)
    bar_top_y = (fpx + chin_px - 1) * p.res_mm             # frame row N-fpx
    assert text.bounds[0][1] >= -1e-9
    assert text.bounds[1][1] <= bar_top_y + 1e-9
    assert text.bounds[1][1] > bar_top_y - p.frame_mm      # and really is on the bar


def test_frame_text_shrinks_to_fit_the_bar():
    """TrueType glyphs run ~40% wider than the old bitmap, so a long string has to
    shrink to fit the ring's bottom bar instead of silently clipping off the edge."""
    long_text = "ZURICH KLOTEN TO GENEVA COINTRIN VIA THE ALPS"
    p, parts, text = _text_body(text=long_text)
    N, _, fpx, chin_px = poster._grid(p)
    S = poster.TEXT_SUB
    tm = parts["text_mask"]
    cols, rows = np.where(tm.any(0))[0], np.where(tm.any(1))[0]
    assert fpx * S <= cols.min() and cols.max() < (N - fpx) * S   # off the corners
    assert (N - fpx) * S <= rows.min() and rows.max() <= (N + chin_px - 1) * S  # on the bar
    _assert_text_meshes(p, parts, text, 20000)








@pytest.mark.parametrize("text,text2", [("HB-EZE", ""), ("", ""),
                                        ("", "HB-EZE"), ("ZURICH", "HB-EZE")])
def test_check_output_passes_on_freshly_built_files(monkeypatch, tmp_path, text, text2):
    """The shipped checker agrees with the shipped builder, whichever caption lines
    were asked for. text2 alone is a valid caption and builds a body — the checker's
    present-iff rule read `p.text` only and FAILed a perfectly good poster."""
    import check_output
    _fake_fetches(monkeypatch, water=True)
    p = _params(text=text, text2=text2, text_mm=3.0)
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, p)
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.3mf").write_bytes(poster.write_3mf(strip))
    params = json.dumps(asdict(p))   # the checker is handed exactly what was built
    assert check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                              str(tmp_path / "path.3mf"), "--params", params]) == 0


def test_check_output_passes_on_a_relief_with_a_grey_band(monkeypatch, tmp_path):
    """The all-water case above never builds a grey body, so the band's own rules
    (flat bottom on one plane, top under the relief ceiling) go unchecked there."""
    import check_output
    _fake_fetches(monkeypatch, elev_top=4000.0)              # dry ramp through 2000m
    p = _params()
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, p)
    assert [b[1] for b in bodies] == ["terrain", "snow"]
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.3mf").write_bytes(poster.write_3mf(strip))
    assert check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                              str(tmp_path / "path.3mf"),
                              "--params", json.dumps(asdict(p))]) == 0


def test_check_output_flags_a_missing_text_body(monkeypatch, tmp_path, capsys):
    """Text asked for but no white body in the frame 3MF is a real failure now,
    not a hint — the body is recoverable from the mesh, unlike the old emboss."""
    import check_output
    _fake_fetches(monkeypatch)
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, _params())   # no text
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.3mf").write_bytes(poster.write_3mf(strip))
    rc = check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                            str(tmp_path / "path.3mf"),
                            "--params", json.dumps(asdict(_params(text="HB-EZE")))])
    assert rc == 1 and "text body" in capsys.readouterr().out


def test_check_output_flags_a_chin_that_overflows_the_plate(monkeypatch, tmp_path, capsys):
    """size_mm still means the poster's *width*; the chin is extra height outside it,
    so a big poster plus a caption can now run off the 256mm plate in y alone. The
    footprint rule is per axis for exactly that reason."""
    import check_output
    _fake_fetches(monkeypatch)
    p = _params(text="HB", text_mm=3.0, chin_mm=250.0)     # 40mm wide, 290mm tall
    # build_poster refuses this frame now — that IS the guard, and it is tested by
    # test_build_poster_rejects_a_frame_taller_than_the_plate. Lift the ceiling for
    # the generation step only: check_output binds PLATE_MM at import, so the checker
    # below still measures the exported mesh against the real 256mm plate.
    monkeypatch.setattr(poster, "USABLE_MM", 1e6)
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, p)
    (tmp_path / "frame.3mf").write_bytes(poster.write_3mf(frame_bodies))
    (tmp_path / "relief.3mf").write_bytes(poster.write_3mf(bodies))
    (tmp_path / "path.3mf").write_bytes(poster.write_3mf(strip))
    rc = check_output.main([str(tmp_path / "frame.3mf"), str(tmp_path / "relief.3mf"),
                            str(tmp_path / "path.3mf"), "--params", json.dumps(asdict(p))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL  frame y footprint" in out       # 290mm > the 256mm plate
    assert "PASS  frame x footprint" in out       # width is still exactly size_mm


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


def test_fetch_osm_masks_uses_the_mirror_when_the_first_fails(monkeypatch, capsys):
    calls = []

    def fake_get(url, timeout=20, tries=2):
        calls.append((url, timeout, tries))
        if len(calls) == 1:
            raise RuntimeError("overpass busy")
        return b'{"elements": []}'

    monkeypatch.setattr(poster, "_get", fake_get)
    m = poster.fetch_osm_masks(B, 16, 0.4)[0]
    assert m.shape == (16, 16) and not m.any()
    assert len(calls) == 2
    assert calls[0][0].startswith(poster.OVERPASS_URLS[0])
    assert calls[1][0].startswith(poster.OVERPASS_URLS[1])
    assert calls[0][1:] == (150, 1)       # Overpass is slow, not 20s; next mirror, not a retry
    assert "natural" in calls[0][0] and "8.1" in calls[0][0]  # query + bbox in the URL
    assert "mirror" in capsys.readouterr().out.lower()


def test_fetch_osm_masks_rejects_a_partial_overpass_response(monkeypatch, capsys):
    """A query that hits [timeout:] answers 200 with what it had so far and a remark.
    That half-answer must never be drawn: the next mirror's full one is."""
    a = _way(_ring(47.02, 8.02, 47.04, 8.04), tags={"natural": "water"})
    b = _way(_ring(47.06, 8.06, 47.08, 8.08), tags={"natural": "water"})
    answers = [{"elements": [a], "remark": 'runtime error: Query timed out in "query" '
                                          'at line 1 after 120 seconds.'},
               {"elements": [a, b]}]
    calls = []
    monkeypatch.setattr(poster, "_get", lambda url, **k: calls.append(url)
                        or json.dumps(answers[len(calls) - 1]).encode())
    water = poster.fetch_osm_masks(B, 100, 0.4)[0]
    assert water[_rc(B, 47.03, 8.03, 100)] and water[_rc(B, 47.07, 8.07, 100)]
    assert len(calls) == 2
    assert "partial" in capsys.readouterr().out


def test_overpass_responses_are_cached_per_query(monkeypatch):
    """Same order, same poster: a regeneration must not re-ask a public mirror that
    may answer differently this minute. A failure is not cached — the next call retries."""
    calls = []
    monkeypatch.setattr(poster, "_get", lambda url, **k: calls.append(url) or b'{"elements": []}')
    poster.fetch_osm_masks(B, 16, 0.4)
    poster.fetch_osm_masks(B, 16, 0.4)
    assert len(calls) == 1
    poster.fetch_osm_masks(_wbounds(47.0, 8.0, 47.2, 8.2), 16, 0.4)
    assert len(calls) == 2

    poster._overpass.cache_clear()
    down = [True]

    def flaky(url, **k):
        if down[0]:
            raise RuntimeError("all down")
        return b'{"elements": []}'

    monkeypatch.setattr(poster, "_get", flaky)
    with pytest.raises(RuntimeError, match="Overpass"):
        poster.fetch_osm_masks(B, 16, 0.4)
    down[0] = False
    assert not poster.fetch_osm_masks(B, 16, 0.4)[0].any()


def test_fetch_osm_masks_skips_transoceanic_spans(monkeypatch, capsys):
    monkeypatch.setattr(poster, "_get",
                        lambda *a, **k: pytest.fail("must not query Overpass"))
    m = poster.fetch_osm_masks(_wbounds(40.0, -70.0, 50.0, 10.0), 32, 0.4)[0]
    assert m.shape == (32, 32) and not m.any()
    assert "water" in capsys.readouterr().out.lower()


def test_sea_is_the_right_hand_side_of_the_coastline_and_prints_flat(monkeypatch):
    """OSM keeps land on the coastline's LEFT: a northbound coast has the sea east.
    And terrarium's seabed (Blackpool: -7.85m) is flattened to 0 before smoothing."""
    m = poster._sea_mask([_way([(47.0, 8.05), (47.1, 8.05)])], B, 100)
    assert m[_rc(B, 47.05, 8.08, 100)] and not m[_rc(B, 47.05, 8.02, 100)]
    assert 0.4 < m.mean() < 0.6
    m = poster._sea_mask([_way([(47.1, 8.05), (47.0, 8.05)])], B, 100)   # reversed
    assert not m[_rc(B, 47.05, 8.08, 100)] and m[_rc(B, 47.05, 8.02, 100)]

    def elev(b, px):   # land ramp 0..30m west, a sloping seabed -8..-1m east
        e = np.tile(np.linspace(0, 30, px), (px, 1))
        e[:, px // 2:] = np.linspace(-8, -1, px - px // 2)
        return e

    east = lambda px: np.tile(np.arange(px) >= px // 2, (px, 1))
    zeros = lambda px: np.zeros((px, px), bool)
    monkeypatch.setattr(poster, "fetch_elevation", elev)
    monkeypatch.setattr(poster, "fetch_osm_masks", lambda b, px, res: (zeros(px), east(px), zeros(px)))
    seen, real = {}, poster.compose_parts
    monkeypatch.setattr(poster, "compose_parts", lambda *a: seen.setdefault("p", real(*a)))
    t = TRACK3.copy()
    t[:, 2] = [0, 100, 200]                    # low hop: 300m span, so 7m of seabed is ~6 layers
    p = _params()
    _, bodies, _ = poster.build_poster(t, p)
    assert [b[1] for b in bodies] == ["terrain", "water"]
    q = seen["p"]
    M = q["surface"].shape[0]
    sea = q["water"].copy()
    sea[:, :M // 2 + 2] = False                # past the shore column the blur blends
    assert sea.any() and np.ptp(q["surface"][sea]) == 0      # one level...
    assert abs(q["surface"][sea][0] - p.plate_mm) < 1e-9     # ...at 0m, the lowest land


def test_fetch_osm_masks_draws_roads_and_runways_by_scale(monkeypatch, capsys):
    """Grey is runways plus the road classes the zoom can hold. B at 100 px is ~189 m
    per printed mm at res 0.4, so primary and up; tertiary is not even asked for.
    A closed coastline way is still an island, never a lake."""
    assert "landuse" not in poster.OVERPASS_QL and "coastline" in poster.OVERPASS_QL
    hw = lambda c, **t: {"highway": c, **t}
    coast = {"natural": "coastline"}
    els = [_way([(47.02, 8.02), (47.08, 8.08)], tags=hw("primary")),
           _way([(47.02, 8.08), (47.08, 8.02)], tags=hw("tertiary")),
           _way([(47.01, 8.05), (47.09, 8.05)], tags=hw("motorway", tunnel="yes")),
           _way([(47.05, 8.02), (47.05, 8.08)], tags={"aeroway": "runway", "width": "45"}),
           _way([(47.0, 8.06), (47.1, 8.06)], tags=coast),            # sea east of 8.06
           _way(_ring(47.03, 8.075, 47.045, 8.09), tags=coast),       # CCW: an island
           _way(_ring(47.085, 8.005, 47.098, 8.02), tags={"natural": "water"})]
    seen = []
    monkeypatch.setattr(poster, "_get", lambda url, **k: seen.append(url)
                        or json.dumps({"elements": els}).encode())
    water, sea, roads = poster.fetch_osm_masks(B, 100, 0.4)
    assert "primary" in seen[0] and "tertiary" not in seen[0]
    at = lambda m, la, lo: m[_rc(B, la, lo, 100)]
    assert at(roads, 47.03, 8.03) and at(roads, 47.05, 8.03)       # primary, runway
    assert at(roads, 47.05, 8.05)                                   # where they cross
    assert not at(roads, 47.03, 8.07)                               # tertiary: out of band
    assert not at(roads, 47.07, 8.05)                               # tunnel: underground
    r, c = _rc(B, 47.05, 8.025, 100)
    assert roads[r - 3:r + 4, c].sum() >= 3                         # runway is 3+ px wide
    assert at(water, 47.09, 8.012) and at(sea, 47.07, 8.08)
    assert not at(water, 47.0375, 8.0825) and not at(sea, 47.0375, 8.0825)   # island: land
    assert 0 < roads.mean() < poster.ROAD_MAX_FRAC

    # a dense grid of one class would grey the plate: that class goes, with a note
    els = [_way([(47.005 + 0.0015 * i, 8.0), (47.005 + 0.0015 * i, 8.1)], tags=hw("primary"))
           for i in range(60)]
    poster._overpass.cache_clear()                                  # same bbox, new answer
    roads = poster.fetch_osm_masks(B, 100, 0.4)[2]
    assert roads.mean() <= poster.ROAD_MAX_FRAC
    assert "dropped" in capsys.readouterr().out


def test_caps_follow_the_slot(monkeypatch, tmp_path):
    """Water/road caps drape into the groove: the slot is blue over the sea, not a
    green rim, and the strip still seats on the one flat SLOT_FLOOR_MM."""
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    lc = np.ones((M, M), np.uint8)
    parts = poster.compose_parts(track, elev, lc, bounds, p)
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert (parts["cap_top"][gmask] == poster.SLOT_FLOOR_MM).all()
    under = gmask & poster._cell_verts(parts["water_cells"])
    assert under.any()
    assert np.allclose(parts["green"][under], poster.SLOT_FLOOR_MM - poster.SLOT_CAP_MM)
    z = poster.SLOT_FLOOR_MM - poster.SLOT_CAP_MM
    assert abs(z - poster._snap(z, p)) < 1e-9                       # 0.68: on the grid

    import check_output
    _fake_fetches(monkeypatch, water=True)
    p = _params()
    frame_bodies, bodies, strip = poster.build_poster(TRACK3, p)
    assert [b[1] for b in bodies] == ["terrain", "water"]
    w = bodies[1][0]
    assert w.is_watertight and w.is_winding_consistent
    assert abs(w.bounds[0][2] - z) < 1e-9
    assert (np.abs(w.vertices[:, 2] - poster.SLOT_FLOOR_MM) < 1e-9).any()
    path = poster.write_3mf(strip)
    assert abs(poster.read_3mf(path)[0][1][:, 2].min() - poster.SLOT_FLOOR_MM) < 1e-4
    for name, data in (("frame.3mf", poster.write_3mf(frame_bodies)),
                       ("relief.3mf", poster.write_3mf(bodies)), ("path.3mf", path)):
        (tmp_path / name).write_bytes(data)
    assert check_output.main([str(tmp_path / n) for n in ("frame.3mf", "relief.3mf", "path.3mf")]
                             + ["--params", json.dumps(asdict(p))]) == 0

    # roads are the same cap, grey, in the snow band's slot
    _fake_fetches(monkeypatch, roads=True)
    _, bodies, _ = poster.build_poster(TRACK3, p)
    assert [b[1] for b in bodies] == ["terrain", "roads"]
    assert bodies[1][2] == poster.COLORS["snow"] and bodies[1][3] == 3
    assert bodies[1][0].is_watertight and bodies[1][0].is_winding_consistent


def test_build_poster_fails_loudly_when_overpass_is_down(monkeypatch):
    """A poster without its coast keeps the seabed in the DEM: different relief from
    the same order. Overpass down is an error (app.py: 502), never a water-less poster."""
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, 500, px), (px, 1)))

    def boom(url, timeout=20, tries=2):
        raise RuntimeError("overpass down")

    monkeypatch.setattr(poster, "_get", boom)
    with pytest.raises(RuntimeError, match="Overpass"):
        poster.build_poster(TRACK3, _params())


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
    assert "ActivityPathPoster" in seen["headers"]["User-Agent"]


@pytest.mark.skipif(not os.environ.get("LIVE"), reason="hits the live Overpass API")
def test_live_lake_zug_water_mask():
    m = poster.fetch_osm_masks(_wbounds(47.08, 8.42, 47.20, 8.55), 256, 0.4)[0]
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


def test_a_small_peak_above_the_snow_line_is_a_solid_grey_body(monkeypatch):
    """The old opening dropped small peaks from the grey mask but not from the terrain,
    so they stayed green and rose above the z_snow plane. As a band a small peak is a
    solid volume that prints fine, so the mask is the bare threshold — the only thing
    still filtered is what the DEM blur and cell-based meshing remove anyway."""
    def elev(b, px):
        e = np.full((px, px), 500.0)
        e[8:13, 8:13] = 3000.0          # a 5px peak, clear of the groove and the border
        e[4, 4] = 3000.0                # a single spiky DEM pixel
        return e

    monkeypatch.setattr(poster, "fetch_elevation", elev)
    monkeypatch.setattr(poster, "fetch_osm_masks",
                        lambda b, px, res: tuple(np.zeros((px, px), bool) for _ in range(3)))
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain", "snow"]   # the peak survives...
    m = bodies[1][0]
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0   # ...as a solid
    # ...and the 1px spike is still gone: smooth_px averages it below the snow line, so
    # the body is one blob over the peak. With the spike it would span >= 4mm in both x
    # and y (the spike sits 4 cells away on each axis).
    assert (m.bounds[1] - m.bounds[0])[:2].max() < 3.0


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
    """The printer lays a 0.2mm first layer and 0.24mm ones after it, so a printable
    height is 0.2 + n*0.24 — not n*0.24, which is what round(z/layer) gave."""
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


def test_green_never_towers_above_the_snow_plane():
    """The key invariant the bare snow-line threshold buys. The old opening eroded the
    grey mask but not the terrain, so peaks it dropped stayed green and rose the full
    relief above z_snow — green and grey then shared layers. With the bare threshold the
    only green left above the plane is the unavoidable one-cell rim around each grey
    region: a rim vertex is a corner of a cell that has another corner at or below the
    plane, so it can exceed the plane by at most one cell's terrain rise.

    The claim covers the whole plate *including its outer vertex ring*. The ramp climbs
    straight off the east edge well above the snow line, which is exactly the case that
    used to break it: the ring is excluded from the water cap (a thin conformal slab
    there would hang off the plate edge) and the band used to be excluded with it, so the
    plate's own skirt wall stayed green all the way up to the terrain. A band is a solid
    resting on the green below it, so it is exempt and reaches the edge.

    Only the slot is excluded — green there is the slot floor, not terrain."""
    p, M, elev, parts = _banded()
    s, z_snow = parts["surface"], parts["z_snow"]
    rise = max(np.abs(np.diff(s, axis=0)).max(), np.abs(np.diff(s, axis=1)).max())
    plate = ~poster._groove_mask(parts["track_px"], (M, M), p)
    assert s.max() > 15 * rise + z_snow                    # the ground really does tower
    assert s[:, -1].min() > z_snow                         # ...and off the plate edge
    assert parts["snow_cells"][:, -1].any()                # so the band reaches that edge
    assert parts["green"][plate].max() <= z_snow + rise + 1e-9

    # ...and that bound is a rim, not a coincidence: every green vertex above the plane
    # touches one at or below it. No green survives *inside* a grey region.
    above = plate & (parts["green"] > z_snow + 1e-9)
    low = np.zeros((M, M), bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            low |= np.roll(np.roll(s <= z_snow + 1e-9, dr, 0), dc, 1)
    assert above.any() and not (above & ~low).any()


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
