import contextlib
import io
import json
import math
import os
import re
import urllib.parse
import warnings
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
    # assign_lanes' clear_px is at least LANE_CLEAR_FRAC of the pitch: that floor must still
    # be outside the cut's analytic reach, W plus the dilation's diagonal sqrt(2) * dil fine pixels
    for p in [_params(res_mm=res) for res in (0.5, 0.4, 0.25)] + [
            poster.resolve(poster.Params(size_mm=s)) for s in poster.SIZES_MM]:
        res_f, W, dil, lane = poster._wall_dims(p)
        assert poster.LANE_CLEAR_FRAC * lane > W + math.sqrt(2) * dil * res_f


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


def test_a_lane_clears_where_the_earlier_walls_moved_to():
    # wall 2 is 1 px from wall 1's input line, and wall 1 moved to lane 1: wall 2 takes lane 2
    out = poster.assign_lanes([[_line(10, 90, y, 120)] for y in (50.0, 50.5, 49.5)], lane_px=4, r_px=4, ramp=4)
    assert np.allclose(out[2][0][0][:, 1], 58.0)


@pytest.mark.parametrize("dims", ["4/4/4", "216"])
def test_two_later_walls_either_side_of_an_earlier_one_take_two_lanes(dims):
    # The earliest wall lies between two later ones, each within r of it but more than r
    # from each other. Counted against the earlier walls' INPUT lines both took lane 1,
    # on the same target, and the crossing cut then deleted the bike whole.
    p = poster.resolve(poster.Params(size_mm=216))
    L = poster._wall_dims(p)[3] / p.res_mm if dims == "216" else 4.0
    ramp = math.ceil(2 * L) if dims == "216" else 4
    walls = [[_line(20, 200, y, 150)] for y in (100.0, 100 - 0.9 * L, 100 + 0.9 * L)]
    out = poster.assign_lanes(walls, lane_px=L, r_px=L, ramp=ramp)
    for w, want in zip(out, (100, 100 + L, 100 + 2 * L)):
        assert np.allclose(w[0][0][ramp:-ramp, 1], want)
    assert all(len(list(poster._components(m))) >= 1 for m in poster.wall_masks(out, _mpx(p), p))


def test_a_lane_clears_where_its_ref_wall_moved_to():
    # wall 2 is within r of wall 1's input only, so wall 1 is its ref, and wall 1 moved to
    # 54: lane 1 off wall 1's input (54.5) would sit on it, so wall 2 takes lane 2
    out = poster.assign_lanes([[_line(10, 90, y, 120)] for y in (50.0, 50.5, 54.3)], lane_px=4, r_px=4, ramp=4)
    assert np.allclose(out[1][0][0][:, 1], 54.0) and np.allclose(out[2][0][0][:, 1], 58.5)


def test_the_lane_move_is_eased_per_piece():
    # r_px > lane_px, so the stations eased in sit outside the lane and are not pushed
    b = [_cat(_line(10, 50, 50.5, 160), _vline(50, 51, 70, 160)), _line(60, 90, 57.0, 160)]
    [_, [(P0, _), (P1, _)]] = poster.assign_lanes([[_line(10, 90, 50.0, 120)], b], lane_px=4, r_px=8, ramp=4)
    assert P0[b[0][0][:, 1] == 57, 1] == pytest.approx([56.25])   # 1/4 of the way at the edge
    assert np.allclose(P1[:, 1], 54.0)          # a piece that starts on the road is not eased


def _dims216():
    """(p, L, ramp) as build_poster passes them at 216mm: L = lane_mm / res_mm."""
    p = poster.resolve(poster.Params(size_mm=216))
    L = poster._wall_dims(p)[3] / p.res_mm
    return p, L, math.ceil(2 * L)


def _jitter(x0, x1, y, j, rng):
    """_line with uniform(-j, j) px of GPS jitter on every station's y."""
    P, h = _line(x0, x1, y, 150)
    P[:, 1] += rng.uniform(-j, j, len(P))
    return P, h


def _lane_changes(P, y0, L):
    """(rounded lane per station, how often it changes) of stations laned off the road y0."""
    k = np.round(abs(P[:, 1] - y0) / L)
    return k, np.count_nonzero(np.diff(k))


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_jittering_neighbour_two_lanes_off_never_flaps_the_lane(seed):
    # wall 1 runs about two lanes off wall 0's road with GPS jitter. Lane 1 used to clear
    # it only where it sat at >= 2L, so wall 2 flipped 1 <-> 3 and every flip drew a
    # segment straight across wall 1, which the crossing cut then deleted.
    p, L, ramp = _dims216()
    rng = np.random.default_rng(seed)
    w0, w2 = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    w1 = _jitter(50, 170, 100 + 2.0 * L, 0.1, rng)
    out = poster.assign_lanes([[w0], [w1], [w2]], L, L, ramp)
    P = out[2][0][0]
    k, changes = _lane_changes(P[_dist_to(w2[0], [w0]) < L], 100, L)
    assert changes == 0 and k[0] == 1
    assert np.hypot(*np.diff(P, axis=0).T).max() <= 1.5 * L
    M = _mpx(p)
    solo = poster.wall_masks(poster.assign_lanes([[w0], [w1]], L, L, ramp), M, p)[1]
    m1 = poster.wall_masks(out, M, p)[1]
    assert len(list(poster._components(m1))) == 1 and m1.sum() >= 0.99 * solo.sum()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_jittery_swim_beside_a_shared_road_is_not_cut(seed):
    # a triathlon: the run shares the bike's road and takes lane 1 off it, toward the
    # swim, which lies about two lanes off the road with +-0.5 px of jitter
    p, L, ramp = _dims216()
    rng = np.random.default_rng(seed)
    swim = _jitter(10, 180, 100 + 2.0 * L, 0.5, rng)
    bike, run = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    out = poster.assign_lanes([[swim], [bike], [run]], L, L, ramp)
    P = out[2][0][0]
    _, changes = _lane_changes(P[_dist_to(run[0], [bike]) < L], 100, L)
    assert changes == 0
    assert np.hypot(*np.diff(P, axis=0).T).max() <= 1.5 * L
    M = _mpx(p)
    solo = poster.wall_masks(poster.assign_lanes([[swim], [bike]], L, L, ramp), M, p)[0]
    m0 = poster.wall_masks(out, M, p)[0]
    assert len(list(poster._components(m0))) == 1 and m0.sum() >= 0.99 * solo.sum()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_neighbour_jittering_across_the_clear_line_is_held_off_not_flapped(seed):
    # wall 1 at 1.9L +-0.5 px: lane 1 clears it at some stations and not at the next, so
    # only a steady lane choice keeps wall 2 off it (343dee3's hold; now a move up to
    # lane 3 before the neighbour starts)
    p, L, ramp = _dims216()
    rng = np.random.default_rng(seed)
    w0, w2 = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    w1 = _jitter(50, 170, 100 + 1.9 * L, 0.5, rng)
    out = poster.assign_lanes([[w0], [w1], [w2]], L, L, ramp)
    assert _lane_changes(out[2][0][0], 100, L)[1] <= 4    # at most up and down once each
    M = _mpx(p)
    solo = poster.wall_masks(poster.assign_lanes([[w0], [w1]], L, L, ramp), M, p)[1]
    m1 = poster.wall_masks(out, M, p)[1]
    assert len(list(poster._components(m1))) == 1 and m1.sum() >= 0.99 * solo.sum()


def test_a_lane_change_that_is_really_needed_happens_once_up_and_once_down_eased():
    # wall 1 blocks lane 1 for x 80..120, just outside r of wall 0 so it is not laned
    # itself: wall 2 must go round it in lane 2, once up and once down, eased
    p, L, ramp = _dims216()
    w0, w2 = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    w1 = _line(80, 120, 100 + 1.05 * L, 150)
    out = poster.assign_lanes([[w0], [w1], [w2]], L, L, ramp)
    assert np.array_equal(out[1][0][0], w1[0])
    P, x = out[2][0][0], w2[0][:, 0]
    k, changes = _lane_changes(P, 100, L)
    alongside = (x >= 80) & (x <= 120)
    assert (k[abs(x - 100) > 20 + 3 * ramp] == 1).all() and (k[alongside] == 2).all()
    assert changes == 2
    assert np.hypot(*np.diff(P, axis=0).T).max() <= 1.5 * L
    assert abs(np.diff(P[:, 1])).max() < 0.75 * L    # eased: never a one-lane jump
    assert _dist_to(P[alongside], out[1]).min() >= 0.9 * L
    assert len(list(poster._components(poster.wall_masks(out, _mpx(p), p)[1]))) == 1


