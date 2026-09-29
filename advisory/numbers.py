"""Which numbers a piece of model-written text contains, and in what units.

The drafting guardrail (advisory/gemini.py) accepts model text only if every
number in it is one code computed, in the unit code computed it in. That is
only as strong as this module's reading of the text, so it reads by class,
not by example:

  digits      every Unicode decimal digit, in any script, is read as a digit
              (Telugu, Odia, Devanagari, fullwidth ...).
  grouping    a number is read whole, however its digits are grouped:
              "10,000", Indian "1,00,000", "10 000", "10'000" are all ten
              thousand, never a 10 and a 0. "10.000" is ten in English and
              ten thousand in much of Europe, so it is read both ways and
              both must be facts.
  numerals    every other numeric character -- fractions (½), circled (⑤),
              Roman (Ⅲ), superscripts (²) -- cannot be checked against a
              fact, so it is reported as it stands.
  units       the words and symbols after a number are matched against a
              lexicon of units (speed, length, depth, pressure, temperature,
              time, percentage) with dots, hyphens and spacing normalised, so
              "54 k.p.h.", "54-kmh" and "54 kilometres per hour" are one unit.
  scale       a number scaled by a magnitude ("50k", "10 lacs", "3x",
              "2 crore") is a different number, so it is reported. So is a
              number glued to Latin letters that are neither a unit nor an
              ordinal ("50kw"): the check cannot know what it means.
  currency    a currency sign before a number is reported: no fact is money.
  words       numbers written as words (English, and common Telugu and Odia
              forms) cannot be checked either, so they are reported.

What it cannot do: know every way a language can say a quantity. A word it
does not recognise after a number is treated as a count noun ("10 hospitals")
and the number is checked on its own. The approving officer remains the last
check, and the console says so.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# --- digits and numerals -------------------------------------------------------

#: A written number: digits, then any groups joined by the separators people
#: group thousands with -- commas, apostrophes, underscores, thin and no-break
#: spaces, or an ordinary space before exactly three digits ("10 000") or
#: before a group with a leading zero ("1 00 000"), which no separate number
#: has -- then any decimal parts.
_NUMERAL = r"\d+(?:[,'_\u00a0\u2009\u202f]\d+|\x20(?:\d{3}(?!\d)|0\d*))*(?:\.\d+)*|\.\d+"
_NUMBER = re.compile(_NUMERAL)
_GROUP_SEPARATORS = re.compile(r"[,'_\u00a0\u2009\u202f\x20]")


def normalise_digits(text: str) -> str:
    """Every decimal digit, in any script, as its ASCII digit."""
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii()
                   and unicodedata.category(c) == "Nd" else c for c in text)


def other_numerals(text: str) -> set[str]:
    """Numeric characters that are not decimal digits: ½, ⑤, Ⅲ, ²."""
    return {c for c in text if unicodedata.category(c) in ("No", "Nl")}


def canonical(token: str) -> str:
    """One spelling per number: 0.30, .3 and 0.3 are the same fact."""
    try:
        value = float(token)
    except ValueError:
        return token
    return f"{value:.2f}".rstrip("0").rstrip(".")


def readings(token: str) -> set[str]:
    """What a written number can mean, canonically: one value, or two when
    the grouping is ambiguous."""
    whole = _GROUP_SEPARATORS.sub("", token)
    if whole.count(".") > 1:                        # "1.234.567": dots group
        return {canonical(whole.replace(".", ""))}
    values = {canonical(whole)}
    if re.fullmatch(r"[1-9]\d{0,2}\.\d{3}", whole):  # "10.000", "1.352"
        values.add(canonical(whole.replace(".", "")))
    return values


def numbers_in(text: str) -> set[str]:
    """Every number in a piece of text, in canonical form."""
    return {v for token in _NUMBER.findall(normalise_digits(text)) for v in readings(token)}


# --- units ----------------------------------------------------------------------

#: Canonical unit -> spellings, written without dots and in lower case; the
#: text is normalised the same way before lookup.
_UNITS: dict[str, tuple[str, ...]] = {
    "%": ("%", "percent", "per cent", "pc", "pct", "percentage"),
    "km/h": ("km/h", "km/hr", "kmh", "kmph", "kph", "km per hour", "km an hour",
             "kilometres per hour", "kilometers per hour", "kilometre per hour",
             "kilometer per hour", "kilometres an hour", "kilometers an hour"),
    "mph": ("mph", "mi/h", "miles per hour", "mile per hour", "miles an hour"),
    "m/s": ("m/s", "mps", "metres per second", "meters per second", "metre per second",
            "meter per second", "ms"),   # "ms" is m s-1 here, as in "54 ms-1"
    "kt": ("kt", "kts", "kn", "knot", "knots"),
    "mm": ("mm", "millimetre", "millimetres", "millimeter", "millimeters"),
    "cm": ("cm", "centimetre", "centimetres", "centimeter", "centimeters"),
    "m": ("m", "metre", "metres", "meter", "meters", "mtr", "mtrs"),
    "km": ("km", "kms", "kilometre", "kilometres", "kilometer", "kilometers"),
    "ft": ("ft", "foot", "feet"),
    "in": ("inch", "inches"),
    "yd": ("yd", "yds", "yard", "yards"),
    "mi": ("mile", "miles"),
    "hPa": ("hpa", "mb", "mbar", "millibar", "millibars", "hectopascal", "hectopascals"),
    "°": ("°", "°c", "°f", "deg", "degree", "degrees", "celsius", "fahrenheit"),
    "h": ("h", "hr", "hrs", "hour", "hours"),
    "min": ("min", "mins", "minute", "minutes"),
    "s": ("s", "sec", "secs", "second", "seconds"),
    "day": ("day", "days"),
    "week": ("week", "weeks"),
    "month": ("month", "months", "fortnight", "fortnights", "year", "years", "yr", "yrs"),
    # A time of day is a claim about when, which no computed fact is.
    "o'clock": ("am", "pm", "hrs ist", "ist", "utc", "o'clock", "oclock"),
    # Units no advisory fact is ever given in. They are read so that a
    # number in one is a quantity -- and so never matches a fact -- rather
    # than a bare number that might.
    "W": ("watt", "watts"),
    "kW": ("kw", "kilowatt", "kilowatts"),
    "MW": ("mw", "megawatt", "megawatts"),
    "kWh": ("kwh", "mwh", "kilowatt hour", "kilowatt hours"),
    "kV": ("kv", "kva", "mva", "volt", "volts", "kilovolt", "kilovolts"),
    "kg": ("kg", "kgs", "kilogram", "kilograms", "kilo", "kilos", "quintal", "quintals"),
    "t": ("tonne", "tonnes", "ton", "tons", "metric ton", "metric tons"),
    "L": ("litre", "litres", "liter", "liters", "ml", "kl", "gallon", "gallons",
          "cusec", "cusecs", "cumec", "cumecs", "tmc", "tmcft"),
    # (No "km2": the digit ends the unit there, and "54 km" is read instead,
    # which no fact is in either.)
    "ha": ("ha", "hectare", "hectares", "acre", "acres", "sq km", "km²", "sq m",
           "m²", "square km", "square kilometres", "square kilometers"),
    "₹": ("rupee", "rupees", "rupaye", "paise", "rs", "inr", "usd", "dollar", "dollars",
          "euro", "euros", "pound", "pounds"),
}
#: The same units as Telugu and Odia write them, matched as prefixes because
#: they take suffixes ("గంటల్లో" -- within hours).
_INDIC_UNITS: dict[str, tuple[str, ...]] = {
    "%": ("శాతం", "ప్రతిశతం", "ଶତକଡ଼ା", "ପ୍ରତିଶତ"),
    "km/h": ("కి.మీ/గం", "కిమీ/గం", "కి.మీ./గం", "କିମି/ଘଣ୍ଟା", "କି.ମି/ଘଣ୍ଟା"),
    "mm": ("మి.మీ", "మిమీ", "మిల్లీమీటర్", "ମିମି", "ମି.ମି", "ମିଲିମିଟର"),
    "cm": ("సెం.మీ", "సెంమీ", "సెంటీమీటర్", "ସେମି", "ସେ.ମି", "ସେଣ୍ଟିମିଟର"),
    "km": ("కి.మీ", "కిమీ", "కిలోమీటర్", "କିମି", "କି.ମି", "କିଲୋମିଟର"),
    "m": ("మీటర్", "మీ", "ମିଟର", "ମି"),
    "h": ("గంట", "ଘଣ୍ଟା"),
    "day": ("రోజు", "ଦିନ"),
    "₹": ("రూపాయ", "రూ.", "ଟଙ୍କା"),
}
#: Not a unit: a scale. A number followed by one is a different number.
SCALE = "×"
_SCALES = ("k", "thousand", "thousands", "lakh", "lakhs", "lac", "lacs", "l", "lk",
           "crore", "crores", "cr", "crs", "mn", "mln", "million", "millions",
           "bn", "billion", "billions", "hundred", "hundreds", "dozen", "dozens",
           "x", "×", "times", "fold")
#: Spellings are looked up with "/" read as " per ", as the text is.
_UNIT_OF = ({spelling: SCALE for spelling in _SCALES}
            | {spelling.replace("/", " per "): unit
               for unit, spellings in _UNITS.items() for spelling in spellings})
_LENGTH_UNITS = {"km", "m", "mi", "ft", "cm", "mm", "yd", "in"}
_TIME_UNITS = {"h", "min", "s", "day", "week"}
_SPEED_OF = {("km", "h"): "km/h", ("m", "s"): "m/s", ("mi", "h"): "mph"}
_INDIC_UNIT_OF = sorted(((sp, unit) for unit, sps in _INDIC_UNITS.items() for sp in sps),
                        key=lambda pair: -len(pair[0]))
_LONGEST_UNIT = max(len(s.split()) for s in _UNIT_OF)

#: A number, then whatever follows it up to the next clause break.
_NUMBER_AND_TAIL = re.compile(rf"({_NUMERAL})([^\d,;:!?()\[\]\n]*)")
_FIRST_WORD = re.compile(r"\s*\S*")
#: Letters glued to a number that change nothing about its value.
_ORDINAL = re.compile(r"(?:st|nd|rd|th)(?![a-z])", re.IGNORECASE)
_CURRENCY_BEFORE = re.compile(r"(?:[\$€£¥₹]|\b(?:rs|inr|usd)\.?)\s*\d[\d.,]*", re.IGNORECASE)


def _speed(words: list[str]) -> str | None:
    """A length per time however joined -- "kilometres per hour", "m per sec",
    "km an hour" -- as a speed; km/h, m/s and mph by name, others as a pair
    no fact is in."""
    for i in range(1, min(len(words) - 1, 4)):
        if words[i] in ("per", "an", "a", "each", "every"):
            length = _UNIT_OF.get(" ".join(words[:i]))
            time = _UNIT_OF.get(words[i + 1])
            if length in _LENGTH_UNITS and time in _TIME_UNITS:
                return _SPEED_OF.get((length, time), f"{length}/{time}")
    return None


def _unit_by_mark(tail: str) -> str | None:
    """A unit given by a mark or in another script, read before any
    normalising could lose it."""
    # Upper-case M and B after a number are millions and billions ("5M",
    # "2 B"); lower-case m is metres, and M/S is still metres per second.
    if re.match(r"[MB](?![A-Za-z/²³])", tail):
        return SCALE
    # Inches and feet by their marks: 70" and 70'. And "in" is inches only
    # where it cannot be the preposition: "70 in." or "70 in of rain".
    if re.match(r'(?:"|″|\'\')', tail) or re.match(r"in(?:\.|\s+of\b)", tail, re.IGNORECASE):
        return "in"
    if re.match(r"(?:'|′)(?!\w)", tail):
        return "ft"
    return next((unit for spelling, unit in _INDIC_UNIT_OF if tail.startswith(spelling)), None)


def _unit_by_words(words: list[str]) -> str | None:
    """A unit spelled out: a speed however joined, else the longest lexicon
    match, else a symbol at the front of the first word ("54°C", "54%")."""
    speed = _speed(words)
    if speed:
        return speed
    for n in range(min(_LONGEST_UNIT, len(words)), 0, -1):
        candidate = " ".join(words[:n])
        if candidate in _UNIT_OF:
            return _UNIT_OF[candidate]
    return next((_UNIT_OF[symbol] for symbol in ("°c", "°f", "°", "%")
                 if words[0].startswith(symbol)), None)


def _unit_after(tail: str) -> str | None:
    """The unit a number is given in, from the text right after it."""
    tail = tail.lstrip(" \u00a0\u2009\u202f-–")   # spaces of every width, hyphens, dashes
    marked = _unit_by_mark(tail)
    if marked:
        return marked
    # A unit ends where its clause does: "48 hours, then" is in hours.
    tail = re.split(r"[,;:!?()\[\]{}]", tail, maxsplit=1)[0]
    # Normalise the way people vary unit spellings: no dots, hyphens as
    # spaces, "/" as "per", lower case. "k.p.h." -> "kph"; "km-per-hour" and
    # "kilometres/hour" -> "... per hour".
    words = re.sub(r"\.", "", tail.lower()).replace("-", " ").replace("/", " per ").split()
    return _unit_by_words(words) if words else None


class Occurrence(NamedTuple):
    """One number where it stands in the text."""

    token: str               # as written, digits normalised
    values: frozenset[str]   # what it can mean, canonical (see `readings`)
    unit: str | None         # the unit after it, SCALE, or None
    tail: str                # the text after it, to the next clause break
    before: str              # the text before it


#: A sign on a number: a minus (−, or - at the start of a word), a plus, or
#: plus-minus. "T−48" and "31%-70%" are labels and ranges, not signs.
_SIGN = re.compile(r"(?:^|[\s(\[{:;,])[−+±-]$")
#: A number named by what precedes it: "category 3", "signal no. 10".
_LABEL = re.compile(r"\b(?:category|cat|grade|level|class|stage|phase|signal|number|no)"
                    r"\.?\s*#?\s*$", re.IGNORECASE)


#: The exponent in "m s-1" or "km h-1": part of the unit, not a number.
_EXPONENT = re.compile(r"\b(?:s|sec|h|hr|m|km)\s*[-−^]$")


def occurrences(text: str) -> list[Occurrence]:
    """Every number in the text, with its unit and surroundings."""
    text = normalise_digits(text)
    return [Occurrence(m.group(1), frozenset(readings(m.group(1))), _unit_after(m.group(2)),
                       m.group(2), text[:m.start()])
            for m in _NUMBER_AND_TAIL.finditer(text)
            if not (m.group(1) in ("1", "2", "3") and _EXPONENT.search(text[:m.start()]))]


def quantities_in(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs, both canonical: "54 per cent" -> ("54", "%")."""
    return {(value, o.unit) for o in occurrences(text)
            if o.unit and o.unit != SCALE for value in o.values}


