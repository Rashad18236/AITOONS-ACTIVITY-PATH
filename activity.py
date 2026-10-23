"""Customer activity files -> legs (sport + lat/lon/time/heart rate). No geometry."""
import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import numpy as np

HR_WINDOW_S = 30.0  # rolling heart-rate window: optical sensors spike and drop out


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
