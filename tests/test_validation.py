from __future__ import annotations

import numpy as np
import pandas as pd

from pairs_ibra.data.loaders import Dataset
from pairs_ibra.data.validation import (
    find_duplicate_series,
    internal_gaps,
    large_returns,
    quality_report,
)


def _prices() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=200)
    a = 10 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    b = 20 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    return pd.DataFrame({"AAAA3": a, "BBBB3": b, "CCCC3": a}, index=idx)


def test_duplicates_detected() -> None:
    dups = find_duplicate_series(_prices())
    assert [(a, b) for a, b, _ in dups] == [("AAAA3", "CCCC3")]


def test_large_returns_flagged() -> None:
    p = _prices()
    p.iloc[100:, 1] *= 2.0   # desdobramento não ajustado
    lr = large_returns(p, 0.40)
    assert list(lr["ticker"]) == ["BBBB3"]
    assert lr["date"].iloc[0] == p.index[100]


def test_internal_gaps() -> None:
    p = _prices()
    p.iloc[50:55, 0] = np.nan
    p.iloc[:30, 1] = np.nan   # antes do IPO não é buraco
    g = internal_gaps(p)
    assert list(g["ticker"]) == ["AAAA3"]
    assert g["longest_gap"].iloc[0] == 5


def test_quality_report_on_synthetic(dataset: Dataset) -> None:
    rep = quality_report(dataset, 0.40)
    assert rep.ok, rep.critical
    assert "Relatório de qualidade" in rep.to_markdown()
