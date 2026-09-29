"""OpenStreetMap exposure: tiling, classification, caching -- with Overpass
replaced by a recorder, so the logic is tested without the service."""

import json
import urllib.request

import pytest

from exposure import osm
from exposure.osm import BBox


@pytest.fixture
def overpass(tmp_path, monkeypatch):
    """A fake Overpass: serves `responses` in order and records each query."""
    monkeypatch.setattr(osm, "CACHE_DIR", tmp_path)
    calls = []
    responses = []

    def fetch(query):
        calls.append(query)
        return responses.pop(0) if responses else {"elements": []}

    monkeypatch.setattr(osm, "_fetch", fetch)
    return calls, responses


def node(i, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def way(i, lat, lon, **tags):
    return {"type": "way", "id": i, "center": {"lat": lat, "lon": lon}, "tags": tags}


SMALL = BBox(16.0, 81.0, 16.5, 81.5)


def test_nodes_and_way_centres_become_assets(overpass):
    calls, responses = overpass
    responses.append({"elements": [
        node(1, 16.2, 81.2, power="substation", name="Narsapur SS", voltage="33000",
             source="survey"),
        way(2, 16.3, 81.3, power="substation"),
        {"type": "way", "id": 3, "tags": {"power": "substation"}},     # no position
        node(4, 16.1, 81.1, amenity="hospital", name="Not a substation"),
    ]})
    assets = osm._load_one_class(SMALL, "substation", refresh=False)
    assert [a.osm_id for a in assets] == ["node/1", "way/2"]
    assert assets[0].tags == {"name": "Narsapur SS", "power": "substation", "voltage": "33000"}
    assert assets[1].name == "unnamed"
    assert len(calls) == 1 and '"power"="substation"' in calls[0]


def test_a_coordinate_of_zero_is_a_position_not_a_gap(overpass):
    _, responses = overpass
    equator = BBox(-1.0, -1.0, 1.0, 1.0)
    responses.append({"elements": [node(9, 0.0, 0.5, amenity="hospital")]})
    assert [a.lat for a in osm._load_one_class(equator, "hospital", refresh=False)] == [0.0]


def test_a_cached_class_is_not_fetched_again(overpass):
    calls, responses = overpass
    responses.append({"elements": [node(1, 16.2, 81.2, amenity="hospital")]})
    first = osm._load_one_class(SMALL, "hospital", refresh=False)
    second = osm._load_one_class(SMALL, "hospital", refresh=False)
    assert first == second and len(calls) == 1
    osm._load_one_class(SMALL, "hospital", refresh=True)
    assert len(calls) == 2


def test_a_large_box_is_tiled_and_stitched_without_duplicates(overpass):
    calls, responses = overpass
    big = BBox(16.0, 81.0, 17.8, 82.8)            # wider than MAX_QUERY_DEGREES
    tiles = osm._split(big)
    assert len(tiles) > 1
    assert all(t.north - t.south <= osm.MAX_QUERY_DEGREES for t in tiles)
    # A road on a tile edge comes back from both tiles; one outside the box
    # (Overpass returns whole ways that merely touch it) must be dropped.
    edge = way(7, 16.9, 81.9, highway="trunk", ref="NH216")
    outside = way(8, 18.5, 81.5, highway="primary")
    for _ in tiles:
        responses.append({"elements": [edge, outside]})
    assets = osm._load_one_class(big, "road_segment", refresh=False)
    assert [a.osm_id for a in assets] == ["way/7"]
    assert len(calls) == len(tiles)
    cached = json.loads((osm.CACHE_DIR / f"osm_{big.as_overpass().replace(',', '_')}_road_segment.json").read_text())
    assert [a["osm_id"] for a in cached] == ["way/7"]


def test_split_covers_the_box_exactly():
    big = BBox(18.4, 84.4, 20.5, 86.6)
    tiles = osm._split(big)
    area = sum((t.north - t.south) * (t.east - t.west) for t in tiles)
    assert area == pytest.approx((big.north - big.south) * (big.east - big.west))
    assert osm._split(SMALL) == [SMALL]


def test_classification_uses_the_first_matching_tag():
    lookup = {"power=substation": "substation", "amenity=hospital": "hospital",
              "emergency=shelter": "shelter"}
    assert osm._classify({"amenity": "hospital", "emergency": "shelter"}, lookup) == "hospital"
    assert osm._classify({"emergency": "shelter"}, lookup) == "shelter"
    assert osm._classify({"shop": "bakery"}, lookup) is None


def test_every_endpoint_is_tried_before_giving_up(monkeypatch):
    tried = []

    def refuse(req, timeout, context):
        tried.append(req.full_url)
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="all Overpass endpoints failed"):
        osm._fetch("[out:json];")
    assert tried == list(osm.ENDPOINTS)
