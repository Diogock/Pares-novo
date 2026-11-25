"""Dados dos modelos BDR: export Bloomberg → preços sintéticos em R$ no calendário B3.

Preço sintético (MODELOS.md §0): ``P_R$ = TR_líq_US$ × USDBRL``, em que o retorno total
líquido soma ao retorno de preço só ``(1 − retenção)`` do componente de dividendos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bdr_models.config import Config
from pairs_ibra.data.loaders import b3_sessions, normalize_ticker, read_bloomberg_wide

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketData:
    """Tudo alinhado aos pregões da B3. Ativos nas colunas (tickers dos EUA, ex.: ``AAPL``)."""

    px_brl: pd.DataFrame  # preço sintético em R$ (retorno total líquido de retenção)
    ret_usd: pd.DataFrame  # retorno diário em US$ (líquido), base do beta
    hedge_brl: pd.Series  # IVVB11 sintético em R$
    hedge_ret_usd: pd.Series
    cdi_daily: pd.Series
    cdi_index: pd.Series
    fx: pd.Series
    dy: pd.DataFrame | None = None  # DY 12m em fração (0,06 = 6%)
    static: pd.DataFrame | None = None  # índice ticker; colunas gics_sector, gics_industry
    members: pd.DataFrame | None = None  # bool: ticker no S&P 500 na data

    @property
    def sessions(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.px_brl.index)


def net_total_return(px: pd.DataFrame, tr: pd.DataFrame, withholding: float) -> pd.DataFrame:
    """Retorno diário líquido: ``r_px + (1 − retenção) × (r_tr − r_px)``."""
    r_px = px.pct_change(fill_method=None)
    r_tr = tr.pct_change(fill_method=None)
    out: pd.DataFrame = r_px + (1.0 - withholding) * (r_tr - r_px)
    return out


def synthetic_brl(ret_usd: pd.DataFrame, fx: pd.Series, valid: pd.DataFrame) -> pd.DataFrame:
    """Índice em R$ a partir de retornos em US$ e do câmbio.

    ``valid`` marca onde o ativo tem preço; fora disso o resultado é NaN. Cada ativo começa em 1
    no seu primeiro dia válido (só os retornos importam).
    """
    r_fx = fx.pct_change(fill_method=None).reindex(ret_usd.index).fillna(0.0)
    r_brl = (1.0 + ret_usd.fillna(0.0)).mul(1.0 + r_fx, axis=0) - 1.0
    level = (1.0 + r_brl.where(valid, 0.0)).cumprod()
    base = level.where(valid).bfill().iloc[0] if len(level) else 1.0
    out: pd.DataFrame = (level / base).where(valid)
    return out


def to_sessions(df: pd.DataFrame, sessions: pd.DatetimeIndex, limit: int) -> pd.DataFrame:
    """Reamostra níveis para os pregões B3: ffill limitado (feriados nos EUA)."""
    union = df.index.union(sessions)
    out: pd.DataFrame = df.reindex(union).ffill(limit=limit).reindex(sessions)
    return out


def _read_wide(cfg: Config, name: str | None) -> pd.DataFrame | None:
    if not name:
        return None
    path = Path(cfg.data.raw_dir) / name
    if not path.exists():
        log.warning("arquivo ausente: %s", path)
        return None
    return read_bloomberg_wide(path, cfg.data.delimiter, cfg.data.date_format, cfg.data.na_values)


def _column(df: pd.DataFrame, name: str, path: str) -> pd.Series:
    key = normalize_ticker(name)
    if key not in df.columns:
        raise KeyError(f"coluna '{name}' não encontrada em {path}; colunas: {list(df.columns)}")
    s: pd.Series = df[key].astype(float)
    return s


def read_composition(path: Path, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Composição point-in-time (``data;ticker;peso``) expandida para diário (bool)."""
    raw = pd.read_csv(path, sep=None, engine="python", dtype=str)
    raw.columns = [c.strip().lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["data"].str.strip(), dayfirst=True)
    raw["ticker"] = raw["ticker"].map(normalize_ticker)
    dates = sorted(raw["date"].unique())
    tickers = sorted(raw["ticker"].unique())
    snap = pd.DataFrame(False, index=pd.DatetimeIndex(dates), columns=tickers)
    for d, g in raw.groupby("date"):
        snap.loc[d, g["ticker"].tolist()] = True
    out: pd.DataFrame = snap.reindex(snap.index.union(sessions)).ffill().reindex(sessions)
    return out.fillna(False).astype(bool)


