"""Seleção por distância (Perlin, 2009): menor SSD entre preços normalizados (base 1).

Os ``distance_candidates`` pares de menor SSD (após o pré-filtro de correlação/setor)
são ranqueados pelo Sharpe in-sample. O spread usa γ = 1 em log-preços normalizados:
ε = ln(P_A/P_A0) − ln(P_B/P_B0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pairs_ibra.config import Config
from pairs_ibra.selection.base import PairSpec, formation_window, issuer_of, sector_of
from pairs_ibra.selection.cointegration import candidate_pairs
from pairs_ibra.selection.scoring import sharpe_score, simulate_rule
from pairs_ibra.spread.stats import half_life


class DistanceSelector:
    method = "distance"

    def select(self, log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
               cfg: Config, sectors: pd.DataFrame) -> list[PairSpec]:
        window = formation_window(log_prices, universe, asof, cfg.windows.formation_days)
        if window.shape[0] < cfg.windows.formation_days or window.shape[1] < 2:
            return []
        norm = np.exp(window - window.iloc[0])
        pairs = candidate_pairs(window, cfg, sectors)
        ssd = [(float(((norm[a] - norm[b]) ** 2).sum()), a, b) for a, b in pairs]
        ssd.sort()
        specs: list[PairSpec] = []
        for d, a, b in ssd[: cfg.selection.distance_candidates]:
            la, lb = window[a].to_numpy(), window[b].to_numpy()
            alpha = float(la[0] - lb[0])
            e = la - lb - alpha
            mu, sigma = float(e.mean()), float(e.std(ddof=1))
            if sigma <= 0:
                continue
            daily, ntr = simulate_rule(la, lb, 1.0, alpha, mu, sigma, cfg)
            sa, sb = sector_of(sectors, a), sector_of(sectors, b)
            specs.append(PairSpec(
                leg_a=a, leg_b=b, gamma=1.0, alpha=alpha, mu=mu, sigma=sigma, half_life=half_life(e),
                method=self.method, formation_start=window.index[0], formation_end=window.index[-1],
                same_issuer=issuer_of(sectors, a) == issuer_of(sectors, b),
                same_sector=(sa == sb and sa != "SEM_SETOR"), score=sharpe_score(daily),
                sector_a=sa, sector_b=sb, pvalue=d, n_trades_in_sample=ntr,
            ))
        specs.sort(key=lambda s: s.score, reverse=True)
        return specs
