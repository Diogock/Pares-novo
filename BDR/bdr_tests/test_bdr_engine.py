import numpy as np
import pandas as pd
from bdr_models.engine import BookView, Order, run

from .conftest import bdays, make_cfg


class Script:
    """Estratégia de teste: ordens fixas por índice do dia de decisão."""

    def __init__(self, plan: dict[int, list[Order]]) -> None:
        self.plan = plan
        self.views: list[BookView] = []

    def on_close(self, view: BookView) -> list[Order]:
        self.views.append(view)
        return self.plan.get(view.i, [])


def _px(n: int, rets: dict[str, float]) -> pd.DataFrame:
    idx = bdays(n)
    return pd.DataFrame({t: (1 + r) ** np.arange(n) for t, r in rets.items()}, index=idx)


def test_caixa_rende_cdi_menos_spread() -> None:
    cfg = make_cfg()
    px = _px(11, {"A": 0.0})
    cdi = pd.Series(0.0004, index=px.index)
    res = run(cfg, "long_only", Script({}), px, px["A"], cdi)
    daily = 0.0004 - 4 / 1e4 / 252
    assert np.isclose(res.nav["nav"].iloc[-1], cfg.backtest.initial_nav * (1 + daily) ** 10)


def test_execucao_em_t_mais_1_com_custo() -> None:
    cfg = make_cfg()
    px = _px(6, {"A": 0.01})
    zero = pd.Series(0.0, index=px.index)
    res = run(cfg, "long_only", Script({1: [Order("A", 0.5, "x")]}), px, px["A"], zero)
    nav0 = cfg.backtest.initial_nav
    assert res.nav["long"].iloc[1] == 0.0  # decisão em 1, nada executado ainda
    assert np.isclose(res.nav["long"].iloc[2], 0.5 * nav0)  # executa no fechamento de 2
    assert np.isclose(res.nav["trading_costs"].iloc[2], 0.5 * nav0 * 8 / 1e4)
    assert np.isclose(res.nav["long"].iloc[3], 0.5 * nav0 * 1.01)  # deriva com o preço


def test_ls_notional_hedge_igual_ao_long_e_aluguel() -> None:
    cfg = make_cfg()
    px = _px(8, {"A": 0.02, "H": 0.0})
    zero = pd.Series(0.0, index=px.index)
    res = run(cfg, "ls_notional", Script({0: [Order("A", 0.3, "x")]}), px[["A"]], px["H"], zero)
    nav = res.nav
    assert np.isclose(nav["short"].iloc[1], nav["long"].iloc[1])
    # banda de 5%: o hedge só é ajustado quando o descasamento passa da banda
    gap = (nav["long"] - nav["short"]).abs() / nav["long"]
    assert (gap.iloc[1:] <= 0.05 + 1e-12).all()
    assert np.isclose(nav["borrow_costs"].iloc[2], nav["short"].iloc[1] * 0.03 / 252)


def test_ls_beta_usa_beta_do_ativo() -> None:
    cfg = make_cfg()
    px = _px(5, {"A": 0.0, "H": 0.0})
    zero = pd.Series(0.0, index=px.index)
    beta = pd.DataFrame({"A": 1.4}, index=px.index)
    res = run(cfg, "ls_beta", Script({0: [Order("A", 0.2, "x")]}), px[["A"]], px["H"], zero, beta)
    assert np.isclose(res.nav["short"].iloc[1], 1.4 * res.nav["long"].iloc[1])


def test_sem_preco_zera_posicao() -> None:
    cfg = make_cfg()
    px = _px(6, {"A": 0.01})
    px.iloc[4:, 0] = np.nan
    zero = pd.Series(0.0, index=px.index)
    res = run(cfg, "long_only", Script({0: [Order("A", 0.5, "x")]}), px, px["A"].ffill(), zero)
    assert res.nav["long"].iloc[4] == 0.0
    assert res.trades["exit_reason"].tolist() == ["dado_faltante"]
