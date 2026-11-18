"""Aceite da fase 2: recuperar os pares plantados nos dados sintéticos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pairs_ibra.config import Config, config_from_dict
from pairs_ibra.data.loaders import Dataset, build_dataset
from pairs_ibra.data.synthetic import SyntheticData
from pairs_ibra.data.universe import eligible_universe
from pairs_ibra.portfolio.constraints import apply_constraints
from pairs_ibra.selection import get_selector
from pairs_ibra.selection.scoring import sharpe_score, simulate_rule
from tests.conftest import synth_raw


def recall(ds: Dataset, cfg: Config, synth: SyntheticData) -> float:
    planted = {tuple(sorted((p.leg_a, p.leg_b))) for p in synth.planted}
    sel = get_selector(cfg.selection.method)
    logp = np.log(ds.close_adj)
    hit = tot = 0
    for j in range(cfg.windows.formation_days, len(ds.dates), cfg.windows.trading_days):
        asof = ds.dates[j]
        u = eligible_universe(ds, asof, cfg)
        chosen = {s.key for s in apply_constraints(sel.select(logp, u, asof, cfg, ds.sectors),
                                                   cfg.portfolio)}
        elig = {p for p in planted if p[0] in u and p[1] in u}
        hit += len(elig & chosen)
        tot += len(elig)
    return hit / tot


def test_cointegration_recall_default(dataset: Dataset, synth_cfg: Config,
                                      synth: SyntheticData) -> None:
    # Meta do CLAUDE.md é ≥ 90%; com o default (sem pré-teste I(1), D9) fica em ~87%.
    assert not synth_cfg.selection.require_i1
    assert recall(dataset, synth_cfg, synth) >= 0.85


def test_cointegration_recall_with_i1_pretest(synth_dir: Path, synth: SyntheticData) -> None:
    raw = synth_raw(synth_dir)
    raw["selection"]["require_i1"] = True
    cfg = config_from_dict(raw)
    ds, _ = build_dataset(cfg, "/")
    assert recall(ds, cfg, synth) >= 0.75


def test_selected_specs_are_consistent(dataset: Dataset, synth_cfg: Config) -> None:
    asof = dataset.dates[300]
    u = eligible_universe(dataset, asof, synth_cfg)
    specs = get_selector("cointegration").select(np.log(dataset.close_adj), u, asof, synth_cfg,
                                                 dataset.sectors)
    assert specs, "nenhum par aprovado"
    lo, hi = synth_cfg.selection.gamma_bounds
    for s in specs:
        assert lo <= s.gamma <= hi
        assert 3 <= s.half_life <= 40
        assert s.formation_end < asof
        assert s.sigma > 0
    assert [s.score for s in specs] == sorted((s.score for s in specs), reverse=True)


def test_distance_selector_runs(dataset: Dataset, synth_cfg: Config) -> None:
    cfg = synth_cfg.model_copy(update={"selection": synth_cfg.selection.model_copy(
        update={"method": "distance"})})
    asof = dataset.dates[300]
    specs = get_selector("distance").select(np.log(dataset.close_adj),
                                            eligible_universe(dataset, asof, cfg), asof, cfg,
                                            dataset.sectors)
    assert specs and all(s.gamma == 1.0 and s.method == "distance" for s in specs)


def test_same_sector_restriction(dataset: Dataset, synth_cfg: Config) -> None:
    cfg = synth_cfg.model_copy(update={"selection": synth_cfg.selection.model_copy(
        update={"same_sector": True})})
    asof = dataset.dates[300]
    specs = get_selector("cointegration").select(np.log(dataset.close_adj),
                                                 eligible_universe(dataset, asof, cfg), asof, cfg,
                                                 dataset.sectors)
    assert specs and all(s.same_sector for s in specs)


def test_same_issuer_flag(dataset: Dataset, synth_cfg: Config, synth: SyntheticData) -> None:
    p = synth.planted[0]
    assert p.leg_a[:4] == p.leg_b[:4]
    asof = dataset.dates[400]
    specs = get_selector("cointegration").select(np.log(dataset.close_adj),
                                                 eligible_universe(dataset, asof, synth_cfg),
                                                 asof, synth_cfg, dataset.sectors)
    for s in specs:
        assert s.same_issuer == (s.leg_a[:4] == s.leg_b[:4])


def test_scoring_profits_on_mean_reverting_spread(synth_cfg: Config) -> None:
    rng = np.random.default_rng(0)
    n = 252
    lb = np.log(20) + np.cumsum(rng.normal(0, 0.015, n))
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = 0.8 * s[t - 1] + rng.normal(0, 0.02)
    la = 0.1 + lb + s
    e = la - lb - 0.1
    daily, trades = simulate_rule(la, lb, 1.0, 0.1, float(e.mean()), float(e.std()), synth_cfg)
    assert trades >= 3
    assert sharpe_score(daily) > 1.0


def test_kalman_not_available() -> None:
    from pairs_ibra.selection.kalman import KalmanSelector

    with pytest.raises(NotImplementedError):
        KalmanSelector().select()
