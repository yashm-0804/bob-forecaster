"""The code that asks Earth Engine and AWS for data, driven with stand-ins.

These check what the code asks for -- which dataset, band, date window and
mask -- how it chooses among what comes back, how it retries and falls back,
and the arithmetic it applies to the arrays. They cannot check what Earth
Engine or AWS would actually return: the recorded extracts in tests/fixtures
and the tests marked `network` do that.
"""

import io
import sys
import urllib.error
from datetime import datetime, timedelta
from email.message import Message

import numpy as np
import pytest

from verify import satellite


class Chain:
    """Stands in for any Earth Engine object. Every attribute and call gives
    another Chain, and every call is logged as a readable path, such as
    `ImageCollection('NASA/GPM_L3/IMERG_V07').select('precipitation')`.
    Calls to getInfo and computePixels are answered by `answer(path, args)`;
    `map` runs the function it is given on a stand-in image."""

    def __init__(self, log, answer, path=""):
        self._log, self._answer, self._path = log, answer, path

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Chain(self._log, self._answer, f"{self._path}.{name}" if self._path else name)

    def __call__(self, *args, **kwargs):
        shown = [a._path if isinstance(a, Chain) else repr(a) for a in args]
        shown += [f"{k}={v._path if isinstance(v, Chain) else repr(v)}" for k, v in kwargs.items()]
        path = f"{self._path}({', '.join(shown)})"
        self._log.append(path)
        if self._path.endswith(("getInfo", "computePixels")):
            return self._answer(path, args)
        if self._path.endswith(".map") and args and callable(args[0]):
            args[0](Chain(self._log, self._answer, "image"))
        return Chain(self._log, self._answer, path)


def structured(**bands):
    """What computePixels returns: one structured array, a field per band."""
    first = next(iter(bands.values()))
    out = np.zeros(first.shape, dtype=[(name, "f8") for name in bands])
    for name, values in bands.items():
        out[name] = values
    return out


GRID_LATS, GRID_LONS = np.meshgrid(np.linspace(16.0, 16.2, 3), np.linspace(81.0, 81.4, 5),
                                   indexing="ij")


@pytest.fixture
def fake_ee(monkeypatch, tmp_path):
    """An Earth Engine stand-in for verify.satellite, with its cache in tmp."""
    log, answers = [], {}

    def answer(path, args):
        for key, value in answers.items():
            if key in path:
                return value(args) if callable(value) else value
        raise AssertionError(f"unexpected Earth Engine request: {path}")

    ee = Chain(log, answer)
    monkeypatch.setattr(satellite, "_ee", lambda: ee)
    monkeypatch.setattr(satellite, "CACHE_DIR", tmp_path)
    return log, answers


# --- verify/satellite.py ------------------------------------------------------

def test_rain_asks_imerg_for_the_window_and_returns_mm_south_first(fake_ee):
    log, answers = fake_ee
    north_first = np.array([[3.0] * 5, [2.0] * 5, [1.0] * 5])
    answers["size().getInfo"] = 96
    answers["computePixels"] = lambda args: structured(rain_mm=north_first)
    start, end = datetime(2025, 10, 26, 0), datetime(2025, 10, 29, 0)
    rain, meta = satellite.observed_rain(start, end, GRID_LATS, GRID_LONS)

    assert rain[:, 0].tolist() == [1.0, 2.0, 3.0], "Earth Engine's rows run north first"
    assert meta["source"] == "NASA/GPM_L3/IMERG_V07" and meta["half_hourly_images"] == 96
    text = "\n".join(log)
    assert "ImageCollection('NASA/GPM_L3/IMERG_V07')" in text
    assert "Date('2025-10-26T00:00:00')" in text and "Date('2025-10-29T00:00:00')" in text
    assert ".select('precipitation')" in text
    assert ".multiply(0.5)" in text, "half-hourly mm/h rates, each half an hour long"
    assert ".resample('bilinear')" in text


def test_the_grid_request_matches_the_hazard_grid(fake_ee):
    log, answers = fake_ee
    seen = {}

    def pixels(args):
        seen.update(args[0]["grid"])
        return structured(rain_mm=np.zeros((3, 5)))

    answers["size().getInfo"] = 1
    answers["computePixels"] = pixels
    satellite.observed_rain(datetime(2025, 10, 26), datetime(2025, 10, 27), GRID_LATS, GRID_LONS)
    assert seen["dimensions"] == {"width": 5, "height": 3}
    t = seen["affineTransform"]
    assert t["scaleX"] == pytest.approx(0.1) and t["scaleY"] == pytest.approx(-0.1)
    assert t["translateX"] == pytest.approx(80.95), "the west edge of the first cell"
    assert t["translateY"] == pytest.approx(16.25), "the north edge of the last row"
    assert seen["crsCode"] == "EPSG:4326"


