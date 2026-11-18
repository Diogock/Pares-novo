"""Leitura dos exports Bloomberg e montagem do dataset padronizado (CLAUDE.md, seção 4).

Formato esperado dos ``.txt`` wide (preços ajustados, preços sem ajuste, volume, VWAP)::

    Dates,PETR4 BZ Equity,VALE3 BZ Equity,...
    02/01/2008,10.51,#N/A,...

- separador ``,`` (configurável), datas ``dd/mm/aaaa``, faltantes ``#N/A``;
- as datas incluem todos os dias úteis da semana; feriados da B3 são removidos
  pelo calendário ``BVMF``.

Mercado: mesmo formato, com colunas de CDI (índice acumulado), IBOV e IBRA.
Composição do IBRA: formato longo ``data;ticker;peso`` (separador detectado).
Setores: Excel auxiliar com abas ``setores``, ``de_para`` e ``exclusoes``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from pairs_ibra.config import Config

log = logging.getLogger(__name__)

SECTOR_COLUMNS = ["ticker", "setor", "subsetor", "segmento", "emissor"]
NO_SECTOR = "SEM_SETOR"


def normalize_ticker(raw: str) -> str:
    """``'Petr4 BZ Equity'`` → ``'PETR4'``."""
    s = str(raw).strip().upper()
    return s.split()[0] if s else s


def issuer_root(ticker: str) -> str:
    """Raiz do emissor pelo ticker B3 (``PETR4`` → ``PETR``; ``TAEE11`` → ``TAEE``)."""
    return ticker[:4]


def read_bloomberg_wide(
    path: str | Path,
    delimiter: str = ",",
    date_format: str = "%d/%m/%Y",
    na_values: list[str] | None = None,
) -> pd.DataFrame:
    """Lê um export wide do Bloomberg. Retorna datas no índice e tickers normalizados."""
    df = pd.read_csv(
        path,
        sep=delimiter,
        na_values=na_values or ["#N/A"],
        keep_default_na=True,
        dtype=str,
        skipinitialspace=True,
    )
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    date_col = df.columns[0]
    dates = pd.to_datetime(df[date_col].str.strip(), format=date_format)
    body = df.drop(columns=[date_col])
    body.columns = pd.Index([normalize_ticker(c) for c in body.columns])
    dup = body.columns[body.columns.duplicated()].tolist()
    if dup:
        raise ValueError(f"{path}: tickers duplicados após normalização: {dup}")
    out = body.apply(lambda s: pd.to_numeric(s.str.strip(), errors="coerce"))
    out.index = pd.DatetimeIndex(dates, name="date")
    out = out.sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    result: pd.DataFrame = out.astype(float)
    return result


def b3_sessions(start: pd.Timestamp, end: pd.Timestamp, calendar: str = "BVMF") -> pd.DatetimeIndex:
    """Pregões da B3 entre ``start`` e ``end`` (inclusive)."""
    import exchange_calendars as xc

    cal = xc.get_calendar(calendar, start=min(start, pd.Timestamp("2007-01-02")))
    first = cal.first_session
    s = max(start, first)
    e = min(end, cal.last_session)
    sessions = cal.sessions_in_range(s, e)
    return pd.DatetimeIndex(sessions.tz_localize(None) if sessions.tz else sessions, name="date")


def align_to_sessions(df: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Mantém só pregões e remove linhas totalmente vazias."""
    out = df.loc[df.index.isin(sessions)]
    return out.dropna(how="all")


def read_market(path: str | Path, cfg: Config) -> pd.DataFrame:
    """Mercado: ``cdi_daily`` (taxa do dia), ``ibov_close`` e ``ibra_close``."""
    raw = pd.read_csv(path, sep=cfg.data.delimiter, na_values=cfg.data.na_values, dtype=str,
                      skipinitialspace=True)
    raw = raw.loc[:, [c for c in raw.columns if not str(c).startswith("Unnamed")]]
    date_col = raw.columns[0]
    idx = pd.DatetimeIndex(pd.to_datetime(raw[date_col].str.strip(), format=cfg.data.date_format),
                           name="date")
    cols = {str(c).strip().upper(): c for c in raw.columns}
    mc = cfg.data.market_columns

    def col(name: str) -> pd.Series:
        key = name.strip().upper()
        if key not in cols:
            raise KeyError(f"coluna '{name}' não encontrada em {path}; colunas: {list(raw.columns)}")
        return pd.Series(pd.to_numeric(raw[cols[key]].str.strip(), errors="coerce").to_numpy(),
                         index=idx)

    cdi_idx = col(mc.cdi_index)
    out = pd.DataFrame({
        "cdi_index": cdi_idx,
        "ibov_close": col(mc.ibov),
        "ibra_close": col(mc.ibra),
    }).sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    return out


