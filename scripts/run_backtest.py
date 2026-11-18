"""Roda o backtest walk-forward e grava results/<run_id>/.

Uso:
    python scripts/run_backtest.py --config configs/base.yaml
    python scripts/run_backtest.py --config configs/experiments/intra_setor.yaml

Lê o parquet de data/processed/ (gerado por build_dataset.py). Com --from-raw,
monta o dataset direto dos .txt.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from pairs_ibra.backtest.engine import run_backtest
from pairs_ibra.backtest.io import make_run_id, save_results
from pairs_ibra.backtest.metrics import summary
from pairs_ibra.config import load_config
from pairs_ibra.data.loaders import build_dataset, load_dataset


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/base.yaml")
    ap.add_argument("--base-dir", default=".")
    ap.add_argument("--from-raw", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    base = Path(args.base_dir)
    if args.from_raw:
        ds, _ = build_dataset(cfg, base)
    else:
        ds = load_dataset(base / cfg.data.processed_dir)
    t0 = time.time()
    res = run_backtest(ds, cfg)
    run_id = args.run_id or make_run_id(args.config)
    out = save_results(res, base / "results" / run_id, args.config, run_id)
    p = summary(res)["performance"]
    print(f"run {run_id} em {time.time() - t0:.0f}s → {out}")
    print(f"retorno a.a. {p.get('return_ann', float('nan')):.2%} | excesso CDI a.a. "
          f"{p.get('excess_ann', float('nan')):.2%} | Sharpe {p.get('sharpe', float('nan')):.2f} | "
          f"max DD {p.get('max_drawdown', float('nan')):.2%} | trades {len(res.trades)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
