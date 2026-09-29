"""How model-written text is read for numbers -- tested by class, not by
example: every unit spelling with every separator, every Unicode numeral,
every decimal digit in every script. The guardrail is only as strong as this
reading, and a list of past bypasses is no evidence about the next one.

The sweeps are one test each that checks every case and lists every one
that fails, rather than a test per spelling: the count of tests should say
how many behaviours are checked, not how long the lexicon is."""

import unicodedata

import pytest

from advisory import gemini
from advisory import numbers as n
from tests.test_gemini import advisory, fake

SEPARATORS = ["", " ", "-", " ", " - "]
SPELLINGS = [(unit, sp) for unit, sps in n._UNITS.items() for sp in sps]


def _variants(spelling: str) -> list[str]:
    """The ways people write one spelling: as is, upper case, and dotted
    abbreviations (k.p.h.). Upper-case "M" alone is left out: after a number
    it is read as millions, which `test_upper_case_m_and_b_are_millions_and_
    billions` covers."""
    out = [spelling] + ([spelling.upper()] if spelling != "m" else [])
    if spelling.isalpha() and len(spelling) <= 4:
        out.append(".".join(spelling) + ".")
    return out


def test_every_unit_spelling_is_read_with_every_separator():
    cases = [(unit, f"expect 54{sep}{form} near the coast")
             for unit, spelling in SPELLINGS for sep in SEPARATORS for form in _variants(spelling)]
    assert len(cases) > 1500
    wrong = [(text, n.quantities_in(text)) for unit, text in cases
             if n.quantities_in(text) != {("54", unit)}]
    assert wrong == []


def test_every_telugu_and_odia_unit_is_read():
    cases = [(unit, f"54{sep}{spelling}లో") for unit, spellings in n._INDIC_UNITS.items()
             for spelling in spellings for sep in ("", " ", "\u00a0", "\u202f")]
    wrong = [text for unit, text in cases if n.quantities_in(text) != {("54", unit)}]
    assert wrong == []


def test_every_decimal_digit_in_every_script_reads_as_its_value():
    digits = [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) == "Nd"]
    assert len(digits) > 500
    for d in digits:
        assert n.normalise_digits(d) == str(unicodedata.digit(d)), (hex(ord(d)), d)


def test_every_other_numeral_is_reported():
    numerals = [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) in ("No", "Nl")]
    assert len(numerals) > 500
    for c in numerals:
        assert n.other_numerals(f"risk is {c} higher") == {c}, hex(ord(c))


@pytest.mark.parametrize("money", ["₹54", "$ 54", "€54", "£54", "¥54", "Rs 54", "Rs. 54", "INR 5,400", "usd54"])
def test_money_is_reported(money):
    assert n.currency_in(f"damage of {money} expected")


@pytest.mark.parametrize("text", [
    "10 hospitals", "48 hospitals at risk", "the 10th-90th percentile", "5 more crews",
    "no one is to be left behind", "3 high-probability assets", "NH216 is closed",
])
def test_counts_and_ordinary_prose_are_not_mistaken_for_units(text):
    assert n.quantities_in(text) == set()
    assert n.number_words_in(text) == set()
    assert n.other_numerals(text) == set() and n.currency_in(text) == set()
    assert n.unreadable_in(text) == set()


# --- grouping: a number is read whole ------------------------------------------

GROUP_SEPARATORS = [",", "'", "_", "\u00a0", "\u2009", "\u202f", " "]


@pytest.mark.parametrize("sep", GROUP_SEPARATORS)
def test_a_grouped_number_is_one_number_whatever_the_separator(sep):
    """Found in review: "10,000" read as a 10 and a 0, both of them facts."""
    for written, value in ((f"10{sep}000", "10000"), (f"1{sep}00{sep}000", "100000"),
                           (f"1{sep}234{sep}567", "1234567"), (f"12{sep}500.5", "12500.5")):
        text = f"{written} households cut off"
        assert n.numbers_in(text) == {value}, repr(text)
        assert n.quantities_in(f"{written} km") == {(value, "km")}, repr(written)


