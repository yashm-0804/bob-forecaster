"""The CAP document an approving officer's decision rests on: who sent it and
to whom, that it is well-formed whatever the text holds, and that approval
is tied to every word read -- translations included."""

import xml.etree.ElementTree as ET
from dataclasses import replace

from advisory import cap
from tests.test_gemini import GOOD_TE, advisory

NS = {"c": cap.CAP_NS}


def _infos(adv):
    return ET.fromstring(adv.to_cap_xml()).findall("c:info", NS)


def test_a_changed_translation_changes_the_identifier():
    """Found in review: the translations could be dropped from the content
    fingerprint and every test still passed -- so an approval given to one
    Telugu text could carry over to another."""
    te = {k: v for k, v in GOOD_TE.items() if k != "language"}
    first = replace(advisory(), translations={"te-IN": te}).sealed()
    changed = replace(advisory(), translations={"te-IN": dict(te, headline="మోంథా: 72 గంటలు")}).sealed()
    assert first.identifier != changed.identifier
    assert first.identifier == replace(advisory(), translations={"te-IN": dict(te)}).sealed().identifier


def test_markup_in_any_text_still_gives_well_formed_cap_with_that_text():
    """Found in review: the escaping could be removed and every test still
    passed. Model text and asset names may hold & < > and quotes."""
    text = 'Peruru "A&B" <wing> & ICU'
    te = {"headline": f"తెలుగు {text}", "instruction": f"సూచన {text}", "description": f"వివరణ {text}"}
    adv = replace(advisory(), headline=text, instruction=text, ensemble_note=text,
                  area_desc=text, translations={"te-IN": te})
    en, telugu = _infos(adv)
    for field in ("headline", "instruction", "description"):
        assert en.findtext(f"c:{field}", namespaces=NS) == text
        assert telugu.findtext(f"c:{field}", namespaces=NS) == te[field]
    assert en.findtext("c:area/c:areaDesc", namespaces=NS) == text


def test_the_sender_is_the_originator_and_the_audience_the_recipient():
    """Found in review: <senderName> named the recipient. CAP 1.2 defines it
    as the originator; the intended recipients are the <audience>."""
    adv = advisory()
    for info in _infos(adv):
        assert info.findtext("c:senderName", namespaces=NS) == cap.SENDER_NAME
        assert info.findtext("c:audience", namespaces=NS) == adv.recipient.name


def test_info_elements_are_in_the_order_cap_1_2_requires():
    """The CAP 1.2 schema is a sequence: a validator rejects elements out of
    order. These are the ones this project emits, in the schema's order."""
    schema_order = ["language", "category", "event", "urgency", "severity", "certainty",
                    "audience", "senderName", "headline", "description", "instruction", "area"]
    for info in _infos(replace(advisory(), translations={"te-IN": {
            k: v for k, v in GOOD_TE.items() if k != "language"}})):
        tags = [child.tag.split("}")[1] for child in info]
        assert tags == sorted(tags, key=schema_order.index), tags