def finalize_market(market: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    m = market.reindex(sessions).ffill()
    cdi = m["cdi_index"]
    m["cdi_daily"] = (cdi / cdi.shift(1) - 1.0).fillna(0.0)
    return m[["cdi_daily", "ibov_close", "ibra_close", "cdi_index"]]


def read_composition(path: str | Path) -> pd.DataFrame:
    """Composição do IBRA em formato longo: ``date, ticker, weight`` (peso em fração)."""
    path = Path(path)
    sample = path.read_text(encoding="utf-8-sig")[:4096]
    sep = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    raw = pd.read_csv(path, sep=sep, dtype=str, encoding="utf-8-sig")
    raw.columns = pd.Index([str(c).strip().lower() for c in raw.columns])
    rename = {"data": "date", "dates": "date", "peso": "weight"}
    raw = raw.rename(columns=rename)
    if not {"date", "ticker"}.issubset(raw.columns):
        raise ValueError(f"{path}: precisa das colunas data;ticker;peso. Recebido: {list(raw.columns)}")
    out = pd.DataFrame({
        "date": pd.to_datetime(raw["date"].str.strip(), dayfirst=True),
        "ticker": raw["ticker"].map(normalize_ticker),
    })
    if "weight" in raw.columns:
        w = pd.to_numeric(raw["weight"].str.strip().str.replace(",", ".", regex=False),
                          errors="coerce")
        sums = w.groupby(out["date"]).sum()
        if (sums > 1.5).any():
            w = w / 100.0
        out["weight"] = w
    else:
        out["weight"] = np.nan
    return out.sort_values(["date", "ticker"]).reset_index(drop=True)


def expand_composition(comp: pd.DataFrame, sessions: pd.DatetimeIndex,
                       tickers: pd.Index) -> pd.DataFrame:
    """Composição vigente por pregão (booleano wide). Cada carteira vale até a próxima."""
    dates = sorted(comp["date"].unique())
    out = pd.DataFrame(False, index=sessions, columns=tickers)
    for i, d in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else sessions[-1] + pd.Timedelta(days=1)
        members = [t for t in comp.loc[comp["date"] == d, "ticker"] if t in out.columns]
        mask = (sessions >= d) & (sessions < end)
        out.loc[mask, members] = True
    return out


@dataclass(frozen=True)
class SectorBook:
    sectors: pd.DataFrame          # index ticker; setor, subsetor, segmento, emissor
    de_para: pd.DataFrame          # ticker_antigo, ticker_novo, data_troca
    exclusions: list[str] = field(default_factory=list)


def read_sectors(path: str | Path | None, tickers: pd.Index) -> SectorBook:
    """Lê o Excel auxiliar. Tickers sem classificação recebem ``SEM_SETOR``."""
    sectors = pd.DataFrame(index=pd.Index([], name="ticker"), columns=SECTOR_COLUMNS[1:])
    de_para = pd.DataFrame(columns=["ticker_antigo", "ticker_novo", "data_troca"])
    exclusions: list[str] = []
    if path is not None and Path(path).exists():
        book = pd.read_excel(path, sheet_name=None, dtype=str)
        if "setores" in book:
            s = book["setores"].rename(columns=lambda c: str(c).lower())
            s["ticker"] = s["ticker"].map(normalize_ticker)
            sectors = s.dropna(subset=["ticker"]).drop_duplicates("ticker").set_index("ticker")
        if "de_para" in book:
            d = book["de_para"].rename(columns=lambda c: str(c).lower()).dropna(subset=["ticker_antigo"])
            d["ticker_antigo"] = d["ticker_antigo"].map(normalize_ticker)
            d["ticker_novo"] = d["ticker_novo"].map(normalize_ticker)
            de_para = d
        if "exclusoes" in book:
            e = book["exclusoes"].rename(columns=lambda c: str(c).lower())
            exclusions = [normalize_ticker(t) for t in e["ticker"].dropna()]
    elif path is not None:
        log.warning("Excel de setores não encontrado em %s; todos ficam %s", path, NO_SECTOR)
    full = sectors.reindex(tickers)
    for c in SECTOR_COLUMNS[1:]:
        if c not in full.columns:
            full[c] = np.nan
    full[["setor", "subsetor", "segmento"]] = full[["setor", "subsetor", "segmento"]].fillna(NO_SECTOR)
    missing_issuer = full["emissor"].isna()
    full.loc[missing_issuer, "emissor"] = [issuer_root(t) for t in full.index[missing_issuer]]
    full.index.name = "ticker"
    return SectorBook(sectors=full[SECTOR_COLUMNS[1:]], de_para=de_para, exclusions=exclusions)


@dataclass(frozen=True)
class Dataset:
    """Dados prontos para o modelo, todos wide (pregão × ticker)."""

    close_adj: pd.DataFrame
    close_raw: pd.DataFrame
    turnover: pd.DataFrame          # volume financeiro em R$
    traded: pd.DataFrame            # True se houve negócio no dia (antes do forward-fill)
    in_index: pd.DataFrame          # pertence ao IBRA na data (point-in-time)
    market: pd.DataFrame            # cdi_daily, ibov_close, ibra_close
    sectors: pd.DataFrame
    exec_price: pd.DataFrame | None = None   # VWAP/abertura ajustados, se execução não for no fechamento

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close_adj.index)

    @property
    def tickers(self) -> pd.Index:
        return self.close_adj.columns

    def truncate(self, end: pd.Timestamp) -> Dataset:
        """Cópia com dados até ``end`` (inclusive). Usado no teste de look-ahead."""
        def cut(x: pd.DataFrame | None) -> pd.DataFrame | None:
            return None if x is None else x.loc[x.index <= end]

        return Dataset(
            close_adj=self.close_adj.loc[self.close_adj.index <= end],
            close_raw=self.close_raw.loc[self.close_raw.index <= end],
            turnover=self.turnover.loc[self.turnover.index <= end],
            traded=self.traded.loc[self.traded.index <= end],
            in_index=self.in_index.loc[self.in_index.index <= end],
            market=self.market.loc[self.market.index <= end],
            sectors=self.sectors,
            exec_price=cut(self.exec_price),
        )


