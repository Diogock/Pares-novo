"""Universo elegível point-in-time (CLAUDE.md, seção 3).

Em ``asof`` (pregão de índice ``i``), a ação é elegível se:
- pertence ao IBRA em ``asof`` (carteira vigente, publicada antes);
- volume financeiro médio dos últimos ``adtv_window`` pregões **antes** de ``asof`` ≥ mínimo;
- negociou em ≥ ``min_trading_days_pct`` dos pregões da janela de formação;
- preço sem ajuste no último pregão antes de ``asof`` ≥ ``min_price``;
- taxa de aluguel ≤ ``max_btc_rate`` (sem base histórica: usa o fallback).

Nenhum dado com data ≥ ``asof`` é usado, exceto a composição do índice.
"""

from __future__ import annotations

import pandas as pd

from pairs_ibra.config import Config
from pairs_ibra.data.loaders import Dataset


def eligible_universe(ds: Dataset, asof: pd.Timestamp, cfg: Config) -> list[str]:
    dates = ds.dates
    i = int(dates.searchsorted(asof))
    if i >= len(dates) or dates[i] != asof:
        raise ValueError(f"{asof} não é pregão do dataset")
    F = cfg.windows.formation_days
    if i < F:
        return []
    u = cfg.universe
    lo = i - F
    members = ds.in_index.iloc[i]
    traded = ds.traded.iloc[lo:i]
    pct = traded.mean()
    a = max(0, i - u.adtv_window)
    adtv = ds.turnover.iloc[a:i].where(ds.traded.iloc[a:i]).fillna(0.0).mean()
    last_raw = ds.close_raw.iloc[i - 1]
    btc_ok = cfg.costs.btc_fallback_rate <= u.max_btc_rate
    ok = (
        members.astype(bool)
        & (pct >= u.min_trading_days_pct)
        & (adtv >= u.min_adtv_brl)
        & (last_raw >= u.min_price)
        & ds.close_adj.iloc[i - 1].notna()
    )
    if not btc_ok:
        return []
    return sorted(ok.index[ok.fillna(False).astype(bool)].tolist())
