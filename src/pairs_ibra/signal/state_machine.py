"""Máquina de estados por par (CLAUDE.md, seção 5.4).

``decide`` é uma função pura: recebe o estado e as observações do fechamento de *t*
e devolve a ação a ser executada em *t+1*. O mesmo código é usado no backtest
e na simulação in-sample do ranking (score de Sharpe).

Prioridade das saídas: forçada (índice/evento/quebra/dado) > stop financeiro >
stop de spread > stop de tempo > convergência.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from pairs_ibra.config import SignalConfig


class PairState(StrEnum):
    FLAT = "FLAT"
    LONG_SPREAD = "LONG_SPREAD"     # compra A, vende γ·B
    SHORT_SPREAD = "SHORT_SPREAD"   # vende A, compra γ·B


class Action(StrEnum):
    HOLD = "HOLD"
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"


class ExitReason(StrEnum):
    CONVERGENCE = "convergencia"
    STOP_Z = "stop_spread"
    STOP_LOSS = "stop_financeiro"
    TIME_STOP = "stop_tempo"
    STRUCTURAL_BREAK = "quebra_estrutural"
    UNIVERSE_EXIT = "saida_universo"
    MISSING_DATA = "dado_faltante"
    END_OF_BACKTEST = "fim_backtest"


# Saídas que disparam cooldown (sem reentrada por ``cooldown_days``).
COOLDOWN_REASONS = frozenset({
    ExitReason.STOP_Z, ExitReason.STOP_LOSS, ExitReason.TIME_STOP, ExitReason.STRUCTURAL_BREAK,
})


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: ExitReason | None = None

    @property
    def new_state_if_flat(self) -> PairState:
        if self.action is Action.ENTER_LONG:
            return PairState.LONG_SPREAD
        if self.action is Action.ENTER_SHORT:
            return PairState.SHORT_SPREAD
        return PairState.FLAT


HOLD = Decision(Action.HOLD)


def decide(
    state: PairState,
    z: float,
    cfg: SignalConfig,
    *,
    days_open: int = 0,
    pnl_pct: float = 0.0,
    cooldown_left: int = 0,
    can_enter: bool = True,
    forced_exit: ExitReason | None = None,
) -> Decision:
    """Decide a ação do par no fechamento de *t*.

    - ``days_open``: pregões desde a execução da entrada.
    - ``pnl_pct``: PnL do par / notional médio por perna na entrada.
    - ``cooldown_left``: pregões restantes de bloqueio após um stop.
    - ``can_enter``: par está na seleção vigente e as pernas são negociáveis.
    - ``forced_exit``: motivo externo de saída (ação saiu do índice, quebra, dado faltante).
    """
    if state is PairState.FLAT:
        if forced_exit is not None or not can_enter or cooldown_left > 0 or not math.isfinite(z):
            return HOLD
        if -cfg.stop_z < z <= -cfg.entry_z:
            return Decision(Action.ENTER_LONG)
        if cfg.entry_z <= z < cfg.stop_z:
            return Decision(Action.ENTER_SHORT)
        return HOLD

    if forced_exit is not None:
        return Decision(Action.EXIT, forced_exit)
    if pnl_pct <= -cfg.stop_loss_pct:
        return Decision(Action.EXIT, ExitReason.STOP_LOSS)
    if not math.isfinite(z):
        return Decision(Action.EXIT, ExitReason.MISSING_DATA)
    if abs(z) >= cfg.stop_z:
        return Decision(Action.EXIT, ExitReason.STOP_Z)
    if days_open >= cfg.time_stop_days:
        return Decision(Action.EXIT, ExitReason.TIME_STOP)
    if state is PairState.LONG_SPREAD and z >= -cfg.exit_z_long:
        return Decision(Action.EXIT, ExitReason.CONVERGENCE)
    if state is PairState.SHORT_SPREAD and z <= cfg.exit_z_short:
        return Decision(Action.EXIT, ExitReason.CONVERGENCE)
    return HOLD


def direction(state: PairState) -> int:
    """+1 comprado no spread, −1 vendido, 0 zerado."""
    return {PairState.FLAT: 0, PairState.LONG_SPREAD: 1, PairState.SHORT_SPREAD: -1}[state]
