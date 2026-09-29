"""Verification metrics and the honesty rules around missing observations."""

from typing import Any

import numpy as np
import pytest

from verify.metrics import (
    brier_score,
    brier_skill_score,
    contingency,
    reliability_bins,
)
from verify.observations import SOURCES, availability

# --- contingency scores --------------------------------------------------

def test_perfect_forecast():
    f = np.array([[1.0, 0.0], [1.0, 0.0]])
    c = contingency(f, f, threshold=0.5)
    assert c.probability_of_detection == 1.0
    assert c.false_alarm_ratio == 0.0
    assert c.critical_success_index == 1.0


def test_forecasting_everything_scores_a_perfect_hit_rate():
    """Why POD is never reported alone.

    A model that cries wolf everywhere detects every event and is useless;
    the false alarm ratio is what exposes it.
    """
    forecast = np.ones((4, 4))
    observed = np.zeros((4, 4)); observed[0, 0] = 1.0
    c = contingency(forecast, observed, threshold=0.5)
    assert c.probability_of_detection == 1.0        # looks perfect
    assert c.false_alarm_ratio > 0.9                # and is nearly all wrong
    assert c.critical_success_index < 0.1


def test_forecasting_nothing_scores_no_false_alarms():
    """The mirror failure."""
    forecast = np.zeros((4, 4))
    observed = np.ones((4, 4))
    c = contingency(forecast, observed, threshold=0.5)
    assert c.probability_of_detection == 0.0
    assert c.misses == 16


def test_mask_excludes_sea_from_the_score():
    """Scoring over sea inflates correct negatives and flatters everything."""
    forecast = np.zeros((2, 4)); observed = np.zeros((2, 4))
    mask = np.array([[True, True, False, False], [True, True, False, False]])
    c = contingency(forecast, observed, threshold=0.5, mask=mask)
    assert c.total == 4


def test_mismatched_shapes_are_rejected():
    with pytest.raises(ValueError, match="must match"):
        contingency(np.zeros((2, 2)), np.zeros((3, 3)), threshold=0.5)


def test_bias_detects_over_forecasting():
    forecast = np.ones((4, 4))
    observed = np.zeros((4, 4)); observed[:2] = 1.0
    assert contingency(forecast, observed, threshold=0.5).bias == 2.0


# --- probabilistic scores ------------------------------------------------

def test_brier_rewards_calibrated_hedging_over_confident_error():
    observed = np.array([1.0, 1.0, 0.0, 0.0])
    confident_wrong = np.array([0.0, 0.0, 1.0, 1.0])
    hedged = np.full(4, 0.5)
    assert brier_score(hedged, observed) < brier_score(confident_wrong, observed)


def test_brier_skill_is_positive_only_when_beating_climatology():
    observed = np.array([1.0, 1.0, 0.0, 0.0])
    assert brier_skill_score(np.array([1.0, 1.0, 0.0, 0.0]), observed) > 0
    # Always forecasting the base rate is the reference: no skill over itself.
    assert brier_skill_score(np.full(4, 0.5), observed) == pytest.approx(0.0, abs=1e-9)


def test_reliability_bins_cover_the_full_range():
    bins = reliability_bins(np.linspace(0, 1, 100), np.zeros(100), n_bins=10)
    assert len(bins) == 10
    assert sum(b["n"] for b in bins) == 100


# --- the honesty rules ---------------------------------------------------

def test_unreachable_observations_give_a_reason_not_a_number():
    """The rule the observation module exists to enforce.

    A fabricated verification is worse than none, because it manufactures the
    confidence the design is meant to withhold. With Earth Engine off, the
    run's observed-verification block is a reason and nothing else.
    """
    import pipeline

    # With Earth Engine off, _observe returns before touching its inputs.
    unused: Any = None
    observed, rain_index = pipeline._observe(*([unused] * 10))
    assert observed["available"] is False
    assert "EARTHENGINE_OFF" in observed["reason"]
    assert set(observed) == {"available", "reason"}
    assert rain_index is None


def test_availability_states_why_each_source_is_unusable():
    a = availability()
    assert a["any_available"] is False
    for s in a["sources"]:
        assert s["available"] is False
        assert s["reason"], f"{s['name']} is unavailable with no reason given"
        assert s["dataset"], "a source must name the real dataset it needs"


def test_every_source_names_a_real_dataset_id():
    """Guards against a placeholder source that cannot actually be wired up."""
    for s in SOURCES.values():
        assert "/" in s.dataset

# The end-to-end check that ensemble self-verification carries its caveat now
# runs offline, in test_pipeline_offline.py.
