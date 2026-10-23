import datetime as dt

import numpy as np
import pytest

import activity

T0 = dt.datetime(2026, 7, 5, 6, 0, tzinfo=dt.timezone.utc)
H = dt.timedelta(hours=1)


def _pts(n, hr=150, lat=47.0, lon0=8.0, step=1e-4, t0=T0):
    """n fixes 1 s apart heading east: [(lat, lon, datetime, hr_or_None)]."""
    hrs = hr if isinstance(hr, list) else [hr] * n
    return [(lat, lon0 + i * step, t0 + dt.timedelta(seconds=i), hrs[i]) for i in range(n)]


def _z(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gpx(tracks, ns="gpxtpx"):
    """Strava-style GPX 1.1 from [(type_or_None, pts)]; HR under Garmin's TrackPointExtension."""
    def pt(la, lo, t, hr):
        time = f"<time>{_z(t)}</time>" if t else ""
        ext = (f"<extensions><{ns}:TrackPointExtension><{ns}:hr>{hr}</{ns}:hr>"
               f"</{ns}:TrackPointExtension></extensions>" if hr is not None else "")
        return f'<trkpt lat="{la}" lon="{lo}"><ele>400.0</ele>{time}{ext}</trkpt>'
    trks = "".join("<trk>" + (f"<type>{ty}</type>" if ty else "") + "<trkseg>"
                   + "".join(pt(*p) for p in pts) + "</trkseg></trk>" for ty, pts in tracks)
    return ('<?xml version="1.0" encoding="UTF-8"?><gpx creator="StravaGPX" version="1.1" '
            'xmlns="http://www.topografix.com/GPX/1/1" '
            f'xmlns:{ns}="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
            f"{trks}</gpx>").encode()


def _tcx(activities):
    """TrainingCenterDatabase v2 from [(Sport, pts)]; no <Position> when lat is None."""
    def tp(la, lo, t, hr):
        pos = (f"<Position><LatitudeDegrees>{la}</LatitudeDegrees>"
               f"<LongitudeDegrees>{lo}</LongitudeDegrees></Position>" if la is not None else "")
        bpm = f"<HeartRateBpm><Value>{hr}</Value></HeartRateBpm>" if hr is not None else ""
        return f"<Trackpoint><Time>{_z(t)[:-1]}.000Z</Time>{pos}{bpm}</Trackpoint>"
    acts = "".join(f'<Activity Sport="{sport}"><Id>{_z(pts[0][2])}</Id>'
                   f'<Lap StartTime="{_z(pts[0][2])}"><Track>'
                   + "".join(tp(*p) for p in pts) + "</Track></Lap></Activity>"
                   for sport, pts in activities)
    return ('<?xml version="1.0" encoding="UTF-8"?><TrainingCenterDatabase '
            'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
            f"<Activities>{acts}</Activities></TrainingCenterDatabase>").encode()


@pytest.mark.parametrize("raw,fam", [
    ("running", "run"), ("Running", "run"), ("trail_running", "run"), ("hiking", "run"),
    ("walking", "run"), ("HKWorkoutActivityTypeRunning", "run"), ("cycling", "bike"),
    ("Biking", "bike"), ("mountain_biking", "bike"), ("e_biking", "bike"), ("Ride", "bike"),
    ("HKWorkoutActivityTypeCycling", "bike"), ("swimming", "swim"), ("transition", "transition"),
    ("", ""), ("9", ""), ("rowing", "rowing")])
def test_sport_family(raw, fam):
    assert activity.sport_family(raw) == fam

def test_smooth_hr_is_a_centred_time_window_mean():
    t = np.arange(120.0)
    s = activity.smooth_hr(t, np.where(t < 60, 100.0, 200.0))
    assert s[30] == 100 and s[90] == 200 and 100 < s[60] < 200

def test_smooth_hr_ignores_missing_samples_and_keeps_long_gaps_missing():
    t = np.arange(120.0)
    s = activity.smooth_hr(t, np.where(t < 60, np.nan, 180.0))
    assert np.isnan(s[10]) and s[50] == 180 and s[100] == 180

def test_parse_gpx_reads_position_time_and_hr():
    (leg,) = activity.parse_gpx(_gpx([("running", _pts(5, hr=[150, None, 152, 153, 154]))]), "run.gpx")
    assert leg.sport == "run" and leg.source == "run.gpx"
    assert leg.lat[0] == 47.0 and abs(leg.lon[4] - 8.0004) < 1e-9
    assert leg.t[0] == T0.timestamp() and leg.t[1] - leg.t[0] == 1.0
    assert leg.hr[0] == 150 and np.isnan(leg.hr[1])

def test_parse_gpx_reads_a_naive_time_as_utc():
    (leg,) = activity.parse_gpx(_gpx([("running", _pts(2))]).replace(b"Z</time>", b"</time>"))
    assert leg.t[0] == T0.timestamp()

def test_parse_gpx_finds_hr_under_any_namespace_prefix():
    (leg,) = activity.parse_gpx(_gpx([("cycling", _pts(3))], ns="ns3"))
    assert leg.sport == "bike" and list(leg.hr) == [150, 150, 150]

def test_parse_gpx_one_leg_per_track():
    legs = activity.parse_gpx(_gpx([("swimming", _pts(3)), (None, _pts(3, t0=T0 + H))]))
    assert [l.sport for l in legs] == ["swim", ""]

def test_parse_gpx_refuses_a_route_without_timestamps():
    pts = [(47.0, 8.0, None, None), (47.0, 8.001, None, None)]
    with pytest.raises(ValueError, match="no timestamps"):
        activity.parse_gpx(_gpx([("running", pts)]), "course.gpx")

def test_parse_tcx_reads_sport_position_and_hr():
    (leg,) = activity.parse_tcx(_tcx([("Biking", _pts(4, hr=140))]), "ride.tcx")
    assert leg.sport == "bike" and len(leg.lat) == 4 and (leg.hr == 140).all()

def test_parse_tcx_skips_trackpoints_without_position():
    pts = _pts(4)
    pts[1] = (None, None, pts[1][2], 150)
    (leg,) = activity.parse_tcx(_tcx([("Running", pts)]))
    assert len(leg.lat) == 3