def liquidity_proxy_membership(turnover: pd.DataFrame, traded: pd.DataFrame, top_n: int,
                               window: int) -> pd.DataFrame:
    """Plano B sem composição histórica: a cada quadrimestre (jan/mai/set), entram os
    ``top_n`` por volume financeiro médio na janela anterior (só dados passados)."""
    dates = pd.DatetimeIndex(turnover.index)
    starts = [d for i, d in enumerate(dates)
              if i > 0 and d.month in (1, 5, 9) and dates[i - 1].month != d.month]
    rows: list[dict[str, object]] = []
    for d in starts:
        i = dates.get_loc(d)
        assert isinstance(i, int)
        lo = max(0, i - window)
        if i - lo < 20:
            continue
        hist = turnover.iloc[lo:i].where(traded.iloc[lo:i]).fillna(0.0).mean()
        top = hist[hist > 0].sort_values(ascending=False).head(top_n)
        rows.extend({"date": d, "ticker": t, "weight": np.nan} for t in top.index)
    return pd.DataFrame(rows, columns=["date", "ticker", "weight"])


def build_dataset(cfg: Config, base_dir: str | Path = ".") -> tuple[Dataset, list[str]]:
    """Lê os arquivos brutos e devolve o dataset e uma lista de avisos."""
    from pairs_ibra.data.validation import find_duplicate_series

    base = Path(base_dir)
    raw_dir = base / cfg.data.raw_dir
    f = cfg.data.files
    kw = dict(delimiter=cfg.data.delimiter, date_format=cfg.data.date_format,
              na_values=cfg.data.na_values)
    warnings: list[str] = []

    adj = read_bloomberg_wide(raw_dir / f.prices_adj, **kw)  # type: ignore[arg-type]
    raw = read_bloomberg_wide(raw_dir / f.prices_raw, **kw)  # type: ignore[arg-type]
    vol = read_bloomberg_wide(raw_dir / f.volume, **kw)  # type: ignore[arg-type]
    market = read_market(raw_dir / f.market, cfg)

    start = pd.Timestamp(cfg.backtest.start)
    end = pd.Timestamp(cfg.backtest.end) if cfg.backtest.end else adj.index.max()
    sessions = b3_sessions(start, end, cfg.data.calendar)
    adj = align_to_sessions(adj, sessions)
    sessions = pd.DatetimeIndex(adj.index, name="date")

    tickers = adj.columns
    for name, frame in (("prices_raw", raw), ("volume", vol)):
        missing = tickers.difference(frame.columns)
        if len(missing):
            warnings.append(f"{name}: {len(missing)} tickers sem dados: {list(missing)[:10]}")
    raw = raw.reindex(index=sessions, columns=tickers)
    vol = vol.reindex(index=sessions, columns=tickers)

    traded = adj.notna() & (vol.fillna(0.0) > 0)
    turnover = vol * raw if cfg.data.volume_kind == "shares" else vol.copy()

    sector_path = (base / f.sectors) if f.sectors else None
    book = read_sectors(sector_path, tickers)

    # tickers antigos/novos com história duplicada
    drop: set[str] = set(book.exclusions)
    for _, r in book.de_para.iterrows():
        if r["ticker_antigo"] in tickers and r["ticker_novo"] in tickers:
            drop.add(str(r["ticker_antigo"]))
    if cfg.data.auto_drop_duplicates:
        for a, b, frac in find_duplicate_series(adj.drop(columns=list(drop & set(tickers)))):
            loser = a if adj[a].notna().sum() < adj[b].notna().sum() else b
            drop.add(loser)
            warnings.append(f"séries duplicadas {a}/{b} ({frac:.0%} retornos iguais): removido {loser}")
    keep = [t for t in tickers if t not in drop]

    adj, raw, turnover, traded = (x[keep] for x in (adj, raw, turnover, traded))
    lim = cfg.data.max_ffill_days
    adj = adj.ffill(limit=lim) if lim else adj
    raw = raw.ffill(limit=lim) if lim else raw

    if cfg.universe.source == "composition":
        if not f.ibra_composition or not (raw_dir / f.ibra_composition).exists():
            raise FileNotFoundError("universe.source=composition exige data.files.ibra_composition")
        comp = read_composition(raw_dir / f.ibra_composition)
        unknown = sorted(set(comp["ticker"]) - set(keep))
        if unknown:
            warnings.append(f"composição: {len(unknown)} tickers sem preço: {unknown[:10]}")
    else:
        comp = liquidity_proxy_membership(turnover, traded, cfg.universe.proxy_top_n, 252)
        warnings.append("universo por proxy de liquidez (sem composição histórica do IBRA)")
    in_index = expand_composition(comp, sessions, pd.Index(keep))

    exec_price = None
    exec_file = f.vwap if cfg.signal.execution == "vwap_t1" else (
        f.open if cfg.signal.execution == "open_t1" else None)
    if exec_file:
        ep = read_bloomberg_wide(raw_dir / exec_file, **kw)  # type: ignore[arg-type]
        exec_price = ep.reindex(index=sessions, columns=keep)

    ds = Dataset(
        close_adj=adj, close_raw=raw, turnover=turnover, traded=traded, in_index=in_index,
        market=finalize_market(market, sessions), sectors=book.sectors.loc[keep],
        exec_price=exec_price,
    )
    return ds, warnings


