"""Monta universo, sinais e betas, roda as variantes e calcula as métricas (MODELOS.md)."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from bdr_models.config import Config, Variant
from bdr_models.data import MarketData, rolling_beta
from bdr_models.engine import Result, Strategy, monthly_beta, run
from bdr_models.signals import relative_series, trend_state
from bdr_models.strategies import DividendStrategy, SectorStrategy
from pairs_ibra.backtest.metrics import performance
from pairs_ibra.data.loaders import normalize_ticker

log = logging.getLogger(__name__)


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def history_ok(px: pd.DataFrame, min_days: int) -> pd.DataFrame:
    """True a partir do ``min_days``-ésimo dia com preço de cada ativo (só passado)."""
    out: pd.DataFrame = px.notna().cumsum() >= max(min_days, 1)
    return out & px.notna()


def sector_universe(cfg: Config, md: MarketData) -> list[str]:
    rows = _read_csv(cfg.sector.etfs_file)
    keep = {"amplo"} if cfg.sector.universe == "amplo" else {"amplo", "completo"}
    tick = [normalize_ticker(r["etf_us"]) for r in rows if r["universo"] in keep]
    missing = [t for t in tick if t not in md.px_brl.columns]
    if missing:
        log.warning("ETFs sem preço no export (ignorados): %s", missing)
    return [t for t in tick if t in md.px_brl.columns]


def dividend_universe(cfg: Config, md: MarketData) -> pd.DataFrame:
    """Elegibilidade diária do modelo 2 (antes de DY e tendência)."""
    d = cfg.dividend
    hedge = normalize_ticker(cfg.data.hedge_ticker)
    etfs = {normalize_ticker(r["etf_us"]) for r in _read_csv(cfg.sector.etfs_file)}
    cols = [c for c in md.px_brl.columns if c != hedge and c not in etfs]
    px = md.px_brl[cols]
    base = history_ok(px, d.min_history_days)
    if d.universe == "spx_pit":
        if md.members is None:
            raise ValueError("dividend.universe=spx_pit exige data.files.spx_composition")
        mem = md.members.reindex(index=px.index, columns=cols).fillna(False).astype(bool)
        base &= mem
    else:
        lst = {normalize_ticker(r["lastro"]) for r in _read_csv(d.bdr_list_file)}
        base &= pd.DataFrame(
            np.repeat(np.array([c in lst for c in cols])[None, :], len(px), axis=0),
            index=px.index,
            columns=cols,
        )
    if md.static is not None and "gics_industry" in md.static.columns:
        ind = md.static["gics_industry"].reindex(cols).fillna("").str.upper()
        bad = np.zeros(len(cols), dtype=bool)
        for word in d.exclude_industry_contains:
            bad |= ind.str.contains(word.upper(), regex=False).to_numpy()
        base.loc[:, bad] = False
        log.info("excluídos por indústria (%s): %d", d.exclude_industry_contains, int(bad.sum()))
    else:
        log.warning("sem GICS (data.files.static): REITs não foram excluídos")
    return base


def signal_base(md: MarketData, variant: Variant) -> pd.Series:
    return md.cdi_index if variant == "long_only" else md.hedge_brl


def betas(cfg: Config, md: MarketData, cols: list[str]) -> pd.DataFrame:
    b = cfg.hedge.beta
    raw = rolling_beta(
        md.ret_usd[cols], md.hedge_ret_usd, b.window, b.min_obs, b.clip_min, b.clip_max
    )
    return monthly_beta(raw) if b.recalc == "monthly" else raw


def build_strategy(cfg: Config, md: MarketData, variant: Variant) -> tuple[Strategy, list[str]]:
    if cfg.backtest.model == "sector":
        cols = sector_universe(cfg, md)
        px = md.px_brl[cols]
        state = trend_state(relative_series(px, signal_base(md, variant)), cfg.trend)
        avail = history_ok(px, cfg.sector.min_history_days)
        return SectorStrategy(state, avail, cfg.sector), cols
    uni = dividend_universe(cfg, md)
    cols = list(uni.columns[uni.any()])
    px = md.px_brl[cols]
    if md.dy is None:
        raise ValueError("modelo dividend exige data.files.dy")
    state = trend_state(relative_series(px, signal_base(md, variant)), cfg.trend)
    rel_stop = relative_series(px, md.hedge_brl)  # stop sempre contra o IVVB11
    sectors: dict[str, str] = {}
    if md.static is not None and "gics_sector" in md.static.columns:
        sec = md.static["gics_sector"].reindex(cols).fillna("")
        sectors = {str(k): str(v) for k, v in sec.items()}
    strat = DividendStrategy(
        rel=rel_stop, state=state, dy=md.dy, universe=uni[cols], sectors=sectors, cfg=cfg.dividend
    )
    return strat, cols


def run_variant(cfg: Config, md: MarketData, variant: Variant) -> Result:
    strat, cols = build_strategy(cfg, md, variant)
    beta = betas(cfg, md, cols) if variant == "ls_beta" else None
    res = run(cfg, variant, strat, md.px_brl[cols], md.hedge_brl, md.cdi_daily, beta)
    if isinstance(strat, DividendStrategy):
        res.meta["book_log"] = pd.DataFrame(strat.log)
    return res


# ---------------------------------------------------------------- métricas


def summarize(res: Result, md: MarketData) -> dict[str, Any]:
    nav = res.nav
    bench = {"ivvb11": md.hedge_brl, "usdbrl": md.fx}
    split = pd.Timestamp(res.config.backtest.calibration_end)
    periods = {
        "total": nav,
        "calibracao": nav.loc[nav.index <= split],
        "oos": nav.loc[nav.index > split],
    }
    out: dict[str, Any] = {"variant": res.variant}
    for name, df in periods.items():
        if len(df) > 2:
            out[name] = performance(df["nav"], df["cdi_daily"], bench)
    n = nav["nav"]
    t = res.trades
    years = len(nav) / res.config.costs.days_per_year
    traded = float((t["entry_value"].abs().sum() * 2) if not t.empty else 0.0)
    out["exposicao"] = {
        "long_medio": float((nav["long"] / n).mean()),
        "short_medio": float((nav["short"] / n).mean()),
        "dolar_liquido_medio": float((nav["net_usd"] / n).mean()),
        "posicoes_media": float(nav["n_positions"].mean()),
    }
    out["custos"] = {
        "negociacao_total_pct_nav0": float(nav["trading_costs"].sum() / n.iloc[0]),
        "aluguel_total_pct_nav0": float(nav["borrow_costs"].sum() / n.iloc[0]),
        "giro_anual_aprox": traded / float(n.mean()) / years if years > 0 else float("nan"),
    }
    if not t.empty:
        closed = t[t["exit_reason"] != "fim_periodo"]
        out["trades"] = {
            "n": int(len(t)),
            "hit_rate": float((closed["net_pnl"] > 0).mean()) if len(closed) else float("nan"),
            "retorno_medio": float(closed["return_on_entry"].mean()) if len(closed) else 0.0,
            "dias_medio": float(closed["days_open"].mean()) if len(closed) else 0.0,
            "saidas": closed["exit_reason"].value_counts(normalize=True).round(4).to_dict(),
        }
    return out


def comparison_table(summaries: list[dict[str, Any]], period: str = "total") -> pd.DataFrame:
    keys = [
        "return_ann",
        "cdi_ann",
        "excess_ann",
        "vol_ann",
        "sharpe",
        "max_drawdown",
        "beta_ivvb11",
        "corr_ivvb11",
        "beta_usdbrl",
    ]
    rows = {}
    for s in summaries:
        p = s.get(period, {})
        row = {k: p.get(k, np.nan) for k in keys}
        row.update({f"exp_{k}": v for k, v in s["exposicao"].items()})
        row["giro_anual"] = s["custos"]["giro_anual_aprox"]
        rows[s["variant"]] = row
    return pd.DataFrame(rows).T


def markdown_table(df: pd.DataFrame) -> str:
    head = "| | " + " | ".join(map(str, df.columns)) + " |"
    sep = "|---|" + "---:|" * len(df.columns)
    body = [
        f"| {i} | " + " | ".join("" if pd.isna(v) else f"{v:.4f}" for v in row) + " |"
        for i, row in zip(df.index, df.to_numpy(dtype=float), strict=True)
    ]
    return "\n".join([head, sep, *body])


def save(results: list[Result], summaries: list[dict[str, Any]], cfg: Config, run_id: str) -> Path:
    out = Path(cfg.backtest.results_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    for r in results:
        r.nav.to_parquet(out / f"nav_{r.variant}.parquet")
        r.trades.to_parquet(out / f"trades_{r.variant}.parquet")
        r.positions.to_parquet(out / f"positions_{r.variant}.parquet")
        bl = r.meta.get("book_log")
        if isinstance(bl, pd.DataFrame):
            bl.to_parquet(out / f"book_{r.variant}.parquet")
    (out / "summary.json").write_text(
        json.dumps(summaries, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    lines = [f"# {cfg.name} ({run_id})", ""]
    for period in ("total", "calibracao", "oos"):
        tab = comparison_table(summaries, period)
        lines += [f"## {period}", "", markdown_table(tab), ""]
    (out / "metrics.md").write_text("\n".join(lines), encoding="utf-8")
    return out
