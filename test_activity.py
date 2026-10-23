import datetime as dt
import io
import zipfile

import numpy as np
import pytest
from garmin_fit_sdk import Encoder, Profile

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


def _fit(sessions, t0=T0):
    """FIT activity from [(sport, n, hr)] back to back: n records 1 s apart heading east,
    heart_rate omitted when hr is None. n=0 is a session with no positioned records."""
    M = Profile["mesg_num"]
    e = Encoder()
    e.on_mesg(M["FILE_ID"], {"type": "activity", "manufacturer": "development", "product": 0,
                             "time_created": t0, "serial_number": 1})
    t, lon0 = t0, 8.0
    for i, (sport, n, hr) in enumerate(sessions):
        for la, lo, ts, h in _pts(n, hr, lon0=lon0, t0=t):
            e.on_mesg(M["RECORD"], {"timestamp": ts, "position_lat": int(la / 180 * 2**31),
                                    "position_long": int(lo / 180 * 2**31)}
                      | ({} if h is None else {"heart_rate": h}))
        secs = max(n, 1)  # an empty session still spans time, so the windows stay ordered
        end = t + dt.timedelta(seconds=secs)
        e.on_mesg(M["SESSION"], {"timestamp": end, "start_time": t, "total_elapsed_time": secs,
                                 "sport": sport, "message_index": i})
        t, lon0 = end, lon0 + n * 1e-4
    return e.close()


