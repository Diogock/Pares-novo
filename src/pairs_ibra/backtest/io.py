"""Gravação dos resultados em ``results/<run_id>/`` (CLAUDE.md, seção 6)."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pandas as pd

from pairs_ibra.backtest.engine import BacktestResult
from pairs_ibra.backtest.metrics import summary
from pairs_ibra.backtest.report import render_html


def make_run_id(config_path: str | Path) -> str:
    return f"{dt.datetime.now():%Y%m%d_%H%M%S}_{Path(config_path).stem}"


def save_results(res: BacktestResult, out_dir: str | Path, config_path: str | Path,
                 run_id: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res.trades.to_parquet(out / "trades.parquet", index=False)
    res.positions.to_parquet(out / "positions.parquet", index=False)
    res.nav.reset_index().to_parquet(out / "nav.parquet", index=False)
    sel = res.pairs_selected.copy()
    res_cols = [c for c in sel.columns if sel[c].dtype == object]
    for c in res_cols:
        sel[c] = sel[c].astype(str)
    sel.to_parquet(out / "pairs_selected.parquet", index=False)
    shutil.copyfile(config_path, out / "config.yaml")
    (out / "config_resolved.json").write_text(res.config.model_dump_json(indent=2))
    (out / "report.html").write_text(render_html(res, run_id), encoding="utf-8")
    s = summary(res)
    flat = {"performance": s["performance"], "trades": s["trades"],
            "turnover_ann": s["turnover_ann"]}
    (out / "metrics.json").write_text(json.dumps(flat, indent=2, default=float))
    for name in ("subperiods", "calibration_oos"):
        frame = s[name]
        if isinstance(frame, pd.DataFrame):
            frame.to_csv(out / f"{name}.csv")
    return out
