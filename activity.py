"""Customer activity files -> legs (sport + lat/lon/time/heart rate). No geometry."""
import bisect
import datetime as dt
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import BinaryIO
import numpy as np
from garmin_fit_sdk import Decoder, Stream

HR_WINDOW_S = 30.0  # rolling heart-rate window: optical sensors spike and drop out
HR_GAP_S = 15.0  # a Health route point further than this from every HR record stays NaN
MAX_SPEED_MS = 60.0  # a fix reached faster than this (216 km/h) is a GPS spike
_HK = "HKWorkoutActivityType"
_TRI = ("swim", "bike", "run")


@dataclass
class Leg:
    """One sport's points. t is POSIX seconds, hr bpm with NaN where the file has none."""
    sport: str
    lat: np.ndarray
    lon: np.ndarray
    t: np.ndarray
    hr: np.ndarray
    source: str = ""


def sport_family(raw: str) -> str:
    """swim/bike/run/transition from any exporter's sport name; "" when unknown or numeric."""
    s = (raw or "").strip().lower()
    if "transition" in s:
        return "transition"
    if "swimbikerun" in s:  # a whole Apple Watch triathlon, which the Health reader refuses
        return ""
    if "swim" in s:
        return "swim"
    if any(k in s for k in ("cycl", "bik", "ride")):
        return "bike"
    if any(k in s for k in ("run", "walk", "hik")):
        return "run"
    return "" if s.isdigit() or not s else s


def smooth_hr(t: np.ndarray, hr: np.ndarray, window_s: float = HR_WINDOW_S) -> np.ndarray:
    """Mean of the finite samples within ±window_s/2 of each t (t ascending); NaN when none.
    Cumulative sums + searchsorted, so O(n) for a whole Ironman."""
    ok = np.isfinite(hr)
    s = np.r_[0.0, np.cumsum(np.where(ok, hr, 0.0))]
    c = np.r_[0, np.cumsum(ok)]
    lo = np.searchsorted(t, t - window_s / 2, "left")
    hi = np.searchsorted(t, t + window_s / 2, "right")
    n = c[hi] - c[lo]
    return np.divide(s[hi] - s[lo], n, out=np.full(len(t), np.nan), where=n > 0)


def _local(el):
    return el.tag.rsplit("}", 1)[-1]  # exporters differ in namespace prefixes


def _all(el, name):
    return [e for e in el.iter() if _local(e) == name]


def _child(el, name):
    return next((c for c in el if _local(c) == name), None) if el is not None else None


def _ts(el, name):
    if el is None:
        raise ValueError(f"{name}: track points have no timestamps — "
                         "this looks like a planned route, not a recorded activity")
    d = dt.datetime.fromisoformat(el.text.strip())
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()  # naive is UTC


def _leg(sport, rows, source):
    lat, lon, t, hr = np.array(rows, float).reshape(-1, 4).T
    return Leg(sport_family(sport), lat, lon, t, hr, source)


def _hr(el):
    return float(el.text) if el is not None and (el.text or "").strip() else np.nan


def parse_gpx(data: bytes, name: str = "") -> list[Leg]:
    """One leg per <trk>, its segments joined. HR is any trkpt descendant named hr
    (Garmin's TrackPointExtension under whatever prefix the exporter picked)."""
    legs = []
    for trk in _all(ET.fromstring(data), "trk"):
        rows = [(float(p.get("lat")), float(p.get("lon")), _ts(_child(p, "time"), name),
                 _hr(next(iter(_all(p, "hr")), None))) for p in _all(trk, "trkpt")]
        ty = _child(trk, "type")
        legs.append(_leg(ty.text if ty is not None else "", rows, name))
    if not any(len(l.t) for l in legs):
        raise ValueError(f"{name}: no track points")
    return legs