def bare_numbers_in(text: str) -> set[str]:
    """Numbers written without a unit at least once: counts, ordinals, ids."""
    return {value for o in occurrences(text) if o.unit is None for value in o.values}


def unreadable_in(text: str) -> set[str]:
    """Numbers whose value the check cannot pin down:

    - scaled by a magnitude ("50k", "10 lacs", "3x");
    - glued to Latin letters that are neither a unit nor an ordinal ("50kv"
      is kV; "50kx" is unreadable). Letters in other scripts glued to a
      number are case endings there ("10ରୁ", from 10), so only known
      magnitude words are read in them (see `number_words_in`);
    - signed ("−48 h", "+5%", "±2 m"): a sign makes it another number;
    - named by a label ("category 3", "signal 10"): a classification no
      computed fact is.
    """
    found: set[str] = set()
    for o in occurrences(text):
        word = _FIRST_WORD.match(o.tail)
        written = o.token + (word.group(0) if word else "")
        glued_latin = re.match(r"[A-Za-z]", o.tail) is not None
        if o.unit == SCALE or (o.unit is None and glued_latin and not _ORDINAL.match(o.tail)):
            found.add(written)
        if _SIGN.search(o.before):
            found.add(o.before[-1] + written)
        if o.unit is None and _LABEL.search(o.before):
            label = _LABEL.search(o.before)
            found.add((label.group(0) if label else "") + o.token)
    return found


