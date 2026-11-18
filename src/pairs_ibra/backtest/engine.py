"""Motor event-driven diário (CLAUDE.md, seção 6).

Ordem de cada pregão *t*:

1. marcação a mercado das posições (retorno ajustado t−1 → t), juros do caixa
   (CDI − spread) e aluguel da perna vendida;
2. execução das ordens decididas no fechamento de t−1 (saídas antes de entradas),
   ao preço de execução de *t* (fechamento por default);
3. se *t* é data de rebalanceamento: universo e seleção com dados < *t*;
   reteste dos pares abertos herdados;
4. z-score no fechamento de *t* e decisão da máquina de estados → ordens para t+1;
5. registro do NAV.

Contabilidade: NAV = caixa + Σ valor (com sinal) das pernas. A compra consome caixa,
a venda a descoberto gera caixa; todo o caixa rende CDI − ``cash_spread_bps``.
Pares abertos que saem da seleção continuam com γ, α, μ e σ originais até fechar,
sem novas entradas.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pairs_ibra.backtest.costs import btc_daily_cost, cash_daily_rate, trading_cost
from pairs_ibra.config import Config
from pairs_ibra.data.loaders import Dataset
from pairs_ibra.data.universe import eligible_universe
from pairs_ibra.portfolio.constraints import apply_constraints
from pairs_ibra.portfolio.sizing import pair_notionals, rolling_beta
from pairs_ibra.selection import PairSelector, PairSpec, get_selector
from pairs_ibra.selection.cointegration import residual_still_stationary
from pairs_ibra.signal.state_machine import (
    COOLDOWN_REASONS,
    Action,
    ExitReason,
    PairState,
    decide,
)
from pairs_ibra.spread.stats import EwmaZ

log = logging.getLogger(__name__)
Key = tuple[str, str]


@dataclass
class Position:
    spec: PairSpec
    state: PairState
    value_a: float
    value_b: float
    entry_value: float
    base: float
    entry_signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_z: float
    entry_gross: float
    costs: float = 0.0
    btc: float = 0.0
    days_open: int = 0
    exit_reason: ExitReason | None = None
    exit_signal_date: pd.Timestamp | None = None
    forced: ExitReason | None = None

    @property
    def value(self) -> float:
        return self.value_a + self.value_b

    @property
    def gross(self) -> float:
        return abs(self.value_a) + abs(self.value_b)


@dataclass
class PendingEntry:
    spec: PairSpec
    action: Action
    signal_date: pd.Timestamp
    z: float


@dataclass
class BacktestResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    pairs_selected: pd.DataFrame
    config: Config
    market: pd.DataFrame | None = None
    log_lines: list[str] = field(default_factory=list)


TRADE_COLUMNS = [
    "leg_a", "leg_b", "direction", "gamma", "method", "formation_end", "entry_signal_date",
    "entry_date", "exit_signal_date", "exit_date", "days_open", "entry_z", "exit_z",
    "entry_gross", "gross_pnl", "trading_costs", "btc_costs", "net_pnl", "return_on_leg",
    "exit_reason", "same_issuer", "same_sector", "sector_a", "sector_b",
]


def rebalance_indices(n_dates: int, formation: int, trading: int) -> list[int]:
    return list(range(formation, n_dates, trading))


class Backtester:
    def __init__(self, ds: Dataset, cfg: Config, selector: PairSelector | None = None) -> None:
        self.ds = ds
        self.cfg = cfg
        self.selector = selector or get_selector(cfg.selection.method)
        self.dates = ds.dates
        self.tickers = list(ds.tickers)
        self.col = {t: i for i, t in enumerate(self.tickers)}
        self.logp_df: pd.DataFrame = ds.close_adj.apply(np.log)
        self.logp = self.logp_df.to_numpy()
        self.close = ds.close_adj.to_numpy()
        self.raw = ds.close_raw.to_numpy()
        self.in_index = ds.in_index.reindex_like(ds.close_adj).fillna(False).to_numpy(dtype=bool)
        rets = ds.close_adj.pct_change(fill_method=None)
        self.rets_df = rets
        self.rets = rets.to_numpy()
        self.exec_ratio: np.ndarray | None = None
        if ds.exec_price is not None and cfg.signal.execution != "close_t1":
            ratio = (ds.exec_price / ds.close_adj).to_numpy()
            self.exec_ratio = np.where(np.isfinite(ratio) & (ratio > 0), ratio, 1.0)
        self.cdi = ds.market["cdi_daily"].reindex(self.dates).fillna(0.0).to_numpy()
        self.ibra_rets = ds.market["ibra_close"].reindex(self.dates).pct_change(fill_method=None)

    # ------------------------------------------------------------------ helpers
    def _ratio(self, j: int, c: int) -> float:
        return 1.0 if self.exec_ratio is None else float(self.exec_ratio[j, c])

    def _spread(self, spec: PairSpec, j: int) -> float:
        la = self.logp[j, self.col[spec.leg_a]]
        lb = self.logp[j, self.col[spec.leg_b]]
        return float(la - spec.gamma * lb - spec.alpha)

    # ------------------------------------------------------------------ main loop
    def run(self) -> BacktestResult:
        cfg, sc = self.cfg, self.cfg.signal
        F, T = cfg.windows.formation_days, cfg.windows.trading_days
        n = len(self.dates)
        if n <= F + 1:
            raise ValueError(f"histórico insuficiente: {n} pregões para formação de {F}")
        rebal = set(rebalance_indices(n, F, T))
        cash = float(cfg.backtest.initial_capital)
        positions: dict[Key, Position] = {}
        pending: dict[Key, PendingEntry] = {}
        active: dict[Key, PairSpec] = {}
        cooldown: dict[Key, int] = {}
        ewma: dict[tuple[Key, pd.Timestamp], EwmaZ] = {}
        trades: list[dict[str, object]] = []
        nav_rows: list[dict[str, object]] = []
        pos_rows: list[dict[str, object]] = []
        sel_rows: list[dict[str, object]] = []

        def close_position(key: Key, j: int, reason: ExitReason) -> float:
            p = positions.pop(key)
            ca, cb = self.col[p.spec.leg_a], self.col[p.spec.leg_b]
            pa = p.value_a * self._ratio(j, ca)
            pb = p.value_b * self._ratio(j, cb)
            cost = trading_cost(pa, cfg.costs) + trading_cost(pb, cfg.costs)
            p.costs += cost
            proceeds = pa + pb - cost
            gross_pnl = (pa + pb) - p.entry_value
            net = gross_pnl - p.costs - p.btc
            trades.append({
                "leg_a": p.spec.leg_a, "leg_b": p.spec.leg_b,
                "direction": 1 if p.state is PairState.LONG_SPREAD else -1,
                "gamma": p.spec.gamma, "method": p.spec.method,
                "formation_end": p.spec.formation_end,
                "entry_signal_date": p.entry_signal_date, "entry_date": p.entry_date,
                "exit_signal_date": p.exit_signal_date or self.dates[j], "exit_date": self.dates[j],
                "days_open": p.days_open, "entry_z": p.entry_z,
                "exit_z": self._z_cache.get(key, float("nan")),
                "entry_gross": p.entry_gross, "gross_pnl": gross_pnl,
                "trading_costs": p.costs, "btc_costs": p.btc, "net_pnl": net,
                "return_on_leg": net / p.base if p.base else float("nan"),
                "exit_reason": reason.value, "same_issuer": p.spec.same_issuer,
                "same_sector": p.spec.same_sector, "sector_a": p.spec.sector_a,
                "sector_b": p.spec.sector_b,
            })
            return proceeds

        self._z_cache: dict[Key, float] = {}
        for j in range(F, n):
            d = self.dates[j]
            interest = btc_total = cost_day = 0.0
            # 1. marcação a mercado e carrego
            if j > F:
                interest = cash * cash_daily_rate(float(self.cdi[j]), cfg.costs)
                cash += interest
                for p in positions.values():
                    ra = self.rets[j, self.col[p.spec.leg_a]]
                    rb = self.rets[j, self.col[p.spec.leg_b]]
                    p.value_a *= 1.0 + (ra if math.isfinite(ra) else 0.0)
                    p.value_b *= 1.0 + (rb if math.isfinite(rb) else 0.0)
                    short = p.value_a if p.value_a < 0 else p.value_b if p.value_b < 0 else 0.0
                    b = btc_daily_cost(short, cfg.costs)
                    p.btc += b
                    btc_total += b
                    p.days_open += 1
                cash -= btc_total

            # 2. execução das ordens de t−1
            for key in [k for k, p in positions.items() if p.exit_reason is not None]:
                reason = positions[key].exit_reason
                assert reason is not None
                c0 = positions[key].costs
                cash += close_position(key, j, reason)
                cost_day += trades[-1]["trading_costs"] - c0  # type: ignore[operator]
            nav_now = cash + sum(p.value for p in positions.values())
            for key, pe in list(pending.items()):
                del pending[key]
                spec = pe.spec
                ca, cb = self.col[spec.leg_a], self.col[spec.leg_b]
                if not (math.isfinite(self.close[j, ca]) and math.isfinite(self.close[j, cb])):
                    continue
                beta_a = beta_b = 1.0
                if cfg.sizing.mode == "beta":
                    lo = max(0, j - cfg.sizing.beta_window)
                    betas = rolling_beta(self.rets_df.iloc[lo:j][[spec.leg_a, spec.leg_b]],
                                         self.ibra_rets.iloc[lo:j], cfg.sizing.beta_window)
                    beta_a, beta_b = float(betas[spec.leg_a]), float(betas[spec.leg_b])
                na, nb = pair_notionals(nav_now, cfg.sizing, spec.gamma, float(self.raw[j, ca]),
                                        float(self.raw[j, cb]), beta_a, beta_b)
                if na <= 0 or nb <= 0:
                    continue
                gross_open = sum(p.gross for p in positions.values())
                if gross_open + na + nb > cfg.portfolio.max_gross_leverage * nav_now:
                    log.debug("%s: entrada %s bloqueada pelo teto de alavancagem", d.date(), key)
                    continue
                sgn = 1.0 if pe.action is Action.ENTER_LONG else -1.0
                ea, eb = sgn * na, -sgn * nb           # valores executados (com sinal)
                cost = trading_cost(ea, cfg.costs) + trading_cost(eb, cfg.costs)
                cash -= ea + eb + cost
                cost_day += cost
                va = ea / self._ratio(j, ca)
                vb = eb / self._ratio(j, cb)
                positions[key] = Position(
                    spec=spec,
                    state=PairState.LONG_SPREAD if sgn > 0 else PairState.SHORT_SPREAD,
                    value_a=va, value_b=vb, entry_value=ea + eb, base=(na + nb) / 2.0,
                    entry_signal_date=pe.signal_date, entry_date=d, entry_z=pe.z,
                    entry_gross=na + nb, costs=cost,
                )

            # 3. rebalanceamento
            if j in rebal:
                universe = eligible_universe(self.ds, d, cfg)
                ranked = self.selector.select(self.logp_df, universe, d, cfg, self.ds.sectors)
                chosen = apply_constraints(ranked, cfg.portfolio)
                active = {s.key: s for s in chosen}
                for rank, s in enumerate(chosen, 1):
                    sel_rows.append({"rebalance_date": d, "rank": rank, "n_universe": len(universe),
                                     "n_candidates": len(ranked), **s.__dict__})
                log.info("%s: universo %d, %d pares aprovados, %d escolhidos",
                         d.date(), len(universe), len(ranked), len(chosen))
                if sc.retest_on_rebalance and cfg.selection.method == "cointegration":
                    for p in positions.values():
                        if p.spec.formation_end >= self.dates[j - 1] or p.exit_reason is not None:
                            continue
                        la = self.logp[j - F:j, self.col[p.spec.leg_a]]
                        lb = self.logp[j - F:j, self.col[p.spec.leg_b]]
                        ok = np.isfinite(la) & np.isfinite(lb)
                        if ok.sum() < F // 2 or not residual_still_stationary(
                                la[ok], lb[ok], p.spec.gamma, p.spec.alpha, cfg):
                            p.forced = ExitReason.STRUCTURAL_BREAK

            # 4. sinais no fechamento de t
            last_day = j == n - 1
            zs: dict[tuple[Key, pd.Timestamp], float] = {}
            all_specs = list(active.items()) + [(k, p.spec) for k, p in positions.items()]
            for key, spec in all_specs:
                tag = (key, spec.formation_end)
                if tag in zs:
                    continue
                e = self._spread(spec, j)
                if sc.zscore_mode == "fixed":
                    zs[tag] = (e - spec.mu) / spec.sigma
                else:
                    tr = ewma.setdefault(tag, EwmaZ(spec.mu, spec.sigma, sc.ewma_lambda))
                    zs[tag] = tr.update(e)

            for key, p in positions.items():
                if p.exit_reason is not None:
                    continue
                z = zs[(key, p.spec.formation_end)]
                self._z_cache[key] = z
                ca, cb = self.col[p.spec.leg_a], self.col[p.spec.leg_b]
                forced = p.forced
                if forced is None and not (self.in_index[j, ca] and self.in_index[j, cb]):
                    forced = ExitReason.UNIVERSE_EXIT
                if last_day:
                    forced = ExitReason.END_OF_BACKTEST
                dec = decide(p.state, z, sc, days_open=p.days_open,
                             pnl_pct=(p.value - p.entry_value) / p.base,
                             cooldown_left=0, forced_exit=forced)
                if dec.action is Action.EXIT:
                    assert dec.reason is not None
                    p.exit_reason = dec.reason
                    p.exit_signal_date = d
                    if dec.reason in COOLDOWN_REASONS:
                        cooldown[key] = sc.cooldown_days + 1

            for key, spec in active.items():
                if key in positions or key in pending or last_day:
                    continue
                ca, cb = self.col[spec.leg_a], self.col[spec.leg_b]
                can = bool(self.in_index[j, ca] and self.in_index[j, cb])
                z = zs[(key, spec.formation_end)]
                dec = decide(PairState.FLAT, z, sc, cooldown_left=cooldown.get(key, 0),
                             can_enter=can)
                if dec.action in (Action.ENTER_LONG, Action.ENTER_SHORT):
                    pending[key] = PendingEntry(spec, dec.action, d, z)

            for key in list(cooldown):
                cooldown[key] -= 1
                if cooldown[key] <= 0:
                    del cooldown[key]

            # 5. registro
            if last_day:
                for key in list(positions):
                    reason = positions[key].exit_reason or ExitReason.END_OF_BACKTEST
                    c0 = positions[key].costs
                    cash += close_position(key, j, reason)
                    cost_day += trades[-1]["trading_costs"] - c0  # type: ignore[operator]
            long_exp = sum(max(p.value_a, 0) + max(p.value_b, 0) for p in positions.values())
            short_exp = sum(min(p.value_a, 0) + min(p.value_b, 0) for p in positions.values())
            nav = cash + long_exp + short_exp
            nav_rows.append({
                "date": d, "nav": nav, "cash": cash, "long": long_exp, "short": short_exp,
                "gross": long_exp - short_exp, "n_positions": len(positions),
                "trading_costs": cost_day, "btc_costs": btc_total, "interest": interest,
                "cdi_daily": float(self.cdi[j]),
            })
            for key, p in positions.items():
                pos_rows.append({
                    "date": d, "leg_a": p.spec.leg_a, "leg_b": p.spec.leg_b, "state": p.state.value,
                    "value_a": p.value_a, "value_b": p.value_b, "pnl": p.value - p.entry_value,
                    "z": self._z_cache.get(key, float("nan")), "days_open": p.days_open,
                })

        nav_df = pd.DataFrame(nav_rows).set_index("date")
        return BacktestResult(
            nav=nav_df,
            trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
            positions=pd.DataFrame(pos_rows),
            pairs_selected=pd.DataFrame(sel_rows),
            config=cfg,
            market=self.ds.market.reindex(nav_df.index),
        )


def run_backtest(ds: Dataset, cfg: Config, selector: PairSelector | None = None) -> BacktestResult:
    return Backtester(ds, cfg, selector).run()
