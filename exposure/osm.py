"""Critical infrastructure from OpenStreetMap via the Overpass API.

These are the assets the brief names -- power grids, arterial roads, medical
shelters -- and they are real, named features, not a synthetic layer. That is
the point: an advisory that says "Narsapur 33/11 kV substation" is actionable
in a way that a district shaded orange is not.

Responses are cached on disk. Overpass is a free shared service and this is a
demo that gets re-run constantly; hammering it is both rude and slow.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from common.errors import reraise_bugs
from ingest.net import https_open, https_request

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

#: Which OSM tags map to which fragility curve. The key is the asset class
#: used throughout impact/, so this table is the join between OSM's taxonomy
#: and ours.
ASSET_QUERIES: dict[str, tuple[str, ...]] = {
    "substation": ('node["power"="substation"]', 'way["power"="substation"]'),
    "transmission_tower": ('node["power"="tower"]',),
    "hospital": ('node["amenity"="hospital"]', 'way["amenity"="hospital"]'),
    "shelter": (
        'node["amenity"="shelter"]',
        'way["amenity"="shelter"]',
        'node["emergency"="shelter"]',
        'way["emergency"="shelter"]',
    ),
    "telecom_tower": (
        'node["man_made"="mast"]["tower:type"="communication"]',
        'node["man_made"="communications_tower"]',
    ),
    "road_segment": (
        'way["highway"="trunk"]',
        'way["highway"="primary"]',
    ),
}


@dataclass
class Asset:
    """One piece of infrastructure, located and classified."""

    osm_id: str
    asset_class: str
    name: str
    lat: float
    lon: float
    tags: dict[str, str]

    @property
    def label(self) -> str:
        """What an advisory calls this asset.

        Name first, then the road reference -- "NH16" is what a public works
        engineer actually recognises, and it is present on most unnamed roads
        here (1,859 of 1,990 in coastal Andhra). The OSM id is the last resort,
        because nobody in a control room thinks in node numbers.
        """
        if self.name and self.name != "unnamed":
            return self.name
        ref = (self.tags or {}).get("ref", "").strip()
        if ref:
            refs = " / ".join(r.strip() for r in ref.split(";") if r.strip())
            return f"{refs} ({self.osm_id.split('/')[-1]})"
        return f"{self.asset_class.replace('_', ' ')} {self.osm_id.split('/')[-1]}"


@dataclass(frozen=True)
class BBox:
    """Area of interest, south/west/north/east."""

    south: float
    west: float
    north: float
    east: float

    def as_overpass(self) -> str:
        return f"{self.south},{self.west},{self.north},{self.east}"

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


#: Coastal Andhra Pradesh around Montha's landfall: the Godavari-Krishna
#: delta, from Machilipatnam up past Kakinada. Covers Konaseema, West and East
#: Godavari, Krishna -- the districts Montha actually hit.
ANDHRA_COAST = BBox(south=15.7, west=80.6, north=17.4, east=82.6)

#: Coastal Odisha around Fani's landfall near Puri, reaching Bhubaneswar and
#: the Chilika lagoon. This is the stretch with the tightest wind-surge
#: coupling in the basin, and where Fani took roughly 156,000 distribution
#: poles in 2019.
ODISHA_COAST = BBox(south=18.4, west=84.4, north=20.5, east=86.6)

#: North Andhra around Hudhud's landfall at Visakhapatnam: a port city rather
#: than a delta, so the exposure mix is different again.
VIZAG_COAST = BBox(south=16.9, west=82.0, north=18.6, east=84.2)

#: Named areas of interest, so a run can be requested by name.
REGIONS = {
    "andhra": ANDHRA_COAST,
    "odisha": ODISHA_COAST,
    "vizag": VIZAG_COAST,
}


def _build_query(bbox: BBox, asset_classes: list[str], timeout: int = 180) -> str:
    parts: list[str] = []
    for cls in asset_classes:
        for selector in ASSET_QUERIES[cls]:
            parts.append(f"  {selector}({bbox.as_overpass()});")
    body = "\n".join(parts)
    return f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout center tags;"


def _fetch(query: str) -> dict[str, Any]:
    """POST to Overpass, falling back to the mirror if the primary is busy."""
    last: Exception | None = None
    for endpoint in ENDPOINTS:
        try:
            req = https_request(
                endpoint,
                data=query.encode(),
                headers={"User-Agent": "bob-forecaster/0.1 (hackathon research)"},
            )
            with https_open(req, timeout=240) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001 - try every mirror before giving up
            reraise_bugs(exc)          # a bug is not a failed source
            last = exc
            time.sleep(2)
    raise RuntimeError(f"all Overpass endpoints failed: {last}")


#: Classes fetched by default. Transmission towers are excluded: OSM has tens
#: of thousands in this AOI, the query times out, and individual towers matter
#: far less than the distribution network that actually fails.
DEFAULT_CLASSES = [
    "substation",
    "hospital",
    "shelter",
    "telecom_tower",
    "road_segment",
]


def load_assets(
    bbox: BBox = ANDHRA_COAST,
    asset_classes: list[str] | None = None,
    refresh: bool = False,
) -> list[Asset]:
    """Fetch infrastructure in the area of interest, caching per class.

    One class per request. A combined query over this AOI exceeds Overpass's
    timeout, and per-class caching means a slow class is fetched once rather
    than re-requested every time any other class changes.
    """
    asset_classes = asset_classes or DEFAULT_CLASSES
    assets: list[Asset] = []
    for cls in asset_classes:
        assets.extend(_load_one_class(bbox, cls, refresh))
    return assets


#: Overpass times out on a large box for a dense class -- roads across a
#: metropolitan area will 504 every time. Anything wider than this in either
#: direction is fetched as tiles and stitched.
MAX_QUERY_DEGREES = 1.1


def _split(bbox: BBox) -> list[BBox]:
    """Quarter a bounding box until each piece is small enough to query."""
    if (bbox.north - bbox.south) <= MAX_QUERY_DEGREES and (
        bbox.east - bbox.west
    ) <= MAX_QUERY_DEGREES:
        return [bbox]

    mid_lat = (bbox.south + bbox.north) / 2
    mid_lon = (bbox.west + bbox.east) / 2
    quads = [
        BBox(bbox.south, bbox.west, mid_lat, mid_lon),
        BBox(bbox.south, mid_lon, mid_lat, bbox.east),
        BBox(mid_lat, bbox.west, bbox.north, mid_lon),
        BBox(mid_lat, mid_lon, bbox.north, bbox.east),
    ]
    return [piece for q in quads for piece in _split(q)]


def _load_one_class(bbox: BBox, cls: str, refresh: bool) -> list[Asset]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"osm_{bbox.as_overpass().replace(',', '_')}_{cls}.json"

    if cache.exists() and not refresh:
        return [Asset(**a) for a in json.loads(cache.read_text())]

    tiles = _split(bbox)
    if len(tiles) > 1:
        # Stitch the tiles, de-duplicating: a way that straddles a tile edge
        # comes back from both sides.
        merged: dict[str, Asset] = {}
        for tile in tiles:
            for a in _load_one_class(tile, cls, refresh):
                merged[a.osm_id] = a
        assets = [a for a in merged.values() if bbox.contains(a.lat, a.lon)]
        cache.write_text(json.dumps([asdict(a) for a in assets], indent=1))
        return assets

    raw = _fetch(_build_query(bbox, [cls]))
    by_class = {sel.split('"')[1] + "=" + sel.split('"')[3]: c
                for c, sels in ASSET_QUERIES.items() for sel in sels}

    assets: list[Asset] = []
    elements = cast(list[dict[str, Any]], raw.get("elements", []))
    for el in elements:
        tags = cast(dict[str, str], el.get("tags", {}))
        # A node carries lat/lon; a way carries its centre. `or` would treat
        # a coordinate of exactly 0.0 as missing, so test for None instead.
        where = el if el.get("lat") is not None else cast(dict[str, Any], el.get("center") or {})
        lat, lon = where.get("lat"), where.get("lon")
        if lat is None or lon is None:
            continue

        resolved = _classify(tags, by_class)
        if resolved != cls:
            continue

        assets.append(
            Asset(
                osm_id=f"{el['type']}/{el['id']}",
                asset_class=cls,
                name=tags.get("name", "unnamed"),
                lat=float(lat),
                lon=float(lon),
                tags={k: v for k, v in tags.items() if k in
                      ("name", "power", "amenity", "highway", "ref", "voltage",
                       "operator", "emergency", "man_made", "beds")},
            )
        )

    cache.write_text(json.dumps([asdict(a) for a in assets], indent=1))
    return assets


def _classify(tags: dict[str, Any], lookup: dict[str, Any]) -> str | None:
    """Map an OSM element's tags onto one of our asset classes."""
    for key in ("power", "amenity", "emergency", "man_made", "highway"):
        if key in tags:
            hit = lookup.get(f"{key}={tags[key]}")
            if hit:
                return hit
    return None


def summarise(assets: list[Asset]) -> str:
    counts: dict[str, int] = {}
    named = 0
    for a in assets:
        counts[a.asset_class] = counts.get(a.asset_class, 0) + 1
        if a.name != "unnamed":
            named += 1
    lines = [f"{len(assets)} assets ({named} named)"]
    for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {cls:<22} {n:>6}")
    return "\n".join(lines)