def odds_and_clock_times_in(text: str) -> set[str]:
    """"1 in 3", "2 out of 5", "15:00": odds and times, never computed facts."""
    text = normalise_digits(text)
    return {m.group(0) for m in _ODDS.finditer(text)} | {m.group(0) for m in _CLOCK.finditer(text)}


def roman_counts_in(text: str) -> set[str]:
    """Roman numerals used as counts: "XLVIII hours"."""
    return {m.group(0) for m in _ROMAN.finditer(text)
            if len(m.group(1)) >= 2 and _unit_after(m.group(2)) not in (None, SCALE)}


def certainty_claims_in(text: str) -> set[str]:
    """"certain", "definitely", "inevitable": certainty the forecast does not
    have. Every advisory's figures are probabilities."""
    return {m.group(0).lower() for m in _CERTAINTY.finditer(text)}


def casualty_claims_in(text: str) -> set[str]:
    """Words claiming deaths or injuries, in English, Telugu or Odia."""
    found = {m.group(0).lower() for m in _CASUALTY.finditer(text)}
    for token in _TOKEN.findall(text):
        found |= {w for w in _INDIC_CASUALTY if token.startswith(w)}
    return found


def currency_in(text: str) -> set[str]:
    """Amounts of money, which no computed fact is: a sign or code before
    the number here; money words after it are a unit (see `_UNITS`)."""
    return {m.group(0).strip() for m in _CURRENCY_BEFORE.finditer(normalise_digits(text))}


