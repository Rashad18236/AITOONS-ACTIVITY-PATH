"""The two chosen lid recipes on their hard cases: contour lines on hills (spacing picked from the
terrain) and the city map from 5 km to 42 km, all drawn at the lid's own scale. Also prints each
test route's climb, to set the rule that picks the recipe.
Run from the Activity Path Poster folder:
  PYTHONPATH="$PWD" uv run python .../litho/render_choice.py
"""
import hashlib, json, os, pickle, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_recipes as RR

RL, RF, poster = RR.RL, RR.RF, RR.poster
RP, activity = RF.RP, RF.activity
NICE = (5, 10, 20, 25, 50, 100, 200, 250, 500)
MAX_LEVELS = 12
MIN_GAP_MM = 2.0             # contour lines at least this far apart on the steepest tenth of the map
LID_BLD_MAX = 30.0           # m per printed mm: buildings read as blocks up to here on the lid


def lid_mpm(b):
    return RP.m_per_mm(b) * 195.2 / (2 * RR.MAP_R)


def lid_masks(z):
    RP.PX = z.N
    old, RP.BLD_MAX = RP.BLD_MAX, LID_BLD_MAX
    try:
        return RP.masks(RP.fetch(z.b), z.b, z.theme["groups"], lid_mpm(z.b))
    finally:
        RP.BLD_MAX = old


def interval(z, e):
    """Round spacing: at most MAX_LEVELS lines, and MIN_GAP_MM apart where the ground is steepest."""
    gy, gx = np.gradient(e, lid_mpm(z.b) * 2 * RR.MAP_R / z.N)
    need = max((np.percentile(e, 99) - np.percentile(e, 1)) / MAX_LEVELS,
               MIN_GAP_MM * lid_mpm(z.b) * np.percentile(np.hypot(gx, gy), 90))
    return next((v for v in NICE if v >= need), NICE[-1])


def lines(c):
    e = RR.edges(c)
    return e | np.roll(e, -1, 0) | np.roll(e, -1, 1)          # 2 px; grown by 1 = 0.85 mm


def contours(z, iv=None):
    e = poster._smooth(np.asarray(z.elev, float), 3)
    iv = iv or interval(z, e)
    T = np.full(e.shape, 1.2)
    T[RL.grow(lines(np.floor(e / iv)), 1)] = 2.6
    T[RL.grow(lines(np.floor(e / (5 * iv))), 2)] = 3.0
    return T, iv


def climb(z):
    e = RL.route_profile(z)
    return float(e.max() - e.min())


