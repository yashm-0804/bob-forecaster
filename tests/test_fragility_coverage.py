"""Every asset the exposure layer loads is scored by the curves meant for it.

Found in review: the road wind curve was keyed "road_tree_blockage" while
roads are "road_segment", so the lookup returned nothing and every road
scored zero from wind -- 127 km/h at Fani included.
"""

import pytest

from exposure.osm import DEFAULT_CLASSES
from impact.fragility import (
    CALIBRATION_ONLY,
    FLOOD_CURVES,
    WIND_CURVES,
    WIND_ONLY,
    combined_failure,
)


@pytest.mark.parametrize("cls", DEFAULT_CLASSES)
def test_every_loaded_class_has_its_curves(cls):
    assert cls in WIND_CURVES, f"{cls} has no wind curve"
    if cls not in WIND_ONLY:
        assert cls in FLOOD_CURVES, f"{cls} has no flood curve and is not declared wind-only"


def test_every_curve_scores_something_that_exists():
    loaded = set(DEFAULT_CLASSES)
    for name in set(WIND_CURVES) | set(FLOOD_CURVES):
        assert name in loaded or name in CALIBRATION_ONLY, f"curve {name!r} matches no asset class"


def test_a_road_in_a_severe_storm_can_be_blocked_by_wind():
    """127 km/h (35.3 m/s) is past the tree-blockage curve's midpoint."""
    assert combined_failure("road_segment", 35.3) > 0.5
    assert combined_failure("road_segment", 10.0) == 0.0