# --- numbers as words ------------------------------------------------------------

#: English "one" is left out: it is far more often a pronoun ("no one", "one
#: of") than a count.
_ENGLISH_NUMBER_WORDS = re.compile(
    r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|"
    r"lakhs?|lacs?|crores?|dozens?|half|halves|twice|thrice|double|doubled|triple|tripled|"
    r"quadruple|quarters?|thirds?|\w+fold|score of|scores of|couple of|pair of|handful|"
    r"tens of|many tens|fortnights?|decades?|halve|halved|halving)\b",
    re.IGNORECASE)
#: A classification in Roman numerals: "category IV", "signal no. X". The
#: numeral in digits is caught as a labelled number (see `unreadable_in`).
_ROMAN_LABEL = re.compile(
    r"\b(?:category|cat|grade|level|class|stage|phase|signal|number|no)\.?\s*#?\s*"
    r"(?:[IVXL]{1,6})\b(?![a-z])", re.IGNORECASE)
#: Odds and times of day, which no computed fact is: "1 in 3", "2 out of 5",
#: "15:00", "3.30 pm" (the last is caught as a unit).
_ODDS = re.compile(r"\b\d[\d.,]*\s+(?:in|out\s+of)\s+\d[\d.,]*\b|\b\d+\s*/\s*\d+\b", re.IGNORECASE)
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
#: A Roman numeral that is a count: followed by a unit ("XLVIII hours").
#: Standing alone it is more often a name ("Phase II" is caught as a label).
#: The lookahead keeps an empty numeral from matching: one did, and took the
#: text up to a real numeral with it, so "out for XLVIII hours" passed.
_ROMAN = re.compile(r"\b(?=[MDCLXVI])(M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
                    r"\s+(\S+(?:\s+\S+)?)")
