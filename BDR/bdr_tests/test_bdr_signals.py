import numpy as np
import pandas as pd
from bdr_models.config import TrendConfig
from bdr_models.signals import trend_conditions, trend_state

from .conftest import bdays

T = TrendConfig(fast=5, mid=10, slow=20, entry_high=20, exit_low=10)


def test_liga_em_alta_e_desliga_na_queda() -> None:
    up = np.linspace(1, 2, 60)
    down = np.linspace(2, 1.5, 30)
    r = pd.DataFrame({"A": np.r_[up, down]}, index=bdays(90))
    s = trend_state(r, T)["A"]
    assert not s.iloc[:20].any()  # sem histórico para a média de 20 e a máxima anterior
    assert s.iloc[20:60].all()
    assert not s.iloc[64:].any()  # MA5 < MA10 poucos dias depois do topo


def test_histerese_fica_ligado_sem_novo_rompimento() -> None:
    up = np.linspace(1, 2, 40)
    flat = np.full(15, 1.995)  # sem nova máxima, acima da mínima anterior
    r = pd.DataFrame({"A": np.r_[up, flat]}, index=bdays(55))
    e, x = trend_conditions(r, T)
    s = trend_state(r, T)["A"]
    assert s.iloc[39]
    assert not e["A"].iloc[41] and not x["A"].iloc[41]
    assert s.iloc[40:42].all()  # nem entrada nem saída: o estado persiste


def test_causal_futuro_nao_muda_passado() -> None:
    rng = np.random.default_rng(1)
    r = pd.DataFrame({"A": np.exp(np.cumsum(rng.normal(0, 0.01, 300)))}, index=bdays(300))
    base = trend_state(r, T)
    r2 = r.copy()
    r2.iloc[200:] *= 3.0
    alt = trend_state(r2, T)
    pd.testing.assert_frame_equal(base.iloc[:200], alt.iloc[:200])
