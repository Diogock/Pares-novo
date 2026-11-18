"""Carrega e valida a configuração YAML (CLAUDE.md, seção 8).

Nenhum parâmetro do modelo é definido no código: tudo vem daqui.
Experimentos podem herdar de outro yaml com a chave ``extends``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataFiles(_Strict):
    prices_adj: str
    prices_raw: str
    volume: str
    market: str
    ibra_composition: str | None = None
    sectors: str | None = None
    vwap: str | None = None
    open: str | None = None


class MarketColumns(_Strict):
    cdi_index: str
    ibov: str
    ibra: str


class DataConfig(_Strict):
    raw_dir: str
    processed_dir: str
    files: DataFiles
    volume_kind: Literal["shares", "brl"]
    delimiter: str
    date_format: str
    na_values: list[str]
    market_columns: MarketColumns
    calendar: str
    max_ffill_days: int = Field(ge=0)
    max_abs_daily_return: float = Field(gt=0)
    auto_drop_duplicates: bool


class UniverseConfig(_Strict):
    index: str
    source: Literal["composition", "liquidity_proxy"]
    proxy_top_n: int = Field(gt=0)
    min_adtv_brl: float = Field(ge=0)
    adtv_window: int = Field(gt=0)
    min_trading_days_pct: float = Field(ge=0, le=1)
    min_price: float = Field(ge=0)
    max_btc_rate: float = Field(ge=0)
    exclude_events: bool


class WindowsConfig(_Strict):
    formation_days: int = Field(gt=20)
    trading_days: int = Field(gt=0)


class HalfLifeBounds(_Strict):
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def _check(self) -> HalfLifeBounds:
        if self.min >= self.max:
            raise ValueError("half_life.min deve ser < half_life.max")
        return self


class SelectionConfig(_Strict):
    method: Literal["distance", "cointegration", "kalman"]
    same_sector: bool
    min_corr: float = Field(ge=-1, le=1)
    stationarity_tests: list[Literal["adf", "pp", "kpss"]]
    min_tests_passed: int = Field(ge=1)
    pvalue: float = Field(gt=0, lt=1)
    require_i1: bool = False
    adf_lags: int = Field(ge=0)
    half_life: HalfLifeBounds
    max_hurst: float
    min_crossings: int = Field(ge=0)
    gamma_bounds: tuple[float, float]
    distance_candidates: int = Field(gt=0)

    @model_validator(mode="after")
    def _check(self) -> SelectionConfig:
        if self.min_tests_passed > len(self.stationarity_tests):
            raise ValueError("min_tests_passed maior que o número de testes")
        lo, hi = self.gamma_bounds
        if not 0 < lo < hi:
            raise ValueError("gamma_bounds deve ser 0 < min < max")
        if self.method == "kalman":
            raise ValueError("selection.method=kalman ainda não implementado (fase 5)")
        return self


class SignalConfig(_Strict):
    zscore_mode: Literal["fixed", "ewma"]
    ewma_lambda: float = Field(gt=0, lt=1)
    entry_z: float = Field(gt=0)
    exit_z_long: float
    exit_z_short: float
    stop_z: float = Field(gt=0)
    stop_loss_pct: float = Field(gt=0)
    time_stop_days: int = Field(gt=0)
    cooldown_days: int = Field(ge=0)
    execution: Literal["close_t1", "vwap_t1", "open_t1"]
    retest_on_rebalance: bool

    @model_validator(mode="after")
    def _check(self) -> SignalConfig:
        if self.stop_z <= self.entry_z:
            raise ValueError("stop_z deve ser > entry_z")
        if self.exit_z_long >= self.entry_z or self.exit_z_short >= self.entry_z:
            raise ValueError("limiares de saída devem ser < entry_z")
        return self


class PortfolioConfig(_Strict):
    n_pairs: int = Field(gt=0)
    max_pairs_per_stock: int = Field(gt=0)
    max_sector_pct: float = Field(gt=0, le=1)
    include_same_issuer: bool
    max_gross_leverage: float = Field(gt=0)


class SizingConfig(_Strict):
    mode: Literal["gamma", "dollar", "beta"]
    leg_pct_nav: float = Field(gt=0, le=1)
    beta_window: int = Field(gt=20)
    lot_size: int = Field(ge=1)


class CostsConfig(_Strict):
    trading_cost_bps: float = Field(ge=0)
    btc_fallback_rate: float = Field(ge=0)
    cash_spread_bps: float


class BacktestConfig(_Strict):
    start: dt.date
    end: dt.date | None = None
    calibration_end: dt.date
    oos_start: dt.date
    initial_capital: float = Field(gt=0)
    subperiods: list[tuple[dt.date, dt.date | None]]


class Config(_Strict):
    data: DataConfig
    universe: UniverseConfig
    windows: WindowsConfig
    selection: SelectionConfig
    signal: SignalConfig
    portfolio: PortfolioConfig
    sizing: SizingConfig
    costs: CostsConfig
    backtest: BacktestConfig

    @model_validator(mode="after")
    def _check(self) -> Config:
        if self.signal.execution == "vwap_t1" and not self.data.files.vwap:
            raise ValueError("execution=vwap_t1 exige data.files.vwap")
        if self.signal.execution == "open_t1" and not self.data.files.open:
            raise ValueError("execution=open_t1 exige data.files.open")
        return self


def ts(d: dt.date) -> pd.Timestamp:
    """Converte uma data da config para ``pd.Timestamp`` sem timezone."""
    return pd.Timestamp(d)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_raw(path: str | Path) -> dict[str, Any]:
    """Lê o yaml resolvendo ``extends`` recursivamente."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    parent = raw.pop("extends", None)
    if parent is not None:
        base = load_raw((path.parent / parent).resolve())
        raw = _deep_merge(base, raw)
    return raw


def load_config(path: str | Path) -> Config:
    return Config.model_validate(load_raw(path))


def config_from_dict(raw: dict[str, Any]) -> Config:
    return Config.model_validate(raw)
