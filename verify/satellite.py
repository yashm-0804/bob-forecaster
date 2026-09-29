"""What actually happened, from satellites, on the model's own grid.

Three observations, each pulled through Earth Engine straight onto the hazard
grid with `computePixels` -- a few kilobytes per layer, cached on disk, so the
free-tier compute quota barely moves:

  rain     GPM IMERG V07 accumulation over a window, mm.
  lights   VIIRS Black Marble night-time radiance before and after landfall.
           The NON-gap-filled product, masked for cloud: the gap-filled one
           carries the last clear night forward when it is cloudy, and under
           a cyclone that shows pre-storm lights and hides the outage. A cell
           with no clear post-storm night is unknown, not a guess.
  flood    Sentinel-1 change detection following UN-SPIDER's recommended
           practice: same-orbit before/after pair, speckle smoothing, the
           after/before ratio of VH backscatter (in dB) above 1.25, permanent
           water and slopes over 5% masked. Reported as the flooded fraction
           of each grid cell.

Each observation carries its provenance -- dates, orbits, how many cells are
unknown -- because a verification is only as good as what it was checked
against.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from exposure.osm import BBox

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "observed"

#: UN-SPIDER Sentinel-1 flood mapping recommended practice.
FLOOD_RATIO = 1.25
SMOOTHING_M = 50
MAX_SLOPE_PCT = 5.0
PERMANENT_WATER_MONTHS = 10

#: Night-lights: a cell must have been lit to lose its lights.
LIT_NW = 2.0


def _ee() -> Any:
    from ingest import earthengine

    if not earthengine.initialise():
        raise RuntimeError(earthengine.availability()[1])
    import ee
    return ee


def _date(ee: Any, when: datetime) -> Any:
    return ee.Date(when.strftime("%Y-%m-%dT%H:%M:%S"))


def _on_grid(ee: Any, image: Any, lats: np.ndarray, lons: np.ndarray) -> dict[str, np.ndarray]:
    """Compute an image directly onto the hazard grid; bands -> arrays.

    The hazard grid runs south to north along axis 0; Earth Engine returns
    rows north first, so the result is flipped to match.
    """
    lat_axis, lon_axis = lats[:, 0], lons[0, :]
    step_lat = float(lat_axis[1] - lat_axis[0])
    step_lon = float(lon_axis[1] - lon_axis[0])
    request = {
        "expression": image,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": len(lon_axis), "height": len(lat_axis)},
            "affineTransform": {
                "scaleX": step_lon, "shearX": 0,
                "translateX": float(lon_axis[0]) - step_lon / 2,
                "shearY": 0, "scaleY": -step_lat,
                "translateY": float(lat_axis[-1]) + step_lat / 2,
            },
            "crsCode": "EPSG:4326",
        },
    }
    raw = ee.data.computePixels(request)
    return {name: np.flipud(np.asarray(raw[name], dtype=float)) for name in raw.dtype.names}


def _cached(key: str, compute: Callable[[], tuple[dict[str, np.ndarray], dict[str, Any]]]
            ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Arrays and provenance, computed once and kept on disk."""
    arrays_path = CACHE_DIR / f"{key}.npz"
    meta_path = CACHE_DIR / f"{key}.json"
    if arrays_path.exists() and meta_path.exists():
        z = np.load(arrays_path)
        return {k: z[k] for k in z.files}, json.loads(meta_path.read_text())
    arrays, meta = compute()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # cast: numpy's stub types **kwargs as its own keyword parameters.
    np.savez_compressed(arrays_path, **cast(dict[str, Any], arrays))
    meta_path.write_text(json.dumps(meta, indent=1))
    return arrays, meta


def _grid_key(lats: np.ndarray, lons: np.ndarray) -> str:
    return (f"{lats.min():.2f}_{lats.max():.2f}_{lons.min():.2f}_{lons.max():.2f}_"
            f"{lats.shape[0]}x{lats.shape[1]}")


# --- rain -----------------------------------------------------------------

