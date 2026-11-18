"""Testes de raiz unitária e cointegração (ADF, PP, KPSS, Johansen)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from arch.unitroot import KPSS, PhillipsPerron
from statsmodels.tsa.adfvalues import mackinnonp
from statsmodels.tsa.stattools import adfuller

Array = npt.NDArray[np.float64]


def adf_stat(x: Array, lags: int) -> float:
    """Estatística t do ADF com constante e ``lags`` defasagens fixas (OLS em numpy).

    Δx_t = c + ρ·x_{t-1} + Σ φ_i·Δx_{t-i} + u_t ; retorna t(ρ).
    Equivalente a ``adfuller(x, maxlag=lags, autolag=None, regression='c')``.
    """
    x = np.asarray(x, dtype=float)
    dx = np.diff(x)
    n = len(dx) - lags
    if n <= lags + 3:
        return float("nan")
    y = dx[lags:]
    cols = [x[lags:-1], np.ones(n)]
    for k in range(1, lags + 1):
        cols.append(dx[lags - k: len(dx) - k])
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - X.shape[1]
    s2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(s2 * xtx_inv[0, 0])
    return float(beta[0] / se)


def adf_pvalue(x: Array, lags: int, n_vars: int = 1) -> float:
    """p-valor do ADF. ``n_vars=2`` usa a distribuição de Engle-Granger (resíduo de cointegração)."""
    stat = adf_stat(x, lags)
    if not np.isfinite(stat):
        return 1.0
    return float(mackinnonp(stat, regression="c", N=n_vars))


def adf_pvalue_auto(x: Array) -> float:
    """ADF com escolha de defasagem por AIC (para teste de I(1) de cada ativo)."""
    return float(adfuller(np.asarray(x, dtype=float), regression="c", autolag="AIC", result_object=False)[1])


def pp_pvalue(x: Array) -> float:
    return float(PhillipsPerron(np.asarray(x, dtype=float), trend="c").pvalue)


def kpss_pvalue(x: Array) -> float:
    """p-valor do KPSS (H0: estacionário). Passa no teste quando p > nível."""
    return float(KPSS(np.asarray(x, dtype=float), trend="c").pvalue)


def is_integrated_order_one(x: Array, pvalue: float) -> bool:
    """Nível com raiz unitária (não rejeita) e primeira diferença estacionária (rejeita)."""
    x = np.asarray(x, dtype=float)
    return adf_pvalue_auto(x) > pvalue and adf_pvalue_auto(np.diff(x)) <= pvalue


def stationarity_votes(resid: Array, tests: Sequence[str], pvalue: float, lags: int,
                       coint: bool = True, adf_p: float | None = None) -> int:
    """Quantos testes indicam resíduo estacionário ao nível ``pvalue``."""
    votes = 0
    for t in tests:
        if t == "adf":
            p = adf_p if adf_p is not None else adf_pvalue(resid, lags, 2 if coint else 1)
            votes += p <= pvalue
        elif t == "pp":
            votes += pp_pvalue(resid) <= pvalue
        elif t == "kpss":
            votes += kpss_pvalue(resid) > pvalue
        else:
            raise ValueError(f"teste desconhecido: {t}")
    return int(votes)


def johansen_trace(log_prices: Array, det_order: int = 0, k_ar_diff: int = 1) -> tuple[float, float]:
    """Estatística traço do Johansen para r=0 e valor crítico a 5%."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    res = coint_johansen(np.asarray(log_prices, dtype=float), det_order, k_ar_diff)
    return float(res.lr1[0]), float(res.cvt[0, 1])
