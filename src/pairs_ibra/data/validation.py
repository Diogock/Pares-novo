"""Checagens de qualidade dos dados (CLAUDE.md, seção 4.3)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pairs_ibra.data.loaders import Dataset


def find_duplicate_series(prices: pd.DataFrame, min_identical: float = 0.9,
                          min_overlap: int = 60) -> list[tuple[str, str, float]]:
    """Pares de colunas com retornos idênticos na maior parte dos dias em comum.

    Detecta o caso ticker antigo + ticker novo com a mesma história.
    """
    rets = prices.pct_change(fill_method=None)
    valid = rets.notna().sum()
    cols = [c for c in rets.columns if valid[c] >= min_overlap]
    r = rets[cols]
    corr = r.corr(min_periods=min_overlap).to_numpy()
    out: list[tuple[str, str, float]] = []
    n = len(cols)
    for i in range(n):
        for j in range(i + 1, n):
            if not np.isfinite(corr[i, j]) or corr[i, j] < 0.99:
                continue
            a, b = r.iloc[:, i], r.iloc[:, j]
            both = a.notna() & b.notna()
            if both.sum() < min_overlap:
                continue
            frac = float((np.abs(a[both] - b[both]) < 1e-9).mean())
            if frac >= min_identical:
                out.append((cols[i], cols[j], frac))
    return out


def large_returns(prices: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Retornos diários acima de |threshold| (provável ajuste faltando)."""
    rets = prices.pct_change(fill_method=None)
    s = pd.Series(rets.to_numpy().ravel(), index=pd.MultiIndex.from_product(
        [rets.index, rets.columns]))
    out = s.loc[s.abs() > threshold].reset_index()
    out.columns = pd.Index(["date", "ticker", "return"])
    return out


def internal_gaps(prices: pd.DataFrame, min_gap: int = 2) -> pd.DataFrame:
    """Buracos (dias sem preço) entre o primeiro e o último dado de cada ativo."""
    rows = []
    for t in prices.columns:
        s = prices[t]
        first, last = s.first_valid_index(), s.last_valid_index()
        if first is None or last is None:
            continue
        na = s.loc[first:last].isna().to_numpy()
        if not na.any():
            continue
        run = 0
        longest = 0
        for v in na:
            run = run + 1 if v else 0
            longest = max(longest, run)
        if longest >= min_gap:
            rows.append({"ticker": t, "missing_days": int(na.sum()), "longest_gap": longest})
    return pd.DataFrame(rows, columns=["ticker", "missing_days", "longest_gap"])


@dataclass
class QualityReport:
    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    large_returns: pd.DataFrame = field(default_factory=pd.DataFrame)
    gaps: pd.DataFrame = field(default_factory=pd.DataFrame)
    duplicates: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.critical

    def to_markdown(self) -> str:
        lines = ["# Relatório de qualidade dos dados", ""]
        lines.append(f"Status: **{'OK' if self.ok else 'ERRO CRÍTICO'}**")
        lines.append("")
        for title, items in (("Erros críticos", self.critical), ("Avisos", self.warnings)):
            lines.append(f"## {title} ({len(items)})")
            lines.extend(f"- {i}" for i in items)
            lines.append("")
        lines.append(f"## Retornos diários acima do limite ({len(self.large_returns)})")
        if len(self.large_returns):
            lines.append(self.large_returns.to_string(index=False))
        lines.append("")
        lines.append(f"## Buracos nas séries ({len(self.gaps)})")
        if len(self.gaps):
            lines.append(self.gaps.sort_values("longest_gap", ascending=False).to_string(index=False))
        return "\n".join(lines)


def quality_report(ds: Dataset, max_abs_return: float,
                   build_warnings: list[str] | None = None) -> QualityReport:
    rep = QualityReport(warnings=list(build_warnings or []))
    rep.large_returns = large_returns(ds.close_adj, max_abs_return)
    if len(rep.large_returns):
        rep.critical.append(
            f"{len(rep.large_returns)} retornos diários > |{max_abs_return:.0%}| sem evento associado "
            "(verificar ajuste por proventos)")
    rep.gaps = internal_gaps(ds.close_adj)
    if len(rep.gaps):
        rep.warnings.append(f"{len(rep.gaps)} ativos com buracos > 1 dia (inelegíveis nessas janelas)")
    rep.duplicates = find_duplicate_series(ds.close_adj)
    if rep.duplicates:
        rep.critical.append(f"séries duplicadas restantes: {rep.duplicates}")
    raw_ok = ds.close_raw.notna().sum().sum()
    if raw_ok == 0:
        rep.critical.append("prices_raw vazio")
    bad_cdi = ds.market["cdi_daily"].abs() > 0.01
    if bad_cdi.any():
        rep.critical.append(f"CDI diário > 1% em {int(bad_cdi.sum())} datas (checar índice acumulado)")
    if not ds.in_index.any(axis=1).all():
        n = int((~ds.in_index.any(axis=1)).sum())
        rep.warnings.append(f"{n} pregões sem nenhuma ação no índice (antes da 1ª carteira?)")
    unclassified = int((ds.sectors["setor"] == "SEM_SETOR").sum())
    if unclassified:
        rep.warnings.append(f"{unclassified} tickers sem setor no Excel auxiliar")
    neg = (ds.close_adj <= 0).sum().sum()
    if neg:
        rep.critical.append(f"{int(neg)} preços ajustados <= 0")
    return rep
