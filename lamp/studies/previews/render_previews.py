"""Preview renders for the theme + close-up-detail proposal. Real DEM and OSM data,
flat 2D shaded mock-ups (not the printed mesh). Writes PNGs next to this file.
Run from the project folder: PYTHONPATH=. uv run python .../render_previews.py"""
import math, sys, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import poster, activity

OUT = os.path.dirname(os.path.abspath(__file__))
PX = 720                       # relief pixels per side
FRAME = 44                     # frame px (≈12mm of 195 → scaled)
CHIN = 58

# ---- themes (plan table) ----------------------------------------------------
T = {
 "classic":       dict(label="Classic green terrain",            frame="#222222", text="#FFFFFF", land="#4CAF50", water="#2196F3", band="#9E9E9E", detail=None,      path="#CC2222", groups=set()),
 "city_marathon": dict(label="City marathon — asphalt",          frame="#222222", text="#FFFFFF", land="#CFCBC2", water="#3F8FD2", band=None,      detail="#4A4A4A", path="#E53935", groups={"streets","rail","buildings"}),
 "dark_orange":   dict(label="Dark terrain — orange route",      frame="#111111", text="#FC4C02", land="#2B2B2B", water="#355C7D", band=None,      detail="#6E6E6E", path="#FC4C02", groups={"streets","trails"}),
 "alpine_hiking": dict(label="Alpine hiking — signpost-yellow trails", frame="#3E2A1E", text="#FFFFFF", land="#CFE3B4", water="#6FA8DC", band="#B9A58B", detail="#FFCC00", path="#D62828", groups={"trails","streets","rail"}),
 "alpine_winter": dict(label="Alpine winter — snow and slate",   frame="#1A1A2E", text="#FFFFFF", land="#B8C7D6", water="#4A90C2", band="#FFFFFF", detail="#4B5563", path="#E63946", groups={"streets","trails"}),
 "triathlon":     dict(label="Triathlon — red/black",            frame="#111111", text="#FFFFFF", land="#2B2B2B", water="#2A6FB5", band="#666666", detail=None,      path="#ED1C24", groups={"streets"}, legs=("#FFFFFF","#ED1C24","#FFC300")),
 "grand_tour":    dict(label="Grand-tour cycling — yellow/pink/red", frame="#222222", text="#FFFFFF", land="#6B8E23", water="#2196F3", band="#9E9E9E", detail="#4A4A4A", path="#FFD400", groups={"streets"}, legs=("#FFFFFF","#F08CAE","#D52B1E")),
 "trail_slate":   dict(label="Trail / ultra — slate and amber",  frame="#1C1F26", text="#FFFFFF", land="#4F5B66", water="#2F6690", band="#8A949E", detail="#E0E0E0", path="#F2C14E", groups={"trails","streets"}),
 "mono_dark":     dict(label="Dark mode — one accent",           frame="#111111", text="#FFFFFF", land="#1E1E1E", water="#2C3E50", band=None,      detail="#3A3A3A", path="#00E5A0", groups={"streets"}),
 "forest":        dict(label="Forest — deep greens",             frame="#1B2A1B", text="#F4EAD5", land="#2F5D3A", water="#5B9BD5", band="#C9D1C8", detail="#D9B36B", path="#FF8C42", groups={"trails","streets"}),
}
LEGS_DEFAULT = ("#FFFFFF", "#CC2222", "#F4EE2A")
T["alpine_hiking"]["legs"] = ("#FFFFFF", "#D62828", "#FF8C42")

# ---- zoom tiers (plan: streets ≤35, trails ≤40, rail ≤150, buildings ≤12 m/mm) ----
TIERS = [("streets", 35, "residential|unclassified|living_street|service|pedestrian"),
         ("trails", 40, "path|footway|track|steps|bridleway|cycleway"),
         ("tertiary", 60, "tertiary"), ("secondary", 150, "secondary"),
         ("primary", 400, "primary"), ("trunk", 1200, "trunk"), ("motorway", 3000, "motorway")]
RAIL_MAX, BLD_MAX = 150, 12

