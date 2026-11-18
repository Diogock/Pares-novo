"""Garantia de walk-forward estrito (CLAUDE.md, seção 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pairs_ibra.backtest.engine import run_backtest
from pairs_ibra.config import Config
from pairs_ibra.data.loaders import Dataset
from pairs_ibra.data.universe import eligible_universe
from pairs_ibra.selection import get_selector
from pairs_ibra.selection.base import formation_window


@pytest.mark.parametrize("method", ["cointegration", "distance"])
def test_selection_ignores_future(dataset: Dataset, synth_cfg: Config, method: str) -> None:
    cfg = synth_cfg.model_copy(update={"selection": synth_cfg.selection.model_copy(
        update={"method": method})})
    asof = dataset.dates[400]
    logp = np.log(dataset.close_adj)
    u = eligible_universe(dataset, asof, cfg)
    base = get_selector(method).select(logp, u, asof, cfg, dataset.sectors)
    noisy = logp.copy()
    rng = np.random.default_rng(0)
    future = noisy.index >= asof
    noisy.loc[future] = noisy.loc[future] + rng.normal(0, 0.5, noisy.loc[future].shape)
    assert get_selector(method).select(noisy, u, asof, cfg, dataset.sectors) == base


def test_formation_window_asserts() -> None:
    idx = pd.bdate_range("2020-01-01", periods=10)
    df = pd.DataFrame({"A": np.arange(10.0)}, index=idx)
    w = formation_window(df, ["A"], idx[5], 3)
    assert list(w.index) == list(idx[2:5])


def test_engine_truncation_invariance(dataset: Dataset, synth_cfg: Config) -> None:
    """Rodar com dados até D ou com o histórico inteiro dá o mesmo resultado antes de D."""
    full_ds = dataset.truncate(dataset.dates[720])
    cut = dataset.dates[600]
    short = run_backtest(full_ds.truncate(cut), synth_cfg)
    full = run_backtest(full_ds, synth_cfg)
    before = full.nav.index < cut
    pd.testing.assert_frame_equal(full.nav.loc[before], short.nav.loc[short.nav.index < cut])
    ft = full.trades[full.trades["exit_date"] < cut].reset_index(drop=True)
    st = short.trades[short.trades["exit_date"] < cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(ft, st)
    assert len(ft) > 10
