"""Gemini 3.7 Flash as the drafting and translation layer.

What Gemini is allowed to do here: rewrite an advisory's prose so it reads the
way a department expects, and translate it into the region's language.

What it is not allowed to do: produce a number. Every wind speed, probability,
depth and count is computed in code and handed to the model as a fact to
cite. That rule is enforced below rather than requested in the prompt -- any
digit in the model's output that does not match a supplied fact causes that
field to be rejected and the template text kept, with a note the operator can
see. A prompt instruction can be ignored; a check cannot.

With no API key the drafter reports itself unavailable and advisories stay
template-drafted in English only. It never pretends to have translated.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from advisory.cap import LANGUAGE_NAMES, Advisory
from advisory.numbers import (
    bare_numbers_in,
    canonical,
    casualty_claims_in,
    certainty_claims_in,
    currency_in,
    number_words_in,
    numbers_in,
    odds_and_clock_times_in,
    other_numerals,
    quantities_in,
    roman_counts_in,
    unreadable_in,
)
from common.errors import reraise_bugs

#: The model the brief names. 3.8 Flash exists; the brief says 3.7.
MODEL = "gemini-3.7-flash"

#: A generate function takes a prompt and returns the model's JSON text. The
#: real one calls Gemini; tests pass a fake.
Generate = Callable[[str], str]


#: Where keys are read from, in the order they are tried. The second is a
#: fallback for when the first runs out of quota; it helps only if it belongs
#: to another Cloud project, since the free tier's quota is per project.
KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_2")


def api_keys() -> list[str]:
    """Every configured key, in the order to try them, each once."""
    keys: list[str] = []
    for name in KEY_VARS:
        key = os.environ.get(name, "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def api_key() -> str | None:
    keys = api_keys()
    return keys[0] if keys else None


def availability() -> tuple[bool, str]:
    """Whether drafting can run, and if not, why -- in the operator's terms."""
    if not api_keys():
        return False, "no Gemini API key (set GEMINI_API_KEY)"
    import importlib.util

    if importlib.util.find_spec("google.genai") is None:
        return False, "google-genai is not installed"
    return True, f"{MODEL} available"


@dataclass(frozen=True)
class Facts:
    """What the model may cite, as numbers and as numbers with their units,
    and the asset names it may repeat."""

    numbers: frozenset[str]
    quantities: frozenset[tuple[str, str]]
    names: frozenset[str] = frozenset()
    #: The numbers that may stand without a unit: those code itself wrote
    #: bare (counts like "3 assets", ordinals, ids). None: any of them.
    bare: frozenset[str] | None = None

    def without_names(self, text: str) -> str:
        """The text with the advisory's own asset names taken out.

        A name is a fact, digits and all: "220kV Purushotamapattinam",
        "NH516A" and "Seven Hills Hospital" are what OpenStreetMap calls
        those assets, not numbers the model made up. Each whole name goes,
        then each digit-bearing word of one, which survives transliteration
        when the rest of the name does not ("సబ్‌స్టేషన్ 201428299").

        The cost: a number that is part of a name may be repeated on its
        own ("201428299 households"). It is never accepted with a unit it
        was not computed in, and the officer approving reads the text.
        """
        words = {w for name in self.names for w in name.split() if any(c.isdigit() for c in w)}
        for name in sorted(self.names | words, key=len, reverse=True):
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " (asset) ", text)
        return text


def allowed_facts(advisory: Advisory) -> Facts:
    """Everything code already wrote or computed, with the unit it was in."""
    numbers: set[str] = set()
    quantities: set[tuple[str, str]] = set()
    bare: set[str] = set()
    names = frozenset(str(a["name"]) for a in advisory.assets if a.get("name"))
    # A name's own quantities are facts about that asset: "220kV ..." is a
    # 220 kV substation, however the model writes it.
    for name in names:
        quantities |= quantities_in(name)
    for text in (advisory.headline, advisory.instruction, advisory.ensemble_note):
        numbers |= numbers_in(text)
        quantities |= quantities_in(text)
        bare |= bare_numbers_in(text)
    for a in advisory.assets:
        pct = canonical(str(round(a["p_failure"] * 100)))
        numbers.add(pct)
        quantities.add((pct, "%"))
        for key, unit in (("wind_kmh", "km/h"), ("depth_m", "m"), ("rain_mm", "mm"),
                          ("consequence", None)):
            if a.get(key) is not None:
                value = canonical(str(a[key]))
                numbers.add(value)
                if unit:
                    quantities.add((value, unit))
                else:
                    bare.add(value)
    return Facts(frozenset(numbers), frozenset(quantities), names, frozenset(bare))


