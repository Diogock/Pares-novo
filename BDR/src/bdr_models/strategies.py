"""Estratégias: tendência setorial em ETFs (modelo 1) e single names com dividendos (modelo 2).

As duas recebem matrizes já calculadas (estado de tendência, DY, universo), alinhadas aos pregões,
e só leem a linha *i* em ``on_close`` (nada posterior a *i*).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from bdr_models.config import DividendModel, SectorModel
from bdr_models.engine import BookView, Order

NO_SECTOR = "SEM_SETOR"


def last_session_of_month(idx: pd.DatetimeIndex) -> np.ndarray:
    period = idx.to_period("M")
    out: np.ndarray = ~period.duplicated(keep="last")
    return out


class SectorStrategy:
    """Compra 1/n (n = ETFs no universo na data) de cada ETF com tendência ligada."""

    def __init__(self, state: pd.DataFrame, available: pd.DataFrame, cfg: SectorModel) -> None:
        self.tickers = list(state.columns)
        self.state = state.to_numpy(dtype=bool)
        self.avail = available.reindex_like(state).fillna(False).to_numpy(dtype=bool)
        self.month_end = last_session_of_month(pd.DatetimeIndex(state.index))
        self.cfg = cfg

    def on_close(self, view: BookView) -> list[Order]:
        i = view.i
        n = int(self.avail[i].sum())
        if n == 0:
            return [Order(t, 0.0, "fora_universo") for t in view.positions]
        w = 1.0 / n
        want = {t for j, t in enumerate(self.tickers) if self.state[i, j] and self.avail[i, j]}
        orders = [Order(t, 0.0, "saida_sinal") for t in view.positions if t not in want]
        rebalance = self.cfg.rebalance == "monthly" and bool(self.month_end[i])
        for t in sorted(want):
            if t not in view.positions:
                orders.append(Order(t, w, "entrada_sinal"))
            elif rebalance:
                orders.append(Order(t, w, "rebalanceamento"))
        return orders


@dataclass
class _Held:
    peak: float
    sector: str


@dataclass
class DividendStrategy:
    """Book de até ``n_slots`` papéis com DY alto e tendência; saída só por stop do relativo.

    - ``rel``: série relativa do stop (P / IVVB11), em R$.
    - ``state``: tendência ligada (entrada).
    - ``dy``: DY 12m em fração.
    - ``universe``: elegível na data (S&P 500 PIT ou lista BDR, sem REIT, com histórico).
    - ``sectors``: setor GICS por ticker (teto por setor).
    """

    rel: pd.DataFrame
    state: pd.DataFrame
    dy: pd.DataFrame
    universe: pd.DataFrame
    sectors: dict[str, str]
    cfg: DividendModel
    held: dict[str, _Held] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    cooldown_until: dict[str, int] = field(default_factory=dict)
    log: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        cols = self.rel.columns
        self.tickers = list(cols)
        self.R = self.rel.to_numpy(dtype=float)
        self.S = self.state.reindex(columns=cols).fillna(False).to_numpy(dtype=bool)
        self.D = self.dy.reindex(index=self.rel.index, columns=cols).to_numpy(dtype=float)
        uni = self.universe.reindex(index=self.rel.index, columns=cols).fillna(False)
        self.U = uni.to_numpy(dtype=bool)

    def sector(self, t: str) -> str:
        return self.sectors.get(t, NO_SECTOR) or NO_SECTOR

    def on_close(self, view: BookView) -> list[Order]:
        i, cfg = view.i, self.cfg
        col = {t: j for j, t in enumerate(self.tickers)}
        # 1. sincroniza com o que foi executado hoje
        for t in list(self.pending):
            if t in view.positions:
                self.held[t] = _Held(peak=self.R[i, col[t]], sector=self.sector(t))
        self.pending.clear()
        for t in list(self.held):
            if t not in view.positions:  # saiu por falta de dado
                del self.held[t]
        orders: list[Order] = []
        # 2. stop sobre o pico do relativo
        for t, h in list(self.held.items()):
            r = self.R[i, col[t]]
            if np.isnan(r):
                continue
            h.peak = max(h.peak, r)
            if r / h.peak - 1.0 <= -cfg.stop_drawdown:
                orders.append(Order(t, 0.0, "stop"))
                del self.held[t]
                self.cooldown_until[t] = i + 1 + cfg.cooldown_days
        # 3. vagas: maior DY entre os elegíveis
        free = cfg.n_slots - len(self.held)
        if free > 0:
            u = self.U[i] & ~np.isnan(self.D[i]) & ~np.isnan(self.R[i])
            if u.any():
                thr = float(np.quantile(self.D[i][u], cfg.dy_quantile))
                ok = u & self.S[i] & (self.D[i] > cfg.min_dy) & (self.D[i] >= thr)
                cand = [
                    j
                    for j in np.flatnonzero(ok)
                    if self.tickers[j] not in self.held
                    and self.cooldown_until.get(self.tickers[j], -1) <= i
                ]
                cand.sort(key=lambda j: -self.D[i, j])
                per_sector: dict[str, int] = {}
                for h in self.held.values():
                    per_sector[h.sector] = per_sector.get(h.sector, 0) + 1
                for j in cand:
                    if free == 0:
                        break
                    t = self.tickers[j]
                    s = self.sector(t)
                    if per_sector.get(s, 0) >= cfg.max_per_sector:
                        continue
                    orders.append(Order(t, cfg.slot_weight, "entrada"))
                    self.pending.add(t)
                    per_sector[s] = per_sector.get(s, 0) + 1
                    free -= 1
        self.log.append(
            {
                "date": view.date,
                "held": len(self.held),
                "new": len(self.pending),
                "stops": sum(o.reason == "stop" for o in orders),
            }
        )
        return orders
