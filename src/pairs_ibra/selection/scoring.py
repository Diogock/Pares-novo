"""Score in-sample: Sharpe da regra de trading simulada na formação, líquido de custos
(Caldeira & Moura, 2013). Usa a mesma máquina de estados e a mesma execução em t+1
do backtest."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from pairs_ibra.backtest.costs import DAYS_PER_YEAR
from pairs_ibra.config import Config
from pairs_ibra.portfolio.sizing import leg_weights
from pairs_ibra.signal.state_machine import COOLDOWN_REASONS, Action, PairState, decide

Array = npt.NDArray[np.float64]


def simulate_rule(log_a: Array, log_b: Array, gamma: float, alpha: float, mu: float,
                  sigma: float, cfg: Config) -> tuple[Array, int]:
    """Retornos diários da regra (base: notional médio por perna = 1) e nº de trades."""
    sc = cfg.signal
    z = (np.asarray(log_a) - gamma * np.asarray(log_b) - alpha - mu) / sigma
    ra = np.expm1(np.diff(log_a, prepend=log_a[0]))
    rb = np.expm1(np.diff(log_b, prepend=log_b[0]))
    wa, wb = leg_weights("dollar" if cfg.sizing.mode == "beta" else cfg.sizing.mode, gamma)
    cost = cfg.costs.trading_cost_bps / 1e4
    btc = cfg.costs.btc_fallback_rate / DAYS_PER_YEAR
    n = len(z)
    out = np.zeros(n)
    state = PairState.FLAT
    va = vb = 0.0          # valores com sinal das pernas
    entry_pnl_base = 0.0
    days = 0
    cooldown = 0
    pending: Action | None = None
    trades = 0
    for t in range(n):
        pnl = 0.0
        if va or vb:
            da, db = va * ra[t], vb * rb[t]
            va += da
            vb += db
            pnl += da + db
            pnl -= btc * (abs(va) if va < 0 else abs(vb) if vb < 0 else 0.0)
            days += 1
        if pending is not None:
            if pending is Action.EXIT:
                pnl -= cost * (abs(va) + abs(vb))
                va = vb = 0.0
            else:
                d = 1.0 if pending is Action.ENTER_LONG else -1.0
                va, vb = d * wa, -d * wb
                pnl -= cost * (wa + wb)
                entry_pnl_base = va + vb
                days = 0
                trades += 1
            pending = None
        out[t] = pnl
        if cooldown > 0:
            cooldown -= 1
        pnl_pct = (va + vb) - entry_pnl_base if state is not PairState.FLAT else 0.0
        dec = decide(state, float(z[t]), sc, days_open=days, pnl_pct=pnl_pct,
                     cooldown_left=cooldown, can_enter=t < n - 1)
        if dec.action is Action.EXIT:
            state = PairState.FLAT
            pending = Action.EXIT
            if dec.reason in COOLDOWN_REASONS:
                cooldown = sc.cooldown_days
        elif dec.action in (Action.ENTER_LONG, Action.ENTER_SHORT):
            state = dec.new_state_if_flat
            pending = dec.action
    return out, trades


def sharpe_score(daily: Array) -> float:
    sd = float(np.std(daily, ddof=1)) if len(daily) > 2 else 0.0
    if sd == 0 or not math.isfinite(sd):
        return 0.0
    return float(np.mean(daily) / sd * math.sqrt(DAYS_PER_YEAR))