def allowed_numbers(advisory: Advisory) -> set[str]:
    """The numbers the model may cite (see `allowed_facts` for units)."""
    return set(allowed_facts(advisory).numbers)


def unverified(text: str, allowed: set[str] | Facts) -> set[str]:
    """Everything in the text that no supplied fact accounts for: numbers that
    were never computed, computed numbers given a different unit, and numbers
    spelled out in words or as other numerals, and money. How the text is
    read is in advisory/numbers.py."""
    facts = allowed if isinstance(allowed, Facts) else Facts(frozenset(allowed), frozenset())
    # Units are checked on the text as written, so a name's digits cannot
    # come back as a quantity; everything else on the text without names.
    bad: set[str] = set()
    if facts.quantities:
        bad |= {f"{n} {u}" for n, u in quantities_in(text) - facts.quantities}
    text = facts.without_names(text)
    bad |= numbers_in(text) - facts.numbers
    # A number code computed in a unit, written without one, is being used
    # for something else: 150 mm of rain as "150 households", a 77 km/h gust
    # as "77 hospitals", a 54% risk as "54 kW" (a unit no fact is in).
    if facts.bare is not None:
        bad |= {f"{n} without its unit" for n in
                (bare_numbers_in(text) & facts.numbers) - facts.bare}
    return (bad | number_words_in(text) | other_numerals(text) | currency_in(text)
            | unreadable_in(text) | odds_and_clock_times_in(text) | casualty_claims_in(text)
            | roman_counts_in(text) | certainty_claims_in(text))


def _facts(advisory: Advisory, key: str) -> dict[str, Any]:
    wanted = [lang for lang in advisory.requested_languages if lang != "en-IN"]
    return {
        "id": key,
        "recipient": advisory.recipient.name,
        "severity": advisory.severity,
        "headline": advisory.headline,
        "instruction": advisory.instruction,
        "ensemble_note": advisory.ensemble_note,
        "translate_into": [f"{LANGUAGE_NAMES.get(lang, lang)} ({lang})" for lang in wanted],
        "assets": [
            {k: a[k] for k in ("name", "asset_class", "p_failure", "wind_kmh",
                               "depth_m", "driver") if k in a}
            for a in advisory.assets
        ],
    }


def _prompt(advisories: list[Advisory]) -> str:
    """One prompt for a whole forecast cycle: every department's advisory.

    One request per cycle rather than per department keeps a full replay
    inside the free tier's daily request limit. Each advisory is still
    checked against its own facts only, so a number borrowed from another
    department's block is rejected like any other unsupported number.
    """
    blocks = [_facts(a, str(i)) for i, a in enumerate(advisories)]
    return f"""You are drafting cyclone preparedness advisories for Indian
government departments, one per department. Each will be reviewed and approved
by a named officer before anything is sent. They are an exercise, not official
IMD warnings.

For each advisory below, rewrite the headline and instruction so they read
clearly to that recipient: direct, specific, action-first, naming the actual
assets. Keep them short. Then translate its headline, instruction and
ensemble_note into each language in its translate_into list. Keep asset names
recognisable (transliterate, do not translate proper nouns).

HARD RULE: in each advisory use only numbers that appear in THAT advisory's
facts, exactly as given. Do not compute, round, estimate or add any number. If
a sentence would need a number that is not in the facts, write it without the
number.

ADVISORIES:
{json.dumps(blocks, ensure_ascii=False, indent=1)}

Reply with JSON only, in this shape, one entry per advisory id:
{{"advisories": [{{"id": "0", "headline": "...", "instruction": "...",
  "translations": [{{"language": "te-IN", "headline": "...",
                     "instruction": "...", "description": "..."}}]}}]}}"""


CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "gemini"


def _cached_generate(prompt: str) -> str:
    """Gemini's reply to this exact prompt, from disk when asked before.

    Replaying a storm re-issues the same prompts. Answering those from disk
    keeps re-runs free of quota and makes them reproducible: the same facts
    give the same approved text, not a fresh sample at temperature 0.2.
    """
    import hashlib

    key = hashlib.sha256(f"{MODEL}\n{prompt}".encode()).hexdigest()[:32]
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return path.read_text()
    text = _gemini_generate(prompt)
    # Only a reply that is a JSON object is kept. A truncated or malformed
    # one is returned for this cycle to reject, but not cached: kept, it
    # would be replayed on every later run of the same facts.
    try:
        keep = isinstance(json.loads(text), dict)
    except ValueError:
        keep = False
    if keep:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return text


