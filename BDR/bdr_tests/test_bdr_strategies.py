import numpy as np
import pandas as pd
from bdr_models.engine import BookView
from bdr_models.strategies import DividendStrategy, SectorStrategy

from .conftest import bdays, make_cfg


def _view(i: int, idx: pd.DatetimeIndex, pos: dict[str, float]) -> BookView:
    return BookView(i=i, date=idx[i], nav=100.0, positions=pos)


def test_setorial_um_sobre_n_do_universo() -> None:
    cfg = make_cfg(sector={"rebalance": "none"})
    idx = bdays(3)
    state = pd.DataFrame({"A": [1, 1, 0], "B": [0, 1, 1], "C": [0, 0, 0]}, index=idx).astype(bool)
    avail = pd.DataFrame(True, index=idx, columns=state.columns)
    s = SectorStrategy(state, avail, cfg.sector)
    o = s.on_close(_view(0, idx, {}))
    assert [(x.ticker, round(x.weight, 4)) for x in o] == [("A", 0.3333)]
    o = s.on_close(_view(2, idx, {"A": 33.0, "B": 33.0}))
    assert {(x.ticker, x.weight) for x in o} == {("A", 0.0)}


def _div(
    n_days: int, rel: dict[str, list[float]], dy: dict[str, float], **over: object
) -> tuple[DividendStrategy, pd.DatetimeIndex]:
    cfg = make_cfg(dividend={**over})
    idx = bdays(n_days)
    r = pd.DataFrame(rel, index=idx)
    state = pd.DataFrame(True, index=idx, columns=r.columns)
    d = pd.DataFrame({t: [v] * n_days for t, v in dy.items()}, index=idx)
    uni = pd.DataFrame(True, index=idx, columns=r.columns)
    sectors = {t: f"S{k}" for k, t in enumerate(r.columns)}
    return DividendStrategy(r, state, d, uni, sectors, cfg.dividend), idx


def test_stop_6pct_do_pico_e_cooldown() -> None:
    path = [1.0, 1.2, 1.2 * 0.95, 1.2 * 0.939, 1.0, 1.0] + [1.0] * 20
    s, idx = _div(len(path), {"A": path}, {"A": 0.05}, dy_quantile=0.0)
    assert [o.ticker for o in s.on_close(_view(0, idx, {}))] == ["A"]
    assert s.on_close(_view(1, idx, {"A": 5.0})) == []  # entrou; pico 1,2
    assert s.on_close(_view(2, idx, {"A": 5.0})) == []  # −5%: segura
    o = s.on_close(_view(3, idx, {"A": 5.0}))  # −6,1%: stop
    assert [(x.ticker, x.reason) for x in o] == [("A", "stop")]
    for i in range(4, 4 + 15):  # cooldown de 15 pregões após a execução da saída (i=4)
        assert s.on_close(_view(i, idx, {})) == [], i
    assert [x.ticker for x in s.on_close(_view(19, idx, {}))] == ["A"]


def test_prioridade_maior_dy_e_vagas_sem_trocar_incumbente() -> None:
    n = 3
    rel = {t: [1.0] * n for t in ["A", "B", "C", "D"]}
    dy = {"A": 0.02, "B": 0.09, "C": 0.07, "D": 0.08}
    s, idx = _div(n, rel, dy, n_slots=2, dy_quantile=0.0)
    o = s.on_close(_view(0, idx, {}))
    assert [x.ticker for x in o] == ["B", "D"]
    assert all(np.isclose(x.weight, 0.05) for x in o)
    # papel de DY maior aparece: o book cheio não troca quem está dentro
    s.D = s.D.copy()
    s.D[1, s.tickers.index("A")] = 0.20
    assert s.on_close(_view(1, idx, {"B": 5.0, "D": 5.0})) == []


def test_filtro_quartil_e_teto_setorial() -> None:
    n = 2
    tick = [f"T{k}" for k in range(8)]
    rel = {t: [1.0] * n for t in tick}
    dy = {t: 0.01 * (k + 1) for k, t in enumerate(tick)}  # 1% a 8%
    s, idx = _div(n, rel, dy)
    o = s.on_close(_view(0, idx, {}))
    assert [x.ticker for x in o] == ["T7", "T6"]  # só o quartil de cima (≥ 6,25%)
    s2, idx2 = _div(n, rel, dy, dy_quantile=0.0, max_per_sector=1)
    s2.sectors = dict.fromkeys(tick, "X")
    assert [x.ticker for x in s2.on_close(_view(0, idx2, {}))] == ["T7"]