def parse_tcx(data: bytes, name: str = "") -> list[Leg]:
    """One leg per <Activity> (a multisport session holds several); trackpoints without
    Position (indoor, pool, GPS not yet locked) are skipped."""
    legs = []
    for act in _all(ET.fromstring(data), "Activity"):
        rows = []
        for tp in _all(act, "Trackpoint"):
            pos = _child(tp, "Position")
            if pos is not None:
                rows.append((float(_child(pos, "LatitudeDegrees").text),
                             float(_child(pos, "LongitudeDegrees").text),
                             _ts(_child(tp, "Time"), name),
                             _hr(_child(_child(tp, "HeartRateBpm"), "Value"))))
        legs.append(_leg(act.get("Sport", ""), rows, name))
    return legs


def parse_fit(data: bytes, name: str = "") -> list[Leg]:
    """One leg per session (a multisport file holds several). A record belongs to the last
    session started at or before it; a transition's records join the next leg, so the path
    runs on unbroken from swim exit to bike to run. Records without position are skipped."""
    dec = Decoder(Stream.from_byte_array(bytearray(data)))
    if not dec.is_fit():
        raise ValueError(f"{name}: not a FIT file")
    m, errors = dec.read()
    if errors:
        raise ValueError(f"{name}: {errors[0]}")
    rows = [(r["position_lat"] * 180 / 2**31, r["position_long"] * 180 / 2**31,
             r["timestamp"].timestamp(), r.get("heart_rate", np.nan))
            for r in m.get("record_mesgs", [])
            if {"timestamp", "position_lat", "position_long"} <= r.keys()]
    sessions = sorted(m.get("session_mesgs", []), key=lambda s: s["start_time"])
    if not sessions:
        return [_leg("", rows, name)]
    sports = [str(s.get("sport", "")) for s in sessions]  # an unknown enum decodes as an int
    starts = [s["start_time"].timestamp() for s in sessions]
    real = [i for i, s in enumerate(sports) if sport_family(s) != "transition"]
    out = {i: [] for i in real}
    for row in rows:
        i = bisect.bisect_right(starts, row[2]) - 1
        j = bisect.bisect_left(real, i)  # this session, or the leg after a transition
        if i >= 0 and j < len(real):
            out[real[j]].append(row)
    return [_leg(sports[i], out[i], name) for i in real]


_DTD_END = re.compile(rb"\]\s*>")


class _NoDTD:
    """A stream with the internal DTD subset at its head, <!DOCTYPE .. [ .. ]>, cut out.
    iOS 16 wrote exports whose subset expat rejects, and nothing here needs it; the rest
    is passed through as it is read, so a multi-GB export.xml is never loaded whole."""

    def __init__(self, f):
        self.f, head = f, f.read(1 << 16)
        i = head.find(b"<!DOCTYPE")
        if i >= 0 and 0 <= head.find(b"[", i) < head.find(b">", i):   # it has a subset
            while not (end := _DTD_END.search(head, i)) and len(head) < 1 << 24:
                if not (more := f.read(1 << 16)):
                    break
                head += more
            if end:
                head = head[:i] + head[end.end():]
        self.head = head

    def read(self, n=-1):
        if not self.head:
            return self.f.read(n)
        out, self.head = (self.head, b"") if n < 0 else (self.head[:n], self.head[n:])
        return out


