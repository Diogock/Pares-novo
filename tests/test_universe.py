from __future__ import annotations

import pandas as pd

from pairs_ibra.config import Config
from pairs_ibra.data.loaders import Dataset
from pairs_ibra.data.synthetic import SyntheticData
from pairs_ibra.data.universe import eligible_universe


def test_universe_filters(dataset: Dataset, synth_cfg: Config, synth: SyntheticData) -> None:
    asof = dataset.dates[300]
    u = eligible_universe(dataset, asof, synth_cfg)
    assert synth.planted[0].leg_a in u
    for t in synth.illiquid:
        assert t not in u                  # ADTV
    assert synth.ipo not in u              # IPO em T/3: sem 98% dos dias na formação
    late = dataset.dates[-1]
    assert synth.delisted not in eligible_universe(dataset, late, synth_cfg)


def test_universe_empty_before_formation(dataset: Dataset, synth_cfg: Config) -> None:
    assert eligible_universe(dataset, dataset.dates[100], synth_cfg) == []


def test_universe_respects_index_membership(dataset: Dataset, synth_cfg: Config,
                                            synth: SyntheticData) -> None:
    asof = dataset.dates[300]
    t = synth.planted[0].leg_a
    ds2 = Dataset(**{**dataset.__dict__, "in_index": dataset.in_index.copy()})
    ds2.in_index.loc[asof, t] = False
    assert t not in eligible_universe(ds2, asof, synth_cfg)


def test_universe_uses_only_past_liquidity(dataset: Dataset, synth_cfg: Config) -> None:
    asof = dataset.dates[300]
    base = eligible_universe(dataset, asof, synth_cfg)
    turnover = dataset.turnover.copy()
    turnover.loc[turnover.index >= asof] = 0.0
    ds2 = Dataset(**{**dataset.__dict__, "turnover": turnover})
    assert eligible_universe(ds2, asof, synth_cfg) == base
    assert isinstance(asof, pd.Timestamp)
