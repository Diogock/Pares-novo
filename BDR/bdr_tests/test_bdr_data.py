import numpy as np
import pandas as pd
from bdr_models.data import net_total_return, rolling_beta, synthetic_brl, to_sessions

from .conftest import bdays


def test_net_total_return_aplica_retencao() -> None:
    idx = bdays(3)
    px = pd.DataFrame({"A": [100.0, 101.0, 102.0]}, index=idx)
    tr = pd.DataFrame({"A": [100.0, 102.0, 104.04]}, index=idx)  # 1 p.p. de dividendo por dia
    r = net_total_return(px, tr, 0.30)
    r_px = 101 / 100 - 1
    assert np.isclose(r.iloc[1, 0], r_px + 0.7 * (0.02 - r_px))


def test_synthetic_brl_compoe_cambio() -> None:
    idx = bdays(3)
    ret = pd.DataFrame({"A": [np.nan, 0.01, -0.02]}, index=idx)
    fx = pd.Series([5.0, 5.1, 5.0], index=idx)
    lvl = synthetic_brl(ret, fx, ret.notna() | True)
    assert lvl.iloc[0, 0] == 1.0
    assert np.isclose(lvl.iloc[1, 0] / lvl.iloc[0, 0], 1.01 * 1.02)
    assert np.isclose(lvl.iloc[2, 0] / lvl.iloc[1, 0], 0.98 * (5.0 / 5.1))


def test_synthetic_brl_nan_fora_do_historico() -> None:
    idx = bdays(4)
    ret = pd.DataFrame({"A": [np.nan, np.nan, 0.01, 0.01]}, index=idx)
    valid = pd.DataFrame({"A": [False, True, True, False]}, index=idx)
    lvl = synthetic_brl(ret, pd.Series(1.0, index=idx), valid)
    assert np.isnan(lvl.iloc[0, 0]) and np.isnan(lvl.iloc[3, 0])
    assert lvl.iloc[1, 0] == 1.0 and np.isclose(lvl.iloc[2, 0], 1.01)


def test_to_sessions_ffill_limitado() -> None:
    idx = bdays(10)
    df = pd.DataFrame({"A": [1.0] + [np.nan] * 9}, index=idx)
    out = to_sessions(df, idx, limit=2)
    assert out["A"].notna().sum() == 3


def test_rolling_beta_recupera_beta_conhecido() -> None:
    rng = np.random.default_rng(0)
    idx = bdays(600)
    m = pd.Series(rng.normal(0, 0.01, 600), index=idx)
    ret = pd.DataFrame({"A": 1.5 * m + rng.normal(0, 0.002, 600), "B": 3.0 * m}, index=idx)
    b = rolling_beta(ret, m, 252, 126, 0.5, 2.0)
    assert abs(b["A"].iloc[-1] - 1.5) < 0.05
    assert b["B"].iloc[-1] == 2.0  # limitado
    assert b["A"].iloc[:125].isna().all()  # sem histórico mínimo