def parse_health_zip(f: BinaryIO, workout_date: str, workout_time: str = "", name: str = "") -> Leg:
    """One workout out of an Apple Health export.zip, read in place (never extracted) in one
    streaming pass over export.xml. The workout is the one with a route that started on
    workout_date, picked by workout_time (within 30 min, an exact minute breaking a tie) when
    the day has several; anything else is refused with the candidates listed, never guessed.
    The route GPX has no heart rate, so each point takes the HR records interpolated by time."""
    pre = f"{name}: " if name else ""
    if not workout_date:
        raise ValueError(f"{pre}Apple Health export: give the workout date")
    try:
        day = dt.date.fromisoformat(workout_date)
        at = dt.time.fromisoformat(workout_time) if workout_time else None
    except ValueError:
        raise ValueError(f"{pre}Apple Health export: the workout date is YYYY-MM-DD "
                         "and the start time HH:MM") from None
    date, days = str(day), {str(day + dt.timedelta(days=k)) for k in (-1, 0, 1)}
    try:
        with zipfile.ZipFile(f) as z:
            xml = max((i for i in z.infolist() if i.filename.endswith(".xml") and "cda" not in i.filename),
                      key=lambda i: i.file_size, default=None)  # by size: the name follows the locale
            if xml is None:
                raise ValueError(f"{pre}not an Apple Health export, the zip holds no export.xml")
            recs, found = [], []
            with z.open(xml) as x:
                it = ET.iterparse(_NoDTD(x), ("start", "end"))
                _, root = next(it)
                depth = 0
                for ev, el in it:
                    depth += 1 if ev == "start" else -1
                    if ev == "start" or depth:
                        continue  # only the root's children, each once it is complete
                    start = el.get("startDate", "")
                    if (el.tag == "Record" and el.get("type") == "HKQuantityTypeIdentifierHeartRate"
                            and start[:10] in days):  # ±1 day: a workout can run past midnight
                        recs.append((dt.datetime.strptime(start, "%Y-%m-%d %H:%M:%S %z").timestamp(),
                                     float(el.get("value"))))
                    elif el.tag == "Workout" and start[:10] == date:
                        ref = el.find("WorkoutRoute/FileReference")
                        if ref is not None and ref.get("path"):
                            found.append((start, el.get("workoutActivityType", ""), ref.get("path")))
                    root.clear()  # memory stays flat on a multi-GB export
            start, ty, path = _pick_workout(found, date, at, pre)
            member = next((n for n in z.namelist() if n.endswith(path)), None)
            if member is None:
                raise ValueError(f"{pre}the export lacks the workout's route {path}")
            legs = parse_gpx(z.read(member), name)
    except (zipfile.BadZipFile, ET.ParseError) as e:
        raise ValueError(f"{pre}not a readable Apple Health export.zip ({e})") from None
    lat, lon, t = (np.concatenate([getattr(l, k) for l in legs]) for k in ("lat", "lon", "t"))
    hr = np.full(len(t), np.nan)
    if recs:
        rt, rv = np.array(sorted(recs)).T
        j = np.searchsorted(rt, t)
        gap = np.minimum(abs(t - rt[np.maximum(j - 1, 0)]), abs(rt[np.minimum(j, len(rt) - 1)] - t))
        hr = np.where(gap <= HR_GAP_S, np.interp(t, rt, rv), np.nan)
    return Leg(sport_family(ty), lat, lon, t, hr, f"Health: {ty.removeprefix(_HK)} {date} {start[11:16]}")


def _pick_workout(found, date, at, pre):
    """(startDate, type, route path) of the one workout meant; ValueError listing the rest."""
    if not found:
        raise ValueError(f"{pre}no workout with a route on {date}")
    listing = lambda ws: ", ".join(f"{s[11:16]} {ty.removeprefix(_HK)}" for s, ty, _ in ws)
    if at is not None:
        off = lambda s: abs(int(s[11:13]) * 60 + int(s[14:16]) - at.hour * 60 - at.minute)
        near = [w for w in found if off(w[0]) <= 30]
        if not near:
            raise ValueError(f"{pre}no workout with a route starts within 30 minutes of "
                             f"{at:%H:%M} on {date}, the day has {listing(found)}")
        found = [w for w in near if off(w[0]) == 0] or near
    if len(found) > 1:
        raise ValueError(f"{pre}{len(found)} workouts with a route on {date} ({listing(found)}): "
                         "give the exact start time of the one to print")
    if "SwimBikeRun" in found[0][1]:
        raise ValueError(f"{pre}Apple Watch triathlon: send the Strava or HealthFit files "
                         "for each leg instead")
    return found[0]


_PARSERS = {".gpx": parse_gpx, ".tcx": parse_tcx, ".fit": parse_fit}


