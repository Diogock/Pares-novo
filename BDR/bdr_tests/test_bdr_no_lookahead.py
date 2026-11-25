"""Perturbar os dados depois de T não muda nada até T (pipeline completo, dados sintéticos)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from bdr_models.data import load_market_data
from bdr_models.runner import run_variant
from bdr_models.synthetic import generate

from .conftest import make_cfg


@pytest.mark.parametrize("model", ["sector", "dividend"])
def test_no_lookahead(tmp_path: Path, model: str) -> None:
    generate(tmp_path, end="2011-12-31", n_stocks=24)
    cfg = make_cfg(
        data={"raw_dir": str(tmp_path), "end": "2011-12-31"},
        backtest={"model": model, "variants": ["ls_beta"], "calibration_end": "2009-12-31"},
    )
    md = load_market_data(cfg)
    base = run_variant(cfg, md, "ls_beta")
    cut = md.sessions[len(md.sessions) // 2]
    later = md.sessions > cut
    rng = np.random.default_rng(3)
    noise = pd.DataFrame(
        rng.lognormal(0, 0.05, md.px_brl.shape), index=md.px_brl.index, columns=md.px_brl.columns
    ).where(pd.Series(later, index=md.px_brl.index), 1.0, axis=0)
    px2 = md.px_brl * noise.cumprod()
    dy2 = (
        md.dy.where(~pd.Series(later, index=md.dy.index), md.dy[::-1].to_numpy(), axis=0)
        if md.dy is not None
        else None
    )
    md2 = type(md)(
        **{
            **md.__dict__,
            "px_brl": px2,
            "dy": dy2,
            "ret_usd": md.ret_usd.where(~pd.Series(later, index=md.ret_usd.index), 0.0, axis=0),
        }
    )
    alt = run_variant(cfg, md2, "ls_beta")
    upto = base.nav.index <= cut
    pd.testing.assert_frame_equal(base.nav.loc[upto], alt.nav.loc[upto])
    assert base.nav["long"].gt(0).any()
