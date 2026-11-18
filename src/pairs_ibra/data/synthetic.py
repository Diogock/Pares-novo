"""Dados sintéticos com pares cointegrados conhecidos (fase 0).

Gera os mesmos arquivos que o pipeline espera do Bloomberg, no mesmo formato:
``prices_adj.txt``, ``prices_raw.txt``, ``volume.txt``, ``market.txt``,
``ibra_composition.txt`` e o Excel ``sectors.xlsx``.

Inclui casos difíceis: IPO no meio do período, deslistagem, ação ilíquida,
ticker antigo/novo com a mesma história, proventos (preço sem ajuste ≠ ajustado),
feriados B3 como ``#N/A`` e um par plantado ON/PN do mesmo emissor.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pairs_ibra.data.loaders import b3_sessions


@dataclass(frozen=True)
class PlantedPair:
    leg_a: str
    leg_b: str
    gamma: float
    half_life: float


@dataclass(frozen=True)
class SyntheticData:
    close_adj: pd.DataFrame
    close_raw: pd.DataFrame
    volume: pd.DataFrame
    market: pd.DataFrame          # cdi_index, ibov, ibra
    composition: pd.DataFrame     # date, ticker, weight
    sectors: pd.DataFrame         # ticker, setor, subsetor, segmento, emissor
    planted: list[PlantedPair]
    duplicates: list[tuple[str, str]]   # (antigo, novo)
    delisted: str
    ipo: str
    illiquid: list[str]


def _roots(n: int, rng: np.random.Generator) -> list[str]:
    letters = np.array(list(string.ascii_uppercase))
    out: set[str] = set()
    while len(out) < n:
        out.add("".join(rng.choice(letters, 4)))
    return sorted(out)


def generate(n_tickers: int = 60, start: str = "2008-01-02", end: str = "2011-12-30",
             n_planted: int = 10, n_sectors: int = 8, seed: int = 7,
             half_life_range: tuple[float, float] = (4.0, 7.0)) -> SyntheticData:
    rng = np.random.default_rng(seed)
    dates = b3_sessions(pd.Timestamp(start), pd.Timestamp(end))
    T = len(dates)
    roots = _roots(n_tickers + 2, rng)
    tickers = [r + "3" for r in roots[:n_tickers]]
    # par plantado 0 é ON/PN do mesmo emissor
    tickers[1] = roots[0] + "4"
    sectors_names = [f"SETOR_{k + 1:02d}" for k in range(n_sectors)]

    mkt = rng.normal(0.0003, 0.014, T)
    sec_f = rng.normal(0.0, 0.008, (T, n_sectors))
    sector_of = {}
    planted: list[PlantedPair] = []
    logp = np.zeros((T, n_tickers))

    def factor_walk(sec: int) -> np.ndarray:
        beta = rng.uniform(0.7, 1.3)
        r = beta * mkt + sec_f[:, sec] + rng.normal(0.0, 0.016, T)
        r[0] = 0.0
        out: np.ndarray = np.log(rng.uniform(5, 60)) + np.cumsum(r)
        return out

    k = 0
    for p in range(n_planted):
        sec = p % n_sectors
        ia, ib = k, k + 1
        k += 2
        lb = factor_walk(sec)
        hl = float(rng.uniform(*half_life_range))
        phi = 0.5 ** (1 / hl)
        sd = rng.uniform(0.04, 0.07)
        eta = rng.normal(0.0, sd * np.sqrt(1 - phi ** 2), T)
        s = np.zeros(T)
        for t in range(1, T):
            s[t] = phi * s[t - 1] + eta[t]
        gamma = float(rng.uniform(0.6, 1.6))
        la = rng.uniform(-0.5, 0.5) + gamma * lb + s
        logp[:, ia], logp[:, ib] = la, lb
        sector_of[tickers[ia]] = sector_of[tickers[ib]] = sectors_names[sec]
        planted.append(PlantedPair(tickers[ia], tickers[ib], gamma, hl))
    for i in range(k, n_tickers):
        sec = int(rng.integers(n_sectors))
        logp[:, i] = factor_walk(sec)
        sector_of[tickers[i]] = sectors_names[sec]

    adj = pd.DataFrame(np.exp(logp), index=dates, columns=tickers)

    # casos especiais (fora dos pares plantados)
    ipo, delisted = tickers[k], tickers[k + 1]
    adj.loc[adj.index[: T // 3], ipo] = np.nan
    adj.loc[adj.index[2 * T // 3:], delisted] = np.nan
    illiquid = [tickers[k + 2], tickers[k + 3]]
    old, new = roots[n_tickers] + "3", tickers[k + 4]
    adj[old] = adj[new]
    sector_of[old] = sector_of[new]

    # proventos: ~4% a.a. em uma data por ano → preço sem ajuste
    raw = adj.copy()
    years = sorted(set(dates.year))
    for tk in raw.columns:
        factor = pd.Series(1.0, index=dates)
        for y in years:
            yd = dates[dates.year == y]
            ex = yd[int(rng.integers(len(yd)))]
            factor.loc[factor.index < ex] *= 1 - 0.04
        raw[tk] = adj[tk] / factor

    turnover_target = rng.uniform(2e7, 2e8, raw.shape[1])
    noise = rng.lognormal(0.0, 0.3, raw.shape)
    vol = pd.DataFrame(turnover_target * noise, index=dates, columns=raw.columns) / raw
    for tk in illiquid:
        vol[tk] = vol[tk] / 100.0
    vol = vol.round(0)

    cdi_daily = np.full(T, (1.10) ** (1 / 252) - 1)
    cdi_daily[0] = 0.0
    ibov = 60000 * np.exp(np.cumsum(mkt))
    ibra = 2500 * np.exp(np.cumsum(mkt * 1.02))
    market = pd.DataFrame({"cdi_index": 1000 * np.cumprod(1 + cdi_daily), "ibov": ibov,
                           "ibra": ibra}, index=dates)

    reb = [d for i, d in enumerate(dates)
           if i == 0 or (d.month in (1, 5, 9) and dates[i - 1].month != d.month)]
    comp_rows = []
    for d in reb:
        live = adj.loc[d].dropna().index
        members = [t for t in live if t != old]  # ticker antigo nunca está no índice
        w = 1.0 / len(members)
        comp_rows += [{"date": d, "ticker": t, "weight": w} for t in members]
    composition = pd.DataFrame(comp_rows)

    sectors = pd.DataFrame({
        "ticker": list(adj.columns),
        "setor": [sector_of[t] for t in adj.columns],
        "subsetor": [sector_of[t] + "_SUB" for t in adj.columns],
        "segmento": [sector_of[t] + "_SEG" for t in adj.columns],
        "emissor": [t[:4] for t in adj.columns],
    })
    return SyntheticData(close_adj=adj, close_raw=raw, volume=vol, market=market,
                         composition=composition, sectors=sectors, planted=planted,
                         duplicates=[(old, new)], delisted=delisted, ipo=ipo, illiquid=illiquid)


# ---------------------------------------------------------------- escrita no formato Bloomberg

def _bbg_name(t: str) -> str:
    return f"{t.capitalize()} BZ Equity"


def write_bloomberg_txt(df: pd.DataFrame, path: str | Path, names: list[str] | None = None,
                        decimals: int = 6) -> None:
    """Escreve no layout do export: ``Dates,Petr4 BZ Equity,...``; todos os dias úteis da
    semana, com ``#N/A`` em feriados e dias sem dado."""
    all_weekdays = pd.bdate_range(df.index.min(), df.index.max())
    out = df.reindex(all_weekdays)
    out = out.round(decimals).astype(object).where(out.notna(), "#N/A")
    out.columns = pd.Index(names or [_bbg_name(c) for c in df.columns])
    out = out.copy()
    out.insert(0, "Dates", all_weekdays.strftime("%d/%m/%Y"))
    out.to_csv(path, index=False)


