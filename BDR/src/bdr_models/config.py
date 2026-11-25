"""Configuração validada dos modelos BDR (BDR/MODELOS.md).

Nenhum parâmetro de modelo fica no código: tudo vem do yaml. Chaves desconhecidas são erro.
Experimentos herdam com ``extends`` (mesma mecânica do ``pairs_ibra.config``).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pairs_ibra.config import load_raw

Variant = Literal["long_only", "ls_beta", "ls_notional"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataFiles(_Strict):
    us_px: str  # PX_LAST dos ativos nos EUA (wide)
    us_tr: str  # TOT_RETURN_INDEX_GROSS_DVDS (wide)
    fx: str  # USDBRL (wide, uma coluna)
    market: str  # mesmo market.txt do modelo IBRA (CDI em índice acumulado)
    dy: str | None = None  # EQY_DVD_YLD_12M (wide), só single names
    static: str | None = None  # csv: ticker, gics_sector, gics_industry
    spx_composition: str | None = None  # longo data;ticker;peso


class DataConfig(_Strict):
    raw_dir: str
    files: DataFiles
    delimiter: str
    date_format: str
    na_values: list[str]
    cdi_column: str
    fx_column: str
    hedge_ticker: str  # ativo nos EUA que sintetiza o IVVB11 (IVV)
    calendar: str
    max_ffill_days: int = Field(
        ge=0
    )  # feriados nos EUA; acima disso o ativo é tratado como sem preço
    withholding_tax: float = Field(ge=0, lt=1)  # retenção sobre dividendos (30%)
    start: dt.date
    end: dt.date | None = None


class TrendConfig(_Strict):
    """Médias alinhadas + rompimento (MODELOS.md §4.1)."""

    fast: int = Field(gt=0)
    mid: int = Field(gt=0)
    slow: int = Field(gt=0)
    entry_high: int = Field(gt=0)  # supera a máxima dos N pregões anteriores
    exit_low: int = Field(gt=0)  # fica abaixo da mínima dos M pregões anteriores

    @model_validator(mode="after")
    def _order(self) -> TrendConfig:
        if not self.fast < self.mid < self.slow:
            raise ValueError("trend: exige fast < mid < slow")
        return self


class BetaConfig(_Strict):
    window: int = Field(gt=1)
    min_obs: int = Field(gt=1)
    clip_min: float
    clip_max: float
    recalc: Literal["monthly", "daily"]
    fallback: float  # beta usado enquanto não há histórico suficiente


class HedgeConfig(_Strict):
    rebalance_band: float = Field(ge=0)  # descasamento máx. (fração do long) antes de ajustar
    beta: BetaConfig


class CostsConfig(_Strict):
    trade_bps_long: float = Field(ge=0)  # BDRs (ETF e ação)
    trade_bps_hedge: float = Field(ge=0)  # IVVB11
    borrow_rate_ann: float = Field(ge=0)  # aluguel do IVVB11
    cash_spread_bps: float = Field(ge=0)  # caixa rende CDI − spread
    days_per_year: int = Field(gt=0)


class SectorModel(_Strict):
    universe: Literal["amplo", "completo"]
    etfs_file: str  # csv bdr, etf_us, universo
    min_history_days: int = Field(ge=0)
    rebalance: Literal["none", "monthly"]  # volta para 1/n no 1º pregão do mês


class DividendModel(_Strict):
    universe: Literal["spx_pit", "bdr_list"]
    bdr_list_file: str  # csv com coluna lastro (acoes.csv)
    exclude_industry_contains: list[str]  # ex.: ["REIT"]
    n_slots: int = Field(gt=0)
    slot_weight: float = Field(gt=0, le=1)  # fração do NAV por entrada
    dy_quantile: float = Field(ge=0, lt=1)  # entra se DY >= quantil (0,75 = 1º quartil)
    min_dy: float  # DY estritamente maior que isso
    max_per_sector: int = Field(gt=0)
    stop_drawdown: float = Field(gt=0, lt=1)  # 6% do pico do relativo
    cooldown_days: int = Field(ge=0)
    min_history_days: int = Field(ge=0)


class BacktestConfig(_Strict):
    model: Literal["sector", "dividend"]
    variants: list[Variant]
    initial_nav: float = Field(gt=0)
    calibration_end: dt.date
    results_dir: str


class Config(_Strict):
    name: str
    data: DataConfig
    trend: TrendConfig
    hedge: HedgeConfig
    costs: CostsConfig
    sector: SectorModel
    dividend: DividendModel
    backtest: BacktestConfig


def load_config(path: str | Path) -> Config:
    return Config.model_validate(load_raw(path))