# ---------------------------------------------------------------- parquet (data/processed)

def _long(wide: pd.DataFrame, name: str) -> pd.DataFrame:
    s = pd.Series(wide.to_numpy().ravel(),
                  index=pd.MultiIndex.from_product([wide.index, wide.columns],
                                                   names=["date", "ticker"]), name=name)
    return s.reset_index()


def save_dataset(ds: Dataset, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    long = pd.concat(
        {"close_adj": ds.close_adj.stack(future_stack=True),
         "close_raw": ds.close_raw.stack(future_stack=True),
         "volume_brl": ds.turnover.stack(future_stack=True),
         "traded": ds.traded.stack(future_stack=True)},
        axis=1,
    )
    long.index.names = ["date", "ticker"]
    long.reset_index().to_parquet(out / "prices.parquet", index=False)
    comp = _long(ds.in_index, "in_index")
    comp.to_parquet(out / "ibra_composition.parquet", index=False)
    ds.sectors.reset_index().to_parquet(out / "sectors.parquet", index=False)
    ds.market.reset_index().to_parquet(out / "market.parquet", index=False)
    if ds.exec_price is not None:
        _long(ds.exec_price, "exec_price").to_parquet(out / "exec_price.parquet", index=False)


def load_dataset(in_dir: str | Path) -> Dataset:
    d = Path(in_dir)
    p = pd.read_parquet(d / "prices.parquet")

    def wide(col: str) -> pd.DataFrame:
        w = p.pivot(index="date", columns="ticker", values=col)
        w.columns.name = None
        return w

    adj = wide("close_adj")
    comp = pd.read_parquet(d / "ibra_composition.parquet").pivot(
        index="date", columns="ticker", values="in_index")
    comp.columns.name = None
    ep_path = d / "exec_price.parquet"
    exec_price = None
    if ep_path.exists():
        e = pd.read_parquet(ep_path).pivot(index="date", columns="ticker", values="exec_price")
        e.columns.name = None
        exec_price = e.reindex(index=adj.index, columns=adj.columns)
    return Dataset(
        close_adj=adj.astype(float),
        close_raw=wide("close_raw").reindex_like(adj).astype(float),
        turnover=wide("volume_brl").reindex_like(adj).astype(float),
        traded=wide("traded").reindex_like(adj).fillna(False).astype(bool),
        in_index=comp.reindex_like(adj).fillna(False).astype(bool),
        market=pd.read_parquet(d / "market.parquet").set_index("date").reindex(adj.index),
        sectors=pd.read_parquet(d / "sectors.parquet").set_index("ticker").reindex(adj.columns),
        exec_price=exec_price,
    )
