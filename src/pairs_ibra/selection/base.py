"""Interface comum dos métodos de seleção (CLAUDE.md, seção 7.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from pairs_ibra.config import Config


@dataclass(frozen=True)
class PairSpec:
    leg_a: str
    leg_b: str
    gamma: float
    alpha: float
    mu: float
    sigma: float
    half_life: float
    method: str
    formation_start: pd.Timestamp
    formation_end: pd.Timestamp
    same_issuer: bool
    same_sector: bool
    score: float
    sector_a: str = ""
    sector_b: str = ""
    pvalue: float = float("nan")
    n_trades_in_sample: int = 0

    @property
    def key(self) -> tuple[str, str]:
        """Identificador do par independente da ordem das pernas."""
        a, b = sorted((self.leg_a, self.leg_b))
        return a, b


class PairSelector(Protocol):
    def select(self, log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
               cfg: Config, sectors: pd.DataFrame) -> list[PairSpec]:
        """Candidatos ranqueados por score (desc). ``log_prices`` só com datas < ``asof``."""
        ...


def check_no_lookahead(frame: pd.DataFrame, asof: pd.Timestamp) -> None:
    if len(frame) and frame.index.max() >= asof:
        raise AssertionError(f"look-ahead: dados até {frame.index.max()} na seleção de {asof}")


def formation_window(log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
                     formation_days: int) -> pd.DataFrame:
    """Últimos ``formation_days`` pregões antes de ``asof``, só ativos sem buracos."""
    w = log_prices.loc[log_prices.index < asof, [t for t in universe if t in log_prices.columns]]
    w = w.iloc[-formation_days:]
    check_no_lookahead(w, asof)
    return w.dropna(axis=1, how="any")


def sector_of(sectors: pd.DataFrame, t: str) -> str:
    if t in sectors.index:
        return str(sectors.at[t, "setor"])
    return "SEM_SETOR"


def issuer_of(sectors: pd.DataFrame, t: str) -> str:
    if t in sectors.index and isinstance(sectors.at[t, "emissor"], str):
        return str(sectors.at[t, "emissor"])
    return t[:4]
