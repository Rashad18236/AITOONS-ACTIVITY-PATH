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
    return poster.Params(**{"size_mm": 40.0, "frame_mm": 4.0, "res_mm": 0.5, **kw})


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
    M = _mpx(p)                                # 64
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


def test_compose_parts_groove_carved():
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    parts = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p)
    tpx = parts["track_px"]
    mid = (tpx[0] + tpx[-1]) / 2      # len(tpx)//2 was the endpoint, not the middle
    x, y = int(round(mid[0])), int(round(mid[1]))
    assert parts["surface"][y, x] - parts["green"][y, x] == p.groove_d_mm  # exactly groove depth
    assert 0 <= x < M and 0 <= y < M                       # track inside the relief plate


def test_compose_parts_shapes_and_caps():
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    lc = np.zeros((M, M), np.uint8)
    lc[5:15, 5:15] = 1                                     # water square, away from track
    lc[30:40, 30:40] = 2                                   # city square
    lc[0, 20:30] = 1                                       # water touching the plate edge
    parts = poster.compose_parts(track, elev, lc, bounds, p)
    assert parts["frame"].shape == (N, N) and parts["green"].shape == (M, M)
    assert parts["frame"][0, 0] == p.base_mm + p.frame_height_mm
    assert parts["green"].min() >= p.plate_mm - p.groove_d_mm - p.cap_mm - 1e-6
    w, c = parts["water"], parts["city"]
    assert w[10, 10] and not w[0, 0]                       # inside square, outside it
    assert not w[0, 25]                                    # 1px border excluded
    assert c[35, 35] and not c[10, 10]
    # cap depression: green is exactly cap_mm below surface inside a cap
    assert abs(parts["surface"][10, 10] - parts["green"][10, 10] - p.cap_mm) < 1e-9
    assert abs(parts["surface"][35, 35] - parts["green"][35, 35] - p.cap_mm) < 1e-9
    # groove cells are never cap cells — a cap slab there would fight the strip
    gmask = poster._groove_mask(parts["track_px"], (M, M), p)
    assert gmask[30:40, 30:40].any()      # the groove really does cross the city square
    assert not (w | c)[gmask].any()
    # so every cell drops by at most one of the two, never both stacked
    drop = parts["surface"] - parts["green"]
    assert drop.max() <= max(p.groove_d_mm, p.cap_mm) + 1e-9
    assert not (w & c).any()


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
    C, nrm = poster._offsets(parts["track_px"])
    half = (p.groove_w_mm / 2 - p.clearance_mm) / p.res_mm   # strip half-width, px
    step = np.arange(0, 3 * half, 0.25)                      # march out from centreline

    def reach(sign):                                         # contiguous carved px
        q = C[:, None] + sign * nrm[:, None] * step[None, :, None]
        ok = groove[q[..., 1].round().astype(int).clip(0, M - 1),
                    q[..., 0].round().astype(int).clip(0, M - 1)]
        return (np.where(ok.all(1), len(step), ok.argmin(1)) - 1) * 0.25

    return (reach(1.0) + reach(-1.0))[2:-2] * p.res_mm       # skip the square ends


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
        w = _groove_widths(p)
        assert w.min() >= p.groove_w_mm - 2 * p.clearance_mm, \
            f"res={res}: groove pinches to {w.min():.2f}mm, " \
            f"strip is {p.groove_w_mm - 2 * p.clearance_mm}mm"
        # and it holds its *nominal* width to within one pixel of rasterisation
        # slack — the seat margin above is too thin to catch a mechanism that
        # narrows the groove by 1/sqrt(2) on the diagonal.
        assert w.min() >= p.groove_w_mm - res, \
            f"res={res}: groove pinches to {w.min():.2f}mm, nominal {p.groove_w_mm}mm"


def test_compose_parts_text_embossed():
    p, N, fpx, elev, track, bounds = _synthetic()
    M = _mpx(p)
    p2 = _params(text="TEST", text_mm=3.0)
    frame = poster.compose_parts(track, elev, np.zeros((M, M), np.uint8), bounds, p2)["frame"]
    bar = frame[N - fpx:, :]
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
    M = _mpx(p)
    surface = np.full((M, M), p.plate_mm + 8.0)            # relief top, plate_mm z-base
    track_px = np.array([[10.0, 40.0], [40.0, 40.0], [55.0, 45.0]])
    m = poster.strip_mesh(track_px, surface, p)
    assert m.is_watertight
    assert m.is_winding_consistent   # watertight alone passes inside-out meshes
    assert m.volume > 0              # outward normals, not inverted
    zmin, zmax = m.bounds[0][2], m.bounds[1][2]
    assert abs(zmax - (surface[0, 0] + p.proud_mm)) < 1e-6
    assert abs(zmin - (surface[0, 0] - p.groove_d_mm)) < 1e-6
    # width across a straight section = groove - 2*clearance
    xs = m.vertices[np.abs(m.vertices[:, 0] - 25 * p.res_mm) < p.res_mm]
    width = xs[:, 1].max() - xs[:, 1].min()
    assert abs(width - (p.groove_w_mm - 2 * p.clearance_mm)) < 0.2