def hexrgb(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

def scene_bounds(legs):
    walls = activity.group_walls(legs)
    return poster.legs_bounds([l for _, ls in walls for l in ls], 15.0), walls

def m_per_mm(b):
    lat = poster._unmerc(0, (b[1]+b[3])/2)[1]
    return (b[2]-b[0]) * 6371000 * math.cos(math.radians(lat)) / 488 / 0.4   # the 216 relief

def fetch(b):
    w, s = poster._unmerc(b[0], b[1]); e, n = poster._unmerc(b[2], b[3])
    q = ('[out:json][timeout:120][maxsize:536870912][bbox:%f,%f,%f,%f];'
         '(way["natural"="water"];relation["natural"="water"];way["waterway"="riverbank"];'
         'relation["waterway"="riverbank"];way["natural"="coastline"];'
         'way["highway"];way["railway"="rail"];way["building"];relation["building"];relation["route"="hiking"];);out geom;' % (s, w, n, e))
    return poster._overpass(q)

def masks(els, b, groups, mpm):
    tag = lambda el, k: (el.get("tags") or {}).get(k)
    pts = lambda el: [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
    tier_of = {hw: n for n, _, rx in TIERS for hw in rx.split("|")}
    classes = [n for n, lim, _ in TIERS if mpm <= lim and (n not in ("streets", "trails") or n in groups)]
    w_px = round(PX / 488 * 3)   # ROAD_MM = 3 cells on the 488 grid
    # trails = ways that belong to a signposted hiking route (Swiss yellow network), not every footpath
    route_ways = [[(p["lat"], p["lon"]) for p in m.get("geometry") or []]
                  for el in els if tag(el, "route") == "hiking"
                  for m in el.get("members", ()) if m.get("type") == "way"]
    items = {n: [] for n, _, _ in TIERS}
    for el in els:
        hw = tag(el, "highway")
        if hw and tier_of.get(hw) in classes and tier_of[hw] != "trails" and not tag(el, "tunnel") and len(pts(el)) >= 2:
            items[tier_of[hw]].append((pts(el), w_px))
    if "trails" in classes:
        items["trails"] = [(g, w_px) for g in route_ways if len(g) >= 2]
    rail = [(pts(el), w_px) for el in els if tag(el, "railway") == "rail" and "rail" in groups and mpm <= RAIL_MAX
            and not tag(el, "tunnel") and len(pts(el)) >= 2]
    while True:   # the existing ROAD_MAX_FRAC rule: drop the finest class while detail > 15% of the plate
        detail = poster._road_mask(rail + [it for c in classes for it in items[c]], b, PX)
        if detail.mean() <= 0.15 or not classes:
            break
        print("    drop", classes[0], f"({detail.mean():.0%})"); classes.pop(0)
    water = [el for el in els if (tag(el, "natural") == "water" or tag(el, "waterway") == "riverbank")]
    bld = [el for el in els if tag(el, "building")] if ("buildings" in groups and mpm <= BLD_MAX) else []
    big = [it for c in classes if c not in ("streets", "trails") for it in items[c]]
    return dict(water=poster._water_mask_from_elements(water, b, PX), detail=detail,
                major=poster._road_mask(big, b, PX),
                buildings=poster._water_mask_from_elements(bld, b, PX) if bld else np.zeros((PX, PX), bool),
                classes=classes, frac=float(detail.mean()))


def hillshade(elev):
    gy, gx = np.gradient(elev)
    az, alt = math.radians(315), math.radians(45)
    slope = np.arctan(2.0 * np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    sh = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - asp)
    return np.clip(sh, 0, 1)

def shade(rgb, sh, k=0.55):
    base = np.array(hexrgb(rgb), float)
    return base * (1 - k + k * sh[..., None] * 1.3)

def compose(theme, elev, M, walls, b, snow=2000.0, caption=("", ""), detail_on=True):
    t = T[theme]
    sh = hillshade(poster._smooth(elev, 2))
    img = shade(t["land"], sh)
    if t["band"]:
        band = elev >= snow
        img[band] = shade(t["band"], sh)[band]
    img[M["water"]] = np.array(hexrgb(t["water"]), float) * (0.9 + 0.1 * sh[M["water"], None])
    det = t["detail"] or t["band"] or "#9E9E9E"
    if detail_on:
        img[M["detail"]] = hexrgb(det)
        bld = M["buildings"]
        img[bld] = np.array(hexrgb(det), float) * 1.1
    else:
        img[M["major"]] = hexrgb(det)
    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img, "RGB")
    # walls: a line with a soft shadow, one colour per sport
    d = ImageDraw.Draw(im)
    legs = t.get("legs", LEGS_DEFAULT)
    names = [n for n, _ in walls]
    for (name, ls), in zip(walls):
        col = t["path"] if name == "strip" else legs[["swim", "bike", "run"].index(name)]
        for l in ls:
            q = poster._to_px(list(zip(l.lat, l.lon)), b, PX)
            q = q[::max(1, len(q) // 1500)]
            pts = [tuple(v) for v in q]
            d.line([(x + 3, y + 4) for x, y in pts], fill=(0, 0, 0), width=7)
    sh_im = im.filter(ImageFilter.GaussianBlur(2))
    im = Image.blend(im, sh_im, 0.0)
    d = ImageDraw.Draw(im)
    for (name, ls), in zip(walls):
        col = t["path"] if name == "strip" else legs[["swim", "bike", "run"].index(name)]
        for l in ls:
            q = poster._to_px(list(zip(l.lat, l.lon)), b, PX)
            q = q[::max(1, len(q) // 1500)]
            d.line([tuple(v) for v in q], fill=hexrgb(col), width=5, joint="curve")
    # frame + caption
    W = PX + 2 * FRAME; H = PX + 2 * FRAME + CHIN
    out = Image.new("RGB", (W, H), hexrgb(t["frame"]))
    out.paste(im, (FRAME, FRAME))
    dd = ImageDraw.Draw(out)
    f1 = ImageFont.truetype(poster.FONT_PATHS[0][0], 30); f2 = ImageFont.truetype(poster.FONT_PATHS[0][0], 20)
    y = PX + FRAME + 8
    dd.text((W / 2, y), caption[0], font=f1, fill=hexrgb(t["text"]), anchor="mt")
    dd.text((W / 2, y + 36), caption[1], font=f2, fill=hexrgb(t["text"]), anchor="mt")
    return out

def oblique(im, elev_deg):
    """Fake a camera at elev_deg above the table: perspective squash + horizon."""
    W, H = im.size
    k = math.sin(math.radians(elev_deg))
    h2 = int(H * k)
    top_inset = int(W * (0.33 if elev_deg < 45 else 0.14))
    src = [(0, 0), (W, 0), (W, H), (0, H)]
    dst = [(top_inset, 0), (W - top_inset, 0), (W, h2), (0, h2)]
    coeffs = _persp(dst, src)
    bg = Image.new("RGB", (W, h2 + 40), (232, 228, 220))
    warped = im.transform((W, h2), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(232, 228, 220))
    bg.paste(warped, (0, 20))
    return bg

def _persp(pa, pb):
    A = []
    for (x, y), (X, Y) in zip(pa, pb):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    Bv = np.array([v for p in pb for v in p], float)
    return tuple(np.linalg.solve(np.array(A, float), Bv))

def city_loop():
    """Synthetic 5 km city run: Zurich old town / Limmat / Bahnhofstrasse (≈ 10 m/mm at 216)."""
    wp = [(47.3769, 8.5417), (47.3741, 8.5399), (47.3706, 8.5392), (47.3672, 8.5399), (47.3660, 8.5440),
          (47.3690, 8.5460), (47.3725, 8.5455), (47.3752, 8.5440), (47.3775, 8.5438), (47.3769, 8.5417)]
    pts = []
    for (a, b), (c, d) in zip(wp[:-1], wp[1:]):
        n = 60
        pts += [(a + (c - a) * i / n, b + (d - b) * i / n) for i in range(n)]
    pts.append(wp[-1])
    la, lo = np.array(pts).T
    return [activity.Leg("run", la, lo, np.arange(len(la), dtype=float), np.full(len(la), 150.0), "city.gpx")]

def main():
    scenes = {
        "zermatt": (activity.read_activity([("z.gpx", open(os.path.expanduser("~/Desktop/zermatt-trail-run/Zermatt_Trail_Run.gpx"), "rb"))]),
                    ("ZERMATT TRAIL RUN", "14.2 KM · +1735 M · 15.08.2026")),
        "zurich_tri": (activity.read_activity([("t.fit", open(os.path.expanduser("~/Desktop/activity-poster-demo/zurich-triathlon.fit"), "rb"))]),
                       ("ZÜRICH TRIATHLON 2026", "3.8 · 180 · 42.2")),
        "zurich_city": (city_loop(), ("ZÜRICH CITY 5K", "ALTSTADT · 05.04.2026")),
    }
    for key, (legs, cap) in scenes.items():
        b, walls = scene_bounds(legs)
        mpm = m_per_mm(b)
        elev = poster.fetch_elevation(b, PX)
        els = fetch(b)
        print(key, f"{mpm:.1f} m/mm, {len(els)} osm elements")
        for theme, t in T.items():
            M = masks(els, b, t["groups"], mpm)
            compose(theme, elev, M, walls, b, caption=cap).save(f"{OUT}/{key}__{theme}.png", optimize=True)
            print("  ", theme, "classes", M["classes"], f"detail {M['frac']:.1%}", "bld", int(M["buildings"].sum()))
        if key == "zermatt":
            M = masks(els, b, set(), mpm)
            today = compose("classic", elev, M, walls, b, caption=cap, detail_on=False)
            today.save(f"{OUT}/zermatt__today.png", optimize=True)
            M2 = masks(els, b, {"streets", "trails", "rail"}, mpm)
            close = compose("classic", elev, M2, walls, b, caption=cap)
            close.save(f"{OUT}/zermatt__closeup.png", optimize=True)
            oblique(today, 58).save(f"{OUT}/camera__today.png", optimize=True)
            oblique(close, 35).save(f"{OUT}/camera__closer.png", optimize=True)
    print("done")

if __name__ == "__main__":
    main()
