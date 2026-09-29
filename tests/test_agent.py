"""The bulletin agent's cycle diff, and asset labelling."""

import json

import pytest

from agent.watch import ReplaySource, diff_cycles
from exposure.osm import Asset


def payload(lead, advisories, red_ids, people=1000):
    return {
        "summary": {"hours_to_landfall": lead, "people_without_power_est": people},
        "advisories": [{"recipient_key": k, "recipient": k.title(), "severity": s}
                       for k, s in advisories],
        "assets": [{"osm_id": i, "name": f"asset {i}", "severity": "red"} for i in red_ids],
    }


def test_first_cycle_says_so():
    assert diff_cycles(None, payload(72, [], []))["first_cycle"] is True


def test_escalation_and_newly_red_are_reported():
    before = payload(72, [("discom", "orange")], ["a"])
    after = payload(48, [("discom", "red"), ("health", "orange")], ["a", "b", "c"])
    d = diff_cycles(before, after)
    assert d["advisories_escalated"] == ["Discom"]
    assert d["advisories_new"] == ["Health"]
    assert d["assets_newly_red"] == ["asset b", "asset c"]
    assert d["red_count"] == {"before": 1, "now": 3}
    assert "2 assets newly red" in d["summary"]


def test_easing_and_withdrawal_are_reported_too():
    """An officer needs to know what they can stand down, not only what got worse."""
    before = payload(24, [("discom", "red"), ("pwd", "orange")], ["a", "b"])
    after = payload(12, [("discom", "orange")], ["a"])
    d = diff_cycles(before, after)
    assert d["advisories_eased"] == ["Discom"]
    assert d["advisories_withdrawn"] == ["Pwd"]
    assert d["assets_no_longer_red"] == ["asset b"]


def test_quiet_cycle_says_nothing_changed():
    p = payload(24, [("discom", "red")], ["a"])
    assert diff_cycles(p, payload(12, [("discom", "red")], ["a"]))["summary"] == "no material change."


def test_replay_runs_far_out_first():
    leads = [c.lead_hours for c in ReplaySource("MONTHA", 2025, leads=(12, 72, 24)).cycles()]
    assert leads == [72, 24, 12]


def test_unnamed_road_is_labelled_by_its_reference():
    road = Asset("way/42", "road_segment", "unnamed", 16.0, 81.0, {"ref": "NH16;NH516A"})
    assert road.label == "NH16 / NH516A (42)"


def test_named_asset_keeps_its_name():
    assert Asset("node/1", "hospital", "Govt Hospital", 16.0, 81.0, {"ref": "X"}).label == "Govt Hospital"


def test_a_degraded_cycle_is_refused_and_the_baseline_kept(monkeypatch):
    """Regression: a timed-out tile request dropped a Fani cycle onto flat
    placeholder terrain, and the diff reported 159 assets standing down."""
    import agent.watch as w

    good = payload(72, [("discom", "red")], ["a", "b"])
    calls = []

    def fake_run(cycle, previous):
        calls.append(previous)
        if cycle.lead_hours == 48:
            raise w.DegradedCycle("no real terrain")
        return (dict(good, changes=w.diff_cycles(previous, good)), type("P", (), {"name": "x"})())

    monkeypatch.setattr(w, "run_cycle", fake_run)
    logged = []
    monkeypatch.setattr(w, "log_event", logged.append)   # exercise event building, not I/O
    events = w.watch(ReplaySource("FANI", 2019, leads=(72, 48, 24)))
    assert "failed" in events[1] and "failed" in logged[1]
    assert logged[1]["at"], "the failure path must build its timestamp without error"
    assert calls[2] is not None and calls[2]["summary"]["hours_to_landfall"] == 72, \
        "the cycle after a failure diffs against the last good one"


def test_a_cycle_that_crashes_costs_that_cycle_not_the_storm(monkeypatch):
    """Found in review: any failure other than DegradedCycle -- a data source
    down, a bug -- ended the replay and the later cycles never ran."""
    import agent.watch as w

    good = payload(72, [("discom", "red")], ["a", "b"])
    calls = []

    def fake_run(cycle, previous):
        calls.append(cycle.lead_hours)
        if cycle.lead_hours == 48:
            raise ConnectionError("Overpass timed out")
        return (dict(good, changes=w.diff_cycles(previous, good)), type("P", (), {"name": "x"})())

    monkeypatch.setattr(w, "run_cycle", fake_run)
    monkeypatch.setattr(w, "log_event", lambda event: None)
    events = w.watch(ReplaySource("FANI", 2019, leads=(72, 48, 24, 12)))
    assert calls == [72, 48, 24, 12]
    assert events[1]["failed"] == "ConnectionError: Overpass timed out"
    assert all("failed" not in e for e in (events[0], events[2], events[3]))


