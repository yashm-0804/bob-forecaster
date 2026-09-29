"""Starting Earth Engine, and the plain-words reason when it cannot start.

A stand-in `ee` module replaces the real one, so every failure the console
has to explain can be produced on demand.
"""

import sys
import types

import pytest

from ingest import earthengine


@pytest.fixture
def fake_ee(monkeypatch):
    """Install a stand-in `ee`; the test sets what Initialize does."""
    module = types.SimpleNamespace(initialized_with=None, fail=None)

    def initialize(project=None):
        module.initialized_with = project
        if module.fail:
            raise module.fail

    class Number:
        def __init__(self, v):
            self.v = v

        def getInfo(self):
            return self.v

    module.Initialize = initialize
    module.Number = Number
    monkeypatch.setitem(sys.modules, "ee", module)
    monkeypatch.delenv("EARTHENGINE_OFF")
    monkeypatch.setenv("EE_PROJECT", "test-project")
    monkeypatch.setitem(earthengine._state, "ready", False)
    return module


def test_a_working_sign_in_names_the_project(fake_ee, monkeypatch):
    monkeypatch.setenv("EE_PROJECT", "my-project")
    ok, why = earthengine.availability()
    assert ok is True
    assert fake_ee.initialized_with == "my-project"
    assert why == "signed in to Earth Engine"
    assert "my-project" not in why, "the project id is not published"


@pytest.mark.parametrize("error, expected", [
    (Exception("Please authorize access to your Earth Engine account by running "
               "earthengine authenticate"), "not signed in"),
    (Exception("Project 'x' is not registered to use Earth Engine."), "not registered"),
    (Exception("Caller does not have required permission"), "not registered or not permitted"),
    (Exception("socket timed out"), "Earth Engine unavailable: socket timed out"),
])
def test_each_failure_becomes_a_reason_an_operator_can_act_on(fake_ee, error, expected):
    fake_ee.fail = error
    ok, why = earthengine.availability()
    assert ok is False
    assert expected in why


def test_switched_off_never_touches_the_library(fake_ee, monkeypatch):
    monkeypatch.setenv("EARTHENGINE_OFF", "1")
    ok, why = earthengine.availability()
    assert ok is False and "EARTHENGINE_OFF" in why
    assert fake_ee.initialized_with is None


def test_without_a_project_nothing_is_billed_to_a_default(fake_ee, monkeypatch):
    monkeypatch.delenv("EE_PROJECT")
    ok, why = earthengine.availability()
    assert ok is False and "EE_PROJECT" in why
    assert fake_ee.initialized_with is None


def test_a_missing_library_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv("EARTHENGINE_OFF")
    monkeypatch.setenv("EE_PROJECT", "test-project")
    monkeypatch.setitem(earthengine._state, "ready", False)
    monkeypatch.setitem(sys.modules, "ee", None)       # makes `import ee` fail
    ok, why = earthengine.availability()
    assert ok is False and why == "earthengine-api is not installed"


def test_success_is_remembered(fake_ee):
    assert earthengine.initialise() is True
    fake_ee.fail = Exception("would fail now")
    assert earthengine.initialise() is True