def _drift(x0, x1, y, amp, lam):
    """_line at y plus a slow sinusoidal GPS drift of amp px, wavelength lam px."""
    P, h = _line(x0, x1, y, 150)
    P[:, 1] += amp * np.sin(2 * np.pi * P[:, 0] / lam)
    return P, h


def _assert_steady_beside_and_neighbour_whole(walls, nb, x0, x1):
    """At 216 dims: wall 2's rounded lane changes at most once over x0..x1 (the neighbour's
    stretch), and wall nb is one piece with >= 99% of its pixels without wall 2."""
    p, L, ramp = _dims216()
    out = poster.assign_lanes(walls, L, L, ramp)
    x = walls[2][0][0][:, 0]
    assert _lane_changes(out[2][0][0][(x >= x0) & (x <= x1)], 100, L)[1] <= 1
    M = _mpx(p)
    solo = poster.wall_masks(poster.assign_lanes(walls[:2], L, L, ramp), M, p)[nb]
    m = poster.wall_masks(out, M, p)[nb]
    assert len(list(poster._components(m))) == 1 and m.sum() >= 0.99 * solo.sum()


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("y, j", [(1.97, 0.5), (1.98, 0.5), (1.99, 0.5), (1.95, 0.3)])
def test_a_neighbour_jittering_just_past_the_clear_line_keeps_the_lane_steady(y, j, seed):
    # lane 1 clears the neighbour at one station and not the next, in gaps longer than
    # any fixed hold: the fewest-changes path keeps one lane past the whole neighbour
    _, L, _ = _dims216()
    w0, w2 = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    w1 = _jitter(50, 170, 100 + y * L, j, np.random.default_rng(seed))
    _assert_steady_beside_and_neighbour_whole([[w0], [w1], [w2]], 1, 50, 170)


@pytest.mark.parametrize("layout", ["neighbour", "triathlon"])
def test_a_neighbour_drifting_slowly_across_the_clear_line_keeps_the_lane_steady(layout):
    # +-0.2 px of drift around 1.92 L, wavelength 80 px: 3840a94 held lane 3, a +-ramp
    # hold flipped every half wave
    _, L, _ = _dims216()
    road, run = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    if layout == "neighbour":
        _assert_steady_beside_and_neighbour_whole(
            [[road], [_drift(50, 170, 100 + 1.92 * L, 0.2, 80)], [run]], 1, 50, 170)
    else:   # the swim drifts beside the bike's road, which the run shares
        _assert_steady_beside_and_neighbour_whole(
            [[_drift(10, 180, 100 + 1.92 * L, 0.2, 80)], [road], [run]], 0, 10, 180)


@pytest.mark.parametrize("gap", [8, 10, 12])
def test_going_round_a_blocker_never_eases_through_the_piece_before_it(gap):
    # wall 1: piece A two lanes off beside lane 1 (x 55..72), then piece B, a blocker in
    # lane 1, from gap px after A ends: a hold that eased wall 2 up early ran through A
    p, L, ramp = _dims216()
    w0, w2 = _line(10, 180, 100.0, 150), _line(10, 180, 100 + 0.3 * L, 150)
    w1 = [_line(55, 72, 100 + 2.05 * L, 150), _line(72 + gap, 120, 100 + 1.05 * L, 150)]
    out = poster.assign_lanes([[w0], w1, [w2]], L, L, ramp)
    M = _mpx(p)
    solo = poster.wall_masks(poster.assign_lanes([[w0], w1], L, L, ramp), M, p)[1]
    m1 = poster.wall_masks(out, M, p)[1]
    for c in poster._components(solo):
        assert (m1 & c).sum() >= 0.99 * c.sum()


@pytest.mark.parametrize("size, groove", [(216, None), (120, None), (216, 2.5)])
def test_a_later_wall_clear_px_away_cuts_no_meshed_cell_of_the_earlier(size, groove):
    # clear_px is where assign_lanes stops pricing a lane's closeness; the raster crossing
    # cut must not reach that far at any heading or sub-pixel phase, override or not
    p = poster.resolve(poster.Params(size_mm=size, **({"groove_w_mm": groove} if groove else {})))
    res_f, W, dil, lane = poster._wall_dims(p)
    cut, gap = poster.lane_dists(lane / p.res_mm, dil)
    assert cut == pytest.approx((W + math.sqrt(2) * dil * res_f) / p.res_mm + math.sqrt(2) / poster.WALL_SUB)
    M = 64
    c = (M - 1) / 2
    for deg in np.linspace(0, 45, 8):
        u = np.array([np.cos(np.radians(deg)), np.sin(np.radians(deg))])
        n = np.array([-u[1], u[0]])
        for ph in (0.0, 0.25, 0.5, 0.75):
            a = c + (ph - gap / 2) * n + np.arange(-20, 21)[:, None] * u
            h = np.full(len(a), 150.0)
            solo = poster.wall_masks([[(a, h)]], M, p)[0]
            both = poster.wall_masks([[(a, h)], [(a + gap * n, h)]], M, p)[0]
            assert not (poster._slab_cells(solo) & ~poster._slab_cells(both)).any(), (deg, ph)


def _flat(p):
    """An (M, M) relief surface, flat at the layer boundary nearest 3mm."""
    M = _mpx(p)
    return np.full((M, M), poster._snap(3.0, p))


def _ray(M, deg):
    """A straight piece through the plate centre at heading deg, stations 1 px apart."""
    c, n = (M - 1) / 2, int((M - 1) / 2) - 3
    return c + np.arange(-n, n + 1)[:, None] * [np.cos(np.radians(deg)), np.sin(np.radians(deg))]


def _figure8(cx, cy, R, hr):
    """A figure eight crossing itself at (cx, cy), stations 1 px apart along it."""
    t = np.linspace(0, 2 * np.pi, 4000)
    Q = np.stack([cx + R * np.sin(t), cy + R * np.sin(t) * np.cos(t)], 1)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(Q, axis=0).T))]
    s = np.arange(0, d[-1], 1.0)
    P = np.stack([np.interp(s, d, Q[:, 0]), np.interp(s, d, Q[:, 1])], 1)
    return P, np.full(len(P), float(hr))


@pytest.mark.parametrize("ramp", [False, True], ids=["150bpm", "100-200bpm"])
def test_a_wall_mesh_is_watertight_seated_and_on_the_layer_grid(ramp):
    # the ramp: a segment whose two ends sit an odd number of layers apart must not
    # take their mean, which is half a layer off the grid, on the mid-layer slice plane
    p = _params(); s = _flat(p); P = _ray(s.shape[0], 30)
    hr = np.linspace(100, 200, len(P)) if ramp else np.full(len(P), 150.0)
    walls = [[(P, hr)]]
    (mask,), (top,) = poster.wall_masks(walls, s.shape[0], p), poster.wall_tops(walls, s, p)
    m = poster.wall_mesh(mask, top, p)
    on_grid = lambda z: np.allclose(z, poster._snap(z, p), rtol=0, atol=1e-9)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    assert abs(m.bounds[0][2] - poster.SLOT_FLOOR_MM) < 1e-9
    assert abs(m.bounds[1][2] - poster._snap(s[0, 0] + poster.wall_height(hr, p).max(), p)) < 1e-9
    assert on_grid(top[mask]) and on_grid(m.vertices[:, 2])


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
        D = poster._dilate(mask, dil)
        # every fine cell touching D, not only those inside it: a cell in block r can touch
        # D through a vertex on row (r+1)*S, which only the closed-block rule counts
        R, Cc = np.nonzero(D[:-1, :-1] | D[1:, :-1] | D[:-1, 1:] | D[1:, 1:])
        r, c = R // S, Cc // S
        assert (g[r, c] & g[r + 1, c] & g[r, c + 1] & g[r + 1, c + 1]).all()


