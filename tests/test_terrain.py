"""Terrain source tests.

The DEM tests run on committed, downsampled Copernicus tiles
(tests/fixtures/dem), so they need neither network nor a warm cache. Tests
marked `network` probe the live bucket and are opt-in.
"""

from pathlib import Path

import numpy as np
import pytest

from hazard.terrain import SEA_LEVEL_M, CopernicusDEM, load_terrain

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
AOI = (15.7, 17.4, 80.6, 82.6)   # coastal Andhra, Montha's landfall region


def test_each_backend_is_actually_distinct():
    """Guards a real bug: every non-'ee' value fell through to the AWS DEM.

    The flat placeholder was silently returned as the real thing, so a
    comparison between them produced identical numbers and looked like the
    swap had no effect.
    """
    _, flat = load_terrain(*AOI, prefer="flat")
    assert flat == "flat-placeholder"


def test_unknown_source_is_rejected_loudly():
    """Silently substituting a different terrain model is worse than failing."""
    with pytest.raises(ValueError, match="unknown terrain source"):
        load_terrain(*AOI, prefer="satellite-vibes")


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "dem" / "andhra_225.npz"


@pytest.fixture(scope="module")
def dem(tmp_path_factory):
    """The real mosaic code, fed the committed tiles (fixtures/dem) at 225
    samples per degree instead of fetching from AWS at 900."""
    import hazard.terrain as terrain

    cache = tmp_path_factory.mktemp("dem")
    tiles = np.load(FIXTURE)
    for name in tiles.files:
        np.save(cache / f"{name}_225.npy", tiles[name].astype("float32"))
    (cache / "dem_15_82.ocean").touch()
    mp = pytest.MonkeyPatch()
    mp.setattr(terrain, "CACHE_DIR", cache)
    mp.setattr(terrain, "SAMPLES_PER_DEG", 225)
    mp.setattr(terrain, "_tile_is_ocean", lambda url: pytest.fail(f"network touched: {url}"))
    try:
        return CopernicusDEM(*AOI)
    finally:
        mp.undo()


def at(dem, lat, lon):
    return (
        float(dem.elevation_m(np.array([lat]), np.array([lon]))[0]),
        float(dem.distance_to_coast_km(np.array([lat]), np.array([lon]))[0]),
    )


def test_open_ocean_reads_as_sea(dem):
    elev, dist = at(dem, 15.90, 82.40)
    assert elev <= SEA_LEVEL_M
    assert dist < 0, "offshore must be negative distance to coast"


def test_delta_towns_are_low_lying(dem):
    """Narasapuram and Machilipatnam sit a few metres above sea level.

    This is why surge matters here at all -- and why an elevation model that
    gets it wrong flags the wrong assets.
    """
    for lat, lon in [(16.43, 81.70), (16.17, 81.13)]:
        elev, dist = at(dem, lat, lon)
        assert 0 < elev < 15, f"expected a low delta town, got {elev:.1f} m"
        assert dist > 0, "a town must be on the land side of the coastline"


def test_inland_is_higher_than_the_coast(dem):
    coast_elev, coast_dist = at(dem, 16.95, 82.24)     # Kakinada port
    inland_elev, inland_dist = at(dem, 17.00, 81.78)   # Rajahmundry, upriver
    assert inland_elev > coast_elev
    assert inland_dist > coast_dist


def test_coastline_is_not_a_straight_line(dem):
    """The whole point of the real DEM.

    A fitted straight coast gives the same distance-to-coast at every latitude
    for a fixed longitude. A real delta does not.
    """
    lats = np.linspace(15.9, 17.2, 40)
    lons = np.full_like(lats, 81.9)
    dists = dem.distance_to_coast_km(lats, lons)
    assert dists.std() > 5.0, "a real coastline varies along its length"


def test_mosaic_is_mostly_sensible(dem):
    """Sanity bounds. The Eastern Ghats clip the north-west corner."""
    assert 0 < dem._mosaic.max() < 3000
    land = dem._mosaic > SEA_LEVEL_M
    assert 0.3 < land.mean() < 0.85, "a coastal box should be part land, part sea"


# --- fetch failures must not masquerade as geography --------------------

@pytest.mark.network
def test_absent_tile_is_treated_as_ocean():
    """N15 E082 is open Bay of Bengal and genuinely absent from the bucket."""
    from hazard.terrain import _tile_is_ocean, _tile_name

    assert _tile_is_ocean(_tile_name(15, 82)) is True


@pytest.mark.network
def test_land_tile_is_not_treated_as_ocean():
    from hazard.terrain import _tile_is_ocean, _tile_name

    assert _tile_is_ocean(_tile_name(16, 81)) is False


def test_unreachable_host_raises_instead_of_becoming_sea():
    """The bug this guards against actually happened.

    A serial run hit transient read failures, those tiles silently became
    zeros, and the derived coastline grew phantom ocean -- which put
    Rajahmundry, some 40 km up the Godavari, at 0.0 km from the coast. The
    mosaic looked entirely plausible at 44% land instead of 55%.
    """
    from hazard.terrain import TileFetchError, _tile_is_ocean

    with pytest.raises(TileFetchError):
        _tile_is_ocean("https://copernicus-dem-30m.s3.amazonaws.invalid/nope.tif")


def test_mosaic_reports_how_it_was_assembled(dem):
    """A partial mosaic should be visible, not inferred."""
    assert dem.tiles_total == 9
    assert dem.tiles_ocean == 1, "only N15 E082 is open sea in this AOI"


def test_a_degenerate_earth_engine_terrain_is_refused():
    """A 3x3 'terrain' once came back from a request with no scale and was
    modelled on for a whole run. It must now be an error, so load_terrain
    falls back to the AWS copy of the same elevation model."""
    import numpy as np
    import pytest

    from hazard.terrain import EarthEngineDEM

    with pytest.raises(ValueError, match="terrain grid"):
        EarthEngineDEM._checked(np.zeros((3, 3), dtype="float32"))
    assert EarthEngineDEM._checked(np.zeros((200, 300))).shape == (200, 300)
