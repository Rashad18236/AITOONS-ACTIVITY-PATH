"""Write a synthetic Strava-style GPX of a Zermatt trail run, for testing the poster tool.

Loop: Zermatt -> Furi -> Riffelalp -> Riffelberg -> Riffelsee -> Grünsee -> Findeln
-> Sunnegga -> Zermatt. Elevation comes from the same terrarium DEM the tool uses, so
pace slows and heart rate rises on the climbs. 1 fix per second, ~2 m GPS scatter,
heart rate and cadence in Garmin's TrackPointExtension, as Strava exports it.
Usage: uv run python make_zermatt_run.py OUT.gpx   (run from the project folder)
"""
import datetime as dt
import math
import sys

import numpy as np

import poster

WAYPOINTS = [  # (lat, lon), a loop
    (46.0207, 7.7491),   # Zermatt, Bahnhofstrasse
    (46.0150, 7.7470),   # along the Matter Vispa
    (46.0080, 7.7420),
    (46.0035, 7.7385),   # Furi
    (46.0020, 7.7500),
    (46.0005, 7.7650),   # Riffelalp
    (45.9965, 7.7740),
    (45.9920, 7.7830),   # Riffelberg
    (45.9885, 7.7815),
    (45.9855, 7.7790),   # Riffelsee
    (45.9930, 7.7900),
    (46.0010, 7.7975),
    (46.0090, 7.8020),   # Grünsee
    (46.0120, 7.7900),
    (46.0135, 7.7800),   # Findeln
    (46.0140, 7.7700),   # Sunnegga
    (46.0170, 7.7610),
    (46.0195, 7.7540),
    (46.0207, 7.7491),   # back in Zermatt
]
rng = np.random.default_rng(15)
R = 6_371_000.0


def densify(wp, step_m=5.0):
    out = []
    for (a, b), (c, d) in zip(wp[:-1], wp[1:]):
        dy = math.radians(c - a) * R
        dx = math.radians(d - b) * R * math.cos(math.radians(a))
        n = max(int(math.hypot(dx, dy) / step_m), 1)
        out += [(a + (c - a) * i / n, b + (d - b) * i / n) for i in range(n)]
    out.append(wp[-1])
    return np.array(out)


path = densify(WAYPOINTS)
lat, lon = path[:, 0], path[:, 1]
seg = np.hypot(np.radians(np.diff(lat)) * R,
               np.radians(np.diff(lon)) * R * np.cos(np.radians(lat[:-1])))
dist = np.r_[0, np.cumsum(seg)]

# elevation from the tool's own DEM (terrarium tiles), nearest pixel
bounds = poster.track_bounds(np.column_stack([lat, lon, np.zeros_like(lat)]), 15.0)
N = 768
dem = poster.fetch_elevation(bounds, N)
px = poster._to_px(zip(lat, lon), bounds, N)
ele = dem[np.clip(px[:, 1].round().astype(int), 0, N - 1),
          np.clip(px[:, 0].round().astype(int), 0, N - 1)].astype(float)
ele = np.convolve(np.pad(ele, 10, mode="edge"), np.ones(21) / 21, "valid")   # ~100 m smoothing

grade = np.gradient(ele, dist)                      # rise per metre along the route
v = np.where(grade > 0, 3.0 / (1 + 10 * grade),     # running uphill slows to a hike
             np.where(grade < -0.25, 2.5, np.minimum(3.0 * (1 + 2 * -grade), 4.0)))
t_at = np.r_[0, np.cumsum(seg / v[:-1])]            # seconds at each densified point

secs = np.arange(0, int(t_at[-1]) + 1)
d_s = np.interp(secs, t_at, dist)
la = np.interp(d_s, dist, lat)
lo = np.interp(d_s, dist, lon)
el = np.interp(d_s, dist, ele)
g_s = np.interp(d_s, dist, grade)

# GPS scatter: smoothed random walk, ~2 m
noise = np.cumsum(rng.normal(0, 0.6, (len(secs), 2)), 0)
noise -= np.convolve(noise[:, 0], np.ones(61) / 61, "same")[:, None] * 0  # keep it simple
noise = np.apply_along_axis(lambda c: c - np.convolve(c, np.ones(121) / 121, "same"), 0, noise)
la += noise[:, 0] / R * 180 / math.pi
lo += noise[:, 1] / (R * math.cos(math.radians(46.0))) * 180 / math.pi

# heart rate: effort follows the grade with ~40 s lag, plus drift and noise
target = np.where(g_s > 0.02, 125 + 270 * g_s, np.where(g_s < -0.02, 138 + 60 * g_s, 146))
target = np.clip(target, 112, 184) + secs / 600 * 0.6
hr = np.empty_like(target)
hr[0] = 100
for i in range(1, len(target)):
    hr[i] = hr[i - 1] + (target[i] - hr[i - 1]) / 40
hr = np.clip(hr + rng.normal(0, 1.5, len(hr)), 60, 200).round().astype(int)
cad = np.clip(np.where(g_s > 0.12, 62, 84) + rng.normal(0, 2, len(secs)), 50, 95).round().astype(int)

t0 = dt.datetime(2026, 8, 15, 5, 30, tzinfo=dt.timezone.utc)
pts = "".join(
    f'   <trkpt lat="{a:.7f}" lon="{b:.7f}">\n    <ele>{e:.1f}</ele>\n'
    f'    <time>{(t0 + dt.timedelta(seconds=int(s))).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>\n'
    f'    <extensions>\n     <gpxtpx:TrackPointExtension>\n      <gpxtpx:hr>{h}</gpxtpx:hr>\n'
    f'      <gpxtpx:cad>{c}</gpxtpx:cad>\n     </gpxtpx:TrackPointExtension>\n    </extensions>\n'
    f'   </trkpt>\n'
    for a, b, e, s, h, c in zip(la, lo, el, secs, hr, cad))
gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
       '<gpx creator="StravaGPX" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
       'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd '
       'http://www.garmin.com/xmlschemas/GpxExtensions/v3 http://www.garmin.com/xmlschemas/GpxExtensionsv3.xsd '
       'http://www.garmin.com/xmlschemas/TrackPointExtension/v1 http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd" '
       'version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
       'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
       'xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3">\n'
       f' <metadata>\n  <time>{t0.strftime("%Y-%m-%dT%H:%M:%SZ")}</time>\n </metadata>\n'
       ' <trk>\n  <name>Zermatt Trail Run</name>\n  <type>running</type>\n  <trkseg>\n'
       + pts + '  </trkseg>\n </trk>\n</gpx>\n')
open(sys.argv[1], "w", encoding="utf-8").write(gpx)

climb = float(np.clip(np.diff(ele), 0, None).sum())
dur = secs[-1]
print(f"wrote {sys.argv[1]}: {len(secs)} fixes, {dist[-1]/1000:.1f} km, +{climb:.0f} m, "
      f"{int(ele.min())}-{int(ele.max())} m, {dur // 3600}h{dur % 3600 // 60:02d}, "
      f"HR {hr.min()}-{hr.max()} bpm")
