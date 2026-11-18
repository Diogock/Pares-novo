"""Sizing dos pares (CLAUDE.md, seção 5.5).

Cada perna recebe, em média, ``leg_pct_nav`` do NAV: o bruto do par é
``2 × leg_pct_nav × NAV``. A divisão entre as pernas depende do modo:

- ``gamma``: valor de B = γ × valor de A (bruto preservado: A = 2/(1+γ), B = 2γ/(1+γ));
- ``dollar``: pernas iguais em R$;
- ``beta``: neutro em beta contra o IBRA (β_A·V_A = β_B·V_B).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from pairs_ibra.config import SizingConfig


def leg_weights(mode: str, gamma: float, beta_a: float = 1.0, beta_b: float = 1.0) -> tuple[float, float]:
    """Pesos (w_A, w_B) com w_A + w_B = 2, aplicados sobre ``leg_pct_nav × NAV``."""
    if mode == "gamma":
        return 2.0 / (1.0 + gamma), 2.0 * gamma / (1.0 + gamma)
    if mode == "dollar":
        return 1.0, 1.0
    if mode == "beta":
        if not (math.isfinite(beta_a) and math.isfinite(beta_b)) or beta_a <= 0 or beta_b <= 0:
            return 1.0, 1.0
        s = beta_a + beta_b
        return 2.0 * beta_b / s, 2.0 * beta_a / s
    raise ValueError(f"sizing.mode desconhecido: {mode}")


def round_to_lot(notional: float, raw_price: float, lot: int) -> float:
    """Arredonda o notional para lotes inteiros pelo preço sem ajuste. 0 se < 1 lote."""
    if not math.isfinite(raw_price) or raw_price <= 0:
        return notional
    lots = round(notional / (raw_price * lot))
    return float(lots * lot * raw_price)


def pair_notionals(nav: float, cfg: SizingConfig, gamma: float, raw_a: float, raw_b: float,
                   beta_a: float = 1.0, beta_b: float = 1.0) -> tuple[float, float]:
    """Notional (R$, positivo) de cada perna, já arredondado para lote."""
    wa, wb = leg_weights(cfg.mode, gamma, beta_a, beta_b)
    base = cfg.leg_pct_nav * nav
    return (round_to_lot(wa * base, raw_a, cfg.lot_size),
            round_to_lot(wb * base, raw_b, cfg.lot_size))


def rolling_beta(returns: pd.DataFrame, index_returns: pd.Series, window: int) -> pd.Series:
    """β de cada ativo contra o índice na janela informada (última linha = data mais recente)."""
    r = returns.iloc[-window:]
    m = index_returns.reindex(r.index)
    ok = m.notna()
    r, m = r.loc[ok], m.loc[ok]
    var = float(np.var(m.to_numpy(), ddof=1)) if len(m) > 2 else float("nan")
    if not var or not math.isfinite(var):
        return pd.Series(np.nan, index=returns.columns)
    cov = pd.Series({c: float(r[c].cov(m)) for c in r.columns})
    return cov / var
