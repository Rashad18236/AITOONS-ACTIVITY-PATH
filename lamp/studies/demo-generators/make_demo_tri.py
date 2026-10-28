"""Write a synthetic Zurich triathlon as one multisport FIT file, for demoing the UI.

Swim loop off Mythenquai, bike down the west shore to Thalwil and back over
Langnau/Adliswil, run out-and-back along the shore (partly on the bike road).
Usage: uv run python make_demo_tri.py OUT.fit
"""
import datetime as dt
import math
import sys

import numpy as np
from garmin_fit_sdk import Encoder, Profile

M = Profile["mesg_num"]
rng = np.random.default_rng(7)


def leg(waypoints, speed_ms):
    """Resample (lat, lon) waypoints at 1 fix per second at `speed_ms`, with GPS noise."""
    pts = []
    for (a, b), (c, d) in zip(waypoints[:-1], waypoints[1:]):
        dy = (c - a) * 111_320
        dx = (d - b) * 111_320 * math.cos(math.radians(a))
        n = max(int(math.hypot(dx, dy) / speed_ms), 1)
        for i in range(n):
            f = i / n
            pts.append((a + f * (c - a), b + f * (d - b)))
    pts.append(waypoints[-1])
    p = np.array(pts)
    return p + rng.normal(0, 3 / 111_320, p.shape)    # ~3 m of GPS scatter


T1 = (47.3530, 8.5360)
swim = leg([T1, (47.3535, 8.5395), (47.3535, 8.5480), (47.3580, 8.5480),
            (47.3580, 8.5400), (47.3540, 8.5385), T1], 1.0)
t1 = leg([T1, (47.3528, 8.5352)], 1.5)
bike = leg([(47.3528, 8.5352), (47.3450, 8.5345), (47.3230, 8.5480), (47.3070, 8.5560),
            (47.2910, 8.5650), (47.2880, 8.5410), (47.3110, 8.5250), (47.3300, 8.5290),
            (47.3450, 8.5330), (47.3528, 8.5352)], 9.0)
t2 = leg([(47.3528, 8.5352), (47.3530, 8.5360)], 1.5)
run = leg([(47.3530, 8.5360), (47.3450, 8.5345), (47.3380, 8.5345), (47.3450, 8.5345),
           (47.3530, 8.5360), (47.3600, 8.5385), (47.3665, 8.5410), (47.3600, 8.5385),
           (47.3530, 8.5360)], 3.3)


def hr_curve(n, lo, hi, wobble):
    x = np.linspace(0, 1, n)
    return lo + (hi - lo) * x + wobble * np.sin(x * 40) + rng.normal(0, 2, n)


sessions = [("swimming", swim, None), ("transition", t1, np.full(len(t1), 125.0)),
            ("cycling", bike, hr_curve(len(bike), 132, 158, 8)),
            ("transition", t2, np.full(len(t2), 150.0)),
            ("running", run, hr_curve(len(run), 150, 182, 5))]

t0 = dt.datetime(2026, 7, 19, 5, 30, tzinfo=dt.timezone.utc)
e = Encoder()
e.on_mesg(M["FILE_ID"], {"type": "activity", "manufacturer": "development", "product": 0,
                         "time_created": t0, "serial_number": 1})
t = t0
for i, (sport, pts, hr) in enumerate(sessions):
    start = t
    for k, (la, lo) in enumerate(pts):
        rec = {"timestamp": t, "position_lat": int(la / 180 * 2 ** 31),
               "position_long": int(lo / 180 * 2 ** 31)}
        if hr is not None:
            rec["heart_rate"] = int(np.clip(hr[k], 60, 220))
        e.on_mesg(M["RECORD"], rec)
        t += dt.timedelta(seconds=1)
    e.on_mesg(M["SESSION"], {"timestamp": t, "start_time": start,
                             "total_elapsed_time": float((t - start).total_seconds()),
                             "sport": sport, "message_index": i})
open(sys.argv[1], "wb").write(e.close())
print(f"wrote {sys.argv[1]}: " + ", ".join(f"{s} {len(p)} fixes" for s, p, _ in sessions))