def test_a_replay_with_a_failed_cycle_exits_non_zero(monkeypatch):
    import sys

    import agent.watch as w

    monkeypatch.setattr(w, "watch", lambda source: [{"file": "a"}, {"failed": "x"}])
    monkeypatch.setattr(sys, "argv", ["watch", "--replay", "FANI", "2019"])
    monkeypatch.setattr("ingest.net.use_certifi_globally", lambda: None)
    with pytest.raises(SystemExit, match="1 of 2 cycles failed"):
        w.main()


def test_an_unknown_region_is_refused_before_any_cycle_runs(monkeypatch, capsys):
    """Found in review: --region with a typo failed every cycle with a KeyError."""
    import sys

    import agent.watch as w

    ran = []
    monkeypatch.setattr(w, "watch", lambda source: ran.append(source) or [])
    monkeypatch.setattr(sys, "argv", ["watch", "--replay", "FANI", "2019", "--region", "odsha"])
    with pytest.raises(SystemExit) as exc:
        w.main()
    assert exc.value.code == 2 and ran == []
    assert "invalid choice: 'odsha'" in capsys.readouterr().err


def test_a_run_file_is_replaced_whole_or_not_at_all(monkeypatch, tmp_path):
    """The console serves data/runs while cycles run; it must never read half
    a file. A failed write leaves the previous cycle's file as it was."""
    import pipeline
    from exposure.osm import REGIONS

    _offline(monkeypatch, terrain="aws-copernicus")
    result = pipeline.run("MONTHA", 2025, lead_hours=48.0, bbox=REGIONS["andhra"])
    path = pipeline.export(result, tmp_path)
    before = path.read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["montha_48h.json"], "no staging file left"

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pipeline.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        pipeline.export(result, tmp_path, extra={"changes": {"summary": "new"}})
    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["montha_48h.json"]


def test_ocean_tiles_are_cached(tmp_path, monkeypatch):
    """A 404 is permanent; asking again every run made terrain fragile."""
    import hazard.terrain as t

    monkeypatch.setattr(t, "CACHE_DIR", tmp_path)
    asked = []
    monkeypatch.setattr(t, "_tile_is_ocean", lambda url: asked.append(url) or True)
    assert t._read_tile(18, 86) is None
    assert t._read_tile(18, 86) is None
    assert len(asked) == 1


def _offline(monkeypatch, terrain="flat"):
    """pipeline.run on local inputs only, with the terrain source chosen."""
    import pipeline
    from tests.test_pipeline_offline import ASSETS

    real_run = pipeline.run
    monkeypatch.setattr(pipeline, "load_assets", lambda bbox: list(ASSETS))

    def run(storm, year, lead_hours, bbox):
        result = real_run(storm, year, lead_hours=lead_hours, bbox=bbox, n_members=6,
                          terrain_prefer="flat", ensemble_source="perturbed",
                          rain_source="r-cliper")
        result.summary["terrain_source"] = terrain
        return result

    monkeypatch.setattr(pipeline, "run", run)


def test_a_cycle_on_placeholder_terrain_is_never_published(monkeypatch, tmp_path):
    """run_cycle's own guard, not a stand-in for it."""
    import agent.watch as w

    _offline(monkeypatch, terrain="flat-placeholder")
    with pytest.raises(w.DegradedCycle, match="no real terrain"):
        w.run_cycle(w.Cycle("MONTHA", 2025, 48, "andhra"), None, out_dir=tmp_path)
    assert list(tmp_path.iterdir()) == [], "nothing was written"


def test_a_published_cycle_carries_its_diff(monkeypatch, tmp_path):
    import agent.watch as w

    _offline(monkeypatch, terrain="aws-copernicus")
    first, path = w.run_cycle(w.Cycle("MONTHA", 2025, 72, "andhra"), None, out_dir=tmp_path)
    assert path.parent == tmp_path
    assert first["changes"]["summary"] == "First forecast cycle for this storm."
    second, _ = w.run_cycle(w.Cycle("MONTHA", 2025, 48, "andhra"), first, out_dir=tmp_path)
    assert "summary" in second["changes"]
    assert json.loads((tmp_path / "montha_48h.json").read_text())["changes"] == second["changes"]


def test_live_watching_says_what_it_needs_instead_of_pretending(monkeypatch):
    import agent.watch as w
    from advisory import gemini

    with pytest.raises(RuntimeError, match="needs Gemini"):
        next(w.LiveSource().cycles())
    monkeypatch.setattr(gemini, "availability", lambda: (True, "ok"))
    with pytest.raises(NotImplementedError, match="use --replay"):
        next(w.LiveSource().cycles())


def test_changes_count_every_red_asset_not_just_the_shipped_table():
    """The table ships 400 assets; a strong storm has more red than that."""
    before = payload(48, [], [])
    after = payload(24, [], [])
    before["red_assets"] = [[f"way/{i}", f"road {i}"] for i in range(500)]
    after["red_assets"] = [[f"way/{i}", f"road {i}"] for i in range(100, 700)]
    diff = diff_cycles(before, after)
    assert diff["red_count"] == {"before": 500, "now": 600}
    assert diff["summary"].startswith("200 assets newly red; 100 no longer red")
