"""Cobertura de todas as transições da seção 5.4."""

from __future__ import annotations

import math

import pytest

from pairs_ibra.config import load_config
from pairs_ibra.signal.state_machine import (
    COOLDOWN_REASONS,
    Action,
    ExitReason,
    PairState,
    decide,
    direction,
)
from tests.conftest import ROOT

SC = load_config(ROOT / "configs" / "base.yaml").signal
F, L, S = PairState.FLAT, PairState.LONG_SPREAD, PairState.SHORT_SPREAD


@pytest.mark.parametrize("z,action", [
    (-2.0, Action.ENTER_LONG), (-3.9, Action.ENTER_LONG), (2.0, Action.ENTER_SHORT),
    (3.9, Action.ENTER_SHORT), (-1.99, Action.HOLD), (1.99, Action.HOLD), (0.0, Action.HOLD),
    (-4.0, Action.HOLD), (4.5, Action.HOLD), (math.nan, Action.HOLD),
])
def test_flat_entries(z: float, action: Action) -> None:
    assert decide(F, z, SC).action is action


def test_flat_blocked() -> None:
    assert decide(F, -2.5, SC, cooldown_left=1).action is Action.HOLD
    assert decide(F, -2.5, SC, can_enter=False).action is Action.HOLD
    assert decide(F, -2.5, SC, forced_exit=ExitReason.UNIVERSE_EXIT).action is Action.HOLD


@pytest.mark.parametrize("state,z,expected", [
    (L, -0.5, ExitReason.CONVERGENCE), (L, 0.3, ExitReason.CONVERGENCE), (L, -0.6, None),
    (S, 0.75, ExitReason.CONVERGENCE), (S, -1.0, ExitReason.CONVERGENCE), (S, 0.8, None),
    (L, -4.0, ExitReason.STOP_Z), (S, 4.0, ExitReason.STOP_Z), (S, 3.9, None),
    (L, math.nan, ExitReason.MISSING_DATA),
])
def test_open_exits_by_z(state: PairState, z: float, expected: ExitReason | None) -> None:
    d = decide(state, z, SC)
    if expected is None:
        assert d.action is Action.HOLD
    else:
        assert d.action is Action.EXIT and d.reason is expected


def test_stop_loss_and_time() -> None:
    assert decide(L, -2.5, SC, pnl_pct=-0.07).reason is ExitReason.STOP_LOSS
    assert decide(L, -2.5, SC, pnl_pct=-0.069).action is Action.HOLD
    assert decide(S, 2.5, SC, days_open=50).reason is ExitReason.TIME_STOP
    assert decide(S, 2.5, SC, days_open=49).action is Action.HOLD


@pytest.mark.parametrize("reason", [ExitReason.STRUCTURAL_BREAK, ExitReason.UNIVERSE_EXIT,
                                    ExitReason.END_OF_BACKTEST, ExitReason.MISSING_DATA])
def test_forced_exits_have_priority(reason: ExitReason) -> None:
    d = decide(L, -4.5, SC, pnl_pct=-0.5, days_open=99, forced_exit=reason)
    assert d.action is Action.EXIT and d.reason is reason


def test_priority_loss_over_spread_over_time() -> None:
    assert decide(L, -4.5, SC, pnl_pct=-0.1, days_open=60).reason is ExitReason.STOP_LOSS
    assert decide(L, -4.5, SC, days_open=60).reason is ExitReason.STOP_Z
    assert decide(L, 0.0, SC, days_open=60).reason is ExitReason.TIME_STOP


def test_cooldown_reasons_and_helpers() -> None:
    assert ExitReason.CONVERGENCE not in COOLDOWN_REASONS
    assert ExitReason.STOP_Z in COOLDOWN_REASONS
    assert direction(L) == 1 and direction(S) == -1 and direction(F) == 0
    assert decide(F, -2.1, SC).new_state_if_flat is L
    assert decide(F, 2.1, SC).new_state_if_flat is S
    assert decide(F, 0.0, SC).new_state_if_flat is F
