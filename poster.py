"""Flight Path Poster core: track -> heightmap -> printable meshes."""
import csv, io, math, re
from dataclasses import dataclass
import numpy as np


def parse_track(name: str, data: bytes) -> np.ndarray:
    """Return (N,3) array of lat, lon, alt_m from FR24 KML or CSV export."""
    text = data.decode("utf-8", "replace")
    pts = _parse_kml(text) if name.lower().endswith(".kml") else _parse_csv(text)
    if len(pts) < 2:
        raise ValueError("No track points found — is this a FlightRadar24 KML/CSV export?")
    return np.array(pts, dtype=float)


def _parse_kml(text):
    # ponytail: regex over XML — FR24 exports are machine-generated, fine here
    pts = [(float(la), float(lo), float(al)) for lo, la, al in
           re.findall(r"<gx:coord>([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)</gx:coord>", text)]
    if not pts:  # plain LineString fallback: "lon,lat,alt lon,lat,alt ..."
        for block in re.findall(r"<coordinates>(.*?)</coordinates>", text, re.S):
            for triple in block.split():
                p = triple.split(",")
                if len(p) >= 2:
                    pts.append((float(p[1]), float(p[0]),
                                float(p[2]) if len(p) > 2 else 0.0))
    return pts


def _parse_csv(text):
    pts = []
    for row in csv.DictReader(io.StringIO(text)):
        pos = row.get("Position") or ""
        if "," in pos:
            lat, lon = map(float, pos.split(","))
            pts.append((lat, lon, float(row.get("Altitude") or 0) * 0.3048))
    return pts
