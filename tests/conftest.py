import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import synthetic  # noqa: E402


@pytest.fixture(scope="session")
def journal(tmp_path_factory):
    d = tmp_path_factory.mktemp("journal")
    return synthetic.make_journal_pdf(d / "journal.pdf")


@pytest.fixture(scope="session")
def mpl(tmp_path_factory):
    d = tmp_path_factory.mktemp("mpl")
    return synthetic.make_mpl_pdf(d / "mpl.pdf")


@pytest.fixture(scope="session")
def journal_run(journal, tmp_path_factory):
    from plotdigitizer.pipeline import digitize
    pdf, card, exp = journal
    out = tmp_path_factory.mktemp("out_journal")
    return digitize(str(pdf), card, out), exp


@pytest.fixture(scope="session")
def mpl_run(mpl, tmp_path_factory):
    from plotdigitizer.pipeline import digitize
    pdf, card, exp = mpl
    out = tmp_path_factory.mktemp("out_mpl")
    return digitize(str(pdf), card, out), exp


@pytest.fixture(scope="session")
def rasterfig(tmp_path_factory):
    d = tmp_path_factory.mktemp("raster")
    return synthetic.make_raster_pdf(d / "raster.pdf")
