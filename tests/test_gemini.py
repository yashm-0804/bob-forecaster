"""The Gemini drafting layer, and above all its number guardrail.

No network: every test injects a fake `generate`. What is being tested is not
Gemini but the rule around it -- that the model may reword and translate, and
may not originate a number.
"""

import json
from datetime import UTC, datetime

import pytest

from advisory import gemini
from advisory.cap import RECIPIENTS, REGION_PROFILES, Advisory, recipient_for


def advisory(languages=("en-IN", "te-IN")):
    return Advisory(
        identifier="T5-TEST-HEALTH-1",
        recipient=RECIPIENTS["health"],
        headline="3 assets at risk from Montha: 1 high-probability, 48 h to landfall",
        instruction="Confirm generator fuel days for: Govt Hospital Peruru.",
        severity="red",
        assets=[{"name": "Govt Hospital Peruru", "asset_class": "hospital",
                 "p_failure": 0.54, "wind_kmh": 77.0, "depth_m": 0.28,
                 "rain_mm": 150.0, "consequence": 1.35, "driver": "flood"}],
        sent=datetime(2025, 10, 26, 9),
        area_desc="coastal Andhra",
        ensemble_note="Across a 50-member track ensemble, failure probability "
                      "spans 31%-70% (10th-90th percentile).",
        requested_languages=languages,
    )


def fake(payload):
    return lambda prompt: json.dumps(payload, ensure_ascii=False)


GOOD_TE = {"language": "te-IN", "headline": "మోంథా: 48 గంటలు",
           "instruction": "జనరేటర్ ఇంధనం నిర్ధారించండి: పేరూరు ఆసుపత్రి",
           "description": "50 సభ్యుల సమిష్టి, 31%-70%"}


def test_clean_response_is_accepted_and_attributed():
    out = gemini.enhance(advisory(), fake({
        "headline": "Montha, 48 h out: Govt Hospital Peruru at 54% risk of flooding",
        "instruction": "Move ground-floor critical care at Govt Hospital Peruru today.",
        "translations": [GOOD_TE],
    }))
    assert out.drafted_by == gemini.MODEL
    assert "te-IN" in out.languages
    assert out.pending_languages == []
    assert out.headline.startswith("Montha, 48 h out")


def test_an_invented_number_rejects_that_field_and_keeps_the_template():
    """The core rule. 60% is not a computed fact for this advisory."""
    original = advisory()
    out = gemini.enhance(original, fake({
        "headline": "Govt Hospital Peruru faces a 60% chance of losing power",
        "instruction": "Move ground-floor critical care today.",
        "translations": [],
    }))
    assert out.headline == original.headline
    assert out.instruction == "Move ground-floor critical care today."
    assert any("60" in n and "headline" in n for n in out.draft_notes)


def test_a_number_hidden_in_native_script_is_still_caught():
    """౯౯ is 99 in Telugu digits -- writing it differently must not hide it."""
    bad = dict(GOOD_TE, instruction="పేరూరు ఆసుపత్రి ౯౯% ప్రమాదంలో ఉంది")
    out = gemini.enhance(advisory(), fake({"translations": [bad]}))
    assert "te-IN" not in out.languages
    assert "te-IN" in out.pending_languages
    assert any("99" in n for n in out.draft_notes)


def test_an_incomplete_translation_is_not_emitted():
    out = gemini.enhance(advisory(), fake({
        "translations": [{"language": "te-IN", "headline": "only a headline"}]}))
    assert "te-IN" not in out.languages


def test_a_language_the_region_did_not_ask_for_is_ignored():
    stray = dict(GOOD_TE, language="ta-IN")
    out = gemini.enhance(advisory(), fake({"translations": [stray]}))
    assert "ta-IN" not in out.languages


def test_garbage_from_the_model_keeps_the_template():
    original = advisory()
    out = gemini.enhance(original, lambda p: "not json at all")
    assert out.headline == original.headline
    assert out.drafted_by == "template"
    assert any("failed" in n for n in out.draft_notes)


