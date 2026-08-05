import numpy as np
import pytest
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
    return poster.Params(**{"size_mm": 40.0, "frame_mm": 4.0, "res_mm": 0.5, **kw})


def _synthetic():
    p = _params()
    N = int(p.size_mm / p.res_mm)              # 80
    fpx = int(p.frame_mm / p.res_mm)           # 8
    inner = N - 2 * fpx                        # 64
    elev = np.tile(np.linspace(0, 1000, inner), (inner, 1))  # E-W gradient
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    bounds = poster.track_bounds(track, p.margin_pct)
    return p, N, fpx, elev, track, bounds


def test_compose_shapes_and_frame():
    p, N, fpx, elev, track, bounds = _synthetic()
    hm, surface, tpx = poster.compose(track, elev, bounds, p)
    assert hm.shape == (N, N) and surface.shape == (N, N)
    assert hm[0, 0] == p.base_mm + p.frame_height_mm       # frame ring is flat
    assert abs(hm[N // 2, fpx] - p.base_mm) < p.relief_mm  # relief starts at base
    assert hm[fpx:N-fpx, fpx:N-fpx].max() <= p.base_mm + p.relief_mm * p.exaggeration + 1e-6


def test_compose_groove_carved():
    p, N, fpx, elev, track, bounds = _synthetic()
    hm, surface, tpx = poster.compose(track, elev, bounds, p)
    mid = tpx[len(tpx) // 2]
    x, y = int(round(mid[0])), int(round(mid[1]))
    assert surface[y, x] - hm[y, x] == p.groove_d_mm       # carved by exactly groove depth
    assert fpx <= x < N - fpx and fpx <= y < N - fpx       # track inside relief area


def test_compose_text_embossed():
    p, N, fpx, elev, track, bounds = _synthetic()
    p2 = _params(text="TEST", text_mm=3.0)
    hm, _, _ = poster.compose(track, elev, bounds, p2)
    bar = hm[N - fpx:, :]
    assert bar.max() > p.base_mm + p.frame_height_mm       # something raised on bottom bar