TRACK3 = np.array([[47.0, 8.0, 0], [47.2, 8.4, 2000], [47.5, 9.0, 3000]])


def _fake_fetches(monkeypatch, lc_code=0):
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_landcover",
                        lambda b, px, k, c: np.full((px, px), lc_code, np.uint8))


def test_build_poster_v2(monkeypatch):
    _fake_fetches(monkeypatch)
    frame_stl, bodies, path_stl = poster.build_poster(TRACK3, _params())
    assert frame_stl[:5] != b"solid" and len(frame_stl) > 84   # binary STL
    names = [b[1] for b in bodies]
    assert names == ["terrain"]                  # all-green lc -> caps absent
    assert bodies[0][2] == poster.COLORS["green"] and bodies[0][3] == 1
    assert bodies[0][0].is_watertight and bodies[0][0].volume > 0
    assert path_stl[:5] != b"solid" and len(path_stl) > 84


def test_build_poster_emits_water_cap(monkeypatch):
    _fake_fetches(monkeypatch, lc_code=1)        # whole plate is water
    _, bodies, _ = poster.build_poster(TRACK3, _params())
    assert [b[1] for b in bodies] == ["terrain", "water"]
    cap = bodies[1][0]
    assert bodies[1][2] == poster.COLORS["water"] and bodies[1][3] == 2
    assert cap.is_watertight and cap.is_winding_consistent and cap.volume > 0


def test_build_poster_derives_km_per_px(monkeypatch):
    """km_per_px must come from the bounds, not a constant: same track, half the
    plate -> ~half the ground size per pixel."""
    seen = []
    monkeypatch.setattr(poster, "fetch_elevation",
                        lambda b, px: np.tile(np.linspace(0, 500, px), (px, 1)))
    monkeypatch.setattr(poster, "fetch_landcover",
                        lambda b, px, k, c: seen.append((px, k, c))
                        or np.zeros((px, px), np.uint8))
    poster.build_poster(TRACK3, _params())
    poster.build_poster(TRACK3, _params(size_mm=80.0, frame_mm=8.0))
    (px_a, km_a, city_a), (px_b, km_b, _) = seen
    assert city_a == _params().city_min_km
    ground_km = px_a * km_a                                # plate side in ground km
    assert abs(px_b * km_b - ground_km) / ground_km < 0.01  # same track -> same ground
    assert 40 < ground_km < 200                            # ~1 deg lon at 47N, +margin
    assert abs(km_b - km_a * px_a / px_b) < 1e-9


def test_build_poster_rejects_oversized_grid():
    track = np.array([[47.0, 8.0, 0], [47.5, 9.0, 3000]])
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(size_mm=2500.0))   # typo, not a request
    with pytest.raises(ValueError):
        poster.build_poster(track, _params(res_mm=0.01))
    with pytest.raises(ValueError):   # groove would cut clean through the relief plate
        poster.build_poster(track, _params(plate_mm=1.0, groove_d_mm=1.5))


def test_generate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    _fake_fetches(monkeypatch, lc_code=1)      # water everywhere -> relief has 2 bodies
    client = TestClient(appmod.app)
    params = '{"size_mm": 40, "frame_mm": 4, "res_mm": 0.5, "text": "ZRH-GVA"}'
    r = client.post("/generate", files={"file": ("f.kml", KML.encode())},
                    data={"params": params})
    assert r.status_code == 200
    import base64
    j = r.json()
    assert set(j) == {"frame", "relief", "path"}
    frame, relief, path = (base64.b64decode(j[k]) for k in ("frame", "relief", "path"))
    assert frame[:5] != b"solid" and len(frame) > 84       # binary STL
    assert path[:5] != b"solid" and len(path) > 84
    assert relief[:2] == b"PK"                             # 3MF is a zip
    assert [b[0] for b in poster.read_3mf(relief)] == ["terrain", "water"]


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


def test_classify_landcover_palette():
    rgb = np.zeros((20, 20, 3), np.uint8)          # default -> green(0)
    rgb[2:8, 2:18] = (0, 100, 200)                 # water bar
    rgb[12:19, 2:19] = (250, 0, 0)                 # big city block
    rgb[10, 10] = (0, 100, 200)                    # 1px pond -> speckle, removed
    rgb[0, 0] = (247, 3, 2)                        # within +-10 of built-up, but 1px -> removed
    lc = poster.classify_landcover(rgb, km_per_px=0.5, city_min_km=1.5)
    assert lc[5, 10] == 1                          # water kept
    assert lc[15, 10] == 2                         # city kept
    assert lc[10, 10] == 0 and lc[0, 0] == 0       # speckles gone
    assert lc[1, 1] == 0


def test_classify_city_threshold_scales():
    rgb = np.zeros((40, 40, 3), np.uint8)
    rgb[10:14, 10:14] = (250, 0, 0)                # 4px-wide town
    # at 0.1 km/px a 1.5km city needs ~15px -> town removed
    assert (poster.classify_landcover(rgb, 0.1, 1.5) == 2).sum() == 0
    # at 1.0 km/px the kernel floors at 3 -> 4px town survives opening
    assert (poster.classify_landcover(rgb, 1.0, 1.5) == 2).sum() > 0


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
