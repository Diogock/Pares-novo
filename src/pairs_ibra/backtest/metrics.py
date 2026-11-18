"""Métricas de desempenho (CLAUDE.md, seção 6.1). Sharpe sobre o capital (NAV)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from pairs_ibra.backtest.costs import DAYS_PER_YEAR


def drawdown(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def max_drawdown_duration(nav: pd.Series) -> int:
    """Maior número de pregões abaixo do pico anterior."""
    under = (nav < nav.cummax()).to_numpy()
    longest = run = 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    return int(longest)


def performance(nav: pd.Series, cdi_daily: pd.Series,
                benchmarks: dict[str, pd.Series] | None = None) -> dict[str, float]:
    """Retorno total e em excesso de CDI, vol, Sharpe, Sortino, drawdown, beta e correlação."""
    nav = nav.dropna()
    r = nav.pct_change().iloc[1:]
    cdi = cdi_daily.reindex(r.index).fillna(0.0)
    n = len(r)
    out: dict[str, float] = {"days": float(n)}
    if n < 2:
        return out
    years = n / DAYS_PER_YEAR
    v = nav.to_numpy(dtype=float)
    growth = float(v[-1] / v[0])
    cdi_growth = float(np.prod(1 + cdi.to_numpy(dtype=float)))
    ex = r - cdi
    sd = float(ex.std(ddof=1))
    downside = ex[ex < 0]
    dsd = float(np.sqrt((downside ** 2).sum() / n)) if len(downside) else float("nan")
    out.update({
        "return_total": growth - 1,
        "return_ann": growth ** (1 / years) - 1,
        "cdi_ann": cdi_growth ** (1 / years) - 1,
        "excess_ann": (growth / cdi_growth) ** (1 / years) - 1,
        "vol_ann": float(r.std(ddof=1)) * math.sqrt(DAYS_PER_YEAR),
        "sharpe": float(ex.mean()) / sd * math.sqrt(DAYS_PER_YEAR) if sd > 0 else float("nan"),
        "sortino": float(ex.mean()) / dsd * math.sqrt(DAYS_PER_YEAR) if dsd and dsd > 0 else float("nan"),
        "max_drawdown": float(drawdown(nav).min()),
        "max_dd_days": float(max_drawdown_duration(nav)),
    })
    for name, px in (benchmarks or {}).items():
        br = px.reindex(nav.index).pct_change(fill_method=None).reindex(r.index)
        ok = br.notna() & r.notna()
        if ok.sum() > 20:
            var = float(br[ok].var())
            out[f"beta_{name}"] = float(r[ok].cov(br[ok]) / var) if var > 0 else float("nan")
            out[f"corr_{name}"] = float(r[ok].corr(br[ok]))
    return out


def trade_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"n_trades": 0.0}
    out = {
        "n_trades": float(len(trades)),
        "hit_rate": float((trades["net_pnl"] > 0).mean()),
        "avg_return_trade": float(trades["return_on_leg"].mean()),
        "avg_days_open": float(trades["days_open"].mean()),
        "net_pnl": float(trades["net_pnl"].sum()),
        "gross_pnl": float(trades["gross_pnl"].sum()),
        "trading_costs": float(trades["trading_costs"].sum()),
        "btc_costs": float(trades["btc_costs"].sum()),
    }
    gross = out["gross_pnl"]
    costs = out["trading_costs"] + out["btc_costs"]
    out["cost_pct_gross"] = costs / gross if gross > 0 else float("nan")
    for reason, frac in trades["exit_reason"].value_counts(normalize=True).items():
        out[f"exit_{reason}"] = float(frac)
    return out


def turnover_ann(nav: pd.DataFrame, trades: pd.DataFrame) -> float:
    """Giro anual: R$ negociado (entradas + saídas) / NAV médio / anos."""
    if trades.empty or len(nav) < 2:
        return 0.0
    traded = 2.0 * float(trades["entry_gross"].sum())
    years = len(nav) / DAYS_PER_YEAR
    return traded / float(nav["nav"].mean()) / years


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby(by)
    return pd.DataFrame({
        "n_trades": g.size(),
        "hit_rate": g["net_pnl"].apply(lambda s: (s > 0).mean()),
        "avg_return_trade": g["return_on_leg"].mean(),
        "net_pnl": g["net_pnl"].sum(),
        "avg_days_open": g["days_open"].mean(),
    })


def period_table(nav: pd.Series, cdi: pd.Series, periods: list[tuple[str, pd.Timestamp, pd.Timestamp]],
                 benchmarks: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    rows = {}
    for name, a, b in periods:
        s = nav.loc[(nav.index >= a) & (nav.index <= b)]
        if len(s) > 2:
            rows[name] = performance(s, cdi, benchmarks)
    return pd.DataFrame(rows).T


def summary(result: Any) -> dict[str, Any]:
    """Todas as métricas de uma rodada (dicionário aninhado)."""
    cfg = result.config
    nav = result.nav
    m = result.market
    bench = {"ibov": m["ibov_close"], "ibra": m["ibra_close"]} if m is not None else None
    out: dict[str, Any] = {
        "performance": performance(nav["nav"], nav["cdi_daily"], bench),
        "trades": trade_stats(result.trades),
        "turnover_ann": turnover_ann(nav, result.trades),
        "avg_gross_exposure": float((nav["gross"] / nav["nav"]).mean()),
        "avg_positions": float(nav["n_positions"].mean()),
    }
    periods = []
    for a, b in cfg.backtest.subperiods:
        ta = pd.Timestamp(a)
        tb = pd.Timestamp(b) if b else nav.index.max()
        periods.append((f"{ta.year}-{tb.year}", ta, tb))
    out["subperiods"] = period_table(nav["nav"], nav["cdi_daily"], periods, bench)
    cal_end = pd.Timestamp(cfg.backtest.calibration_end)
    oos = pd.Timestamp(cfg.backtest.oos_start)
    out["calibration_oos"] = period_table(
        nav["nav"], nav["cdi_daily"],
        [("calibracao", nav.index.min(), cal_end), ("oos", oos, nav.index.max())], bench)
    t = result.trades
    if not t.empty:
        t = t.assign(tipo=np.where(t["same_issuer"], "mesmo_emissor", "demais"),
                     setor_par=np.where(t["same_sector"], "intra_setor", "cross_setor"))
        out["by_issuer"] = breakdown(t, "tipo")
        out["by_sector_type"] = breakdown(t, "setor_par")
        out["by_sector"] = breakdown(t, "sector_a")
        out["by_exit"] = breakdown(t, "exit_reason")
    return out