def test_without_a_key_nothing_is_claimed(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    out = gemini.enhance(advisory())
    assert out.drafted_by == "template"
    assert out.languages == ["en-IN"]
    assert out.pending_languages == ["te-IN"]
    assert any("API key" in n for n in out.draft_notes)


def test_decimal_spellings_are_the_same_fact():
    assert gemini.numbers_in("0.30 and .3 and 0.3") == {"0.3"}


# --- the language bug this replaced --------------------------------------

def test_no_language_block_without_its_text():
    """Regression: te-IN blocks used to carry the English text."""
    xml = advisory().to_cap_xml()
    assert "<language>te-IN</language>" not in xml
    assert "<language>en-IN</language>" in xml


def test_odisha_asks_for_odia_and_its_own_utilities():
    """Regression: the Fani run was labelled Telugu and addressed to Andhra discoms."""
    odisha = REGION_PROFILES["odisha"]
    assert "or-IN" in odisha.languages and "te-IN" not in odisha.languages
    assert "TPCODL" in recipient_for("discom", odisha).name
    assert "APEPDCL" not in recipient_for("discom", odisha).name


def test_cap_sent_time_is_correct_on_a_utc_server():
    """Regression: "+05:30" was appended to whatever the local clock said."""

    from advisory.cap import _cap_time
    assert _cap_time(datetime(2025, 10, 26, 3, 30, tzinfo=UTC)) == "2025-10-26T09:00:00+05:30"


def test_env_file_fills_gaps_but_never_overrides_the_shell(tmp_path, monkeypatch):
    import os

    import envfile

    env = tmp_path / ".env"
    env.write_text("# local secrets\nGEMINI_API_KEY='from-file'\nOTHER_TEST_VAR=x\n")
    monkeypatch.setenv("OTHER_TEST_VAR", "from-shell")
    # setenv first, so teardown restores the key's absence after load() sets it.
    monkeypatch.setenv("GEMINI_API_KEY", "placeholder")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert envfile.load(env) == ["GEMINI_API_KEY"]
    assert os.environ["GEMINI_API_KEY"] == "from-file"
    assert os.environ["OTHER_TEST_VAR"] == "from-shell"


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


def test_overload_is_retried_then_succeeds():
    from advisory.gemini import _with_retries

    attempts, waits = [], []

    def call():
        attempts.append(1)
        if len(attempts) < 3:
            raise _Err(503)
        return "ok"

    assert _with_retries(call, waits=(1, 2, 3), sleep=waits.append) == "ok"
    assert waits == [1, 2]


def test_a_bad_request_is_not_retried():
    import pytest

    from advisory.gemini import _with_retries

    waits = []

    def call():
        raise _Err(400)

    with pytest.raises(_Err):
        _with_retries(call, waits=(1, 2), sleep=waits.append)
    assert waits == []


def test_persistent_overload_gives_up_and_keeps_the_template():
    from advisory.gemini import _with_retries

    waits = []

    def call():
        raise _Err(503)

    import pytest
    with pytest.raises(_Err):
        _with_retries(call, waits=(1, 2), sleep=waits.append)
    assert waits == [1, 2]


# --- one request per cycle ---------------------------------------------------

def _second():
    from dataclasses import replace
    return replace(advisory(), identifier="T5-TEST-DISCOM-1", recipient=RECIPIENTS["discom"],
                   headline="2 assets at risk from Montha, 48 h to landfall",
                   instruction="Pre-position crews near: Kakinada Sub station.",
                   assets=[{"name": "Kakinada Sub station", "asset_class": "substation",
                            "p_failure": 0.4, "wind_kmh": 80.0, "depth_m": 0.1,
                            "rain_mm": 120.0, "consequence": 2.0, "driver": "flood"}])


def test_a_cycle_is_drafted_in_one_request():
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return json.dumps({"advisories": [
            {"id": "0", "headline": "Montha, 48 h out: Govt Hospital Peruru at risk",
             "translations": [GOOD_TE]},
            {"id": "1", "headline": "Montha, 48 h out: crews to Kakinada Sub station",
             "translations": [GOOD_TE]},
        ]}, ensure_ascii=False)

    out = gemini.enhance_all([advisory(), _second()], generate)
    assert len(prompts) == 1
    assert [a.drafted_by for a in out] == [gemini.MODEL, gemini.MODEL]
    assert "Kakinada" in out[1].headline


def test_a_number_borrowed_from_another_department_is_rejected():
    """54% is a fact for the hospital, not for the substation."""
    out = gemini.enhance_all([advisory(), _second()], fake({"advisories": [
        {"id": "1", "headline": "Kakinada Sub station at 54% risk", "translations": []},
    ]}))
    assert out[1].headline == _second().headline
    assert any("54" in n for n in out[1].draft_notes)


def test_an_advisory_missing_from_the_reply_keeps_its_template():
    out = gemini.enhance_all([advisory(), _second()], fake({"advisories": [
        {"id": "0", "headline": "Montha, 48 h out: Govt Hospital Peruru at risk"},
    ]}))
    assert out[0].drafted_by == gemini.MODEL
    assert out[1].drafted_by == _second().drafted_by
    assert any("returned nothing" in n for n in out[1].draft_notes)


def test_a_daily_quota_is_named_and_not_retried():
    from advisory.gemini import _with_retries

    class Quota(Exception):
        code = 429

    def generate(prompt):
        raise Quota("429 RESOURCE_EXHAUSTED quotaId GenerateRequestsPerDayPerProjectPerModel")

    out = gemini.enhance_all([advisory(), _second()], generate)
    assert all("daily request quota" in a.draft_notes[-1] for a in out)
    waits = []
    import pytest
    with pytest.raises(Quota):
        _with_retries(lambda: generate(""), waits=(1, 2), sleep=waits.append)
    assert waits == []


def test_a_replayed_prompt_is_answered_from_disk(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gemini, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(gemini, "_gemini_generate",
                        lambda prompt: calls.append(prompt) or '{"advisories": []}')
    for _ in range(2):
        assert gemini._cached_generate("same facts") == '{"advisories": []}'
    assert len(calls) == 1
    gemini._cached_generate("different facts")
    assert len(calls) == 2


@pytest.mark.parametrize("reply", ['{"advisories": [', "not json", "[1, 2]", ""])
def test_a_malformed_reply_is_not_cached(tmp_path, monkeypatch, reply):
    """Found in review: a truncated reply was written to the cache and then
    replayed, as the answer, on every later run of the same facts."""
    calls = []
    monkeypatch.setattr(gemini, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(gemini, "_gemini_generate", lambda prompt: calls.append(prompt) or reply)
    assert gemini._cached_generate("facts") == reply
    assert gemini._cached_generate("facts") == reply
    assert len(calls) == 2, "asked again, not answered from the cache"
    assert list(tmp_path.iterdir()) == []


# --- numbers that are not digits, and digits in the wrong unit ----------------

def test_a_number_written_in_words_is_rejected():
    """Found in review: "sixty percent ... two days" passed a digits-only check."""
    original = advisory()
    out = gemini.enhance(original, fake({
        "headline": "Govt Hospital Peruru faces a sixty percent chance of losing power in two days",
    }))
    assert out.headline == original.headline
    assert out.drafted_by != gemini.MODEL
    assert any("sixty" in n and "two" in n for n in out.draft_notes)


def test_a_computed_number_in_the_wrong_unit_is_rejected():
    """54 is a failure probability here; "54 km/h" and "70 cm" are inventions."""
    original = advisory()
    out = gemini.enhance(original, fake({
        "headline": "Expect 54 km/h gusts and 70 cm of flooding at Govt Hospital Peruru",
    }))
    assert out.headline == original.headline
    notes = " ".join(out.draft_notes)
    assert "54 km/h" in notes and "70 cm" in notes


def test_the_right_number_in_the_right_unit_still_passes():
    out = gemini.enhance(advisory(), fake({
        "headline": "Govt Hospital Peruru: 54 per cent failure risk, 77 km/h wind, 48 h out",
    }))
    assert out.drafted_by == gemini.MODEL


@pytest.mark.parametrize("words", ["యాభై శాతం", "రెండు రోజుల్లో", "ପଚାଶ ପ୍ରତିଶତ", "ଦୁଇ ଦିନ"])
def test_number_words_in_telugu_and_odia_are_caught(words):
    bad = dict(GOOD_TE, headline=f"మోంథా: {words}")
    out = gemini.enhance(advisory(), fake({"translations": [bad]}))
    assert "te-IN" in out.pending_languages


def test_quantities_are_read_with_their_units():
    assert gemini.quantities_in("31%-70%, 48 h, 0.28 m, 77 km/h, 150 mm") == {
        ("31", "%"), ("70", "%"), ("48", "h"), ("0.28", "m"), ("77", "km/h"), ("150", "mm")}
    assert gemini.quantities_in("48 hospitals") == set(), "a unit must end at a word boundary"


# --- replies of the wrong shape ------------------------------------------------

@pytest.mark.parametrize("reply", [
    {"headline": 5},
    {"instruction": ["a", "list"]},
    {"translations": ["te-IN"]},
    {"translations": "te-IN"},
    {"translations": [{"language": "te-IN", "headline": 7, "instruction": "x", "description": "y"}]},
    {"advisories": [{"id": "0", "headline": None, "translations": [None]}]},
    ["not", "an", "object"],
])
def test_a_reply_of_the_wrong_shape_keeps_the_template_and_never_raises(reply):
    original = advisory()
    out = gemini.enhance(original, fake(reply))
    assert out.headline == original.headline
    assert out.instruction == original.instruction
    assert "te-IN" in out.pending_languages


# --- the bypasses found in the second review -----------------------------------

@pytest.mark.parametrize("text, offending", [
    ("Expect 54-km/h gusts at Govt Hospital Peruru", "54 km/h"),
    ("Risk is 77-per-cent at Govt Hospital Peruru", "77 %"),
    ("Triple the usual risk at Govt Hospital Peruru", "triple"),
    ("A quarter of the wards will flood", "quarter"),
    ("A threefold rise in risk", "threefold"),
])
def test_hyphenated_units_and_multiplier_words_are_caught(text, offending):
    out = gemini.enhance(advisory(), fake({"headline": text}))
    assert out.drafted_by != gemini.MODEL
    assert offending in " ".join(out.draft_notes)


@pytest.mark.parametrize("headline", [
    "మోంథా: 77 శాతం ముప్పు",          # 77 percent -- 77 is wind in km/h here, not a percentage
    "మోంథా: 54 కి.మీ/గం గాలులు",      # 54 km/h -- 54 is a failure probability
    "ମୋନ୍ଥା: 70 ସେମି ଜଳ",             # 70 cm -- no depth of 70 cm was computed
])
def test_a_translation_cannot_move_a_number_to_another_unit(headline):
    bad = dict(GOOD_TE, headline=headline)
    out = gemini.enhance(advisory(), fake({"translations": [bad]}))
    assert "te-IN" in out.pending_languages


def test_the_right_units_in_telugu_still_pass():
    good = dict(GOOD_TE, headline="మోంథా: 54 శాతం ముప్పు, 48 గంటల్లో")
    out = gemini.enhance(advisory(), fake({"translations": [good]}))
    assert "te-IN" in out.languages