def read_activity(files: list[tuple[str, BinaryIO]], workout_date: str = "",
                  workout_time: str = "") -> list[Leg]:
    """Every leg of an order's files, empty ones included, cleaned, sorted by start time and
    with sports assigned. Anything wrong with the order is a ValueError for the operator."""
    legs = []
    for name, f in files:
        ext = os.path.splitext(name)[1].lower()
        if ext not in (*_PARSERS, ".zip"):
            raise ValueError(f"{name}: unsupported file type, send GPX, TCX, FIT or an Apple Health export.zip")
        try:  # customer files: whatever a parser trips over is the file's fault, never a 500
            legs += ([parse_health_zip(f, workout_date, workout_time, name)] if ext == ".zip"
                     else _PARSERS[ext](f.read(), name))
        except Exception as e:
            if name and isinstance(e, ValueError) and str(e).startswith(name):
                raise
            raise ValueError(f"{name}: could not read this file ({type(e).__name__}: {e})") from None
    legs = [_clean(l) for l in legs]
    if not any(len(l.t) >= 2 for l in legs):
        raise ValueError("no GPS track in these files — indoor or pool activity?")
    key, keys = -np.inf, []
    for l in legs:  # an empty leg has no time: it stays after the leg it followed in the files
        key = l.t[0] if len(l.t) else key
        keys.append(key)
    legs = [legs[i] for i in sorted(range(len(legs)), key=keys.__getitem__)]
    full = [l for l in legs if len(l.t) >= 2]
    sports = {l.sport for l in full}
    if sports == {""}:
        if len(full) == 3:  # three exports without metadata: a triathlon in time order
            for l, s in zip(full, _TRI):
                l.sport = s
    elif "" in sports:
        names = ", ".join(dict.fromkeys(l.source for l in full if not l.sport))
        raise ValueError(f"{names}: no sport recorded, while the other files have one — "
                         "send every file with its sport")
    elif len(sports) > 1 and (odd := sorted(sports - set(_TRI))):
        raise ValueError(f"{', '.join(odd)}: a multisport order can only hold swim, bike and run legs")
    return legs


def _sub(l, i):
    return Leg(l.sport, l.lat[i], l.lon[i], l.t[i], l.hr[i], l.source)


def _speed(l):
    """m/s between consecutive fixes: equirectangular distance, dt floored at 1 s."""
    mid = np.radians(l.lat[:-1] + l.lat[1:]) / 2
    d = np.hypot(np.radians(np.diff(l.lon)) * np.cos(mid), np.radians(np.diff(l.lat)))
    return 6371e3 * d / np.maximum(np.diff(l.t), 1)


def _clean(l):
    """Finite fixes in time order, no repeated position, isolated GPS spikes gone."""
    l = _sub(l, np.isfinite(l.lat) & np.isfinite(l.lon) & np.isfinite(l.t))
    l = _sub(l, np.argsort(l.t, kind="stable"))
    l = _sub(l, np.r_[True, (np.diff(l.lat) != 0) | (np.diff(l.lon) != 0)][:len(l.t)])
    # ponytail: isolated spikes only; two bad fixes in a row survive
    fast, keep = _speed(l) > MAX_SPEED_MS, np.ones(len(l.t), bool)
    keep[1:-1] = ~(fast[:-1] & fast[1:])  # interior: too fast both in and out
    l = _sub(l, keep)
    fast, keep = _speed(l) > MAX_SPEED_MS, np.ones(len(l.t), bool)
    if len(fast):
        keep[[0, -1]] = ~fast[[0, -1]]  # an end too fast to its new neighbour
    return _sub(l, keep)


def group_walls(legs: list[Leg]) -> list[tuple[str, list[Leg]]]:
    """[("strip", legs)] for one sport (or none), else one (sport, legs) per sport in order of
    first appearance: a sport's legs merge into one wall. Legs under 2 fixes are left out."""
    full = [l for l in legs if len(l.t) >= 2]
    sports = list(dict.fromkeys(l.sport for l in full))
    if len(sports) == 1:
        return [("strip", full)]
    return [(s, [l for l in full if l.sport == s]) for s in sports]


def legs_note(legs: list[Leg]) -> str:
    """Status line: the Health workout picked, then each leg's GPS and HR coverage."""
    parts = [s for s in dict.fromkeys(l.source for l in legs) if s.startswith("Health:")]
    for l in legs:
        label, share = l.sport or "activity", np.isfinite(l.hr).mean() if len(l.hr) else 0.0
        parts.append(f"{label}: no GPS track, not printed" if len(l.t) < 2
                     else f"{label}: no HR, low line" if share == 0
                     else f"{label}: HR {round(100 * share)}%")
    return " · ".join(parts)