@pytest.mark.parametrize("res", [0.5, 0.4, 0.25])
def test_a_curved_wall_has_no_pinholes_and_its_top_covers_it(res):
    # Two segment rectangles leave a wedge outside their shared vertex: without _ribbon's
    # bevel a curved wall had a pinhole every few mm, some stations no wall at all.
    p = _params(res_mm=res, groove_w_mm=1.44); M, S = _mpx(p), poster.WALL_SUB
    for R in (8, 13.3, 27.7):
        P, h = _arc((M - 1) / 2, (M - 1) / 2, R, 150)
        walls = [[(P[: len(P) // 2], h[: len(h) // 2])]]
        (m,), (top,) = poster.wall_masks(walls, M, p), poster.wall_tops(walls, _flat(p), p)
        C, nrm = poster._offsets(walls[0][0][0] * S)[:2]
        assert _min_width_mm(poster._cell_verts(poster._slab_cells(m)), C, nrm, p.res_mm / S) >= 0.84
        assert (top[m] > poster.SLOT_FLOOR_MM).all()


def test_repeated_stations_draw_the_same_wall_without_a_warning():
    # snapping and the lane push-out leave consecutive duplicate stations
    p = _params(); s = _flat(p); P = _ray(s.shape[0], 30); h = np.full(len(P), 150.0)
    k = np.repeat(np.arange(len(P)), 3)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = [(poster.wall_masks(w, s.shape[0], p), poster.wall_tops(w, s, p))
               for w in ([[(P, h)]], [[(P[k], h[k])]])]
    assert all(np.array_equal(a, b) for a, b in zip(sum(out[0], []), sum(out[1], [])))


def test_a_later_wall_runs_through_and_the_earlier_one_is_cut_clear_of_it():
    p = _params(); M, S = _mpx(p), poster.WALL_SUB
    ma, mb = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_vline(30, 5, 55, 150)]], M, p)
    assert len(list(poster._components(mb))) == 1 and len(list(poster._components(ma))) == 2
    win = lambda m: np.argwhere(m[25 * S:36 * S, 25 * S:36 * S])
    A, B = win(ma), win(mb)
    gap = np.sqrt(((A[:, None] - B[None]) ** 2).sum(-1)).min() * p.res_mm / S
    assert gap >= p.clearance_mm


def test_walls_in_neighbouring_lanes_are_not_cut():
    p = _params(); M = _mpx(p); lane = poster._wall_dims(p)[3] / p.res_mm
    ma, mb = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_line(5, 55, 30.0 + lane, 150)]], M, p)
    assert len(list(poster._components(ma))) == len(list(poster._components(mb))) == 1 and not (ma & mb).any()


def test_a_fragment_too_short_to_handle_is_dropped(capsys):
    p = _params(); M = _mpx(p)
    ma, _ = poster.wall_masks([[_line(5, 55, 30.0, 150)], [_vline(10, 5, 55, 150)]], M, p)
    assert len(list(poster._components(ma))) == 1 and "dropped" in capsys.readouterr().out


def test_a_wall_crossing_itself_stays_one_piece():
    p = _params(); M = _mpx(p)
    (m,) = poster.wall_masks([[_figure8(31, 31, 20, 150)]], M, p)
    assert len(list(poster._components(m))) == 1


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
    return p, N, fpx, elev


