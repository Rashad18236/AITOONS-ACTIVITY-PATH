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
    mid = (tpx[0] + tpx[-1]) / 2      # len(tpx)//2 was the endpoint, not the middle
    x, y = int(round(mid[0])), int(round(mid[1]))
    assert surface[y, x] - hm[y, x] == p.groove_d_mm       # carved by exactly groove depth
    assert fpx <= x < N - fpx and fpx <= y < N - fpx       # track inside relief area


def test_strip_seats_in_groove_at_every_angle():
    """Fit invariant: the carved groove is never narrower than the strip.

    Rasterisation puts each edge within half a pixel of nominal, so absolute
    per-pixel containment is a sub-pixel stricter than the physical fit — the
    strip is slid in, not pinned to the centreline. Contiguous perpendicular
    width per station is the criterion. line(width=) fails this at ~45°."""
    p, N, fpx, elev, _, _ = _synthetic()
    a = np.linspace(0, np.pi / 2, 40)                    # arc sweeps 90° of heading
    trk = np.stack([47.0 + 0.3 * np.sin(a), 8.0 + 0.3 * (1 - np.cos(a)),
                    np.zeros_like(a)], 1)
    bounds = poster.track_bounds(trk, p.margin_pct)
    hm, surface, tpx = poster.compose(trk, elev, bounds, p)
    groove = (surface - hm) > 0
    C, nrm = poster._offsets(tpx)
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm   # strip half-width, px
    step = np.arange(0, 3 * half, 0.25)                      # march out from centreline

    def reach(sign):                                         # contiguous carved px
        q = C[:, None] + sign * nrm[:, None] * step[None, :, None]
        ok = groove[q[..., 1].round().astype(int).clip(0, N - 1),
                    q[..., 0].round().astype(int).clip(0, N - 1)]
        return (np.where(ok.all(1), len(step), ok.argmin(1)) - 1) * 0.25

    w = (reach(1.0) + reach(-1.0))[2:-2] * p.res_mm          # skip the square ends
    assert w.min() >= p.groove_w_mm - 2 * p.clearance_mm, \
        f"groove pinches to {w.min():.2f}mm, strip is {p.groove_w_mm - 2 * p.clearance_mm}mm"


def test_compose_text_embossed():
    p, N, fpx, elev, track, bounds = _synthetic()
    p2 = _params(text="TEST", text_mm=3.0)
    hm, _, _ = poster.compose(track, elev, bounds, p2)
    bar = hm[N - fpx:, :]
    assert bar.max() > p.base_mm + p.frame_height_mm       # something raised on bottom bar


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
    N = int(p.size_mm / p.res_mm)
    surface = np.full((N, N), 10.0)
    track_px = np.array([[10.0, 40.0], [40.0, 40.0], [70.0, 45.0]])
    m = poster.strip_mesh(track_px, surface, p)
    assert m.is_watertight
    assert m.is_winding_consistent   # watertight alone passes inside-out meshes
    assert m.volume > 0              # outward normals, not inverted
    zmin, zmax = m.bounds[0][2], m.bounds[1][2]
    assert abs(zmax - (10.0 + p.proud_mm)) < 1e-6
    assert abs(zmin - (10.0 - p.groove_d_mm)) < 1e-6
    # width across a straight section = groove - 2*clearance
    xs = m.vertices[np.abs(m.vertices[:, 0] - 25 * p.res_mm) < p.res_mm]
    width = xs[:, 1].max() - xs[:, 1].min()
    assert abs(width - (p.groove_w_mm - 2 * p.clearance_mm)) < 0.2


def test_build_poster_end_to_end(monkeypatch):
    p = _params()
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda bounds, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    track = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])
    stl_a, stl_b = poster.build_poster(track, p)
    assert stl_a[:5] != b"solid" and len(stl_a) > 84   # binary STL
    assert len(stl_b) > 84


def test_build_poster_rejects_oversized_grid():
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(size_mm=2500.0))   # typo, not a request
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(res_mm=0.01))


def test_generate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda bounds, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    client = TestClient(appmod.app)
    params = '{"size_mm": 40, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files={"file": ("f.kml", KML.encode())},
                    data={"params": params})
    assert r.status_code == 200
    import base64
    assert len(base64.b64decode(r.json()["poster"])) > 84
    assert len(base64.b64decode(r.json()["path"])) > 84


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