def _gemini_generate(prompt: str) -> str:
    return _with_key_fallback(api_keys(), lambda key: _generate_with(key, prompt))


def _generate_with(key: str, prompt: str) -> str:
    from google import genai
    from google.genai import types

    # The SDK's types are partly unknown to the checker; the reply is checked
    # structurally below, so the client is treated as untyped here.
    client: Any = genai.Client(api_key=key)
    config = types.GenerateContentConfig(response_mime_type="application/json",
                                         temperature=0.2)
    response = _with_retries(lambda: client.models.generate_content(
        model=MODEL, contents=prompt, config=config))
    if not response.text:
        # A safety block or an empty candidate. Say so, rather than letting
        # json.loads fail on None somewhere downstream.
        raise ValueError("Gemini returned no text")
    return response.text


#: Waits between attempts, seconds. Overload (503) and rate limits (429) are
#: usually gone within a few seconds; anything else fails at once.
RETRY_WAITS = (2.0, 5.0, 12.0)


def _with_retries[T](call: Callable[[], T], waits: tuple[float, ...] = RETRY_WAITS,
                     sleep: Callable[[float], object] | None = None) -> T:
    """Run `call`, retrying only errors that are worth waiting out."""
    import time

    sleep = sleep or time.sleep
    for wait in (*waits, None):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - classified below
            code = getattr(exc, "code", None)
            transient = code in (429, 500, 502, 503, 504) and not _daily_quota(exc)
            if not transient or wait is None:
                raise
            sleep(wait)
    raise AssertionError("unreachable")


def _daily_quota(exc: Exception) -> bool:
    """A per-day quota: waiting seconds will not help, so do not retry."""
    return "PerDay" in str(exc)


class QuotaSpent(Exception):
    """Every configured key has used up its daily quota in this process."""


#: Keys whose daily quota ran out while this process ran. They are not tried
#: again, so a replay does not spend a request finding out once per cycle.
_SPENT: set[str] = set()


def _with_key_fallback[T](keys: list[str], call: Callable[[str], T],
                          spent: set[str] | None = None) -> T:
    """`call` with the first key whose quota is not spent, moving to the next
    key only when a quota refuses. Any other failure, such as an overloaded
    model, is the same for every key, so it is raised rather than spending
    the next key's quota on it."""
    spent = _SPENT if spent is None else spent
    usable = [k for k in keys if k not in spent]
    if not usable:
        raise QuotaSpent("every Gemini key has used its daily quota")
    last: Exception = QuotaSpent("every Gemini key has used its daily quota")
    for key in usable:
        try:
            return call(key)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _daily_quota(exc):
                spent.add(key)
            elif getattr(exc, "code", None) != 429:
                raise
            last = exc          # this key's quota refused; try the next
    raise last


def _failure_note(exc: Exception) -> str:
    if isinstance(exc, QuotaSpent):
        return "Gemini daily request quota reached on every key; template kept."
    if _daily_quota(exc):
        return "Gemini daily request quota reached; template kept."
    code = getattr(exc, "code", None)
    return (f"Gemini drafting failed ({type(exc).__name__}"
            f"{f' {code}' if code else ''}); template kept.")


def enhance(advisory: Advisory, generate: Generate | None = None) -> Advisory:
    """One advisory through Gemini. See `enhance_all`."""
    return enhance_all([advisory], generate)[0]