def build_from_frames(
    cfg: Config,
    us_px: pd.DataFrame,
    us_tr: pd.DataFrame,
    fx: pd.Series,
    cdi_index: pd.Series,
    dy: pd.DataFrame | None = None,
    static: pd.DataFrame | None = None,
    members: pd.DataFrame | None = None,
    sessions: pd.DatetimeIndex | None = None,
) -> MarketData:
    """Monta ``MarketData`` a partir de séries já lidas (usado pelo loader e pelos testes)."""
    start = pd.Timestamp(cfg.data.start)
    end = pd.Timestamp(cfg.data.end) if cfg.data.end else us_px.index.max()
    if sessions is None:
        sessions = b3_sessions(start, end, cfg.data.calendar)
    lim = cfg.data.max_ffill_days
    tr = us_tr.reindex(columns=us_px.columns)
    tr = tr.where(tr.notna(), us_px)  # sem TR: usa preço (sem dividendos)
    # níveis em US$ no calendário B3 (ffill nos feriados dos EUA)
    px_s = to_sessions(us_px, sessions, lim)
    tr_s = to_sessions(tr, sessions, lim)
    fx_s = to_sessions(fx.to_frame("fx"), sessions, lim)["fx"]
    ret_usd = net_total_return(px_s, tr_s, cfg.data.withholding_tax)
    px_brl = synthetic_brl(ret_usd, fx_s, tr_s.notna())
    h = normalize_ticker(cfg.data.hedge_ticker)
    if h not in px_brl.columns:
        raise KeyError(f"ativo de hedge {h} ausente dos preços")
    cdi_s = to_sessions(cdi_index.to_frame("cdi"), sessions, lim)["cdi"]
    cdi_daily = (cdi_s / cdi_s.shift(1) - 1.0).fillna(0.0)
    dy_s = None
    if dy is not None:
        dy_s = to_sessions(dy, sessions, lim) / 100.0  # Bloomberg entrega em %
    return MarketData(
        px_brl=px_brl,
        ret_usd=ret_usd,
        hedge_brl=px_brl[h],
        hedge_ret_usd=ret_usd[h],
        cdi_daily=cdi_daily,
        cdi_index=cdi_s,
        fx=fx_s,
        dy=dy_s,
        static=static,
        members=members.reindex(sessions).fillna(False).astype(bool)
        if members is not None
        else None,
    )


def load_market_data(cfg: Config) -> MarketData:
    """Lê os exports de ``data.raw_dir`` (MODELOS.md §3)."""
    f = cfg.data.files
    raw = Path(cfg.data.raw_dir)
    us_px = _read_wide(cfg, f.us_px)
    us_tr = _read_wide(cfg, f.us_tr)
    fx_df = _read_wide(cfg, f.fx)
    mkt = _read_wide(cfg, f.market)
    if us_px is None or fx_df is None or mkt is None:
        raise FileNotFoundError(f"faltam arquivos obrigatórios em {raw} (us_px, fx, market)")
    us_tr = us_tr if us_tr is not None else us_px
    fx = _column(fx_df, cfg.data.fx_column, f.fx)
    cdi = _column(mkt, cfg.data.cdi_column, f.market)
    dy = _read_wide(cfg, f.dy)
    static = None
    if f.static and (raw / f.static).exists():
        st = pd.read_csv(raw / f.static, dtype=str)
        st.columns = [c.strip().lower() for c in st.columns]
        st["ticker"] = st["ticker"].map(normalize_ticker)
        static = st.set_index("ticker")
    start = pd.Timestamp(cfg.data.start)
    end = pd.Timestamp(cfg.data.end) if cfg.data.end else us_px.index.max()
    sessions = b3_sessions(start, end, cfg.data.calendar)
    members = None
    if f.spx_composition and (raw / f.spx_composition).exists():
        members = read_composition(raw / f.spx_composition, sessions)
    md = build_from_frames(cfg, us_px, us_tr, fx, cdi, dy, static, members, sessions)
    big = md.px_brl.pct_change(fill_method=None).abs() > 0.5
    if big.to_numpy().any():
        bad = big.any()[lambda s: s].index.tolist()[:10]
        log.warning("retornos diários > 50%% em R$ (conferir ajuste): %s", bad)
    return md


def rolling_beta(
    ret: pd.DataFrame, bench: pd.Series, window: int, min_obs: int, lo: float, hi: float
) -> pd.DataFrame:
    """Beta móvel de cada coluna contra ``bench`` (só dados até t), limitado a [lo, hi]."""
    b = bench.reindex(ret.index)
    mask = ret.notna() & b.notna().to_numpy()[:, None]
    x = ret.where(mask)
    y = pd.DataFrame(
        np.repeat(b.to_numpy()[:, None], ret.shape[1], axis=1), index=ret.index, columns=ret.columns
    ).where(mask)
    mx = x.rolling(window, min_periods=min_obs).mean()
    my = y.rolling(window, min_periods=min_obs).mean()
    cov = (x * y).rolling(window, min_periods=min_obs).mean() - mx * my
    var = (y * y).rolling(window, min_periods=min_obs).mean() - my * my
    beta: pd.DataFrame = (cov / var.where(var > 0)).clip(lo, hi)
    return beta