def observed_rain(start: datetime, end: datetime, lats: np.ndarray, lons: np.ndarray
                  ) -> tuple[np.ndarray, dict[str, Any]]:
    """GPM IMERG V07 rainfall accumulated between two times, mm."""
    key = f"imerg_{start:%Y%m%d%H}_{end:%Y%m%d%H}_{_grid_key(lats, lons)}"

    def compute() -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        ee = _ee()
        coll = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
                .filterDate(_date(ee, start), _date(ee, end)).select("precipitation"))
        n = coll.size().getInfo()
        # Half-hourly rates in mm/h: each image contributes half an hour.
        # IMERG is 0.1 degrees, coarser than the grid, so it is interpolated
        # rather than averaged; the projection is restored after summing.
        native = coll.first().projection()
        total = (coll.sum().multiply(0.5).rename("rain_mm")
                 .setDefaultProjection(native).resample("bilinear"))
        arrays = _on_grid(ee, total, lats, lons)
        return {"rain_mm": arrays["rain_mm"]}, {
            "source": "NASA/GPM_L3/IMERG_V07", "start": start.isoformat(),
            "end": end.isoformat(), "half_hourly_images": n,
        }

    arrays, meta = _cached(key, compute)
    return arrays["rain_mm"], meta


# --- lights ---------------------------------------------------------------

def nightlight_drop(landfall: datetime, lats: np.ndarray, lons: np.ndarray
                    ) -> tuple[np.ndarray, dict[str, Any]]:
    """Fractional drop in night-time radiance after landfall, per cell.

    NaN where the cell was not lit beforehand or had no clear night after.
    """
    key = f"viirs_{landfall:%Y%m%d%H}_{_grid_key(lats, lons)}"

    def compute() -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        ee = _ee()
        coll = ee.ImageCollection("NASA/VIIRS/002/VNP46A2")

        def clear(img: Any) -> Any:
            ntl = img.select("DNB_BRDF_Corrected_NTL")
            quality = img.select("Mandatory_Quality_Flag")
            # 0 and 1 are high-quality retrievals; 2 is poor, 255 is none.
            return ntl.updateMask(quality.lte(1))

        pre = (coll.filterDate(_date(ee, landfall - timedelta(days=14)),
                               _date(ee, landfall - timedelta(days=3)))
               .map(clear).median().rename("pre"))
        post = (coll.filterDate(_date(ee, landfall + timedelta(hours=12)),
                                _date(ee, landfall + timedelta(days=3)))
                .map(clear).median().rename("post"))
        # Radiance is ~500 m and the grid 2.2 km, so each cell is the mean of
        # the pixels inside it -- not one sampled pixel. A composite has no
        # fixed projection, so the source's is restored before averaging, and
        # masked (cloudy) pixels are left out of the mean rather than counted
        # as dark. Only then are the gaps filled with -1 to survive transfer.
        native = coll.first().select("DNB_BRDF_Corrected_NTL").projection()
        both = (pre.addBands(post).setDefaultProjection(native)
                .reduceResolution(ee.Reducer.mean(), maxPixels=1024)
                .unmask(-1))
        arrays = _on_grid(ee, both, lats, lons)
        return {"pre": arrays["pre"], "post": arrays["post"]}, {
            "source": "NASA/VIIRS/002/VNP46A2 (DNB_BRDF_Corrected_NTL, quality-masked)",
            "pre_window_days": [-14, -3], "post_window_days": [0.5, 3],
        }

    arrays, meta = _cached(key, compute)
    pre, post = arrays["pre"], arrays["post"]
    pre = np.where(pre < 0, np.nan, pre)
    post = np.where(post < 0, np.nan, post)
    lit = pre >= LIT_NW
    drop = np.where(lit & np.isfinite(post), 1.0 - post / np.where(lit, pre, 1.0), np.nan)
    meta = dict(meta, lit_cells=int(lit.sum()),
                lit_cells_unknown_after=int((lit & ~np.isfinite(post)).sum()))
    return np.clip(drop, -1.0, 1.0), meta