def test_a_dot_that_may_be_a_thousands_separator_is_read_both_ways():
    assert n.numbers_in("10.000 homes") == {"10", "10000"}
    assert n.numbers_in("1.234.567 homes") == {"1234567"}
    # Not ambiguous: a leading zero, or not three digits after the dot.
    assert n.numbers_in("0.125 and 1.25 and 12.5") == {"0.12", "1.25", "12.5"}


def test_a_list_is_not_a_grouped_number():
    assert n.numbers_in("10, 20 and 30") == {"10", "20", "30"}
    assert n.numbers_in("12 h, then 24 h") == {"12", "24"}


# --- scale: a number times a magnitude is a different number ---------------------

def test_every_scale_is_reported_glued_spaced_or_hyphenated():
    texts = [f"about 50{sep}{form} people" for scale in n._SCALES
             for sep in ("", " ", "-", "\u00a0") for form in {scale, scale.upper(), scale.capitalize()}]
    wrong = [t for t in texts if not n.unreadable_in(t) or n.quantities_in(t)]
    assert wrong == []


def test_upper_case_m_and_b_are_millions_and_billions():
    assert n.unreadable_in("5M people") == {"5M"}
    assert n.unreadable_in("2 B in losses") == {"2 B"}
    assert n.quantities_in("54 M/S gusts") == {("54", "m/s")}
    assert n.quantities_in("54 m surge") == {("54", "m")}


def test_letters_glued_to_a_number_must_be_a_unit_or_an_ordinal():
    assert n.unreadable_in("a 50kx generator") == {"50kx"}
    assert n.quantities_in("a 50kw generator") == {("50", "kW")}, "kW is a unit, just not a fact's"
    assert n.unreadable_in("NH516A is closed") == {"516A"}
    assert n.unreadable_in("the 10th-90th percentile, the 1st, 2nd and 3rd crews") == set()
    assert n.unreadable_in("54km/h gusts, 54mm of rain, 12h out") == set()


def test_case_endings_in_other_scripts_are_not_scales_but_scale_words_are():
    assert n.unreadable_in("10ରୁ 90 ପର୍ଯ୍ୟନ୍ତ") == set()          # from 10 to 90
    assert n.number_words_in("10లక్షల మంది") == {"లక్ష"}          # 10 lakh people
    assert n.number_words_in("10ଲକ୍ଷ ଲୋକ") == {"ଲକ୍ଷ"}


# --- through the guardrail -----------------------------------------------------

OTHER_UNITS = sorted({sp for unit, sp in SPELLINGS if unit != "%"})


def test_a_probability_cannot_come_back_in_any_other_unit():
    """54 is a failure probability in this advisory, and nothing else."""
    headlines = [f"Govt Hospital Peruru: 54{sep}{spelling}" for spelling in OTHER_UNITS
                 for sep in (" ", "-")]
    accepted = [h for h in headlines
                if gemini.enhance(advisory(), fake({"headline": h})).drafted_by == gemini.MODEL]
    assert accepted == []


def test_the_probability_in_its_own_unit_passes_in_every_spelling():
    refused = [sp for sp in n._UNITS["%"] if gemini.enhance(
        advisory(), fake({"headline": f"Govt Hospital Peruru: 54 {sp} risk"})).drafted_by != gemini.MODEL]
    assert refused == []


