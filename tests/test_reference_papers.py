"""Acceptance tests on the real reference papers (spec: Testfälle).

The PDFs are not in the repository. Drop them into tests/fixtures/ (see
tests/fixtures/README.md) together with hand-written Figure Cards and the
reference CSVs, then implement these tests.
"""

from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
BASTVIKEN = FIX / "Bastviken2008.pdf"
BLEES = FIX / "Blees2014.pdf"


@pytest.mark.skipif(not BASTVIKEN.exists(), reason="Bastviken2008.pdf not provided")
def test_bastviken_fig2_counts():
    """Main panels: Paul 151, Peter 208, Hummingbird 59; insets: Paul 75, Peter 89.
    Values within +-1 umol/L (Peter +-2) of the reference sheet."""
    pytest.skip("TODO: add Figure Card fixtures/Bastviken2008_fig2.json and reference CSV")


@pytest.mark.skipif(not BASTVIKEN.exists(), reason="Bastviken2008.pdf not provided")
def test_bastviken_fig2_legend():
    """Paul 11, Peter 10, Hummingbird 6 series; DOY with year 2001."""
    pytest.skip("TODO")


@pytest.mark.skip(reason="stage 5 (raster) not implemented; Blees2014.pdf not provided")
def test_blees_fig1_raster():
    """44 CH4, 40 d13C, 25 MOR values after WPD correction, plus axis points."""


@pytest.mark.skip(reason="needs Figure Card with text_checks for Blees2014 (p. 315, Results)")
def test_blees_text_checks():
    """near-bottom 40-160 umol/L CH4; sediment from 20 cm ~5 mmol/L."""


@pytest.mark.skip(reason="stage 5 (raster) not implemented")
def test_blees_axis_break_open_question():
    """one tick after the break -> open question, no invented values."""
