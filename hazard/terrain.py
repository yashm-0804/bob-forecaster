"""Real terrain from the Copernicus 30 m digital elevation model.

Replaces the flat-plain placeholder in surge_screen.py. That placeholder had a
straight coastline and a constant inland slope, so it knew nothing about the
creeks, embankments and distributary channels of the Godavari-Krishna delta --
which are precisely what route surge inland. Results computed on it were
directional only.

The tiles are public on AWS with no credentials and are Cloud-Optimized
GeoTIFFs, so a windowed, decimated read pulls only the bytes covering the area
of interest instead of the whole 1-degree tile. Nothing here touches Earth
Engine or its compute quota.

Source: Copernicus DEM GLO-30, ESA, s3://copernicus-dem-30m (open data).
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from common.errors import reraise_bugs
from hazard.surge_screen import ElevationSource
from ingest.net import https_open, https_request

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

#: Public HTTPS endpoint for the open-data bucket. GDAL reads it through
#: /vsicurl/, which issues HTTP range requests against the COG.
TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)

#: Samples per degree to read. Native is 3600 (30 m) and the COGs carry
#: overviews at /2, /4 and /8 -- so 900 lands exactly on the /4 overview and
#: GDAL fetches only that level. Asking for a size between overview levels, or
#: using an averaging resampler, forces a full-resolution read of the whole
#: tile instead: the difference is seconds versus many minutes over HTTP.
#: 900 per degree is ~123 m, still an order of magnitude finer than the 0.02
#: degree hazard grid, and fine enough to resolve the delta's inlets.
SAMPLES_PER_DEG = 900

#: Anything at or below this height is treated as sea when deriving the
#: coastline. Copernicus DSM returns values near zero over open water.
SEA_LEVEL_M = 0.5


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return TILE_URL.format(ns=ns, lat=abs(lat), ew=ew, lon=abs(lon))



class TileFetchError(RuntimeError):
    """A tile that should exist could not be read.

    Deliberately distinct from a tile that legitimately does not exist.
    Treating a failed fetch as ocean silently corrupts the land mask and the
    coastline derived from it, and the result still looks entirely plausible --
    which is exactly how it goes unnoticed.
    """


def _tile_is_ocean(url: str) -> bool:
    """Whether this square is genuinely absent from the bucket.

    The bucket holds land tiles only, so a 404 means open ocean and zeros are
    the right answer. Any other failure is a fetch problem, not a statement
    about geography, so it is raised rather than swallowed.

    Checking with a HEAD first also saves GDAL's retry-and-backoff on the
    tiles that will never exist.
    """
    import urllib.error

    req = https_request(url, method="HEAD")
    try:
        with https_open(req, timeout=20) as resp:
            if resp.status == 200:
                return False
            raise TileFetchError(f"unexpected status {resp.status} for {url}")
    except urllib.error.HTTPError as exc:
        exc.close()              # the error carries an open response
        if exc.code == 404:
            return True          # genuinely open ocean
        raise TileFetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TileFetchError(f"could not reach {url}: {exc}") from exc


def _read_tile(lat: int, lon: int, attempts: int = 3) -> np.ndarray | None:
    """Read one 1-degree tile, decimated.

    Returns None only when the tile genuinely does not exist, which means open
    ocean. A tile that exists but cannot be read is retried and then raised as
    TileFetchError -- never quietly turned into zeros.
    """
    import os

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.errors import RasterioIOError

    # The bucket is public; without this GDAL looks for credentials and fails.
    # Set here rather than left to the caller so the module works standalone.
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

    cache = CACHE_DIR / f"dem_{lat}_{lon}_{SAMPLES_PER_DEG}.npy"
    if cache.exists():
        return np.load(cache)
    # A 404 is permanent -- the square is open sea -- so it is cached too.
    # Leaving it uncached sent every run back to the network for it, and one
    # timed-out check was enough to knock a whole run onto placeholder terrain.
    ocean = CACHE_DIR / f"dem_{lat}_{lon}.ocean"
    if ocean.exists():
        return None

    url = _tile_name(lat, lon)
    if _tile_is_ocean(url):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ocean.touch()
        return None

    vsi = f"/vsicurl/{url}"
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with rasterio.open(vsi) as src:
                data = src.read(
                    1,
                    out_shape=(SAMPLES_PER_DEG, SAMPLES_PER_DEG),
                    resampling=Resampling.bilinear,
                ).astype("float32")
            break
        except RasterioIOError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise TileFetchError(
            f"tile N{lat} E{lon} exists but could not be read after "
            f"{attempts} attempts: {last}"
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(cache, data)
    return data


class CopernicusDEM:
    """Elevation and distance-to-coast over a bounding box.

    Implements the same interface as FlatDeltaPlain, so surge_screen.py and
    pipeline.py are unchanged by the swap.
    """

    def __init__(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
    ) -> None:
        self.bounds = (lat_min, lat_max, lon_min, lon_max)
        self._mosaic, self._extent = self._build_mosaic()
        self._coast_km: np.ndarray | None = None

    def _build_mosaic(self) -> tuple[np.ndarray, tuple[float, float, float, float]]:
        """Stitch every 1-degree tile covering the bounds into one array.

        Tiles are fetched concurrently. Each is an independent read of a few
        hundred KB, so wall time is dominated by round-trip latency rather than
        bandwidth: serially this takes many minutes, in parallel roughly as
        long as the slowest single tile.
        """
        from concurrent.futures import ThreadPoolExecutor

        lat_min, lat_max, lon_min, lon_max = self.bounds
        lat0, lat1 = math.floor(lat_min), math.floor(lat_max)
        lon0, lon1 = math.floor(lon_min), math.floor(lon_max)

        rows, cols = lat1 - lat0 + 1, lon1 - lon0 + 1
        n = SAMPLES_PER_DEG
        mosaic = np.zeros((rows * n, cols * n), dtype="float32")

        # (row, col) in the mosaic -> (lat, lon) of that tile, north to south
        wanted: dict[tuple[int, int], tuple[int, int]] = {
            (r, c): (lat, lon)
            for r, lat in enumerate(range(lat1, lat0 - 1, -1))
            for c, lon in enumerate(range(lon0, lon1 + 1))
        }

        ocean = 0
        # Four workers, not nine. Nine concurrent GDAL range-readers against
        # the same S3 bucket reliably trips a read failure part-way through;
        # four gets most of the speedup without it. Wall time is latency-bound
        # either way, so the extra parallelism bought little.
        with ThreadPoolExecutor(max_workers=min(4, len(wanted))) as pool:
            # _read_tile raises on a tile that exists but will not read, so a
            # partial mosaic propagates as an error instead of quietly
            # becoming sea.
            def fetch(item: tuple[tuple[int, int], tuple[int, int]]
                      ) -> tuple[tuple[int, int], np.ndarray | None]:
                return item[0], _read_tile(*item[1])

            for (r, c), tile in pool.map(fetch, wanted.items()):
                if tile is not None:
                    mosaic[r * n:(r + 1) * n, c * n:(c + 1) * n] = tile
                else:
                    ocean += 1   # genuinely absent from the bucket: open sea

        self.tiles_total = len(wanted)
        self.tiles_ocean = ocean

        # extent as (north, south, west, east) of the mosaic's outer edges
        return mosaic, (lat1 + 1.0, float(lat0), float(lon0), lon1 + 1.0)

    def _sample(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Bilinear sample of the mosaic at arbitrary lat/lon points."""
        from scipy.ndimage import map_coordinates

        north, south, west, east = self._extent
        h, w = self._mosaic.shape

        row = (north - lats) / (north - south) * (h - 1)
        col = (lons - west) / (east - west) * (w - 1)

        return map_coordinates(
            self._mosaic, [row, col], order=1, mode="nearest"
        ).astype("float32")

    def elevation_m(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Ground height above sea level, metres."""
        return self._sample(lats, lons)

    def distance_to_coast_km(
        self, lats: np.ndarray, lons: np.ndarray
    ) -> np.ndarray:
        """Distance inland from the shoreline, km. Negative offshore.

        The coastline is derived from the terrain itself rather than fitted to
        a straight line, so it follows the real shape of the delta -- including
        the inlets that carry surge much further inland than a smooth coast
        would suggest.
        """
        from scipy.ndimage import distance_transform_edt

        coast = self._coast_km
        if coast is None:
            sea = self._mosaic <= SEA_LEVEL_M

            # Distance from each land cell to the nearest sea cell, and from
            # each sea cell to the nearest land cell. Combining them signed
            # gives one field that is positive inland and negative offshore.
            # (With default flags the transform returns an array; asarray
            # says so to a type checker that sees a union.)
            to_sea = np.asarray(distance_transform_edt(~sea))
            to_land = np.asarray(distance_transform_edt(sea))
            signed = np.where(sea, -to_land, to_sea)

            north, south, _, _ = self._extent
            km_per_cell = (north - south) * 111.0 / self._mosaic.shape[0]
            coast = (signed * km_per_cell).astype("float32")
            self._coast_km = coast

        from scipy.ndimage import map_coordinates

        north, south, west, east = self._extent
        h, w = coast.shape
        row = (north - lats) / (north - south) * (h - 1)
        col = (lons - west) / (east - west) * (w - 1)
        return map_coordinates(
            coast, [row, col], order=1, mode="nearest"
        ).astype("float32")

    def describe(self) -> str:
        land = self._mosaic > SEA_LEVEL_M
        return (
            f"Copernicus DEM GLO-30 mosaic {self._mosaic.shape[0]}x{self._mosaic.shape[1]} "
            f"(~{111_000 / SAMPLES_PER_DEG:.0f} m/px)\n"
            f"  land {land.mean() * 100:.0f}% of mosaic · "
            f"max {self._mosaic.max():.0f} m · mean land {self._mosaic[land].mean():.1f} m"
        )


class EarthEngineDEM(CopernicusDEM):
    """The same elevation data, fetched through Earth Engine instead of AWS.

    Earth Engine mosaics the tiles and averages them down server-side, so this
    path needs no GDAL. It is fetched at the AWS path's resolution
    (SAMPLES_PER_DEG), so the two sources are interchangeable -- and can be
    checked against each other.

    Quota note: one `computePixels` request over the bounding box, cached to
    disk. A few EECU-seconds, not hours.
    """

    ASSET = "COPERNICUS/DEM/GLO30_2024_1"
    #: Anything smaller than this is a failed fetch, not a terrain model.
    MIN_SIDE = 100
    #: Output pixels per request side: half a degree, ~13 MB of 30 m input.
    BLOCK = SAMPLES_PER_DEG // 2

    def __init__(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        project: str | None = None,
    ) -> None:
        self.bounds = (lat_min, lat_max, lon_min, lon_max)
        self._project = project
        self._mosaic = self._fetch()
        # Pixel centres of the outer rows and columns, which is what the
        # shared sampler maps to the first and last index.
        half = 0.5 / SAMPLES_PER_DEG
        self._extent = (lat_max - half, lat_min + half, lon_min + half, lon_max - half)
        self._coast_km: np.ndarray | None = None

    def _fetch(self) -> np.ndarray:
        lat_min, lat_max, lon_min, lon_max = self.bounds
        n = SAMPLES_PER_DEG
        cache = CACHE_DIR / f"ee_dem_{lat_min}_{lat_max}_{lon_min}_{lon_max}_{n}.npy"
        if cache.exists():
            return self._checked(np.load(cache))

        import ee
        import ee.data as ee_data

        from ingest import earthengine

        if not earthengine.initialise(self._project):
            raise RuntimeError(earthengine.availability()[1])

        coll = ee.ImageCollection(self.ASSET).select("DEM")
        # A mosaic has no projection of its own; restore the tiles' before
        # averaging 30 m pixels into each output pixel. Open sea has no tile,
        # so it is masked -- and becomes 0 m, as on the AWS path.
        native = coll.first().projection()
        image = (coll.mosaic().setDefaultProjection(native)
                 .reduceResolution(ee.Reducer.mean(), maxPixels=64)
                 .unmask(0).toFloat())
        width = round((lon_max - lon_min) * n)
        height = round((lat_max - lat_min) * n)

        def block(r0: int, c0: int) -> tuple[int, int, np.ndarray]:
            h, w = min(self.BLOCK, height - r0), min(self.BLOCK, width - c0)
            raw = ee_data.computePixels({
                "expression": image,
                "fileFormat": "NUMPY_NDARRAY",
                "grid": {
                    "dimensions": {"width": w, "height": h},
                    "affineTransform": {"scaleX": 1 / n, "shearX": 0,
                                        "translateX": lon_min + c0 / n,
                                        "shearY": 0, "scaleY": -1 / n,
                                        "translateY": lat_max - r0 / n},
                    "crsCode": "EPSG:4326",
                },
            })
            return r0, c0, np.asarray(raw["DEM"], dtype="float32")

        # The 30 m pixels behind the whole box are ~180 MB, over Earth
        # Engine's per-request limit, so it is fetched in blocks.
        from concurrent.futures import ThreadPoolExecutor

        array = np.zeros((height, width), dtype="float32")
        rows = [r for r in range(0, height, self.BLOCK) for _ in range(0, width, self.BLOCK)]
        cols = [c for _ in range(0, height, self.BLOCK) for c in range(0, width, self.BLOCK)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for r0, c0, part in pool.map(block, rows, cols):
                array[r0:r0 + part.shape[0], c0:c0 + part.shape[1]] = part
        array = self._checked(array)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(cache, array)
        return array

    @classmethod
    def _checked(cls, array: np.ndarray) -> np.ndarray:
        """Refuse a degenerate fetch rather than model a coast on it.

        An earlier version of this path asked Earth Engine for the terrain
        without a scale and got back a 3x3 array, which silently became the
        terrain for a whole run. A size check turns that into an error, and
        load_terrain falls back to AWS.
        """
        if min(array.shape) < cls.MIN_SIDE:
            raise ValueError(f"Earth Engine returned a {array.shape} terrain grid; "
                             f"expected at least {cls.MIN_SIDE} px a side")
        return array

    # Sampling and coastline derivation are inherited: identical to the AWS
    # path, which is why the two sources can be checked against each other.

    def describe(self) -> str:
        land = self._mosaic > SEA_LEVEL_M
        return (
            f"Copernicus GLO-30 via Earth Engine, {self._mosaic.shape[0]}x"
            f"{self._mosaic.shape[1]} (~{111_000 / SAMPLES_PER_DEG:.0f} m/px)\n"
            f"  land {land.mean() * 100:.0f}% · max {self._mosaic.max():.0f} m"
        )


def load_terrain(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    prefer: str = "auto",
    project: str | None = None,
) -> tuple[ElevationSource, str]:
    """Return the best terrain source available, and say which one it is.

    Order is deliberate. Earth Engine first, because the brief asks for it and
    because it needs no GDAL. AWS second, because it needs no credentials.
    The flat placeholder last, so a demo never hard-fails on a missing
    dependency -- but it announces itself loudly, since results computed on it
    are directional only.
    """
    from hazard.surge_screen import FlatDeltaPlain

    if prefer == "flat":
        return FlatDeltaPlain(), "flat-placeholder"

    orders = {
        "auto": ["ee", "aws"],
        "ee": ["ee"],
        "aws": ["aws"],
    }
    if prefer not in orders:
        raise ValueError(
            f"unknown terrain source {prefer!r}; expected auto, ee, aws or flat"
        )

    builders = {
        "ee": lambda: (
            EarthEngineDEM(lat_min, lat_max, lon_min, lon_max, project),
            "earth-engine",
        ),
        "aws": lambda: (
            CopernicusDEM(lat_min, lat_max, lon_min, lon_max),
            "aws-copernicus",
        ),
    }

    attempts: list[str] = []
    for backend in orders[prefer]:
        try:
            return builders[backend]()
        except Exception as exc:  # noqa: BLE001 - any failure means try the next source
            reraise_bugs(exc)          # a bug is not a failed source
            attempts.append(f"{backend}: {type(exc).__name__}: {exc}")

    print("WARNING: no real elevation source available, using flat placeholder.")
    for line in attempts:
        print(f"  tried {line}")
    return FlatDeltaPlain(), "flat-placeholder"
