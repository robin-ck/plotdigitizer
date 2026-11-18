import numpy as np
import pytest

from plotdigitizer.vector import Calibration, quantisation_step


def test_piecewise_uneven_ticks_exact_at_ticks():
    c = Calibration([100, 160.66, 220, 279.34], [0, 50, 100, 150])
    for p, v in zip([100, 160.66, 220, 279.34], [0, 50, 100, 150]):
        assert c(p) == pytest.approx(v)
    assert c(130.33) == pytest.approx(25)  # midpoint of first segment


def test_extrapolation_linear_from_end_segments():
    c = Calibration([0, 10, 30], [0, 1, 2])
    assert c(-10) == pytest.approx(-1)
    assert c(40) == pytest.approx(2.5)


def test_inverted_depth_axis():
    c = Calibration([300, 100], [20, 0])  # sorted internally
    assert c(200) == pytest.approx(10)
    assert c.inverse(5) == pytest.approx(150)


def test_log_axis_in_log_space():
    c = Calibration([0, 50, 100], [1, 10, 100], "log")
    assert c(25) == pytest.approx(10 ** 0.5)
    assert c(150) == pytest.approx(1000)
    assert c.inverse(10) == pytest.approx(50)


def test_residual_documents_uneven_spacing():
    assert Calibration([0, 10, 20], [0, 1, 2]).residual() == pytest.approx(0)
    assert Calibration([0, 10.66, 20], [0, 1, 2]).residual() > 0.3


def test_quantisation_step():
    rng = np.random.default_rng(0)
    v = np.round(rng.integers(100, 600, 200) * 0.66, 4)
    assert quantisation_step(v) == pytest.approx(0.66, abs=1e-3)
    assert quantisation_step(rng.uniform(0, 100, 200)) == 0.0
