"""Sinal de tendência relativa (MODELOS.md §0.2 e §4.1).

Sobre a série relativa ``R`` de cada ativo (preço/CDI ou preço/IVVB11):

- **liga** quando ``MA_fast > MA_mid > MA_slow`` e ``R_t`` supera a máxima dos ``entry_high``
  pregões anteriores (Donchian);
- **desliga** quando ``MA_fast < MA_mid`` ou ``R_t`` fica abaixo da mínima dos ``exit_low``
  pregões anteriores.

O estado em *t* usa só dados até *t* (janelas que terminam em *t*). A execução é em *t+1*,
quem defasa é o motor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bdr_models.config import TrendConfig


def relative_series(px: pd.DataFrame, base: pd.Series) -> pd.DataFrame:
    """``R = P / base`` (base = índice CDI ou IVVB11 sintético)."""
    out: pd.DataFrame = px.div(base.reindex(px.index), axis=0)
    return out


def trend_conditions(r: pd.DataFrame, cfg: TrendConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Condições de entrada e de saída em cada data (booleanas; NaN vira False)."""
    ma_f = r.rolling(cfg.fast, min_periods=cfg.fast).mean()
    ma_m = r.rolling(cfg.mid, min_periods=cfg.mid).mean()
    ma_s = r.rolling(cfg.slow, min_periods=cfg.slow).mean()
    hi = r.rolling(cfg.entry_high, min_periods=cfg.entry_high).max().shift(1)
    lo = r.rolling(cfg.exit_low, min_periods=cfg.exit_low).min().shift(1)
    entry = (ma_f > ma_m) & (ma_m > ma_s) & (r > hi)
    exit_ = (ma_f < ma_m) | (r < lo)
    return entry.fillna(False).astype(bool), exit_.fillna(False).astype(bool)


def trend_state(r: pd.DataFrame, cfg: TrendConfig) -> pd.DataFrame:
    """Estado liga/desliga (histerese). Entrada e saída no mesmo dia: fica desligado."""
    entry, exit_ = trend_conditions(r, cfg)
    e = entry.to_numpy()
    x = exit_.to_numpy()
    valid = r.notna().to_numpy()
    state = np.zeros(e.shape, dtype=bool)
    on = np.zeros(e.shape[1], dtype=bool)
    for i in range(e.shape[0]):
        on = np.where(on, ~x[i], e[i] & ~x[i]) & valid[i]
        state[i] = on
    return pd.DataFrame(state, index=r.index, columns=r.columns)