# --- flood ----------------------------------------------------------------

def _best_pair(ee: Any, aoi: Any, landfall: datetime) -> tuple[Any, datetime, datetime, int]:
    """The earliest post-landfall Sentinel-1 date and the latest pre-landfall
    date on the SAME relative orbit -- change detection is only valid when
    both images see the ground from the same geometry."""
    coll = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
            .filterDate(_date(ee, landfall - timedelta(days=24)),
                        _date(ee, landfall + timedelta(days=12))))
    times = coll.aggregate_array("system:time_start").getInfo()
    orbits = coll.aggregate_array("relativeOrbitNumber_start").getInfo()
    scenes = [(datetime.fromtimestamp(t / 1000, tz=UTC).replace(tzinfo=None), o)
              for t, o in zip(times, orbits, strict=True)]
    return (coll, *pick_pair(scenes, landfall))


def pick_pair(scenes: list[tuple[datetime, int]], landfall: datetime
              ) -> tuple[datetime, datetime, int]:
    """(before, after, orbit): the earliest pass after landfall that has an
    earlier pass on the same relative orbit, and that earlier pass.

    Scenes are (time, relative orbit), naive UTC; frames of one pass are
    merged by rounding to the hour.
    """
    hourly = sorted({(t.replace(minute=0, second=0, microsecond=0), o) for t, o in scenes})
    for post_time, orbit in (s for s in hourly if s[0] > landfall):
        before = [s for s in hourly if s[1] == orbit and s[0] < landfall]
        if before:
            return before[-1][0], post_time, orbit
    raise LookupError("no same-orbit Sentinel-1 pair around landfall")


def flood_fraction(landfall: datetime, bbox: BBox, lats: np.ndarray, lons: np.ndarray
                   ) -> tuple[np.ndarray, dict[str, Any]]:
    """Share of each grid cell newly flooded, by Sentinel-1 change detection."""
    key = f"s1flood_{landfall:%Y%m%d%H}_{_grid_key(lats, lons)}"

    def compute() -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        ee = _ee()
        aoi = ee.Geometry.Rectangle([bbox.west, bbox.south, bbox.east, bbox.north])
        coll, pre_t, post_t, orbit = _best_pair(ee, aoi, landfall)

        def mosaic(t: datetime) -> Any:
            day = coll.filter(ee.Filter.eq("relativeOrbitNumber_start", orbit)).filterDate(
                _date(ee, t - timedelta(hours=12)), _date(ee, t + timedelta(hours=12)))
            return day.select("VH").mosaic().focal_mean(SMOOTHING_M, "circle", "meters")

        ratio = mosaic(post_t).divide(mosaic(pre_t))
        flooded = ratio.gt(FLOOD_RATIO)

        permanent = (ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("seasonality")
                     .gte(PERMANENT_WATER_MONTHS))
        slope = ee.Terrain.slope(ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1")
                                 .select("DEM").mosaic()
                                 .setDefaultProjection("EPSG:4326", None, 30))
        steep = slope.tan().multiply(100).gt(MAX_SLOPE_PCT)
        flooded = flooded.where(permanent.Or(steep), 0).unmask(0)

        # Work at 100 m, then take the flooded share of each grid cell.
        fine = flooded.rename("flooded").toFloat().reproject(crs="EPSG:4326", scale=100)
        coarse = fine.reduceResolution(ee.Reducer.mean(), maxPixels=2048)
        arrays = _on_grid(ee, coarse, lats, lons)
        return {"fraction": arrays["flooded"]}, {
            "source": "COPERNICUS/S1_GRD VH, UN-SPIDER change detection",
            "before": pre_t.isoformat(), "after": post_t.isoformat(),
            "relative_orbit": orbit,
            "after_minus_landfall_days": round((post_t - landfall).total_seconds() / 86400, 1),
            "masked": ["JRC permanent water (>=10 months)", "slope > 5%"],
        }

    arrays, meta = _cached(key, compute)
    return arrays["fraction"], meta
