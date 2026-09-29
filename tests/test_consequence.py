"""Criticality weighting and sub-grid depth refinement.

Both were added to fix a ranking that sorted correctly but discriminated
almost not at all. These pin the behaviour and, in the depth case, a real bug
the change introduced and then had to fix.
"""

import numpy as np
import pytest

from exposure.osm import Asset
from impact.consequence import criticality, expected_consequence
from impact.rollup import MAX_LOCAL_DEEPENING, HazardGrids


def asset(cls, name="unnamed", **tags):
    return Asset(osm_id="node/1", asset_class=cls, name=name,
                 lat=16.4, lon=81.7, tags={"name": name, **tags})


# --- criticality ---------------------------------------------------------

@pytest.mark.parametrize("voltage,expected_min", [
    ("400000", 5.0), ("220000;132000", 3.5), ("132000", 2.0), ("33000", 0.9),
])
def test_substation_weight_follows_voltage(voltage, expected_min):
    """Transmission voltage is the one hard criticality signal OSM carries."""
    c = criticality(asset("substation", "X", voltage=voltage))
    assert c.score >= expected_min
    assert c.confidence == "measured"


def test_multi_voltage_tag_uses_the_highest():
    """A substation stepping 220 to 132 kV sits at the 220 kV level."""
    assert criticality(asset("substation", "X", voltage="220000;132000")).score == \
           criticality(asset("substation", "Y", voltage="220000")).score


def test_unmapped_voltage_falls_back_and_says_so():
    c = criticality(asset("substation", "X"))
    assert c.confidence == "class-default"
    assert "not mapped" in c.basis


def test_emergency_hospital_outweighs_a_nursing_home():
    big = criticality(asset("hospital", "Govt General Hospital", emergency="yes"))
    small = criticality(asset("hospital", "Renuka Nursing Home"))
    assert big.score > small.score * 4
    assert big.confidence == "measured"
    assert small.confidence == "inferred"


def test_name_inference_is_labelled_as_inference():
    """A guess from a name must never present as measurement."""
    c = criticality(asset("hospital", "Government General Hospital"))
    assert c.confidence == "inferred"


def test_trunk_road_outweighs_primary():
    assert criticality(asset("road_segment", "A", highway="trunk")).score > \
           criticality(asset("road_segment", "B", highway="primary")).score


def test_every_weight_states_its_basis():
    for cls in ("substation", "hospital", "road_segment", "shelter", "telecom_tower"):
        c = criticality(asset(cls))
        assert c.basis and c.confidence


def test_consequence_orders_by_what_is_lost_not_just_likelihood():
    """A 30% chance of losing a 400 kV substation beats a 70% chance of a clinic."""
    substation = expected_consequence(0.30, 6.0)
    clinic = expected_consequence(0.70, 0.6)
    assert substation > clinic


# --- sub-grid depth refinement ------------------------------------------

@pytest.fixture
def grids():
    lats, lons = np.meshgrid(np.array([16.0, 16.1]), np.array([81.0, 81.1]), indexing="ij")
    z = np.zeros_like(lats)
    return HazardGrids(lats, lons, [z], [z], z)


def test_raised_ground_drains(grids):
    """An asset above its cell's mean sees less water, without limit."""
    assert grids.refined_depth_m(1.5, rise=0.5) == pytest.approx(1.0)
    assert grids.refined_depth_m(1.5, rise=10.0) == 0.0


def test_a_hollow_cannot_flood_without_limit(grids):
    """The bug this guards against actually shipped.

    An unbounded correction poured 154 m of water into valley floors whose
    2.2 km cell averaged over the Eastern Ghats, driving substation failure
    probabilities to 1.00 in a 93 km/h storm.
    """
    assert grids.refined_depth_m(1.0, rise=-154.0) == pytest.approx(
        1.0 + MAX_LOCAL_DEEPENING
    )


def test_a_dry_cell_stays_dry(grids):
    """Sub-grid terrain redistributes flooding within a cell. It cannot create it."""
    assert grids.refined_depth_m(0.0, rise=-50.0) == 0.0


def test_no_terrain_means_no_correction(grids):
    """The flat placeholder and the test fixtures must behave as before."""
    assert grids.elevation_offset_m(16.0, 81.0) == 0.0


# --- population estimate must not inflate --------------------------------

def test_criticality_redistributes_population_without_inflating_it():
    """Regression: the estimate jumped 59,000 -> 1,247,000 on the same storm.

    Criticality is a relative weight where 1.0 is typical, so scaling an
    already-arbitrary per-substation headcount by it inflated the total by 21x
    with no new evidence behind it.
    """
    from impact.consequence import Criticality
    from impact.rollup import AssetRisk, population_affected

    def sub(p, weight):
        return AssetRisk(
            asset=asset("substation"), p_failure_mean=p, p_failure_p10=p,
            p_failure_p90=p, wind_ms_median=0, depth_m_median=0, rain_mm=0,
            dominant_driver="flood",
            criticality=Criticality(weight, "test", "measured"),
        )

    flat = [sub(0.5, 1.0) for _ in range(10)]
    varied = [sub(0.5, w) for w in (6, 4, 4, 2.5, 2.5, 1.5, 1, 1, 1, 1)]

    # Same storm, same probabilities: total magnitude must be comparable.
    assert population_affected(varied) == pytest.approx(
        population_affected(flat), rel=0.05
    )


def test_population_still_favours_the_larger_substation():
    """Redistribution must still do its job."""
    from impact.consequence import Criticality
    from impact.rollup import AssetRisk, population_affected

    def sub(p, weight):
        return AssetRisk(
            asset=asset("substation"), p_failure_mean=p, p_failure_p10=p,
            p_failure_p90=p, wind_ms_median=0, depth_m_median=0, rain_mm=0,
            dominant_driver="flood",
            criticality=Criticality(weight, "test", "measured"),
        )

    big_at_risk = population_affected([sub(0.9, 6.0), sub(0.1, 1.0)])
    small_at_risk = population_affected([sub(0.1, 6.0), sub(0.9, 1.0)])
    assert big_at_risk > small_at_risk


def test_no_substations_means_no_estimate():
    from impact.rollup import population_affected
    assert population_affected([]) == 0


def test_a_shop_tagged_emergency_does_not_rank_as_a_referral_hospital():
    """Regression: "Koteswara rao medical shop" ranked third overall.

    OSM applies emergency=yes loosely. An artifact at the top of the list
    costs far more credibility than one buried in it, so the name vetoes the
    tag when the two disagree.
    """
    shop = criticality(asset("hospital", "Koteswara rao medical shop", emergency="yes"))
    real = criticality(asset("hospital", "Government General Hospital", emergency="yes"))
    assert shop.score < 1.0
    assert real.score >= 3.0
    assert "but the name indicates" in shop.basis
    assert shop.confidence == "inferred", "a vetoed tag is no longer a measurement"


def test_dental_hospital_tagged_emergency_is_also_vetoed():
    c = criticality(asset("hospital", "Krupa Multi Speciality Dental Hospital", emergency="yes"))
    assert c.score < 1.0