#: Words that claim a certainty no ensemble probability gives.
_CERTAINTY = re.compile(r"\b(?:certain(?:ly)?|definite(?:ly)?|guaranteed|inevitabl[ey]|"
                        r"sure\s+to|bound\s+to|without\s+doubt|no\s+doubt)\b", re.IGNORECASE)
#: Deaths and injuries. An infrastructure advisory has no computed casualty
#: figure, so any claim of one -- with or without a number -- is the model's.
_CASUALTY = re.compile(r"\b(?:dead|deaths?|died|dies|dying|killed|kills|fatalit\w*|casualt\w*|"
                       r"injur\w*|drown\w*|lives\s+lost|bodies)\b", re.IGNORECASE)
_INDIC_CASUALTY = ("మరణ", "మృతి", "మృత", "చనిపో", "గాయ", "ମୃତ୍ୟୁ", "ମୃତ", "ମରି", "ଆହତ")
#: A quantity said with an article: "a week", "an hour", "one day".
_ARTICLE_QUANTITY = re.compile(
    r"\b(?:a|an|one)\s+(?:week|fortnight|month|year|day|hour|minute)s?\b", re.IGNORECASE)
#: Common Telugu and Odia number words, matched as word prefixes. A false
#: match costs only a translation, which then shows as pending.
_INDIC_NUMBER_WORDS = (
    "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు", "ఎనిమిది", "తొమ్మిది", "పది",
    "ఇరవై", "ముప్పై", "నలభై", "యాభై", "అరవై", "డెబ్బై", "ఎనభై", "తొంభై",
    "వంద", "వెయ్యి", "వేల", "లక్ష", "కోటి", "సగం", "రెట్టింపు", "మూడింతలు", "పావు",
    "ଦୁଇ", "ତିନି", "ଚାରି", "ପାଞ୍ଚ", "ଛଅ", "ସାତ", "ଆଠ", "ନଅ", "ଦଶ",
    "କୋଡ଼ିଏ", "ତିରିଶ", "ଚାଳିଶ", "ପଚାଶ", "ଷାଠିଏ", "ସତୁରୀ", "ଅଶୀ", "ନବେ",
    "ଶହେ", "ହଜାର", "ଲକ୍ଷ", "କୋଟି", "ଅଧା", "ଦୁଇଗୁଣ", "ତିନିଗୁଣ", "ଚାରିଭାଗରୁ",
)
_TOKEN = re.compile(r"[^\s.,;:!?()\[\]{}\"'“”‘’/-]+")


def number_words_in(text: str) -> set[str]:
    """Numbers written as words, in English, Telugu or Odia."""
    found = {m.group(0).lower() for m in _ENGLISH_NUMBER_WORDS.finditer(text)}
    found |= {m.group(0) for m in _ROMAN_LABEL.finditer(text)}
    # ... unless the article joins a unit: "miles an hour" is a speed.
    for m in _ARTICLE_QUANTITY.finditer(text):
        before = text[:m.start()].split()
        if not (before and re.sub(r"\W", "", before[-1].lower()) in _UNIT_OF):
            found.add(m.group(0).lower())
    # A word glued to digits ("10లక్షల", 10 lakh) is still a word.
    for token in _TOKEN.findall(normalise_digits(text)):
        for piece in re.split(r"\d+", token):
            found |= {w for w in _INDIC_NUMBER_WORDS if piece.startswith(w)}
    return found