def _band(M):
    """A horizontal groove band across the relief plate, rows M//2-2 .. M//2+2."""
    g = np.zeros((M, M), bool)
    g[M // 2 - 2:M // 2 + 3] = True
    return g


def test_compose_parts_frame_and_relief_levels():
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    parts = poster.compose_parts(_band(M), elev, np.zeros((M, M), np.uint8), p)
    assert parts["frame"].shape == (N, N)
    assert parts["green"].shape == (M, M) and parts["surface"].shape == (M, M)
    assert parts["frame"][0, 0] == p.base_mm + p.frame_height_mm   # frame ring is flat
    assert parts["frame"][N // 2, N // 2] == p.base_mm             # backplate under relief
    assert abs(parts["green"][M // 2, 0] - p.plate_mm) < p.relief_mm  # relief starts at plate
    assert parts["green"].max() <= p.plate_mm + p.relief_mm * p.exaggeration + 1e-6


def test_compose_parts_slot_floor_is_constant():
    """The slot is carved to a constant floor, so every wall seats on a flat seat
    regardless of the terrain it crosses (depth varies, floor does not)."""
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    gmask = _band(M)
    parts = poster.compose_parts(gmask, elev, np.zeros((M, M), np.uint8), p)
    assert (parts["green"][gmask] == poster.SLOT_FLOOR_MM).all()
    assert 0 < poster.SLOT_FLOOR_MM < p.plate_mm           # plate stays connected under it
    # the elevation ramp means the slot really does vary in depth along the groove
    depth = parts["surface"][gmask] - parts["green"][gmask]
    assert depth.max() - depth.min() > 1.0


def test_compose_parts_shapes_and_caps():
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    p = _params(snow_line_m=400.0)                         # under the ramp's high end
    lc = np.zeros((M, M), np.uint8)
    lc[5:15, 5:15] = 1                                     # water square, away from groove
    lc[30:40, 30:40] = 2                                   # snow square
    lc[0, 20:30] = 1                                       # water touching the plate edge
    parts = poster.compose_parts(_band(M), elev, lc, p)
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
    gmask = _band(M)
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
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    rng = np.random.default_rng(3)
    noisy = poster._smooth(elev + rng.normal(0, 3.0, (M, M)), p.smooth_px)
    s = poster.compose_parts(_band(M), noisy, np.zeros((M, M), np.uint8), p)["surface"]
    assert np.abs(s - poster._snap(s, p)).max() < 1e-9
    assert len(np.unique(s.round(9))) > 5              # a real hill keeps its levels
    off = poster.compose_parts(_band(M), noisy, np.zeros((M, M), np.uint8),
                               _params(layer_mm=0.0))["surface"]
    assert np.abs(off - poster._snap(off, p)).max() > 1e-3      # 0 = opt out


def test_sub_layer_noise_collapses_to_a_flat_plane():
    """DEM noise smaller than a layer must not survive as scattered islands, while
    the surrounding relief keeps every level it had."""
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    e = elev.copy()
    e[5:20, 5:20] = 500.0                              # a flat plateau in the ramp...
    rng = np.random.default_rng(0)
    noisy = e + rng.normal(0, 3.0, (M, M))             # ...under ~0.09mm of wobble
    lc = np.zeros((M, M), np.uint8)
    raw = poster.compose_parts(_band(M), noisy, lc, _params(layer_mm=0.0))["surface"]
    got = poster.compose_parts(_band(M), poster._smooth(noisy, p.smooth_px), lc, p)["surface"]
    box = (slice(8, 17), slice(8, 17))                 # well inside the plateau
    assert len(np.unique(raw[box].round(9))) > 50      # every pixel its own level
    assert len(np.unique(got[box].round(9))) <= 2      # one plane (two at a boundary)
    assert len(np.unique(got.round(9))) > 5            # the ramp is not flattened


def test_smooth_is_an_identity_at_zero():
    e = np.arange(25.0).reshape(5, 5)
    assert (poster._smooth(e, 0.0) == e).all()
    assert poster._smooth(e, 2.0).shape == e.shape
    assert abs(poster._smooth(e, 2.0).mean() - e.mean()) < 1.0   # edge-clamped, no drift


def _min_width_mm(mask, C, nrm, res):
    """Narrowest perpendicular width, in mm, of what _slab_mesh meshes from the vertex
    `mask` (the cells with all four corners set), across the stations C (pixel space,
    unit normals nrm) of a grid of pitch res; two stations skipped per end.

    The contiguous run of each station's perpendicular inside those cells, in 0.05 px
    steps out to 64 px a side. Not a rounding of each sample to its nearest vertex:
    that reads up to a pixel past the meshed edge, and it passed a
    0.84mm-core wall that meshed 0.75mm wide at 30 deg."""
    cells = mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]
    step = np.arange(0, 64, 0.05)

    def reach(sign):
        q = np.floor(C[:, None] + sign * nrm[:, None] * step[None, :, None]).astype(int)
        c, r = q[..., 0], q[..., 1]
        ok = (r >= 0) & (c >= 0) & (r < cells.shape[0]) & (c < cells.shape[1])
        ok &= cells[r.clip(0, cells.shape[0] - 1), c.clip(0, cells.shape[1] - 1)]
        return (np.where(ok.all(1), len(step), ok.argmin(1)) - 1) * 0.05

    return ((reach(1.0) + reach(-1.0))[2:-2] * res).min()   # skip the square ends


def test_compose_parts_text_is_a_mask_not_an_emboss():
    """Text is printed white as its own body, so the frame heightmap stays flat —
    the glyph pixels come back as a mask instead, on its own finer grid."""
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    S = poster.TEXT_SUB
    lc = np.zeros((M, M), np.uint8)
    q = _params(text="TEST", text_mm=3.0)
    parts = poster.compose_parts(_band(M), elev, lc, q)
    frame, tm = parts["frame"], parts["text_mask"]
    H = N + poster._grid(q)[3]
    assert frame.max() == p.base_mm + p.frame_height_mm    # ring is flat, nothing embossed
    assert tm.shape == ((H - 1) * S + 1, (N - 1) * S + 1) and tm.dtype == bool
    assert parts["text_res"] == q.res_mm / S
    assert tm.any() and tm[:(N - fpx) * S, :].sum() == 0   # glyphs live on the bottom bar
    assert not poster.compose_parts(_band(M), elev, lc, _params())["text_mask"].any()


# --- the chin: extra frame height at the bottom, for the caption ----------------

def _chinned(**kw):
    """(bare parts, chinned parts, chin_px) over the same synthetic terrain."""
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    lc, g = np.zeros((M, M), np.uint8), _band(M)
    q = _params(**kw)
    return (poster.compose_parts(g, elev, lc, p),
            poster.compose_parts(g, elev, lc, q), poster._grid(q)[3])


def test_the_chin_extends_the_frame_downward_and_leaves_the_opening_alone():
    """The chin is extra ring at the bottom only: the inner opening keeps its exact
    indices and values, so the relief plate that drops into it is untouched."""
    p, N, fpx, elev = _synthetic()
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
    p, N, fpx, elev = _synthetic()
    parts = poster.compose_parts(_band(_mpx(q)), elev, np.zeros((_mpx(q), _mpx(q)), np.uint8), q)
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
    p, N, fpx, elev = _synthetic()
    q = _params(text="MMMM", text2="MMMM", text_mm=6.0)
    tm = poster.compose_parts(_band(_mpx(q)), elev, np.zeros((_mpx(q), _mpx(q)), np.uint8),
                              q)["text_mask"]
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
    p, N, fpx, elev = _synthetic()
    q = _params(text="ZURICH", text2="HB-EZE", text_mm=6.0)
    parts = poster.compose_parts(_band(_mpx(q)), elev, np.zeros((_mpx(q), _mpx(q)), np.uint8), q)
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


LEGS3 = [_leg("run", 300, 150)]
TRI3 = [_leg("swim", 200, np.nan), _leg("bike", 400, 140, t0=3600, lat0=47.01),
        _leg("run", 300, 160, t0=7200, lat0=47.02)]


def _fake_fetches(monkeypatch, water=False, elev_top=500.0, roads=False):
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, elev_top, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_osm_masks",
                        lambda b, px, res, **kw: (
                            np.full((px, px), water, bool), np.zeros((px, px), bool),
                            np.full((px, px), roads, bool)))


def _fake_strips(monkeypatch):
    """Every relief body in one order: a W-E ramp to 4000 m (the band east of 2000 m),
    water on the west quarter and a road across the middle (a bridge over the water)."""
    def masks(b, px, res, **kw):
        water, road = np.zeros((px, px), bool), np.zeros((px, px), bool)
        water[:, :px // 4] = True
        road[3 * px // 8:5 * px // 8] = True
        return water, np.zeros((px, px), bool), road
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, 4000.0, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_osm_masks", masks)


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
    _, _, paths = poster.build_poster(TRI3, _params())
    assert [(n, b[0][1], b[0][2]) for n, b in paths] == [
        ("path_swim", "swim", "#FFFFFF"), ("path_bike", "bike", "#CC2222"), ("path_run", "run", "#F4EE2A")]


def _noisy_loop_leg(sport="swim", speed_ms=1.0, scatter_m=3.0, seed=0):
    """A 633 x 317 m (1.9 km) closed rectangle off 47.355N 8.54E, one fix per second at
    speed_ms with Gaussian scatter_m on every fix, no HR: a slow, jittery swim or walk."""
    c = np.array([[0, 0], [633, 0], [633, 317], [0, 317], [0, 0]], float)   # east, north m
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
    q = np.r_[np.arange(0, s[-1], speed_ms), s[-1]]
    en = np.stack([np.interp(q, s, c[:, 0]), np.interp(q, s, c[:, 1])], 1)
    en += np.random.default_rng(seed).normal(0, scatter_m, en.shape)
    m_lon = 111_320 * math.cos(math.radians(47.355))
    return activity.Leg(sport, 47.355 + en[:, 1] / 111_320, 8.54 + en[:, 0] / m_lon,
                        np.arange(len(q), dtype=float), np.full(len(q), np.nan))


def _noisy_tri(swim):
    """swim, then a clean 9 km bike and 4.5 km run 1.7-2.8 km south of it: a triathlon's
    map, ~24 m per relief px at 216, so 3 m of scatter is 0.12 px and a 1 m step 0.04."""
    return [swim, _leg("bike", 1200, 140, t0=3600, lat0=47.33, lon0=8.50),
            _leg("run", 600, 160, t0=7200, lat0=47.34, lon0=8.52)]


def _swim_216(speed_ms=1.0, scatter_m=3.0):
    """(p, M, (P, hr)): the noisy loop's leg_stations at 216 on the _noisy_tri map."""
    p = poster.resolve(poster.Params(size_mm=216)); M = _mpx(p)
    legs = _noisy_tri(_noisy_loop_leg(speed_ms=speed_ms, scatter_m=scatter_m))
    return p, M, poster.leg_stations(legs[0], poster.legs_bounds(legs, p.margin_pct), M)


def _length(P):
    return np.hypot(*np.diff(P, axis=0).T).sum()


def test_a_noisy_slow_track_keeps_one_pixel_station_spacing():
    # scatter over a 1 m step zigzags the raw polyline ~4x its real length, and _offsets
    # resampled over that put the demo swim's 525 stations ~0.27 px apart
    _, _, (P, _) = _swim_216()
    _, _, (P0, _) = _swim_216(scatter_m=0.0)
    spacing, stretch = np.hypot(*np.diff(P, axis=0).T).mean(), _length(P) / _length(P0)
    assert 0.8 <= spacing <= 1.25
    assert abs(stretch - 1) < 0.15


@pytest.mark.parametrize("speed_ms", [1.0, 1.4])     # a swim and a walk
def test_a_noisy_slow_loop_does_not_collapse_onto_itself(speed_ms):
    # at 0.27 px stations, 3*r stations back was ~4 px of path, inside r: every station
    # repeated the loop's start, and the demo swim snapped onto a 4.2 x 1.1 px blob
    p, L, ramp = _dims216()
    _, M, (P, hr) = _swim_216(speed_ms)
    _, _, (P0, _) = _swim_216(speed_ms, scatter_m=0.0)
    (Q, hq), = poster.collapse_passes([(P, hr)], L, ramp)
    box_off = max(np.abs(Q.min(0) - P.min(0)).max(), np.abs(Q.max(0) - P.max(0)).max())
    assert box_off <= 2
    (m,) = poster.wall_masks([[(Q, hq)]], M, p)
    res_f, W = poster._wall_dims(p)[:2]
    pieces, wall_mm, loop_mm = len(list(poster._components(m))), m.sum() * res_f ** 2 / W, _length(P0) * p.res_mm
    assert pieces == 1
    assert wall_mm > 0.8 * loop_mm


def test_the_repeat_gap_is_measured_in_px_not_stations():
    # stations 0.25 px apart on a straight road: 3*r stations back is 3 px, inside r, so a
    # gap counted in stations made the whole road a repeat of its first 3 px
    piece = (np.stack([np.arange(10, 90.25, 0.25), np.full(321, 50.0)], 1), np.full(321, 150.0))
    (P, _), = poster.collapse_passes([piece], r_px=4, ramp=4)
    moved = np.abs(P - piece[0]).max()
    assert moved == 0


def test_build_poster_prints_a_noisy_swim(monkeypatch):
    # the demo triathlon at 216: "swim: too short to print at this size, no path file"
    _fake_fetches(monkeypatch)
    _, _, paths = poster.build_poster(_noisy_tri(_noisy_loop_leg()), poster.Params(size_mm=216))
    stems = [n for n, _ in paths]
    assert stems == ["path_swim", "path_bike", "path_run"]
    assert paths[0][1][0][0].is_watertight


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


def test_generate_says_when_a_leg_is_too_short_to_print(monkeypatch):
    # a 2-fix swim meshes under MIN_PIECE_MM: no path_swim file, and the status line says so
    from fastapi.testclient import TestClient
    import app as appmod
    from test_activity import _fit
    _fake_fetches(monkeypatch)
    fit = _fit([("swimming", 2, None), ("cycling", 120, 140), ("running", 90, 160)])
    r = TestClient(appmod.app).post("/generate", files=[("files", ("tri.fit", fit, "application/octet-stream"))],
                                    data={"params": json.dumps({"size_mm": 120.0})})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["paths"]) == ["path_bike", "path_run"]
    assert r.json()["legs"].endswith(" · swim: too short to print at this size, no path file")


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


def test_build_poster_v2(monkeypatch):
    _fake_fetches(monkeypatch)
    frame_bodies, bodies, paths = poster.build_poster(LEGS3, _params())
    assert [b[1] for b in frame_bodies] == ["frame"]            # no text asked for
    assert frame_bodies[0][2] == poster.COLORS["frame"] and frame_bodies[0][3] == 1
    assert frame_bodies[0][0].is_watertight and frame_bodies[0][0].volume > 0
    names = [b[1] for b in bodies]
    assert names == ["terrain"]                  # dry, below the snow line -> no caps
    assert bodies[0][2] == poster.COLORS["green"] and bodies[0][3] == 1
    assert bodies[0][0].is_watertight and bodies[0][0].volume > 0
    assert [(n, [b[1:] for b in bs]) for n, bs in paths] == [
        ("path", [("strip", poster.COLORS["strip"], 1)])]
    assert paths[0][1][0][0].is_watertight and paths[0][1][0][0].volume > 0


def test_build_poster_text_is_its_own_white_body(monkeypatch):
    """Text prints white on the black frame: a second body sitting exactly
    TEXT_EMBOSS_MM proud of the ring, not an emboss in the frame's own filament."""
    _fake_fetches(monkeypatch)
    p = _params(text="HB-EZE")
    frame_bodies, _, _ = poster.build_poster(LEGS3, p)
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
    _, bodies, _ = poster.build_poster(LEGS3, _params())
    assert [b[1] for b in bodies] == ["terrain", "water"]
    cap = bodies[1][0]
    assert bodies[1][2] == poster.COLORS["water"] and bodies[1][3] == 2
    assert cap.is_watertight and cap.is_winding_consistent and cap.volume > 0



def test_build_poster_rejects_oversized_grid():
    with pytest.raises(ValueError):
        poster.build_poster(LEGS3, _params(size_mm=2500.0))   # typo, not a request
    with pytest.raises(ValueError):
        poster.build_poster(LEGS3, _params(res_mm=0.01))
    with pytest.raises(ValueError):   # slot floor would reach the back of the relief plate
        poster.build_poster(LEGS3, _params(plate_mm=1.0))


def test_build_poster_rejects_a_frame_taller_than_the_plate():
    """The chin is height the plate has to find, and only check_output.py said so.

    250mm with two caption lines is 249.6 x 260.0mm — 4mm of overhang nobody saw
    until the files were sliced. The refusal names both axes and the size that fits."""
    p = poster.Params(size_mm=250.0, text="ZURICH", text2="HB-EZE")
    with pytest.raises(ValueError) as e:
        poster.build_poster(LEGS3, p)
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
        poster.build_poster(LEGS3, _params(plate_mm=2.0, cap_mm=3.0))


def _run_gpx():
    """A 300-fix run with heart rate as a Strava GPX upload, for /generate."""
    from test_activity import _gpx, _pts
    return "run.gpx", _gpx([("running", _pts(300))]), "application/gpx+xml"


def test_generate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    _fake_fetches(monkeypatch, water=True)     # water everywhere -> relief has 2 bodies
    client = TestClient(appmod.app)
    # 120 is the smallest size the shop sells; frame_mm/res_mm are pinned coarse so
    # the endpoint test stays fast. Any other size_mm is a 400 (see the test below).
    params = '{"size_mm": 120, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files=[("files", _run_gpx())], data={"params": params})
    assert r.status_code == 200, r.text
    import base64
    j = r.json()
    assert set(j) == {"frame", "relief", "paths", "colours", "resolved", "legs"}
    assert j["resolved"]["frame_mm"] == 4 and j["resolved"]["text"] == "ZRH-GVA"
    assert list(j["paths"]) == ["path"] and j["legs"] == "run: HR 100%"   # one sport, one file
    frame, relief, path = (base64.b64decode(v) for v in (j["frame"], j["relief"], j["paths"]["path"]))
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
        "/generate", files=[("files", _run_gpx())],
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
    post = lambda params: client.post("/generate", files=[("files", _run_gpx())],
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
        "/generate", files=[("files", _run_gpx())],
        data={"params": '{"size_mm": 216, "text": "ZURICH", "text2": "HB-EZE",'
                        ' "chin_mm": 20}'})
    assert r.status_code == 400          # an input check: the order's fault, not the server's
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
        "/generate", files=[("files", ("x.gpx", b"junk"))], data={"params": "{}"})
    assert r.status_code == 400 and r.json()["detail"].startswith("x.gpx: ")


def test_generate_bad_params_json():
    from fastapi.testclient import TestClient
    import app as appmod
    client = TestClient(appmod.app)
    files = [("files", _run_gpx())]
    assert client.post("/generate", files=files,
                       data={"params": "not-json"}).status_code == 400
    assert client.post("/generate", files=files,   # valid JSON, not an object
                       data={"params": "5"}).status_code == 400


def test_generate_refuses_a_param_of_the_wrong_type():
    from fastapi.testclient import TestClient
    import app as appmod
    r = TestClient(appmod.app).post("/generate", files=[("files", _run_gpx())],
                                    data={"params": json.dumps({"size_mm": 120, "wall_mm": "abc"})})
    assert r.status_code == 400, r.text


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
        n = len(poster.relief_colours(poster.THEMES["classic"]) if plate == "relief"
                else poster.SLOTS[plate])                # relief: 3 even with 1 body used
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
    frame, relief, paths = poster.build_poster(TRI3, p)
    assert [n for n, _ in paths] == ["path_swim", "path_bike", "path_run"]
    for plate, bodies in [("frame", frame), ("relief", relief), *paths]:
        f, out = tmp_path / f"{plate}.3mf", tmp_path / plate
        f.write_bytes(poster.write_3mf(bodies))
        out.mkdir()
        r = subprocess.run([ORCA, "--debug", "1", "--slice", "0", "--export-3mf", "sliced.3mf",
                            "--outputdir", str(out), str(f)], capture_output=True, timeout=600)
        assert r.returncode == 0, r.stdout[-2000:]
        g = zipfile.ZipFile(out / "sliced.3mf").read("Metadata/plate_1.gcode").decode()
        cfg = dict(re.findall(r"^; (\w+) = (.*)$", g, re.M))
        assert cfg["layer_height"] == "0.24" and cfg["prime_tower_width"] == "130"
        cols = (poster.relief_colours(poster.THEMES["classic"]) if plate == "relief"
                else [poster.COLORS[k] for k in poster.SLOTS[plate]])
        # Orca switches the tower off itself for a one-filament plate (path)
        assert cfg["enable_prime_tower"] == ("1" if len(cols) > 1 else "0")
        assert cfg["wall_loops"] == poster.PLATES[plate]["wall_loops"]
        assert cfg["filament_colour"] == ";".join(cols)
        if plate == "frame":   # bead-only caption tops read as hollow outline letters in Orca
            assert "; FEATURE: Top surface" in g.split("; CHANGE_LAYER")[-1]


# --- themes --------------------------------------------------------------------

def _cfg(data):
    """project_settings.config of a 3MF, as a dict."""
    import zipfile
    return json.loads(zipfile.ZipFile(io.BytesIO(data)).read("Metadata/project_settings.config"))


def test_every_theme_in_the_table_is_complete():
    from collections import Counter
    hexes = ("frame", "text", "land", "water", "band", "detail", "path")
    is_hex = lambda v: isinstance(v, str) and re.fullmatch(r"#[0-9A-F]{6}", v)
    for k, t in poster.THEMES.items():
        assert t.label, k
        for f in hexes:
            v = getattr(t, f)
            assert is_hex(v) or (v is None and f in ("band", "detail")), (k, f, v)
        assert sorted(t.legs) == ["bike", "run", "swim"] and all(map(is_hex, t.legs.values())), k
        assert t.groups <= {"streets", "trails", "rail", "buildings"}, k
        # no theme inherits classic's hand-tuned 3x3
        n = len(poster.relief_colours(t))
        assert len(poster._project_settings("relief", t)["flush_volumes_matrix"]) == n * n, k
    keys = [k for ks in poster.THEME_GROUPS.values() for k in ks]
    assert list(poster.THEME_GROUPS) == ["events", "rooms", "industrial", "nature", "running"]
    assert sorted(keys) == sorted(poster.THEMES) and len(keys) == len(set(keys))
    # plan finding 5: 22 themes on four relief slots, 9 on three, gallery on two
    assert Counter(len(poster.relief_colours(t)) for t in poster.THEMES.values()) == {4: 22, 3: 9, 2: 1}


def test_classic_theme_is_todays_output(monkeypatch):
    """The default theme is the pre-theme output: COLORS on every body, the same slots,
    classic's hand flush table at the same place in the config. The byte-for-byte
    comparison against cba3d62 (bodies, vertices, every 3MF member) is in task-1-report."""
    t, C = poster.THEMES["classic"], poster.COLORS
    assert poster.Params().theme == "classic"
    assert (t.frame, t.text, t.land, t.water, t.band, t.detail, t.path) == (
        C["frame"], C["text"], C["green"], C["water"], C["snow"], None, C["strip"])
    assert t.legs == {s: C[s] for s in ("swim", "bike", "run")} and t.groups == frozenset()
    _fake_strips(monkeypatch)
    frame, relief, paths = poster.build_poster(TRI3, _params(text="HB", text_mm=3.0))
    assert [b[1:] for b in frame] == [("frame", "#222222", 1), ("text", "#FFFFFF", 2)]
    assert [b[1:] for b in relief] == [("terrain", "#4CAF50", 1), ("water", "#2196F3", 2),
                                       ("snow", "#9E9E9E", 3), ("roads", "#9E9E9E", 3)]
    assert [(s, b[0][1:]) for s, b in paths] == [
        ("path_swim", ("swim", "#FFFFFF", 1)), ("path_bike", ("bike", "#CC2222", 1)),
        ("path_run", ("run", "#F4EE2A", 1))]
    cfg = poster._project_settings("relief")
    assert cfg["filament_colour"] == ["#4CAF50", "#2196F3", "#9E9E9E"]
    assert cfg["flush_volumes_matrix"] == ["0", "400", "550", "350", "0", "600", "250", "300", "0"]
    keys = list(cfg)   # json.dumps keeps this order: the config's bytes
    assert keys[keys.index("mmu_segmented_region_interlocking_depth") + 1] == "flush_volumes_matrix"


def test_a_four_slot_theme_declares_four_filaments(monkeypatch):
    t = poster.THEMES["alpine_hiking"]
    _fake_strips(monkeypatch)
    _, relief, paths = poster.build_poster(TRI3, _params(theme="alpine_hiking"))
    assert [b[1:] for b in relief] == [("terrain", "#CFE3B4", 1), ("water", "#6FA8DC", 2),
                                       ("snow", "#B9A58B", 3), ("roads", "#FFCC00", 4)]
    assert [b[0][2] for _, b in paths] == ["#FFFFFF", "#D62828", "#FF8C42"]
    cfg = _cfg(poster.write_3mf(relief, theme=t))
    assert cfg["filament_colour"] == ["#CFE3B4", "#6FA8DC", "#B9A58B", "#FFCC00"]
    assert len(cfg["filament_type"]) == 4
    # row = from, column = to; luma land 219 > detail 200 > band 167 > water 160
    assert np.array(cfg["flush_volumes_matrix"]).reshape(4, 4).tolist() == [
        ["0", "300", "300", "300"], ["550", "0", "550", "550"],
        ["550", "300", "0", "550"], ["550", "300", "300", "0"]]
    assert len(cfg["different_settings_to_system"]) == 6


def test_a_two_slot_theme_declares_two_filaments(monkeypatch):
    # no band and no detail colour: nothing grey above 2000 m, and no roads at all
    _fake_strips(monkeypatch)
    _, relief, _ = poster.build_poster(LEGS3, _params(theme="gallery"))
    assert [b[1:] for b in relief] == [("terrain", "#FFFFFF", 1), ("water", "#E6E6E3", 2)]
    cfg = _cfg(poster.write_3mf(relief, theme=poster.THEMES["gallery"]))
    assert cfg["filament_colour"] == ["#FFFFFF", "#E6E6E3"]
    assert cfg["flush_volumes_matrix"] == ["0", "300", "550", "0"]
    assert len(cfg["different_settings_to_system"]) == 4


def test_unknown_theme_is_refused(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    from test_activity import _fit
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: pytest.fail("fetched before checking the theme"))
    with pytest.raises(ValueError, match=r"unknown theme 'nope'; one of: classic, city_marathon"):
        poster.build_poster(LEGS3, _params(theme="nope"))
    r = TestClient(appmod.app).post(
        "/generate", files=[("files", ("run.fit", _fit([("running", 90, 160)]), "application/octet-stream"))],
        data={"params": json.dumps({"size_mm": 120.0, "theme": "nope"})})
    assert r.status_code == 400 and "unknown theme" in r.json()["detail"]


def test_generate_returns_the_theme_colours(monkeypatch):
    import base64
    from fastapi.testclient import TestClient
    import app as appmod
    from test_activity import _fit
    _fake_strips(monkeypatch)
    fit = _fit([("swimming", 60, None), ("cycling", 120, 140), ("running", 90, 160)])
    r = TestClient(appmod.app).post(
        "/generate", files=[("files", ("tri.fit", fit, "application/octet-stream"))],
        data={"params": json.dumps({"size_mm": 120.0, "theme": "alpine_hiking", "text": "ZERMATT"})})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["colours"] == {"frame": ["#3E2A1E", "#FFFFFF"],
                            "relief": ["#CFE3B4", "#6FA8DC", "#B9A58B", "#FFCC00"],
                            "paths": {"path_swim": ["#FFFFFF"], "path_bike": ["#D62828"],
                                      "path_run": ["#FF8C42"]}}
    # ...and the 3MFs carry the theme too, not classic
    got = lambda data: _cfg(base64.b64decode(data))["filament_colour"]
    assert got(j["relief"]) == j["colours"]["relief"] and got(j["frame"]) == j["colours"]["frame"]
    assert got(j["paths"]["path_bike"]) == ["#D62828"]


def _text_body(**kw):
    """The shipped 250mm text case, without paying for a whole build_poster."""
    p = poster.resolve(poster.Params(**{"size_mm": 250.0, "text": "HB-EZE", **kw}))
    M = poster._grid(p)[1]
    parts = poster.compose_parts(_band(M), np.zeros((M, M), np.float32),
                                 np.zeros((M, M), np.uint8), p)
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


def _write_order(tmp_path, built):
    """Write a build_poster result as its .3mf files -> check_output's positional args."""
    frame, relief, paths = built
    files = [("frame", frame), ("relief", relief), *paths]
    for stem, bodies in files:
        (tmp_path / f"{stem}.3mf").write_bytes(poster.write_3mf(bodies))
    return [str(tmp_path / f"{stem}.3mf") for stem, _ in files]


@pytest.mark.parametrize("text,text2", [("HB-EZE", ""), ("", ""),
                                        ("", "HB-EZE"), ("ZURICH", "HB-EZE")])
def test_check_output_passes_on_freshly_built_files(monkeypatch, tmp_path, text, text2):
    """The shipped checker agrees with the shipped builder, whichever caption lines
    were asked for. text2 alone is a valid caption and builds a body — the checker's
    present-iff rule read `p.text` only and FAILed a perfectly good poster."""
    import check_output
    _fake_fetches(monkeypatch, water=True)
    p = _params(text=text, text2=text2, text_mm=3.0)
    files = _write_order(tmp_path, poster.build_poster(TRI3, p))   # three path files
    params = json.dumps(asdict(p))   # the checker is handed exactly what was built
    assert check_output.main(files + ["--params", params]) == 0


def test_check_output_passes_on_a_relief_with_a_grey_band(monkeypatch, tmp_path):
    """The all-water case above never builds a grey body, so the band's own rules
    (flat bottom on one plane, top under the relief ceiling) go unchecked there."""
    import check_output
    _fake_fetches(monkeypatch, elev_top=4000.0)              # dry ramp through 2000m
    p = _params()
    built = poster.build_poster(LEGS3, p)
    assert [b[1] for b in built[1]] == ["terrain", "snow"]
    assert check_output.main(_write_order(tmp_path, built)
                             + ["--params", json.dumps(asdict(p))]) == 0


def test_check_output_flags_a_missing_text_body(monkeypatch, tmp_path, capsys):
    """Text asked for but no white body in the frame 3MF is a real failure now,
    not a hint — the body is recoverable from the mesh, unlike the old emboss."""
    import check_output
    _fake_fetches(monkeypatch)
    files = _write_order(tmp_path, poster.build_poster(LEGS3, _params()))   # no text
    rc = check_output.main(files + ["--params", json.dumps(asdict(_params(text="HB-EZE")))])
    assert rc == 1 and "text body" in capsys.readouterr().out


def test_check_output_flags_a_path_file_with_two_bodies_or_the_wrong_wall(monkeypatch, tmp_path, capsys):
    """One filament per path plate (spec 4): a second body would share its layers."""
    import check_output
    _fake_fetches(monkeypatch)
    p = _params()
    frame, relief, paths = poster.build_poster(TRI3, p)
    files = _write_order(tmp_path, (frame, relief, paths))
    bodies = dict(paths)
    (tmp_path / "path_run.3mf").write_bytes(poster.write_3mf(bodies["path_run"] + bodies["path_bike"]))
    (tmp_path / "path_bike.3mf").write_bytes(poster.write_3mf(bodies["path_swim"]))
    rc = check_output.main(files + ["--params", json.dumps(asdict(p))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL  path_run.3mf holds one body" in out and "PASS  path_swim.3mf holds one body" in out
    assert "FAIL  path_bike.3mf body is bike" in out and "PASS  path_run.3mf body is run" in out


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
    files = _write_order(tmp_path, poster.build_poster(LEGS3, p))
    rc = check_output.main(files + ["--params", json.dumps(asdict(p))])
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
    monkeypatch.setattr(poster, "fetch_osm_masks",
                        lambda b, px, res, **kw: (zeros(px), east(px), zeros(px)))
    seen, real = {}, poster.compose_parts
    monkeypatch.setattr(poster, "compose_parts", lambda *a: seen.setdefault("p", real(*a)))
    p = _params()                              # 30m of land: the 300m span floor, so
    _, bodies, _ = poster.build_poster(LEGS3, p)   # 7m of seabed left in would be ~3 layers
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


F = _wbounds(47.0, 8.0, 47.0036, 8.0053)    # ~400 m box: ~10 m per printed mm at 100 px
_F = lambda r, c: (47.0036 - 0.0036 * r / 100, 8.0 + 0.0053 * c / 100)   # F px (r, c) -> lat, lon
EVERY = frozenset({"streets", "trails", "rail", "buildings"})
_geom = lambda pts: [{"lat": a, "lon": o} for a, o in pts]
_hiking = lambda *ways: dict(type="relation", tags={"type": "route", "route": "hiking"},
                             members=[dict(type="way", ref=i, role="", geometry=_geom(g))
                                      for i, g in enumerate(ways)])


def test_fine_classes_need_both_zoom_and_theme(monkeypatch, capsys):
    """Streets, hiking routes and rail are drawn only when the theme permits them AND
    the zoom can hold them. Trails are the member ways of route=hiking relations, one
    road width like everything else; a closed member loop is a trail, never a lake.
    Rail includes narrow gauge (every Swiss mountain line) but not sidings. Too much
    grey drops streets first, then trails, then tertiary."""
    row = lambda r, c0=5, c1=95: [_F(r, c0), _F(r, c1)]
    col = lambda c, r0, r1: [_F(r0, c), _F(r1, c)]
    loop = [_F(10, 55), _F(10, 90), _F(30, 90), _F(30, 55), _F(10, 55)]
    hiking = _hiking(row(60), loop)
    hiking["members"] += [dict(type="node", ref=9, role="guidepost", lat=47.002, lon=8.002),
                          dict(type="way", ref=8, role="", tags={"highway": "footway", "tunnel": "yes"},
                               geometry=_geom(row(40, 5, 45)))]
    rail = {"railway": "rail"}
    els = [_way(row(80), tags={"highway": "residential"}), hiking,
           _way(col(25, 50, 95), tags=rail),
           _way(col(15, 10, 30), tags={**rail, "tunnel": "yes"}),
           _way(col(90, 64, 76), tags={"railway": "narrow_gauge"}),      # Gornergrat-style
           _way(col(40, 10, 30), tags={**rail, "service": "siding"})]
    seen = []
    monkeypatch.setattr(poster, "_get", lambda url, **k: seen.append(urllib.parse.unquote(url))
                        or json.dumps({"elements": els}).encode())

    poster.fetch_osm_masks(B, 100, 0.4, groups=EVERY)          # ~189 m/mm: too far out
    poster.fetch_osm_masks(F, 100, 0.4)                         # close, but not permitted
    for q in seen:
        assert not any(k in q for k in ("residential", "route", "railway")), q
    # classic's query is exactly what it was: same string, same Overpass cache key
    w, s = poster._unmerc(F[0], F[1]); e, n = poster._unmerc(F[2], F[3])
    assert seen[1].endswith(poster.OVERPASS_QL.format(
        s=s, w=w, n=n, e=e, roads='way["highway"~"^(tertiary|secondary|primary|trunk|motorway)$"];'))

    water, sea, roads = poster.fetch_osm_masks(F, 100, 0.4, groups=EVERY)
    q = seen[2]
    assert "residential" in q and 'relation["route"="hiking"]' in q
    assert 'way["railway"~"^(rail|narrow_gauge)$"]' in q
    at = lambda m, r, c: m[_rc(F, *_F(r, c), 100)]
    assert at(roads, 80, 50)                                        # the street
    assert at(roads, 60, 50)                                        # the hiking route
    assert at(roads, 10, 70) and at(roads, 20, 55)                  # the loop's edge...
    assert not at(roads, 20, 72) and not water.any()                # ...not a lake
    assert at(roads, 70, 25) and at(roads, 70, 90)                  # standard and narrow gauge
    assert not at(roads, 40, 25)                                    # tunnelled footway member
    assert not at(roads, 20, 15) and not at(roads, 20, 40)          # rail tunnel, siding
    width = lambda r: roads[r - 8:r + 9, _rc(F, *_F(r, 50), 100)[1]].sum()
    r_trail, r_street = _rc(F, *_F(60, 50), 100)[0], _rc(F, *_F(80, 50), 100)[0]
    assert width(r_trail) == width(r_street) == round(poster.ROAD_MM / 0.4) + 1   # ROAD_MM
    assert "dropped" not in capsys.readouterr().out

    # a dense street grid would grey the plate: streets go first, the hiking route stays
    els[0:1] = [_way(row(4 * i), tags={"highway": "residential"}) for i in range(25)]
    poster._overpass.cache_clear()
    roads = poster.fetch_osm_masks(F, 100, 0.4, groups=EVERY)[2]
    out = capsys.readouterr().out
    assert "streets" in out and "dropped" in out and "trails" not in out
    assert roads.mean() <= poster.ROAD_MAX_FRAC
    assert at(roads, 60, 50) and not at(roads, 80, 50)

    # dense streets AND dense trails: streets, then trails, and tertiary survives
    els[:] = ([_way(row(4 * i), tags={"highway": "residential"}) for i in range(25)]
              + [_hiking(*[row(4 * i + 2) for i in range(25)]),
                 _way(col(50, 5, 95), tags={"highway": "tertiary"})])
    poster._overpass.cache_clear()
    roads = poster.fetch_osm_masks(F, 100, 0.4, groups=EVERY)[2]
    out = capsys.readouterr().out
    assert out.index("roads: streets") < out.index("roads: trails") and "tertiary" not in out
    assert at(roads, 30, 50) and not at(roads, 30, 20)              # tertiary only

    # between 35 and 40 m/mm: hiking routes, no streets
    F38 = _wbounds(47.0, 8.0, 47.0134, 8.0198)                       # ~37.6 m/mm at 100 px
    els[:] = [_way([(47.003, 8.001), (47.003, 8.019)], tags={"highway": "residential"}),
              _hiking([(47.0067, 8.001), (47.0067, 8.019)])]
    roads = poster.fetch_osm_masks(F38, 100, 0.4, groups=EVERY)[2]
    assert "residential" not in seen[-1] and 'relation["route"="hiking"]' in seen[-1]
    assert roads[_rc(F38, 47.0067, 8.01, 100)] and not roads[_rc(F38, 47.003, 8.01, 100)]


def test_detail_in_its_own_colour_is_capped_at_20_percent(monkeypatch, capsys):
    """The cap that keeps classic's shared grey from becoming a block (15%) dropped
    Zermatt's streets at 16%. A theme with its own detail colour holds 20%; classic and
    the other band-shared themes keep 15%. One mask between the two caps."""
    els = [_way([_F(r, 5), _F(r, 95)], tags={"highway": "residential"})
           for r in (10, 30, 50, 70, 90)]
    monkeypatch.setattr(poster, "_get", lambda url, **k: json.dumps({"elements": els}).encode())
    own = poster.fetch_osm_masks(F, 100, 0.4, groups=EVERY, max_frac=poster.DETAIL_MAX_FRAC)[2]
    assert poster.ROAD_MAX_FRAC < own.mean() <= poster.DETAIL_MAX_FRAC
    assert "dropped" not in capsys.readouterr().out
    shared = poster.fetch_osm_masks(F, 100, 0.4, groups=EVERY)[2]   # default: ROAD_MAX_FRAC
    assert not shared.any() and "roads: streets" in capsys.readouterr().out

    caps = []
    _fake_fetches(monkeypatch)
    monkeypatch.setattr(poster, "fetch_osm_masks", lambda b, px, res, **kw: caps.append(
        kw["max_frac"]) or tuple(np.zeros((px, px), bool) for _ in range(3)))
    for theme in ("classic", "triathlon", "alpine_hiking"):     # band-shared x2, own detail
        poster.build_poster(LEGS3, _params(theme=theme))
    assert caps == [poster.ROAD_MAX_FRAC, poster.ROAD_MAX_FRAC, poster.DETAIL_MAX_FRAC]


def test_caps_follow_the_slot(monkeypatch, tmp_path):
    """Water/road caps drape into the groove: the slot is blue over the sea, not a
    green rim, and the strip still seats on the one flat SLOT_FLOOR_MM."""
    p, N, fpx, elev = _synthetic()
    M = _mpx(p)
    lc = np.ones((M, M), np.uint8)
    gmask = _band(M)
    parts = poster.compose_parts(gmask, elev, lc, p)
    assert (parts["cap_top"][gmask] == poster.SLOT_FLOOR_MM).all()
    under = gmask & poster._cell_verts(parts["water_cells"])
    assert under.any()
    assert np.allclose(parts["green"][under], poster.SLOT_FLOOR_MM - poster.SLOT_CAP_MM)
    z = poster.SLOT_FLOOR_MM - poster.SLOT_CAP_MM
    assert abs(z - poster._snap(z, p)) < 1e-9                       # 0.68: on the grid

    import check_output
    _fake_fetches(monkeypatch, water=True)
    p = _params()
    built = poster.build_poster(LEGS3, p)
    bodies = built[1]
    assert [b[1] for b in bodies] == ["terrain", "water"]
    w = bodies[1][0]
    assert w.is_watertight and w.is_winding_consistent
    assert abs(w.bounds[0][2] - z) < 1e-9
    assert (np.abs(w.vertices[:, 2] - poster.SLOT_FLOOR_MM) < 1e-9).any()
    files = _write_order(tmp_path, built)
    assert abs(poster.read_3mf((tmp_path / "path.3mf").read_bytes())[0][1][:, 2].min()
               - poster.SLOT_FLOOR_MM) < 1e-4
    assert check_output.main(files + ["--params", json.dumps(asdict(p))]) == 0

    # roads are the same cap, grey, in the snow band's slot
    _fake_fetches(monkeypatch, roads=True)
    _, bodies, _ = poster.build_poster(LEGS3, p)
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
        poster.build_poster(LEGS3, _params())


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
    _, bodies, _ = poster.build_poster(LEGS3, _params())
    assert [b[1] for b in bodies] == ["terrain", "snow"]
    cap = bodies[1][0]
    assert bodies[1][2] == poster.COLORS["snow"] and bodies[1][3] == 3
    assert cap.is_watertight and cap.is_winding_consistent and cap.volume > 0
    # ...and the threshold is the parameter, not a constant
    _, bodies, _ = poster.build_poster(LEGS3, _params(snow_line_m=5000.0))
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
                        lambda b, px, res, **kw: tuple(np.zeros((px, px), bool) for _ in range(3)))
    _, bodies, _ = poster.build_poster(LEGS3, _params())
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
    _, bodies, _ = poster.build_poster(LEGS3, _params())
    assert [b[1] for b in bodies] == ["terrain", "water"]


# --- grey elevation band -----------------------------------------------------

def _banded(snow_line_m=600.0, lc_all=False, groove=None, **kw):
    """Synthetic E-W ramp (0-1000m) with the ground above `snow_line_m` marked grey, and
    `groove(M, p)` (default _band) carved."""
    p = _params(snow_line_m=snow_line_m, **kw)
    M = _mpx(p)
    elev = np.tile(np.linspace(0, 1000, M), (M, 1))
    lc = np.zeros((M, M), np.uint8)
    lc[np.ones_like(elev, bool) if lc_all else (elev >= snow_line_m)] = 2
    g = _band(M) if groove is None else groove(M, p)
    return p, M, elev, poster.compose_parts(g, elev, lc, p)


def _wall_groove(M, p, deg=60):
    """The groove one straight wall at heading deg carves. Oblique, so its staircase edge
    leaves green rim vertices next to the band; the straight _band leaves none."""
    P = _ray(M, deg)
    return poster.groove_from_masks(poster.wall_masks([[(P, np.full(len(P), 150.0))]], M, p), M, p)


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

    Only the slot is excluded — green there is the slot floor, not terrain. A real
    wall's groove, so the rim the bound is about really occurs."""
    p, M, elev, parts = _banded(groove=_wall_groove)
    s, z_snow = parts["surface"], parts["z_snow"]
    rise = max(np.abs(np.diff(s, axis=0)).max(), np.abs(np.diff(s, axis=1)).max())
    plate = ~_wall_groove(M, p)
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
    gmask = _band(M)
    assert np.abs(top - parts["surface"])[~gmask].max() < 1e-9
    assert verts.any() and gmask.any()


def test_snow_line_above_the_dem_leaves_no_band():
    p, M, elev, parts = _banded(snow_line_m=5000.0, lc_all=True)
    assert not parts["snow_cells"].any()
    assert poster.band_mesh(parts, p) is None
    gmask = _band(M)
    assert (parts["green"][~gmask] == parts["surface"][~gmask]).all()


def test_snow_line_below_the_dem_leaves_no_green_above_the_plate():
    p, M, elev, parts = _banded(snow_line_m=-100.0, lc_all=True)
    assert abs(parts["z_snow"] - p.plate_mm) < 1e-9        # clamped to the plate, not under
    verts = poster._cell_verts(parts["snow_cells"])
    assert verts.mean() > 0.8
    assert np.abs(parts["green"][verts] - p.plate_mm).max() < 1e-9
