from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pairs_ibra.backtest.engine import run_backtest
from pairs_ibra.backtest.metrics import summary
from pairs_ibra.config import Config
from pairs_ibra.data.loaders import Dataset
from pairs_ibra.portfolio.sizing import pair_notionals
from pairs_ibra.selection.base import PairSpec
from tests.conftest import make_cfg

F = 30


def tiny_cfg(**over: dict[str, object]) -> Config:
    base: dict[str, dict[str, object]] = {
        "windows": {"formation_days": F, "trading_days": 1000},
        "costs": {"trading_cost_bps": 4, "btc_fallback_rate": 0.03, "cash_spread_bps": 0},
        "signal": {"retest_on_rebalance": False},
    }
    for k, v in over.items():
        base[k] = {**base.get(k, {}), **v}
    return make_cfg(**base)  # type: ignore[arg-type]


def tiny_dataset(spread: np.ndarray, cdi: float = 0.0) -> Dataset:
    n = len(spread)
    idx = pd.bdate_range("2010-01-04", periods=n)
    b = np.full(n, 10.0)
    a = 10.0 * np.exp(spread)
    adj = pd.DataFrame({"AAAA3": a, "BBBB3": b}, index=idx)
    true = pd.DataFrame(True, index=idx, columns=adj.columns)
    market = pd.DataFrame({"cdi_daily": cdi, "ibov_close": 100.0, "ibra_close": 100.0}, index=idx)
    sectors = pd.DataFrame({"setor": ["S1", "S1"], "subsetor": "x", "segmento": "x",
                            "emissor": ["AAAA", "BBBB"]}, index=adj.columns)
    return Dataset(close_adj=adj, close_raw=adj.copy(), turnover=adj * 1e9, traded=true,
                   in_index=true.copy(), market=market, sectors=sectors)


class StubSelector:
    def __init__(self, specs: list[PairSpec]) -> None:
        self.specs = specs
        self.calls: list[pd.Timestamp] = []

    def select(self, log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
               cfg: Config, sectors: pd.DataFrame) -> list[PairSpec]:
        assert log_prices.loc[log_prices.index < asof].index.max() < asof
        self.calls.append(asof)
        return self.specs


def stub_spec(ds: Dataset) -> PairSpec:
    t0, t1 = ds.dates[0], ds.dates[F - 1]
    return PairSpec("AAAA3", "BBBB3", 1.0, 0.0, 0.0, 0.01, 5.0, "stub", t0, t1, False, True, 1.0,
                    "S1", "S1")


def test_cash_only_grows_at_cdi_minus_spread() -> None:
    ds = tiny_dataset(np.zeros(80), cdi=0.0004)
    cfg = tiny_cfg(costs={"cash_spread_bps": 4})
    res = run_backtest(ds, cfg, StubSelector([]))
    daily = 0.0004 - 0.0004 / 252
    expected = cfg.backtest.initial_capital * (1 + daily) ** (len(res.nav) - 1)
    assert res.nav["nav"].iloc[-1] == pytest.approx(expected, rel=1e-12)
    assert res.trades.empty


def test_single_trade_accounting_and_t_plus_1() -> None:
    n = 60
    s = np.zeros(n)
    k = F + 5
    s[k] = s[k + 1] = -0.025           # z = −2,5 no fechamento de k
    ds = tiny_dataset(s)
    cfg = tiny_cfg()
    res = run_backtest(ds, cfg, StubSelector([stub_spec(ds)]))
    assert len(res.trades) == 1
    tr = res.trades.iloc[0]
    assert tr["entry_signal_date"] == ds.dates[k]
    assert tr["entry_date"] == ds.dates[k + 1]           # executa em t+1
    assert tr["exit_signal_date"] == ds.dates[k + 2]     # z volta a 0 → convergência
    assert tr["exit_date"] == ds.dates[k + 3]
    assert tr["exit_reason"] == "convergencia"
    assert tr["direction"] == 1

    cap = cfg.backtest.initial_capital
    na, nb = pair_notionals(cap, cfg.sizing, 1.0, 10 * math.exp(-0.025), 10.0)
    gross = na * (math.exp(0.025) - 1)
    assert tr["gross_pnl"] == pytest.approx(gross, rel=1e-9)
    exit_val = na * math.exp(0.025) + nb
    costs = 4e-4 * (na + nb) + 4e-4 * exit_val
    assert tr["trading_costs"] == pytest.approx(costs, rel=1e-9)
    btc = 2 * nb * 0.03 / 252
    assert tr["btc_costs"] == pytest.approx(btc, rel=1e-9)
    assert res.nav["nav"].iloc[-1] == pytest.approx(cap + gross - costs - btc, rel=1e-12)