def test_an_observation_is_fetched_once_and_then_read_from_disk(fake_ee):
    log, answers = fake_ee
    calls = []
    answers["size().getInfo"] = 48
    answers["computePixels"] = lambda args: calls.append(1) or structured(rain_mm=np.ones((3, 5)))
    window = (datetime(2025, 10, 26), datetime(2025, 10, 27))
    first = satellite.observed_rain(*window, GRID_LATS, GRID_LONS)
    second = satellite.observed_rain(*window, GRID_LATS, GRID_LONS)
    assert len(calls) == 1
    assert np.array_equal(first[0], second[0]) and first[1] == second[1]


def test_night_lights_drop_is_computed_only_where_it_can_be(fake_ee):
    """Lit before and seen after: the fractional drop. Not lit before, or
    cloudy after (-1 on the wire): unknown, never a guess. A cell brighter
    after is a negative drop, clipped at -1."""
    log, answers = fake_ee
    pre = np.array([[10.0, 1.0, 10.0, 10.0, 0.0]] * 3)
    post = np.array([[2.0, 0.5, -1.0, 30.0, 0.0]] * 3)
    answers["computePixels"] = lambda args: structured(pre=np.flipud(pre), post=np.flipud(post))
    landfall = datetime(2025, 10, 28, 21)
    drop, meta = satellite.nightlight_drop(landfall, GRID_LATS, GRID_LONS)

    row = drop[0]
    assert row[0] == pytest.approx(0.8)
    assert np.isnan(row[1]), "a cell under the lit threshold cannot lose its lights"
    assert np.isnan(row[2]), "no clear night after: unknown"
    assert row[3] == -1.0 and np.isnan(row[4])
    assert meta["lit_cells"] == 9 and meta["lit_cells_unknown_after"] == 3
    text = "\n".join(log)
    assert "ImageCollection('NASA/VIIRS/002/VNP46A2')" in text
    assert "Date('2025-10-14T21:00:00')" in text and "Date('2025-10-25T21:00:00')" in text
    assert "Date('2025-10-29T09:00:00')" in text and "Date('2025-10-31T21:00:00')" in text
    assert "image.select('Mandatory_Quality_Flag').lte(1)" in text, "cloud and poor retrievals masked"
    assert "unmask(-1)" in text


def test_flooding_uses_a_same_orbit_pair_and_masks_water_and_slopes(fake_ee):
    log, answers = fake_ee
    landfall = datetime(2025, 10, 28, 21)
    ms = lambda t: int((t - datetime(1970, 1, 1)).total_seconds() * 1000)
    scenes = [(landfall - timedelta(days=6), 12), (landfall + timedelta(hours=26), 99),
              (landfall + timedelta(days=2, hours=3), 12)]
    answers["system:time_start"] = [ms(t) for t, _ in scenes]
    answers["relativeOrbitNumber_start"] = [o for _, o in scenes]
    answers["computePixels"] = lambda args: structured(flooded=np.full((3, 5), 0.25))
    from exposure.osm import BBox

    fraction, meta = satellite.flood_fraction(landfall, BBox(16.0, 16.2, 81.0, 81.4),
                                              GRID_LATS, GRID_LONS)
    assert np.allclose(fraction, 0.25)
    assert meta["relative_orbit"] == 12, "orbit 99 has no pass before landfall to compare with"
    assert meta["after_minus_landfall_days"] == 2.1
    text = "\n".join(log)
    assert "ImageCollection('COPERNICUS/S1_GRD')" in text and "'VH'" in text
    assert f"gt({satellite.FLOOD_RATIO})" in text
    assert "focal_mean(50, 'circle', 'meters')" in text
    assert "Image('JRC/GSW1_4/GlobalSurfaceWater').select('seasonality').gte(10)" in text
    assert "gt(5.0)" in text, "slopes over 5% masked"


def test_without_earth_engine_an_observation_says_why(monkeypatch):
    from ingest import earthengine

    monkeypatch.setattr(earthengine, "initialise", lambda *a: False)
    monkeypatch.setattr(earthengine, "availability", lambda: (False, "not signed in to Earth Engine"))
    with pytest.raises(RuntimeError, match="not signed in"):
        satellite._ee()


# --- hazard/terrain.py ------------------------------------------------------------

class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(outcome):
    def fake(req, timeout, context):
        assert req.get_method() == "HEAD", "the ocean check must not download the tile"
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)
    return fake


@pytest.mark.parametrize("outcome, ocean", [
    (200, False),
    (urllib.error.HTTPError("u", 404, "Not Found", Message(), io.BytesIO()), True),
])
def test_a_missing_tile_is_open_sea_and_a_present_one_is_land(monkeypatch, outcome, ocean):
    from hazard import terrain

    monkeypatch.setattr("urllib.request.urlopen", _urlopen(outcome))
    assert terrain._tile_is_ocean("https://example.invalid/t.tif") is ocean


