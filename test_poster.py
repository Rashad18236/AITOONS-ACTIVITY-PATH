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