def km(leg):
    la, lo = np.radians(leg.lat), np.radians(leg.lon)
    a = np.sin(np.diff(la) / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2
    return float(np.sum(2 * 6371 * np.arcsin(np.sqrt(a))))


def synthetic(wp, name, n=60):
    pts = []
    for (a, b), (c, d) in zip(wp[:-1], wp[1:]):
        pts += [(a + (c - a) * i / n, b + (d - b) * i / n) for i in range(n)]
    pts.append(wp[-1])
    la, lo = np.array(pts).T
    return activity.Leg("run", la, lo, np.arange(len(la), dtype=float), np.full(len(la), 150.0), name)


# Triemli, up to Uto Kulm, the ridge to Felsenegg, down to Leimbach, back
UTO = [(47.3668, 8.4955), (47.3575, 8.4900), (47.3497, 8.4919), (47.3400, 8.4985), (47.3305, 8.5030),
       (47.3240, 8.5070), (47.3290, 8.5160), (47.3380, 8.5200), (47.3480, 8.5150), (47.3590, 8.5060),
       (47.3668, 8.4955)]
# lake shore, Hirslanden, Zurichberg, Oerlikon, Wipkingen, Altstetten, Wiedikon, Enge, Wollishofen
CITY42 = [(47.3667, 8.5450), (47.3540, 8.5560), (47.3400, 8.5720), (47.3520, 8.5800), (47.3600, 8.5700),
          (47.3780, 8.5600), (47.3950, 8.5650), (47.4110, 8.5450), (47.4060, 8.5200), (47.3930, 8.5280),
          (47.3900, 8.4850), (47.3780, 8.4750), (47.3700, 8.5100), (47.3600, 8.5300), (47.3400, 8.5320),
          (47.3330, 8.5420), (47.3560, 8.5370), (47.3667, 8.5450)]


def light_fetch(b):
    """Water and main roads only: all a marathon-size lid draws, and light enough for Overpass."""
    f = os.path.join(HERE, "osm_light_" + hashlib.sha1(json.dumps([round(v, 7) for v in b]).encode()).hexdigest()[:12] + ".pkl")
    if os.path.exists(f):
        return pickle.load(open(f, "rb"))
    w, s = poster._unmerc(b[0], b[1])
    e, n = poster._unmerc(b[2], b[3])
    q = ('[out:json][timeout:120][maxsize:536870912][bbox:%f,%f,%f,%f];'
         '(way["natural"="water"];relation["natural"="water"];way["waterway"="riverbank"];'
         'relation["waterway"="riverbank"];way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"];'
         'way["railway"="rail"];);out geom;' % (s, w, n, e))
    els = poster._overpass(q)
    pickle.dump(els, open(f, "wb"))
    return els


def city_scene(leg, fetch=None, bounds=None):
    real = RP.fetch
    if fetch:
        RP.fetch = fetch
    try:
        z = RF.Scene([leg], 360, "city_marathon", walls=[("run", [leg])], bounds=bounds)
        z.M = lid_masks(z)
    finally:
        RP.fetch = real
    print("  lid classes:", z.M["classes"], f"detail {z.M['frac']:.0%}", "buildings", bool(z.M["buildings"].any()))
    return z


def main():
    rows = []
    real, RP.fetch = RP.fetch, lambda b: []           # no lakes in the Uetliberg box
    uto = synthetic(UTO, "uto.gpx")
    zh = RF.Scene([uto], 360, "alpine_hiking", walls=[("run", [uto])])
    RP.fetch = real
    cap = ("UETLIBERG TRAIL RUN", f"{km(uto):.1f} KM  ·  26.10.2026")
    RR.pair(*RR.disc(RR.finish_map(zh, contours(zh, 50)[0]), caption=cap), "choice_hill_50")
    T, iv = contours(zh)
    RR.pair(*RR.disc(RR.finish_map(zh, T), caption=cap), "choice_hill")
    rows.append(("Uetliberg hill loop (synthetic)", climb(zh), iv, lid_mpm(zh.b)))

    z = RF.Scene(RF.load("zermatt"), 360, "alpine_hiking")
    T, iv = contours(z)
    RR.pair(*RR.disc(RR.finish_map(z, T)), "choice_mountain")
    Tt, rt = RR.disc(RR.finish_map(z, T), ring=(0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.4, 2.8, 3.2))
    RR.save(RR.pad(RR.lit(Tt, rt), RR.DARK), "litho_testlid", 0.8)
    rows.append(("Zermatt trail run (synthetic)", climb(z), iv, lid_mpm(z.b)))

    old = RF.Scene(RF.load("city"), 360, "city_marathon")
    old.M = lid_masks(old)
    RR.pair(*RR.disc(RR.finish_map(old, RR.city_map(old)), caption=("ZURICH OLD TOWN 5K", "5.0 KM  ·  12.10.2026")), "choice_city5k")
    rows.append(("Zurich old town 5K (synthetic)", climb(old), contours(old)[1], lid_mpm(old.b)))

    run = next(l for l in RF.load("tri") if l.sport == "run")
    lake = city_scene(run, bounds=poster.legs_bounds([run], 15.0))
    RR.pair(*RR.disc(RR.finish_map(lake, RR.city_map(lake)), caption=("ZURICH LAKESIDE RUN", f"{km(run):.1f} KM  ·  12.07.2026")), "choice_city10k")
    rows.append(("Zurich lakeside run (triathlon demo)", climb(lake), contours(lake)[1], lid_mpm(lake.b)))

    m42 = synthetic(CITY42, "z42.gpx", 80)
    mar = city_scene(m42, fetch=light_fetch)
    RR.pair(*RR.disc(RR.finish_map(mar, RR.city_map(mar)), caption=("ZURICH CITY RUN", f"{km(m42):.1f} KM  ·  19.04.2026")), "choice_marathon")
    rows.append(("Zurich city loop (synthetic)", climb(mar), contours(mar)[1], lid_mpm(mar.b)))

    print(f"\n  {'route':40s} {'climb m':>8s} {'contour m':>10s} {'lid m/mm':>9s}")  # climb = elevation range along the route
    for name, c, i, m in rows:
        print(f"  {name:40s} {c:8.0f} {i:10d} {m:9.0f}")
    print(f"  city loop length {km(m42):.1f} km")


if __name__ == "__main__":
    main()
