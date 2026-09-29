"""GFS forecast rainfall: fetching, placement on the grid, and ensemble spread."""

import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ingest import gfs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gfs"


def test_issue_time_rounds_down_to_a_gfs_cycle():
    assert gfs.issue_time_for(datetime(2025, 10, 26, 21)) == datetime(2025, 10, 26, 18)
    assert gfs.issue_time_for(datetime(2025, 10, 27, 5, 59)) == datetime(2025, 10, 27, 0)


def test_coverage_starts_with_the_open_archive():
    assert gfs.covered(datetime(2025, 10, 26))
    assert not gfs.covered(datetime(2019, 5, 1)), "Fani predates the AWS archive"


def test_members_keep_gfs_totals_where_they_agree():
    """A member that matches the ensemble mean gets exactly the GFS field."""
    g = np.array([[100.0, 50.0]])
    same = np.array([[40.0, 20.0]])
    out = gfs.member_fields(g, [same, same])
    assert np.allclose(out[0], g)


def test_members_shift_rain_along_their_own_tracks():
    """Without this every member would carry the same field and every
    rainfall probability would collapse to 0 or 1."""
    g = np.array([[100.0, 100.0]])
    west = np.array([[60.0, 20.0]])
    east = np.array([[20.0, 60.0]])
    a, b = gfs.member_fields(g, [west, east])
    assert a[0, 0] > b[0, 0] and b[0, 1] > a[0, 1]


def test_redistribution_is_capped():
    """A cell the mean barely rains on must not be multiplied into a flood."""
    g = np.array([[100.0]])
    out = gfs.member_fields(g, [np.array([[100.0]]), np.array([[2.0]])])
    assert out[0].max() <= 100.0 * gfs.RATIO_BOUNDS[1]


def test_dry_cells_in_the_parametric_model_keep_the_gfs_value():
    """Where R-CLIPER says nothing, GFS is not zeroed out by a 0/0 ratio."""
    g = np.array([[30.0]])
    out = gfs.member_fields(g, [np.zeros((1, 1)), np.zeros((1, 1))])
    assert out[0][0, 0] == 30.0


def test_montha_forecast_rain_is_physically_plausible(monkeypatch):
    """On the real forecast field, cropped to the Bay of Bengal (fixtures/gfs)."""
    monkeypatch.setattr(gfs, "CACHE_DIR", FIXTURES)
    init = datetime(2025, 10, 26, 18)
    lats, lons = np.meshgrid(np.linspace(15.7, 17.4, 30), np.linspace(80.6, 82.6, 30), indexing="ij")
    mm = gfs.on_grid(init, lats, lons)
    assert np.isfinite(mm).all() and mm.min() >= 0
    assert 50 < mm.max() < 600, "a cyclone's three-day total, not zero and not absurd"


# --- the download path, on a real GRIB2 message -------------------------------

class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _grib_message(values):
    """A genuine GRIB2 message built by eccodes: 31 x 16, 2-degree grid from
    60N, 0E, scanning north to south."""
    import eccodes

    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        eccodes.codes_set_values(gid, values.ravel())
        return eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)


def test_the_right_field_is_cut_from_the_file_and_decoded(tmp_path, monkeypatch):
    """The .idx says where APCP 0-3 day acc sits; only that byte range is
    fetched, and the decoded grid keeps its orientation."""
    monkeypatch.setattr(gfs, "CACHE_DIR", tmp_path)
    field = np.arange(31 * 16, dtype=float).reshape(31, 16)
    blob = _grib_message(field)
    prefix = b"x" * 100                       # an unrelated record before ours
    idx = "\n".join([
        "1:0:d=2025102618:TMP:2 m above ground:72 hour fcst:",
        f"2:{len(prefix)}:d=2025102618:APCP:surface:0-3 day acc fcst:",
        f"3:{len(prefix) + len(blob)}:d=2025102618:UGRD:10 m above ground:72 hour fcst:",
    ])
    ranges = []

    def urlopen(req, timeout=None, context=None):
        if isinstance(req, str):                           # the .idx
            return _Resp(idx.encode())
        ranges.append(req.headers["Range"])
        start, end = map(int, req.headers["Range"].split("=")[1].split("-"))
        return _Resp((prefix + blob + b"y" * 50)[start:end + 1])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    init = datetime(2025, 10, 26, 18)
    lats, lons, mm = gfs.fetch_accumulation(init)
    assert ranges == [f"bytes={len(prefix)}-{len(prefix) + len(blob) - 1}"]
    assert lats[0] == 60.0 and lats[1] == 58.0, "north to south, as the file scans"
    assert lons[1] == 2.0
    np.testing.assert_allclose(mm, field, atol=0.5)
    # Cached: a second call reads the disk, not the network.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: 1 / 0)
    np.testing.assert_allclose(gfs.fetch_accumulation(init)[2], mm)


def test_a_file_without_the_field_is_an_error_not_zeros(tmp_path, monkeypatch):
    monkeypatch.setattr(gfs, "CACHE_DIR", tmp_path)
    idx = "1:0:d=2025102618:TMP:2 m above ground:72 hour fcst:"
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None, context=None: _Resp(idx.encode()))
    with pytest.raises(LookupError, match="no APCP"):
        gfs.fetch_accumulation(datetime(2025, 10, 26, 18))