def write_sectors_xlsx(sectors: pd.DataFrame, path: str | Path,
                       de_para: pd.DataFrame | None = None,
                       exclusions: list[str] | None = None) -> None:
    with pd.ExcelWriter(path) as xw:
        sectors.to_excel(xw, sheet_name="setores", index=False)
        (de_para if de_para is not None else
         pd.DataFrame(columns=["ticker_antigo", "ticker_novo", "data_troca"])
         ).to_excel(xw, sheet_name="de_para", index=False)
        pd.DataFrame({"ticker": exclusions or []}).to_excel(xw, sheet_name="exclusoes", index=False)


def write_all(data: SyntheticData, raw_dir: str | Path, sectors_path: str | Path,
              with_de_para: bool = False) -> None:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_bloomberg_txt(data.close_adj, raw_dir / "prices_adj.txt")
    write_bloomberg_txt(data.close_raw, raw_dir / "prices_raw.txt")
    write_bloomberg_txt(data.volume, raw_dir / "volume.txt", decimals=0)
    write_bloomberg_txt(data.market, raw_dir / "market.txt",
                        names=["BZACCETP Index", "IBOV Index", "IBRA Index"])
    comp = data.composition.assign(
        data=data.composition["date"].dt.strftime("%d/%m/%Y"),
        ticker=data.composition["ticker"] + " BZ",
        peso=(data.composition["weight"] * 100).round(4),
    )[["data", "ticker", "peso"]]
    comp.to_csv(raw_dir / "ibra_composition.txt", sep=";", index=False)
    dp = None
    if with_de_para:
        dp = pd.DataFrame([{"ticker_antigo": a, "ticker_novo": b, "data_troca": ""}
                           for a, b in data.duplicates])
    Path(sectors_path).parent.mkdir(parents=True, exist_ok=True)
    write_sectors_xlsx(data.sectors, sectors_path, dp)
