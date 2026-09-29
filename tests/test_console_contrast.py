"""Text colours in the console meet WCAG AA contrast (4.5:1 for small text)
against every panel background, computed from the page's own CSS variables."""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()


def var(name: str) -> str:
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert m, f"--{name} not defined"
    return m.group(1)


def luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted([luminance(a), luminance(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("text", ["ink", "ink-dim", "ink-faint"])
@pytest.mark.parametrize("background", ["bg", "panel", "panel-2"])
def test_text_meets_wcag_aa_on_every_panel(text, background):
    assert contrast(var(text), var(background)) >= 4.5