@pytest.mark.parametrize("outcome", [
    302, urllib.error.HTTPError("u", 503, "Unavailable", Message(), io.BytesIO()),
    urllib.error.URLError("no route"), TimeoutError("slow"),
])
def test_anything_else_is_a_fetch_error_never_sea(monkeypatch, outcome):
    """A transient failure once became zeros, and phantom ocean 40 km inland."""
    from hazard import terrain

    monkeypatch.setattr("urllib.request.urlopen", _urlopen(outcome))
    with pytest.raises(terrain.TileFetchError):
        terrain._tile_is_ocean("https://example.invalid/t.tif")


class _Dataset:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, band, out_shape, resampling):
        return np.full(out_shape, 7.0)


def test_a_tile_that_fails_to_read_is_retried_then_cached(monkeypatch, tmp_path):
    import rasterio
    from rasterio.errors import RasterioIOError

    from hazard import terrain

    monkeypatch.setattr(terrain, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(terrain, "_tile_is_ocean", lambda url: False)
    monkeypatch.setattr(terrain.time, "sleep", lambda s: None)
    attempts = []

    def flaky(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise RasterioIOError("connection reset")
        return _Dataset()

    monkeypatch.setattr(rasterio, "open", flaky)
    tile = terrain._read_tile(16, 81)
    assert tile is not None and tile.shape == (terrain.SAMPLES_PER_DEG,) * 2 and tile[0, 0] == 7.0
    assert len(attempts) == 3 and attempts[0].startswith("/vsicurl/")
    assert terrain._read_tile(16, 81) is not None and len(attempts) == 3, "read from the cache"


def test_a_tile_that_never_reads_is_an_error_not_zeros(monkeypatch, tmp_path):
    import rasterio
    from rasterio.errors import RasterioIOError

    from hazard import terrain

    monkeypatch.setattr(terrain, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(terrain, "_tile_is_ocean", lambda url: False)
    monkeypatch.setattr(terrain.time, "sleep", lambda s: None)

    def broken(path):
        raise RasterioIOError("gone")

    monkeypatch.setattr(rasterio, "open", broken)
    with pytest.raises(terrain.TileFetchError, match="after 3 attempts"):
        terrain._read_tile(16, 81)
    assert list(tmp_path.iterdir()) == [], "nothing cached"


def test_earth_engine_terrain_is_fetched_in_blocks_and_assembled(monkeypatch, tmp_path):
    """The box is over Earth Engine's per-request limit, so it comes in
    blocks; each block must land where its request said it was."""
    from hazard import terrain
    from ingest import earthengine

    n = terrain.SAMPLES_PER_DEG
    log, requests = [], []

    def answer(path, args):
        grid = args[0]["grid"]
        t, d = grid["affineTransform"], grid["dimensions"]
        requests.append((round((81.0 + 0 - t["translateX"]) * -n), d["width"], d["height"]))
        row0 = round((16.6 - t["translateY"]) * n)
        col0 = round((t["translateX"] - 81.0) * n)
        return structured(DEM=np.full((d["height"], d["width"]), float(row0 * 10_000 + col0)))

    ee = Chain(log, answer)
    monkeypatch.setitem(sys.modules, "ee", ee)
    monkeypatch.setitem(sys.modules, "ee.data", ee.data)
    monkeypatch.setattr(earthengine, "initialise", lambda *a: True)
    monkeypatch.setattr(terrain, "CACHE_DIR", tmp_path)

    dem = terrain.EarthEngineDEM(16.0, 16.6, 81.0, 81.6)
    size = round(0.6 * n)
    assert dem._mosaic.shape == (size, size)
    block = terrain.EarthEngineDEM.BLOCK
    assert len(requests) == 4, "two blocks down, two across"
    assert dem._mosaic[0, 0] == 0 and dem._mosaic[0, block] == block
    assert dem._mosaic[block, 0] == block * 10_000 and dem._mosaic[-1, -1] == block * 10_001
    text = "\n".join(log)
    assert f"ImageCollection('{terrain.EarthEngineDEM.ASSET}').select('DEM')" in text
    assert "unmask(0)" in text, "open sea has no tile and becomes 0 m"
    # Cached: a second build asks nothing.
    requests.clear()
    terrain.EarthEngineDEM(16.0, 16.6, 81.0, 81.6)
    assert requests == []


def test_terrain_falls_back_from_earth_engine_to_aws_to_flat(monkeypatch, capsys):
    from hazard import terrain

    def refuse(*a, **k):
        raise RuntimeError("not signed in to Earth Engine")

    class AWS:
        def __init__(self, *a):
            pass

    monkeypatch.setattr(terrain, "EarthEngineDEM", refuse)
    monkeypatch.setattr(terrain, "CopernicusDEM", AWS)
    _, source = terrain.load_terrain(16.0, 16.6, 81.0, 81.6)
    assert source == "aws-copernicus"

    monkeypatch.setattr(terrain, "CopernicusDEM", refuse)
    _, source = terrain.load_terrain(16.0, 16.6, 81.0, 81.6)
    assert source == "flat-placeholder"
    out = capsys.readouterr().out
    assert "tried ee: RuntimeError: not signed in" in out and "tried aws" in out
