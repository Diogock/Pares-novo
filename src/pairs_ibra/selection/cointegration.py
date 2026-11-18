"""Seleção por cointegração (CLAUDE.md, seção 5.2).

A. pré-filtro: correlação de retornos ≥ ``min_corr`` (e mesmo setor, se configurado);
B. log-preços I(1); regressão ln P_A = α + γ ln P_B + ε nos dois sentidos, fica a ordem
   de menor p-valor (Engle-Granger); resíduo estacionário em ≥ ``min_tests_passed``
   de ADF/PP/KPSS; γ dentro de ``gamma_bounds``;
C. meia-vida, Hurst e cruzamentos da média;
D. score = Sharpe in-sample da regra, líquido de custos.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from pairs_ibra.config import Config
from pairs_ibra.selection.base import PairSpec, formation_window, issuer_of, sector_of
from pairs_ibra.selection.scoring import sharpe_score, simulate_rule
from pairs_ibra.spread.stats import fit_hedge, half_life, hurst_exponent, mean_crossings
from pairs_ibra.spread.tests import adf_pvalue, is_integrated_order_one, stationarity_votes

log = logging.getLogger(__name__)


def candidate_pairs(window: pd.DataFrame, cfg: Config, sectors: pd.DataFrame) -> list[tuple[str, str]]:
    """Pares (i<j) que passam no pré-filtro de correlação e, opcionalmente, de setor."""
    rets = window.diff().iloc[1:]
    corr = np.corrcoef(rets.to_numpy().T)
    cols = list(window.columns)
    out = []
    sel = cfg.selection
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr[i, j]
            if not math.isfinite(c) or c < sel.min_corr or c > 0.9999:
                continue
            if sel.same_sector:
                sa, sb = sector_of(sectors, cols[i]), sector_of(sectors, cols[j])
                if sa != sb or sa == "SEM_SETOR":
                    continue
            out.append((cols[i], cols[j]))
    return out


class CointegrationSelector:
    method = "cointegration"

    def select(self, log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
               cfg: Config, sectors: pd.DataFrame) -> list[PairSpec]:
        sel = cfg.selection
        window = formation_window(log_prices, universe, asof, cfg.windows.formation_days)
        if window.shape[0] < cfg.windows.formation_days or window.shape[1] < 2:
            return []
        i1 = [t for t in window.columns
              if not sel.require_i1 or is_integrated_order_one(window[t].to_numpy(), sel.pvalue)]
        window = window[i1]
        pairs = candidate_pairs(window, cfg, sectors)
        arr = {t: window[t].to_numpy() for t in window.columns}
        lo_g, hi_g = sel.gamma_bounds
        specs: list[PairSpec] = []
        for a, b in pairs:
            best: tuple[float, str, str, float, float, np.ndarray] | None = None
            for y, x in ((a, b), (b, a)):
                alpha, gamma, e = fit_hedge(arr[y], arr[x])
                if not (lo_g <= gamma <= hi_g):
                    continue
                p = adf_pvalue(e, sel.adf_lags, n_vars=2)
                if best is None or p < best[0]:
                    best = (p, y, x, alpha, gamma, e)
            if best is None:
                continue
            p, y, x, alpha, gamma, e = best
            hl = half_life(e)
            if not (sel.half_life.min <= hl <= sel.half_life.max):
                continue
            if mean_crossings(e) < sel.min_crossings:
                continue
            votes = stationarity_votes(e, sel.stationarity_tests, sel.pvalue, sel.adf_lags,
                                       coint=True, adf_p=p)
            if votes < sel.min_tests_passed:
                continue
            if not hurst_exponent(e) < sel.max_hurst:
                continue
            mu, sigma = float(e.mean()), float(e.std(ddof=1))
            daily, ntr = simulate_rule(arr[y], arr[x], gamma, alpha, mu, sigma, cfg)
            sa, sb = sector_of(sectors, y), sector_of(sectors, x)
            specs.append(PairSpec(
                leg_a=y, leg_b=x, gamma=gamma, alpha=alpha, mu=mu, sigma=sigma, half_life=hl,
                method=self.method, formation_start=window.index[0], formation_end=window.index[-1],
                same_issuer=issuer_of(sectors, y) == issuer_of(sectors, x),
                same_sector=(sa == sb and sa != "SEM_SETOR"), score=sharpe_score(daily),
                sector_a=sa, sector_b=sb, pvalue=p, n_trades_in_sample=ntr,
            ))
        specs.sort(key=lambda s: s.score, reverse=True)
        log.info("%s: %d ativos, %d I(1), %d candidatos, %d aprovados",
                 asof.date(), len(universe), len(i1), len(pairs), len(specs))
        return specs


def residual_still_stationary(log_a: np.ndarray, log_b: np.ndarray, gamma: float, alpha: float,
                              cfg: Config) -> bool:
    """Reteste rolante de um par aberto, com o γ/α originais, na janela mais recente."""
    e = log_a - gamma * log_b - alpha
    sel = cfg.selection
    votes = stationarity_votes(e, sel.stationarity_tests, sel.pvalue, sel.adf_lags, coint=True)
    return votes >= sel.min_tests_passed