def enhance_all(advisories: list[Advisory], generate: Generate | None = None
                ) -> list[Advisory]:
    """Every advisory in a cycle, drafted in one request, checked one by one.

    Each field of each advisory is accepted or rejected on its own, so one
    invented number in a translation costs that translation, not the whole
    advisory. Anything rejected is recorded in `draft_notes` for the
    approving officer.
    """
    if not advisories:
        return []
    if generate is None:
        ok, reason = availability()
        if not ok:
            return [replace(a, draft_notes=[*a.draft_notes, f"Template text only: {reason}."])
                    for a in advisories]
        generate = _cached_generate

    try:
        data = json.loads(generate(_prompt(advisories)))
    except Exception as exc:  # noqa: BLE001 - any failure means keep the template
        reraise_bugs(exc)          # a bug is not a failed source
        note = _failure_note(exc)
        return [replace(a, draft_notes=[*a.draft_notes, note]) for a in advisories]

    # The reply is a list keyed by id; a single object is accepted for a
    # single advisory.
    by_id = _replies_by_id(data, len(advisories))
    out: list[Advisory] = []
    for i, advisory in enumerate(advisories):
        try:
            out.append(_apply(advisory, by_id.get(str(i), {})))
        except Exception as exc:  # noqa: BLE001 - one bad reply must not end the cycle
            reraise_bugs(exc)          # a bug is not a failed source
            out.append(replace(advisory, draft_notes=[
                *advisory.draft_notes,
                f"Gemini reply unusable ({type(exc).__name__}); template kept."]))
    return out


def _replies_by_id(data: object, count: int) -> dict[str, dict[str, Any]]:
    """Each advisory's part of the reply, by id. The reply is a list keyed by
    id; a single object is accepted when there is a single advisory."""
    reply = _as_dict(data)
    if isinstance(reply.get("advisories"), list):
        entries = (_as_dict(item) for item in _as_list(reply.get("advisories")))
        return {str(e.get("id")): e for e in entries if e}
    return {"0": reply} if reply and count == 1 else {}


def _as_dict(value: object) -> dict[str, Any]:
    """A JSON object from an untrusted reply, or an empty one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    """A JSON array from an untrusted reply, or an empty one."""
    return cast(list[object], value) if isinstance(value, list) else []


def _text(value: object) -> str:
    """A reply field as stripped text; anything that is not text is empty."""
    return value.strip() if isinstance(value, str) else ""


def _accept_english(data: dict[str, Any], allowed: Facts, notes: list[str]) -> dict[str, str]:
    """The rewritten headline and instruction that pass, by field."""
    accepted: dict[str, str] = {}
    for field in ("headline", "instruction"):
        value = data.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            notes.append(f"Rejected Gemini {field}: not text.")
            continue
        text = value.strip()
        bad = unverified(text, allowed)
        if bad:
            notes.append(f"Rejected Gemini {field}: cited {sorted(bad)} not in the computed facts.")
        elif text:
            accepted[field] = text
    return accepted


def _accept_translations(data: dict[str, Any], wanted: list[str], allowed: Facts,
                         notes: list[str]) -> dict[str, dict[str, str]]:
    """The translations that are complete and pass, by language."""
    accepted: dict[str, dict[str, str]] = {}
    for item in _as_list(data.get("translations")):
        t = _as_dict(item)
        lang = t.get("language")
        if not isinstance(lang, str) or lang not in wanted:
            continue
        fields = {k: _text(t.get(k)) for k in ("headline", "instruction", "description")}
        bad: set[str] = set()
        for value in fields.values():
            bad |= unverified(value, allowed)
        if not all(fields.values()):
            notes.append(f"Rejected {lang} translation: incomplete.")
        elif bad:
            notes.append(f"Rejected {lang} translation: cited {sorted(bad)} "
                         "not in the computed facts.")
        else:
            accepted[lang] = fields
    return accepted


def _apply(advisory: Advisory, data: object) -> Advisory:
    """Accept what passes the number check for this advisory; note the rest.

    The reply is untrusted: valid JSON of the wrong shape is refused field by
    field, never allowed to raise.
    """
    wanted = [lang for lang in advisory.requested_languages if lang != "en-IN"]
    allowed = allowed_facts(advisory)
    notes = list(advisory.draft_notes)
    reply = _as_dict(data)
    if not reply:
        notes.append("Gemini returned nothing for this advisory; template kept.")

    english = _accept_english(reply, allowed, notes)
    new_translations = _accept_translations(reply, wanted, allowed, notes)
    translations = {**advisory.translations, **new_translations}
    for lang in wanted:
        if lang not in translations:
            name = LANGUAGE_NAMES.get(lang, lang)
            notes.append(f"{name} text pending: not produced or not verified.")

    changed = bool(english or new_translations)
    return replace(
        advisory,
        headline=english.get("headline", advisory.headline),
        instruction=english.get("instruction", advisory.instruction),
        translations=translations,
        drafted_by=MODEL if changed else advisory.drafted_by,
        draft_notes=notes,
    )
