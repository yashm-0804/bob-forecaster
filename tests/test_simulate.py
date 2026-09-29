"""The simulated sensor network, run end to end through the real ingest path.

Offline: IMD's best track ships with imdtrack, and the terrain is the flat
placeholder. Thresholds are floors under what this run actually produces, so
a regression in QC or in the simulator shows up as a failure here.
"""

from datetime import timedelta

import pytest

from exposure.osm import ANDHRA_COAST
from hazard.surge_screen import FlatDeltaPlain
from ingest.tracks import load_storm
from telemetry import simulate
from telemetry.ingest import TelemetryStore, parse

CLUSTER = (16.5, 81.7)


@pytest.fixture(scope="module")
def storm():
    return load_storm("MONTHA", 2025)


@pytest.fixture(scope="module")
def report(storm, tmp_path_factory):
    store = TelemetryStore(tmp_path_factory.mktemp("net") / "t.sqlite3")
    return simulate.run(storm, FlatDeltaPlain(), ANDHRA_COAST, store, cluster=CLUSTER)


def test_every_tier_the_siting_rules_allow_is_placed(report):
    assert report["nodes"]["A"] > 20, "Tier A is the backbone"
    assert report["nodes"]["B"] > 5, "the rain cluster was requested"
    assert {"D", "E"} <= set(report["nodes"])


def test_every_fault_type_is_injected(report):
    assert all(n > 0 for n in report["faults_injected"].values()), report["faults_injected"]


def test_qc_catches_the_faults_that_are_detectable(report):
    injected, caught = report["faults_injected"], report["faults_caught"]
    for fault in ("seized", "misconfig", "spike"):
        assert caught[fault] / injected[fault] >= 0.9, (fault, caught, injected)
    # Drift is caught once the offset clears about 1.4 hPa; earlier readings
    # are too close to the truth to call. Roughly half is the honest ceiling.
    assert caught["drift"] / injected["drift"] >= 0.4


def test_clean_readings_are_almost_never_flagged(report):
    assert report["clean_readings"] > 5000
    assert report["false_flag_rate"] < 0.01


def test_every_simulated_message_is_a_valid_observation(storm):
    """The simulator speaks the same wire format the API validates."""
    nodes = simulate.place_nodes(FlatDeltaPlain(), ANDHRA_COAST, CLUSTER)
    landfall = storm.times[storm.landfall_index]
    count = 0
    for msg, _ in simulate.simulate(storm, nodes, landfall - timedelta(hours=31),
                                    landfall + timedelta(hours=1)):
        parse(msg)
        count += 1
    assert count > 1000


def test_the_same_seed_gives_the_same_network(storm):
    nodes = simulate.place_nodes(FlatDeltaPlain(), ANDHRA_COAST, CLUSTER)
    landfall = storm.times[storm.landfall_index]
    window = (landfall - timedelta(hours=2), landfall)
    first = list(simulate.simulate(storm, nodes, *window))
    second = list(simulate.simulate(storm, nodes, *window))
    assert first == second