# Each found accepted in review: a computed number reused without its unit or
# in a unit outside the lexicon, a sign, a label, a duration said in words,
# money after the number, inches by their mark. 48, 54, 70, 77, 150 and 3 are
# all computed facts of this advisory.
REUSED = [
    "Govt Hospital Peruru: 54% risk, 150 households cut off",     # 150 mm of rain
    "Govt Hospital Peruru: 54% risk, 77 hospitals affected",      # a 77 km/h gust
    "Govt Hospital Peruru: 54% risk; 54-70 patients",
    "Govt Hospital Peruru: 54% risk; 54 kW generator",
    "Govt Hospital Peruru: 54% risk; 54 kilowatt generator",
    "Govt Hospital Peruru: 54% risk; 54 tonnes of oxygen",
    "Govt Hospital Peruru: 54% risk; 54 litres of diesel",
    "Govt Hospital Peruru: 54% risk; 54 gallons of diesel",
    "Govt Hospital Peruru: 54% risk; 54 rupees",
    "Govt Hospital Peruru: 54% risk; 3 rupees a bed",
    "Govt Hospital Peruru: 54% risk; category 3 storm",
    "Govt Hospital Peruru: 54% risk; signal no. 3 hoisted",
    "Govt Hospital Peruru: 54% risk; −48 h",
    "Govt Hospital Peruru: 54% risk; +54% since yesterday",
    "Govt Hospital Peruru: 54% risk; expect a week without power",
    "Govt Hospital Peruru: 54% risk, 54 kilometres/hour",
    "Govt Hospital Peruru: 54% risk, 54 m/sec",
    "Govt Hospital Peruru: 54% risk, 77 metres per hour",
    "Govt Hospital Peruru: 54% risk, 70 in of rain",
    'Govt Hospital Peruru: 54% risk, 70" rain',
    "Govt Hospital Peruru: 54% risk, 3 kV lines down",
    "Govt Hospital Peruru: 54% risk; a category IV storm",
    "Govt Hospital Peruru: 54% risk; signal no. X hoisted at the port",
    "Govt Hospital Peruru: 54% risk; tens of households cut off",
    # Found in review: bare facts reused as casualties, odds, times, spans.
    "Govt Hospital Peruru: 54% risk; 10 dead",
    "Govt Hospital Peruru: 54% risk; 3 patients died",
    "Govt Hospital Peruru: 54% risk; risk of injury to staff",
    "Govt Hospital Peruru: 54% risk; a 1 in 3 chance of flooding",
    "Govt Hospital Peruru: 54% risk; 1 out of 3 generators",
    "Govt Hospital Peruru: 54% risk; power out for 50 months",
    "Govt Hospital Peruru: 54% risk; evacuate by 3 pm",
    "Govt Hospital Peruru: 54% risk; evacuate by 10:00",
    "Govt Hospital Peruru: 54% risk; repairs will take a fortnight",
    "పేరూరు ఆసుపత్రి: 54% ప్రమాదం; 10 మంది మృతి",
    # Found in review: Roman counts, fractions, "halve", overstated certainty.
    "Govt Hospital Peruru: 54% risk; XLVIII hours without power",
    "Govt Hospital Peruru: 54% risk; 1/3 of the grid",
    "Govt Hospital Peruru: 54% risk; halve the staff",
    "Govt Hospital Peruru: 54% risk; certain failure",
    "Govt Hospital Peruru: 54% risk; flooding is inevitable",
    # Found in review: a Roman count at the end of the text, or before a
    # comma, was never read -- an empty match before it took its place.
    "Govt Hospital Peruru: 54% risk; power out for XLVIII hours",
    "Govt Hospital Peruru: 54% risk; power out for XLVIII hours.",
    "Govt Hospital Peruru: 54% risk; XLVIII hours, perhaps more",
    "Govt Hospital Peruru: 54% risk; 77 hours, perhaps more",
]


@pytest.mark.parametrize("headline", REUSED)
def test_a_computed_number_reused_or_restated_is_rejected(headline):
    out = gemini.enhance(advisory(), fake({"headline": headline}))
    assert out.drafted_by != gemini.MODEL, headline


@pytest.mark.parametrize("headline", [
    "Govt Hospital Peruru: 54% risk, winds to 77 km/h, 48 h out",
    "Govt Hospital Peruru: 54 percent risk of a 48-hour outage",
    "Govt Hospital Peruru: 54% risk; 150 mm of rain; 0.28 m of water",
    "Govt Hospital Peruru, one of 3 assets at risk: 54%, 48 h to landfall",
    "Govt Hospital Peruru: 54% risk (the 10th-90th percentile spans 31%-70%)",
    "Govt Hospital Peruru: 54% risk, gusts of 77 kilometres per hour, T−48 h",
    "Govt Hospital Peruru: 54% risk; I advise a mix of crews, first class response",
    "Govt Hospital Peruru: 54% risk; ७७ km/h gusts",
    "Govt Hospital Peruru: 54% risk; make sure staff are ready, 77 km/h",
    # A unit ends where its clause does, and is still read there.
    "Govt Hospital Peruru: 54% risk, 48 h, 77 km/h; act now",
    "Govt Hospital Peruru: 54% risk (48 h out)",
])
def test_computed_numbers_in_their_own_units_still_pass(headline):
    """Includes words that look like labels or numerals but are not: "I" as
    a pronoun, "a mix" of crews, "class" as a noun."""
    out = gemini.enhance(advisory(), fake({"headline": headline}))
    assert out.drafted_by == gemini.MODEL, out.draft_notes