def _health_zip(workouts, hr, pad_cda=4096):
    """iPhone-style export.zip from workouts [(type, "YYYY-MM-DD HH:MM:SS +ZZZZ", n)] and HR
    records [(date, bpm)]: export.xml with its DOCTYPE, one route GPX per workout with n > 0
    fixes 1 s apart (UTC, no HR), and an export_cda.xml of pad_cda bytes stored uncompressed."""
    fmt = "%Y-%m-%d %H:%M:%S %z"
    recs = "".join(f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" '
                   f'unit="count/min" creationDate="{d}" startDate="{d}" endDate="{d}" value="{v}"/>\n'
                   for d, v in hr)
    buf, wos = io.BytesIO(), ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (ty, start, n) in enumerate(workouts):
            t0 = dt.datetime.strptime(start, fmt)
            end = (t0 + dt.timedelta(seconds=max(n, 60))).strftime(fmt)
            route = ""
            if n:
                z.writestr(f"apple_health_export/workout-routes/route_{i}.gpx",
                           _gpx([(None, _pts(n, hr=None, t0=t0.astimezone(dt.timezone.utc)))]))
                route = (f'\n  <WorkoutRoute sourceName="Watch" startDate="{start}" endDate="{end}">'
                         f'\n   <FileReference path="/workout-routes/route_{i}.gpx"/>\n  </WorkoutRoute>\n ')
            wos += (f' <Workout workoutActivityType="HKWorkoutActivityType{ty}" duration="{max(n, 60) / 60}" '
                    f'durationUnit="min" sourceName="Watch" startDate="{start}" endDate="{end}">{route}</Workout>\n')
        z.writestr("apple_health_export/export.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [<!ELEMENT HealthData ANY>]>\n'
                   f'<HealthData locale="en_CH">\n{recs}{wos}</HealthData>\n')
        z.writestr("apple_health_export/export_cda.xml", b" " * pad_cda, compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


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

def test_parse_fit_splits_a_multisport_file_and_attaches_transitions_to_the_next_leg():
    legs = activity.parse_fit(_fit([("swimming", 5, None), ("transition", 2, 120),
                                    ("cycling", 6, 140), ("transition", 2, 130),
                                    ("running", 4, 160)]), "tri.fit")
    assert [l.sport for l in legs] == ["swim", "bike", "run"]
    assert [len(l.lat) for l in legs] == [5, 8, 6]
    assert np.isnan(legs[0].hr).all() and legs[1].hr[0] == 120 and legs[2].hr[-1] == 160
    assert abs(legs[0].lat[0] - 47.0) < 1e-6 and legs[0].source == "tri.fit"

def test_parse_fit_keeps_a_session_without_gps_as_an_empty_leg():
    legs = activity.parse_fit(_fit([("swimming", 0, None), ("cycling", 3, 140)]))
    assert [l.sport for l in legs] == ["swim", "bike"] and len(legs[0].lat) == 0

def test_parse_fit_refuses_a_non_fit_file():
    with pytest.raises(ValueError, match="not a FIT file"):
        activity.parse_fit(b"hello", "x.fit")

def test_parse_fit_reports_a_damaged_file_as_a_value_error_naming_it():
    with pytest.raises(ValueError, match="cut.fit"):
        activity.parse_fit(_fit([("running", 3, 150)])[:-5], "cut.fit")

RUN_0800 = ("Running", "2026-05-01 08:00:00 +0200", 60)
EVERY_5S = [(f"2026-05-01 08:00:{s:02d} +0200", 150) for s in range(0, 60, 5)]

def test_health_export_takes_the_workout_and_joins_hr_by_time():
    leg = activity.parse_health_zip(io.BytesIO(_health_zip([RUN_0800], EVERY_5S)), "2026-05-01")
    assert leg.sport == "run" and len(leg.lat) == 60 and np.allclose(leg.hr, 150)
    assert leg.source == "Health: Running 2026-05-01 08:00"

def test_health_export_never_guesses_between_two_workouts():
    z = _health_zip([("Running", "2026-05-01 08:00:00 +0200", 30),
                     ("Cycling", "2026-05-01 17:45:00 +0200", 30)], [])
    with pytest.raises(ValueError) as e:
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")
    assert "08:00" in str(e.value) and "17:45" in str(e.value)
    assert activity.parse_health_zip(io.BytesIO(z), "2026-05-01", "17:40").sport == "bike"

def test_health_export_refuses_a_day_without_a_route():
    z = _health_zip([("Running", "2026-05-01 08:00:00 +0200", 0)], [])
    with pytest.raises(ValueError, match="no workout with a route"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")

def test_health_export_leaves_hr_gaps_missing():
    recs = [(f"2026-05-01 08:00:{s:02d} +0200", 150) for s in (0, 5, 10, 55)]
    leg = activity.parse_health_zip(io.BytesIO(_health_zip([RUN_0800], recs)), "2026-05-01")
    assert np.isfinite(leg.hr[:15]).all() and np.isnan(leg.hr[30])

def test_health_export_keeps_hr_after_local_midnight():
    recs = [(f"2026-05-01 23:5{m}:00 +0200", 140) for m in range(10)] + [("2026-05-02 00:05:00 +0200", 140)]
    z = _health_zip([("Walking", "2026-05-01 23:50:00 +0200", 1200)], recs)
    leg = activity.parse_health_zip(io.BytesIO(z), "2026-05-01")
    assert leg.hr[900] == 140          # 00:05:00, the next calendar day

def test_health_export_refuses_an_apple_watch_triathlon():
    z = _health_zip([("SwimBikeRun", "2026-05-01 08:00:00 +0200", 30)], [])
    with pytest.raises(ValueError, match="Strava or HealthFit"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01")

def test_health_export_needs_the_workout_date():
    with pytest.raises(ValueError, match="workout date"):
        activity.parse_health_zip(io.BytesIO(_health_zip([], [])), "")

def test_health_export_takes_the_exact_start_when_two_workouts_are_close():
    z = _health_zip([("Running", "2026-05-01 07:45:00 +0200", 30),
                     ("Running", "2026-05-01 08:05:00 +0200", 30)], [])
    with pytest.raises(ValueError, match="07:45 Running, 08:05 Running"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01", "08:00")
    assert activity.parse_health_zip(io.BytesIO(z), "2026-05-01", "08:05").source.endswith("08:05")
    with pytest.raises(ValueError, match="within 30 minutes"):
        activity.parse_health_zip(io.BytesIO(z), "2026-05-01", "12:00")

def test_health_export_refuses_a_file_that_is_not_a_zip():
    with pytest.raises(ValueError, match="export.zip: not a readable"):
        activity.parse_health_zip(io.BytesIO(b"hello"), "2026-05-01", name="export.zip")

_file = lambda name, data: (name, io.BytesIO(data))

def test_read_activity_dispatches_by_extension_and_refuses_others():
    legs = activity.read_activity([_file("a.gpx", _gpx([("running", _pts(5))])),
                                   _file("b.tcx", _tcx([("Running", _pts(5, t0=T0 + H))]))])
    assert [l.source for l in legs] == ["a.gpx", "b.tcx"]
    with pytest.raises(ValueError, match="unsupported"):
        activity.read_activity([_file("flight.kml", b"<kml/>")])

def test_a_file_that_cannot_be_read_is_a_value_error_naming_it():
    with pytest.raises(ValueError, match=r"^broken\.gpx: could not read this file \(ParseError"):
        activity.read_activity([_file("broken.gpx", b"this is not xml")])
    bad_lat = _gpx([("running", _pts(2))]).replace(b'lat="47.0"', b'lat="north"', 1)
    with pytest.raises(ValueError, match=r"^bad\.gpx: could not read this file \(ValueError"):
        activity.read_activity([_file("bad.gpx", bad_lat)])
    with pytest.raises(ValueError, match=r"^junk\.fit: not a FIT file$"):  # already named: unchanged
        activity.read_activity([_file("junk.fit", b"\x00" * 64)])

def test_three_files_without_sport_are_swim_bike_run_in_time_order():
    fs = [_file(f"{i}.gpx", _gpx([(None, _pts(5, t0=T0 + i * H))])) for i in (2, 0, 1)]
    assert [l.sport for l in activity.read_activity(fs)] == ["swim", "bike", "run"]

def test_a_file_without_sport_next_to_files_with_one_is_refused():
    fs = [_file("a.gpx", _gpx([("running", _pts(5))])), _file("b.gpx", _gpx([(None, _pts(5, t0=T0 + H))]))]
    with pytest.raises(ValueError, match="b.gpx"):
        activity.read_activity(fs)

def test_a_multisport_order_with_an_unknown_sport_is_refused():
    fs = [_file("a.gpx", _gpx([("rowing", _pts(5))])), _file("b.gpx", _gpx([("running", _pts(5, t0=T0 + H))]))]
    with pytest.raises(ValueError, match="rowing"):
        activity.read_activity(fs)

def test_one_sport_in_several_files_is_one_strip_wall():
    fs = [_file(f"{i}.gpx", _gpx([("cycling", _pts(5, t0=T0 + i * H))])) for i in (0, 1)]
    assert [(n, len(ls)) for n, ls in activity.group_walls(activity.read_activity(fs))] == [("strip", 2)]

def test_a_duathlon_groups_by_sport_in_order_of_first_appearance():
    fs = [_file(f"{i}.gpx", _gpx([(s, _pts(5, t0=T0 + i * H))]))
          for i, s in enumerate(("running", "cycling", "running"))]
    assert [(n, len(ls)) for n, ls in activity.group_walls(activity.read_activity(fs))] == [("run", 2), ("bike", 1)]

def test_a_gps_spike_is_dropped():
    pts = _pts(10)
    pts[5] = (47.5, pts[5][1], pts[5][2], 150)          # one fix 55 km north
    (leg,) = activity.read_activity([_file("a.gpx", _gpx([("running", pts)]))])
    assert len(leg.lat) == 9 and leg.lat.max() < 47.01

def test_a_leg_without_gps_is_reported_and_not_printed():
    legs = activity.read_activity([_file("tri.fit", _fit([("swimming", 0, None), ("cycling", 5, 140), ("running", 5, 160)]))])
    assert [n for n, _ in activity.group_walls(legs)] == ["bike", "run"]
    assert "swim: no GPS track, not printed" in activity.legs_note(legs)

def test_files_without_any_gps_are_refused():
    with pytest.raises(ValueError, match="no GPS"):
        activity.read_activity([_file("pool.fit", _fit([("swimming", 0, None)]))])

def test_legs_note_reports_hr_coverage_per_leg():
    legs = activity.read_activity([_file("tri.fit", _fit([("swimming", 5, None), ("cycling", 4, 140), ("running", 4, 160)]))])
    assert activity.legs_note(legs) == "swim: no HR, low line · bike: HR 100% · run: HR 100%"
