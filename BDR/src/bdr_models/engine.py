"""Motor diário dos modelos BDR (MODELOS.md §0).

Linha do tempo de cada pregão *i*:

1. marcação a mercado das posições (preço sintético em R$) e do hedge, juros do caixa e aluguel;
2. execução, no fechamento de *i*, das ordens decididas no fechamento de *i−1*;
3. ajuste do hedge agregado (variantes ``ls_*``);
4. a estratégia olha o fechamento de *i* e devolve ordens para *i+1*.

As ordens são pesos-alvo (fração do NAV do dia da execução). Peso 0 zera a posição.
Posições sem ordem derivam com o preço.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from bdr_models.config import Config, Variant

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Order:
    ticker: str
    weight: float  # fração do NAV na execução; 0 = zerar
    reason: str


@dataclass
class BookView:
    """O que a estratégia enxerga no fechamento de *i* (já com as execuções do dia)."""

    i: int
    date: pd.Timestamp
    nav: float
    positions: dict[str, float]  # R$ por ticker (só comprado)


class Strategy(Protocol):
    def on_close(self, view: BookView) -> list[Order]: ...


@dataclass
class _Lot:
    entry_i: int
    entry_date: pd.Timestamp
    invested: float  # compras − vendas (R$)
    costs: float
    first_value: float
    reason_in: str


@dataclass
class Result:
    config: Config
    variant: Variant
    nav: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame  # longo: date, ticker, value
    meta: dict[str, object] = field(default_factory=dict)


def monthly_beta(beta: pd.DataFrame) -> pd.DataFrame:
    """Beta recalculado só no último pregão de cada mês e mantido no mês seguinte."""
    period = pd.DatetimeIndex(beta.index).to_period("M")
    last = ~period.duplicated(keep="last")
    out: pd.DataFrame = beta.where(pd.Series(last, index=beta.index), np.nan).ffill()
    return out


def run(
    cfg: Config,
    variant: Variant,
    strategy: Strategy,
    px: pd.DataFrame,
    hedge_px: pd.Series,
    cdi_daily: pd.Series,
    beta: pd.DataFrame | None = None,
) -> Result:
    """Simula a estratégia numa variante de hedge. ``px`` e ``hedge_px`` em R$ nos pregões B3."""
    c = cfg.costs
    dpy = c.days_per_year
    idx = pd.DatetimeIndex(px.index)
    tickers = list(px.columns)
    col = {t: j for j, t in enumerate(tickers)}
    P = px.to_numpy(dtype=float)
    H = hedge_px.reindex(idx).to_numpy(dtype=float)
    cdi = cdi_daily.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    B = beta.reindex(index=idx, columns=tickers).to_numpy(dtype=float) if beta is not None else None
    fallback = cfg.hedge.beta.fallback
    hedged = variant != "long_only"
    if hedged and np.isnan(H).all():
        raise ValueError("série do hedge vazia")

    cash = cfg.backtest.initial_nav
    pos: dict[str, float] = {}
    lots: dict[str, _Lot] = {}
    short = 0.0  # valor (positivo) vendido de IVVB11
    pending: list[Order] = []
    nav_rows: list[dict[str, float]] = []
    trades: list[dict[str, object]] = []
    pos_rows: list[tuple[pd.Timestamp, str, float]] = []
    cost_long = c.trade_bps_long / 1e4
    cost_hedge = c.trade_bps_hedge / 1e4

    def close_lot(t: str, i: int, proceeds: float, cost: float, reason: str) -> None:
        lot = lots.pop(t)
        lot.costs += cost
        pnl = proceeds - lot.invested - lot.costs
        trades.append(
            {
                "ticker": t,
                "entry_date": lot.entry_date,
                "exit_date": idx[i],
                "days_open": i - lot.entry_i,
                "entry_value": lot.first_value,
                "net_pnl": pnl,
                "return_on_entry": pnl / lot.first_value if lot.first_value else np.nan,
                "trading_costs": lot.costs,
                "entry_reason": lot.reason_in,
                "exit_reason": reason,
            }
        )

    for i in range(len(idx)):
        day_cost = day_borrow = day_interest = 0.0
        forced: list[str] = []
        if i > 0:
            for t in list(pos):
                j = col[t]
                p0, p1 = P[i - 1, j], P[i, j]
                if np.isnan(p1) or np.isnan(p0):
                    forced.append(t)  # sem preço: zera pelo último valor conhecido
                    continue
                pos[t] *= p1 / p0
            if short and not (np.isnan(H[i]) or np.isnan(H[i - 1])):
                short *= H[i] / H[i - 1]
            rate = cdi[i] - c.cash_spread_bps / 1e4 / dpy
            day_interest = cash * rate
            cash += day_interest
            day_borrow = short * c.borrow_rate_ann / dpy
            cash -= day_borrow
        for t in forced:
            v = pos.pop(t)
            cash += v  # sem custo: não há preço para negociar
            close_lot(t, i, v, 0.0, "dado_faltante")
        nav = cash + sum(pos.values()) - short

        traded_today = bool(forced)
        for o in pending:
            if o.ticker not in col or np.isnan(P[i, col[o.ticker]]):
                continue
            cur = pos.get(o.ticker, 0.0)
            target = o.weight * nav
            delta = target - cur
            if abs(delta) < 1e-9 * max(nav, 1.0):
                continue
            cost = abs(delta) * cost_long
            cash -= delta + cost
            day_cost += cost
            traded_today = True
            if cur == 0.0 and target > 0:
                lots[o.ticker] = _Lot(i, idx[i], delta, cost, delta, o.reason)
                pos[o.ticker] = target
            elif target <= 0:
                pos.pop(o.ticker, None)
                close_lot(o.ticker, i, -delta, cost, o.reason)
            else:
                pos[o.ticker] = target
                lots[o.ticker].invested += delta
                lots[o.ticker].costs += cost
        pending = []

        long_val = sum(pos.values())
        if hedged:
            if variant == "ls_beta":
                tgt = 0.0
                for t, v in pos.items():
                    b = B[i, col[t]] if B is not None else np.nan
                    tgt += v * (fallback if np.isnan(b) else b)
            else:
                tgt = long_val
            band = cfg.hedge.rebalance_band * long_val
            need = traded_today or abs(short - tgt) > band or (long_val == 0 and short > 0)
            if need and not np.isnan(H[i]):
                d = tgt - short
                cost = abs(d) * cost_hedge
                cash += d - cost  # vender mais IVVB11 gera caixa
                short = tgt
                day_cost += cost
        nav = cash + long_val - short

        nav_rows.append(
            {
                "nav": nav,
                "cash": cash,
                "long": long_val,
                "short": short,
                "net_usd": long_val - short,
                "n_positions": float(len(pos)),
                "trading_costs": day_cost,
                "borrow_costs": day_borrow,
                "cash_interest": day_interest,
                "cdi_daily": cdi[i],
            }
        )
        for t, v in pos.items():
            pos_rows.append((idx[i], t, v))

        view = BookView(i=i, date=idx[i], nav=nav, positions=dict(pos))
        pending = strategy.on_close(view) if i < len(idx) - 1 else []

    for t in list(pos):  # fim do período: fecha no papel, sem custo
        close_lot(t, len(idx) - 1, pos[t], 0.0, "fim_periodo")

    nav_df = pd.DataFrame(nav_rows, index=idx)
    trades_df = pd.DataFrame(trades)
    pos_df = pd.DataFrame(pos_rows, columns=["date", "ticker", "value"])
    return Result(cfg, variant, nav_df, trades_df, pos_df)