def test_short_spread_and_stop_z_with_cooldown() -> None:
    n = 70
    s = np.zeros(n)
    k = F + 2
    s[k:k + 3] = 0.03                   # z = 3 → vende spread
    s[k + 3:k + 20] = 0.045             # z = 4,5 → stop de spread
    ds = tiny_dataset(s)
    cfg = tiny_cfg(signal={"stop_loss_pct": 0.5})
    res = run_backtest(ds, cfg, StubSelector([stub_spec(ds)]))
    first = res.trades.iloc[0]
    assert first["direction"] == -1 and first["exit_reason"] == "stop_spread"
    # z fica em 4,5 (≥ stop_z): não reentra; depois volta a 0: nenhuma entrada nova
    assert len(res.trades) == 1


def test_cooldown_blocks_reentry_for_n_days() -> None:
    n = 80
    s = np.zeros(n)
    k = F + 2
    s[k:k + 2] = -0.025                 # entra
    s[k + 2] = -0.045                   # stop de spread (z = −4,5)
    s[k + 3:] = -0.025                  # z = −2,5 de novo: bloqueado pelo cooldown
    ds = tiny_dataset(s)
    cfg = tiny_cfg(signal={"stop_loss_pct": 0.5, "time_stop_days": 200})
    res = run_backtest(ds, cfg, StubSelector([stub_spec(ds)]))
    t = res.trades
    assert t.iloc[0]["exit_reason"] == "stop_spread"
    stop_signal = ds.dates.get_loc(t.iloc[0]["exit_signal_date"])
    re_signal = ds.dates.get_loc(t.iloc[1]["entry_signal_date"])
    assert re_signal - stop_signal == cfg.signal.cooldown_days + 1


def test_time_stop() -> None:
    n = 120
    s = np.zeros(n)
    s[F + 2:] = -0.025
    ds = tiny_dataset(s)
    cfg = tiny_cfg(signal={"time_stop_days": 10})
    res = run_backtest(ds, cfg, StubSelector([stub_spec(ds)]))
    assert res.trades.iloc[0]["exit_reason"] == "stop_tempo"
    assert res.trades.iloc[0]["days_open"] == 11  # decide em 10, executa no pregão seguinte


def test_stop_loss() -> None:
    n = 60
    s = np.zeros(n)
    k = F + 2
    s[k:k + 2] = -0.025
    s[k + 2:] = -0.035                 # z = −3,5: ainda aberto, mas perde
    ds = tiny_dataset(s)
    cfg = tiny_cfg(signal={"stop_loss_pct": 0.005})
    res = run_backtest(ds, cfg, StubSelector([stub_spec(ds)]))
    assert res.trades.iloc[0]["exit_reason"] == "stop_financeiro"


def test_universe_exit() -> None:
    n = 60
    s = np.zeros(n)
    k = F + 2
    s[k:] = -0.025
    ds = tiny_dataset(s)
    ds.in_index.iloc[k + 5:, 0] = False
    res = run_backtest(ds, tiny_cfg(), StubSelector([stub_spec(ds)]))
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "saida_universo"
    assert tr["exit_signal_date"] == ds.dates[k + 5]
    assert len(res.trades) == 1   # não reentra fora do índice


def test_end_of_backtest_closes_everything() -> None:
    n = 50
    s = np.zeros(n)
    s[F + 2:] = -0.025
    ds = tiny_dataset(s)
    res = run_backtest(ds, tiny_cfg(), StubSelector([stub_spec(ds)]))
    assert res.trades.iloc[-1]["exit_reason"] == "fim_backtest"
    assert res.nav["n_positions"].iloc[-1] == 0


def test_rebalance_schedule() -> None:
    ds = tiny_dataset(np.zeros(100))
    stub = StubSelector([])
    run_backtest(ds, tiny_cfg(windows={"trading_days": 20}), stub)
    assert stub.calls == [ds.dates[i] for i in range(F, 100, 20)]


def test_full_synthetic_backtest(dataset: Dataset, synth_cfg: Config) -> None:
    res = run_backtest(dataset, synth_cfg)
    assert len(res.trades) > 50
    nav = res.nav
    assert (nav["gross"] <= synth_cfg.portfolio.max_gross_leverage * nav["nav"] + 1).all()
    # cada par aberto ocupa ~2% bruto do NAV
    one = res.trades["entry_gross"] / synth_cfg.backtest.initial_capital
    assert one.median() == pytest.approx(0.02, rel=0.25)
    s = summary(res)
    assert s["performance"]["sharpe"] > 0  # pares plantados devem dar lucro
    assert abs(s["performance"]["corr_ibov"]) < 0.5
    assert set(res.trades["exit_reason"]) <= {
        "convergencia", "stop_spread", "stop_financeiro", "stop_tempo", "quebra_estrutural",
        "saida_universo", "dado_faltante", "fim_backtest"}
    assert not res.pairs_selected.empty
