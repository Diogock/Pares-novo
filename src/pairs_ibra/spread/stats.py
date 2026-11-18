"""Estatísticas do spread (CLAUDE.md, seção 5.3)."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]


def fit_hedge(y: Array, x: Array) -> tuple[float, float, Array]:
    """OLS ``y = α + γ·x + ε``. Retorna (α, γ, ε)."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    xm, ym = x.mean(), y.mean()
    dx = x - xm
    var = float(dx @ dx)
    if var == 0:
        return float("nan"), float("nan"), np.full_like(y, np.nan)
    gamma = float(dx @ (y - ym)) / var
    alpha = ym - gamma * xm
    return float(alpha), gamma, y - alpha - gamma * x


def spread(log_a: Array, log_b: Array, gamma: float, alpha: float) -> Array:
    """ε_t = ln P_A − γ·ln P_B − α."""
    return np.asarray(log_a, dtype=float) - gamma * np.asarray(log_b, dtype=float) - alpha


def half_life(e: Array) -> float:
    """Meia-vida OU: Δε_t = a + b·ε_{t−1} + u ; HL = −ln2 / ln(1 + b). ``inf`` se b ≥ 0."""
    e = np.asarray(e, dtype=float)
    lag = e[:-1]
    d = np.diff(e)
    lm = lag - lag.mean()
    var = float(lm @ lm)
    if var == 0:
        return math.inf
    b = float(lm @ (d - d.mean())) / var
    if b >= 0 or b <= -1:
        return math.inf if b >= 0 else 0.0
    return -math.log(2.0) / math.log(1.0 + b)


def hurst_exponent(e: Array, max_lag: int = 20) -> float:
    """Hurst pelo escalonamento do desvio dos incrementos: std(ε_{t+k} − ε_t) ∝ k^H.

    Passeio aleatório ≈ 0,5; reversão à média < 0,5.
    """
    e = np.asarray(e, dtype=float)
    max_lag = min(max_lag, len(e) // 4)
    lags = np.arange(2, max_lag + 1)
    tau = np.array([np.std(e[k:] - e[:-k]) for k in lags])
    ok = tau > 0
    if ok.sum() < 3:
        return float("nan")
    slope = np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0]
    return float(slope)


def mean_crossings(e: Array) -> int:
    """Número de vezes que o spread cruza a própria média."""
    e = np.asarray(e, dtype=float)
    s = np.sign(e - e.mean())
    s = s[s != 0]
    return int(np.sum(s[1:] != s[:-1]))


def zscore_fixed(e: Array, mu: float, sigma: float) -> Array:
    return (np.asarray(e, dtype=float) - mu) / sigma


class EwmaZ:
    """z-score com média e variância EWMA causais: z_t usa estimativas até t−1."""

    def __init__(self, mu: float, sigma: float, lam: float) -> None:
        self.mean = mu
        self.var = sigma * sigma
        self.lam = lam

    def update(self, e: float) -> float:
        z = (e - self.mean) / math.sqrt(self.var) if self.var > 0 else float("nan")
        if math.isfinite(e):
            d = e - self.mean
            self.mean += (1 - self.lam) * d
            self.var = self.lam * self.var + (1 - self.lam) * d * d
        return z
