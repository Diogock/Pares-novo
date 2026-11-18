from __future__ import annotations

import math

import numpy as np
import pytest
from statsmodels.tsa.stattools import adfuller

from pairs_ibra.spread.stats import (
    EwmaZ,
    fit_hedge,
    half_life,
    hurst_exponent,
    mean_crossings,
    zscore_fixed,
)
from pairs_ibra.spread.tests import (
    adf_pvalue,
    adf_stat,
    is_integrated_order_one,
    johansen_trace,
    kpss_pvalue,
    pp_pvalue,
    stationarity_votes,
)


def ar1(phi: float, n: int, seed: int = 0, sd: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sd, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x


def rw(n: int, seed: int = 1) -> np.ndarray:
    return np.cumsum(np.random.default_rng(seed).normal(0, 1, n))


@pytest.mark.parametrize("hl", [3.0, 10.0, 25.0])
def test_half_life_recovers_known_ou(hl: float) -> None:
    phi = 0.5 ** (1 / hl)
    x = ar1(phi, 20_000, seed=3)
    assert half_life(x) == pytest.approx(hl, rel=0.1)


def test_half_life_random_walk_is_large() -> None:
    assert half_life(rw(5000)) > 100


def test_half_life_explosive_is_inf() -> None:
    x = np.cumprod(np.full(100, 1.05))
    assert math.isinf(half_life(x))


def test_hurst() -> None:
    assert hurst_exponent(rw(5000)) == pytest.approx(0.5, abs=0.05)
    assert hurst_exponent(ar1(0.8, 5000)) < 0.3


def test_mean_crossings() -> None:
    assert mean_crossings(np.array([1.0, -1, 1, -1, 1])) == 4
    assert mean_crossings(np.arange(10.0)) == 1


def test_fit_hedge_known() -> None:
    rng = np.random.default_rng(0)
    x = rw(1000)
    y = 0.3 + 1.7 * x + rng.normal(0, 0.01, 1000)
    a, g, e = fit_hedge(y, x)
    assert g == pytest.approx(1.7, abs=1e-3)
    assert a == pytest.approx(0.3, abs=0.02)
    assert abs(e.mean()) < 1e-9


def test_adf_stat_matches_statsmodels() -> None:
    x = ar1(0.95, 500, seed=5)
    for lags in (0, 1, 3):
        ref = adfuller(x, maxlag=lags, autolag=None, regression="c", result_object=False)[0]
        assert adf_stat(x, lags) == pytest.approx(ref, rel=1e-8)


def test_unit_root_tests_discriminate() -> None:
    st, nst = ar1(0.7, 500), rw(500)
    assert adf_pvalue(st, 1) < 0.01 and adf_pvalue(nst, 1) > 0.05
    assert pp_pvalue(st) < 0.01 and pp_pvalue(nst) > 0.05
    assert kpss_pvalue(st) > 0.05 and kpss_pvalue(nst) < 0.05
    assert stationarity_votes(st, ["adf", "pp", "kpss"], 0.05, 1, coint=False) == 3
    assert stationarity_votes(nst, ["adf", "pp", "kpss"], 0.05, 1, coint=False) == 0


def test_engle_granger_pvalue_is_more_conservative() -> None:
    x = ar1(0.9, 300, seed=11)
    assert adf_pvalue(x, 1, n_vars=2) > adf_pvalue(x, 1, n_vars=1)


def test_integrated_order_one() -> None:
    assert is_integrated_order_one(rw(500, seed=4), 0.05)
    assert not is_integrated_order_one(ar1(0.5, 500), 0.05)


def test_johansen_detects_cointegration() -> None:
    x = rw(1000)
    y = 2 * x + ar1(0.5, 1000, seed=9)
    stat, crit = johansen_trace(np.column_stack([y, x]))
    assert stat > crit


def test_zscores() -> None:
    assert list(zscore_fixed(np.array([1.0, 3.0]), 1.0, 2.0)) == [0.0, 1.0]
    tr = EwmaZ(0.0, 1.0, 0.97)
    assert tr.update(2.0) == pytest.approx(2.0)   # usa só estimativas anteriores
    assert tr.mean > 0
