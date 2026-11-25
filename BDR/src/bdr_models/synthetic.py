"""Dados sintéticos no formato dos exports Bloomberg dos modelos BDR (testes e ``data/sample``).

Gera ETFs setoriais, o IVV, ações com DY e setor GICS, câmbio, CDI e a composição do S&P 500
(com entradas e saídas), em arquivos wide ``Dates,<ticker> US Equity,...`` como os reais.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SECTOR_ETFS = ["IYW", "IYF", "IYE", "IYJ", "IYK", "IYC", "IYM", "IDU", "IYZ", "USRT", "IXJ"]
GICS = [
    "Information Technology",
    "Financials",
    "Energy",
    "Industrials",
    "Utilities",
    "Consumer Staples",
    "Health Care",
    "Materials",
]


def _fmt(df: pd.DataFrame, suffix: str = " US Equity") -> pd.DataFrame:
    out = df.copy()
    out.columns = [f"{c}{suffix}" for c in out.columns]
    out.index = pd.DatetimeIndex(out.index).strftime("%d/%m/%Y")
    out.index.name = "Dates"
    return out


def generate(
    out_dir: str | Path,
    start: str = "2008-01-01",
    end: str = "2014-12-31",
    n_stocks: int = 40,
    seed: int = 7,
) -> dict[str, Path]:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range(start, end)
    n = len(dates)

    mkt = rng.normal(0.0003, 0.011, n)  # fator S&P
    ivv = 100 * np.exp(np.cumsum(mkt))
    cols: dict[str, np.ndarray] = {"IVV": ivv}
    for k, t in enumerate(SECTOR_ETFS):
        # tendência relativa em regimes: drift alterna a cada ~1 ano
        regime = np.sign(np.sin(np.arange(n) / (120 + 15 * k) + k))
        drift = 0.0004 * regime
        beta = 0.7 + 0.06 * k
        r = beta * mkt + drift + rng.normal(0, 0.008, n)
        cols[t] = 50 * np.exp(np.cumsum(r))
    stocks = [f"S{j:02d}" for j in range(n_stocks)]
    dy_cols: dict[str, np.ndarray] = {}
    for j, t in enumerate(stocks):
        regime = np.sign(np.sin(np.arange(n) / (80 + 7 * j) + j))
        r = (0.6 + 0.02 * j) * mkt + 0.0006 * regime + rng.normal(0, 0.014, n)
        p = 30 * np.exp(np.cumsum(r))
        if j % 13 == 5:  # algumas deslistam no meio
            p[int(n * 0.7) :] = np.nan
        cols[t] = p
        base_dy = 0.5 + 8.0 * (j % 10) / 9  # 0,5% a 8,5%
        dy_cols[t] = np.clip(base_dy + np.cumsum(rng.normal(0, 0.03, n)), 0, None)
    px = pd.DataFrame(cols, index=dates)
    # retorno total: soma DY/252 ao preço (só ações e IVV, ETFs ~2% a.a.)
    div = pd.DataFrame(0.02 / 252, index=dates, columns=px.columns)
    for t in stocks:
        div[t] = dy_cols[t] / 100 / 252
    tr = px.pct_change(fill_method=None).add(div).add(1).cumprod() * px.iloc[0]
    tr = tr.where(px.notna())
    dy = pd.DataFrame(dy_cols, index=dates).where(px[stocks].notna())

    fx = 2.0 * np.exp(np.cumsum(rng.normal(0.0001, 0.009, n) - 0.3 * mkt))
    cdi = np.cumprod(np.full(n, (1 + 0.10) ** (1 / 252)))

    files = {
        "us_px": out / "bdr_us_px.txt",
        "us_tr": out / "bdr_us_tr.txt",
        "dy": out / "bdr_us_dy.txt",
        "fx": out / "bdr_fx.txt",
        "market": out / "market.txt",
        "static": out / "bdr_static.csv",
        "spx_composition": out / "spx_composition.txt",
    }
    _fmt(px.round(4)).to_csv(files["us_px"], na_rep="#N/A")
    _fmt(tr.round(4)).to_csv(files["us_tr"], na_rep="#N/A")
    _fmt(dy.round(4)).to_csv(files["dy"], na_rep="#N/A")
    _fmt(pd.DataFrame({"USDBRL": fx}, index=dates).round(5), " Curncy").to_csv(files["fx"])
    m = pd.DataFrame({"CDI": cdi}, index=dates)
    m.index = pd.DatetimeIndex(m.index).strftime("%d/%m/%Y")
    m.index.name = "Dates"
    m.round(8).to_csv(files["market"])
    static = pd.DataFrame(
        {
            "ticker": stocks,
            "gics_sector": [GICS[j % len(GICS)] for j in range(n_stocks)],
            "gics_industry": [
                "Equity Real Estate Investment Trusts (REITs)" if j % 17 == 3 else "Industry"
                for j in range(n_stocks)
            ],
        }
    )
    static.to_csv(files["static"], index=False)
    # composição: rebalanceamentos trimestrais; 1 em cada 8 ações só entra no meio
    rows = []
    for d in pd.date_range(start, end, freq="QS"):
        for j, t in enumerate(stocks):
            late = (
                j % 8 == 2
                and d < pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
            )
            if not late:
                rows.append({"data": d.strftime("%d/%m/%Y"), "ticker": f"{t} UN", "peso": 1.0})
    pd.DataFrame(rows).to_csv(files["spx_composition"], sep=";", index=False)
    return files
