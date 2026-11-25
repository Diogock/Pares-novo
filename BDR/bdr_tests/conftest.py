from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from bdr_models.config import Config

from pairs_ibra.config import load_raw

BASE = "BDR/configs/base.yaml"


def make_cfg(**over: Any) -> Config:
    """Config base com sobrescritas por seção: make_cfg(costs={"trade_bps_long": 0})."""
    raw = load_raw(BASE)
    for sec, vals in over.items():
        if isinstance(vals, dict):
            raw[sec] = {**raw[sec], **vals}
        else:
            raw[sec] = vals
    return Config.model_validate(raw)


@pytest.fixture
def cfg() -> Config:
    return make_cfg()


def bdays(n: int, start: str = "2010-01-04") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)
