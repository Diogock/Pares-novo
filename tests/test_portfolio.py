from __future__ import annotations

import pandas as pd
import pytest

from pairs_ibra.backtest.costs import btc_daily_cost, cash_daily_rate, trading_cost
from pairs_ibra.config import load_config
from pairs_ibra.portfolio.constraints import apply_constraints
from pairs_ibra.portfolio.sizing import leg_weights, pair_notionals, round_to_lot
from pairs_ibra.selection.base import PairSpec
from tests.conftest import ROOT

CFG = load_config(ROOT / "configs" / "base.yaml")


def spec(a: str, b: str, score: float, sa: str = "S1", sb: str = "S1", same_issuer: bool = False) -> PairSpec:
    t = pd.Timestamp("2010-01-01")
    return PairSpec(a, b, 1.0, 0.0, 0.0, 0.1, 5.0, "cointegration", t, t, same_issuer,
                    sa == sb, score, sa, sb)


def test_leg_weights() -> None:
    assert leg_weights("dollar", 3.0) == (1.0, 1.0)
    wa, wb = leg_weights("gamma", 3.0)
    assert wb / wa == pytest.approx(3.0) and wa + wb == pytest.approx(2.0)
    wa, wb = leg_weights("beta", 1.0, beta_a=2.0, beta_b=1.0)
    assert 2.0 * wa == pytest.approx(1.0 * wb)
    assert leg_weights("beta", 1.0, beta_a=-1.0) == (1.0, 1.0)


def test_lot_rounding() -> None:
    assert round_to_lot(1_000_000, 10.0, 100) == 1_000_000
    assert round_to_lot(1_049, 10.0, 100) == 1_000
    assert round_to_lot(400, 10.0, 100) == 0.0     # < 1 lote é ignorado
    na, nb = pair_notionals(100e6, CFG.sizing, 1.0, 25.0, 13.0)
    assert na == pytest.approx(1e6, rel=0.01) and nb == pytest.approx(1e6, rel=0.01)


def test_costs() -> None:
    # girar 100% do NAV custa 4 bps
    assert trading_cost(100e6, CFG.costs) == pytest.approx(40_000)
    assert btc_daily_cost(-1e6, CFG.costs) * 252 == pytest.approx(30_000)
    assert cash_daily_rate(0.0004, CFG.costs) == pytest.approx(0.0004 - 0.0004 / 252)


def test_constraints_per_stock_and_sector() -> None:
    ranked = [spec("A", "B", 9), spec("A", "C", 8), spec("A", "D", 7), spec("E", "F", 6, "S2", "S2")]
    out = apply_constraints(ranked, CFG.portfolio.model_copy(update={"n_pairs": 10}))
    assert [(s.leg_a, s.leg_b) for s in out] == [("A", "B"), ("A", "C"), ("E", "F")]
    many = [spec(f"X{i}", f"Y{i}", 10 - i) for i in range(10)]
    out = apply_constraints(many, CFG.portfolio.model_copy(update={"n_pairs": 10}))
    assert len(out) == 3   # 30% de 10


def test_constraints_same_issuer_flag() -> None:
    r = [spec("PETR3", "PETR4", 5, same_issuer=True)]
    assert apply_constraints(r, CFG.portfolio) == r
    assert apply_constraints(r, CFG.portfolio.model_copy(update={"include_same_issuer": False})) == []
