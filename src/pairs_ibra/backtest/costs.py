"""Modelo único de custos (CLAUDE.md, seção 5.6).

- negociação: ``trading_cost_bps`` sobre cada R$ negociado (compra ou venda),
  já incluindo corretagem, emolumentos e slippage;
- aluguel (BTC): taxa a.a. sobre o valor da perna vendida, por pregão (base 252);
- caixa: rende CDI − ``cash_spread_bps`` a.a.
"""

from __future__ import annotations

from pairs_ibra.config import CostsConfig

DAYS_PER_YEAR = 252


def trading_cost(traded_notional: float, cfg: CostsConfig) -> float:
    return abs(traded_notional) * cfg.trading_cost_bps / 1e4


def btc_daily_cost(short_notional: float, cfg: CostsConfig, rate: float | None = None) -> float:
    r = cfg.btc_fallback_rate if rate is None else rate
    return abs(short_notional) * r / DAYS_PER_YEAR


def cash_daily_rate(cdi_daily: float, cfg: CostsConfig) -> float:
    return cdi_daily - cfg.cash_spread_bps / 1e4 / DAYS_PER_YEAR