HEADLINES = [
    "Montha, 48 h out: 10,000 households near Govt Hospital Peruru cut off",
    "Montha, 48 h out: 10 000 households near Govt Hospital Peruru cut off",
    "Montha, 48 h out: 1,00,000 people near Govt Hospital Peruru",
    "Govt Hospital Peruru: 50k patients, 48 h out",
    "Govt Hospital Peruru: 10 lacs affected, 48 h out",
    "Govt Hospital Peruru: 3x the usual load, 48 h out",
    "Govt Hospital Peruru: 1M people, 48 h out",
    "Govt Hospital Peruru: a 48kw generator",
]


def test_a_name_survives_transliteration_but_not_a_new_unit():
    """Documented limit: the digits of a name may be repeated on their own,
    as a transliterated name keeps them. With a unit they are an invention."""
    base = advisory()
    listed = gemini.replace(base, assets=[dict(base.assets[0], name="substation 201428299")],
                            instruction="Pre-position crews near: substation 201428299.")
    te = gemini.enhance(listed, fake({"headline": "Montha, 48 h out: సబ్‌స్టేషన్ 201428299"}))
    assert te.drafted_by == gemini.MODEL, te.draft_notes
    bad = gemini.enhance(listed, fake({"headline": "Montha, 48 h out: 201428299 km of line down"}))
    assert bad.drafted_by != gemini.MODEL


@pytest.mark.parametrize("headline", HEADLINES)
def test_a_grouped_or_scaled_number_is_rejected(headline):
    """48, 0 and 1 are all facts of this advisory; none of these numbers is."""
    original = advisory()
    out = gemini.enhance(original, fake({"headline": headline}))
    assert out.headline == original.headline, headline
    assert out.drafted_by != gemini.MODEL, headline


def test_the_advisorys_own_asset_names_are_facts_digits_and_all():
    base = advisory()
    names = ["220kV Purushotamapattinam", "NH516A", "7star Hospitals", "Seven Hills Hospital"]
    assets = [dict(base.assets[0], name=name) for name in names]
    with_names = gemini.replace(base, assets=assets)
    headline = "Montha, 48 h out: " + ", ".join(names) + " at 54% risk"
    out = gemini.enhance(with_names, fake({"headline": headline}))
    assert out.drafted_by == gemini.MODEL, out.draft_notes
    # A digit-bearing word of a name counts on its own, as it survives
    # transliteration: "220kV" here is that substation's own word.
    out = gemini.enhance(with_names, fake({"headline": "Montha, 48 h out: 220kV పురుషోత్తమపట్నం at 54% risk"}))
    assert out.drafted_by == gemini.MODEL, out.draft_notes
    # Digits taken out of a name and used as a number are the model's own.
    for headline in ("Montha, 48 h out: 516 poles down near NH516A", "Montha, 48 h out: 7 stars",
                     "Montha, 48 h out: 220 lines at 54% risk"):
        out = gemini.enhance(with_names, fake({"headline": headline}))
        assert out.drafted_by != gemini.MODEL, headline


@pytest.mark.parametrize("numeral", ["½", "¾", "⑤", "Ⅲ", "²", "൰", "፲"])
def test_numerals_that_are_not_digits_are_rejected(numeral):
    out = gemini.enhance(advisory(), fake({"headline": f"Govt Hospital Peruru risk up {numeral}"}))
    assert out.drafted_by != gemini.MODEL
