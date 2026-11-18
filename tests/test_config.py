from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pairs_ibra.config import config_from_dict, load_config
from tests.conftest import ROOT, base_raw


def test_base_yaml_loads_with_documented_defaults() -> None:
    cfg = load_config(ROOT / "configs" / "base.yaml")
    assert cfg.windows.formation_days == 252
    assert cfg.windows.trading_days == 63
    assert cfg.selection.method == "cointegration"
    assert cfg.selection.require_i1 is False
    assert cfg.signal.entry_z == 2.0 and cfg.signal.stop_z == 4.0
    assert cfg.signal.execution == "close_t1"
    assert cfg.sizing.leg_pct_nav == 0.01
    assert cfg.costs.trading_cost_bps == 4
    assert cfg.costs.cash_spread_bps == 4
    assert str(cfg.backtest.start) == "2008-01-02"
    assert str(cfg.backtest.oos_start) == "2013-01-01"


def test_unknown_key_is_rejected() -> None:
    raw = base_raw()
    raw["signal"]["entry_zz"] = 2.0
    with pytest.raises(ValidationError):
        config_from_dict(raw)


@pytest.mark.parametrize("section,key,value", [
    ("signal", "stop_z", 1.5),            # stop menor que entrada
    ("signal", "execution", "vwap_t1"),   # sem arquivo de VWAP
    ("selection", "min_tests_passed", 4),
    ("selection", "gamma_bounds", [5.0, 0.2]),
    ("selection", "method", "kalman"),
    ("sizing", "mode", "xyz"),
])
def test_invalid_values_rejected(section: str, key: str, value: object) -> None:
    raw = base_raw()
    raw[section][key] = value
    with pytest.raises(ValidationError):
        config_from_dict(raw)


def test_experiment_extends_base(tmp_path: Path) -> None:
    exp = tmp_path / "exp.yaml"
    exp.write_text(f"extends: {ROOT / 'configs' / 'base.yaml'}\nsignal:\n  entry_z: 2.5\n")
    cfg = load_config(exp)
    assert cfg.signal.entry_z == 2.5
    assert cfg.signal.exit_z_long == 0.5  # herdado


def test_shipped_experiments_are_valid() -> None:
    for p in (ROOT / "configs" / "experiments").glob("*.yaml"):
        load_config(p)
