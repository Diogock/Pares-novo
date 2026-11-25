"""Roda um experimento dos modelos BDR em todas as variantes do yaml.

Uso:
    python BDR/scripts/run_bdr_backtest.py --config BDR/configs/experiments/setorial_amplo.yaml
Saída em ``backtest.results_dir/<run_id>/`` (nav, trades, posições, summary.json, metrics.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging

from bdr_models.config import load_config
from bdr_models.data import load_market_data
from bdr_models.runner import comparison_table, run_variant, save, summarize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    md = load_market_data(cfg)
    results, summaries = [], []
    for v in cfg.backtest.variants:
        logging.info("rodando %s / %s", cfg.name, v)
        r = run_variant(cfg, md, v)
        results.append(r)
        summaries.append(summarize(r, md))
    run_id = args.run_id or f"{cfg.name}_{dt.datetime.now():%Y%m%d_%H%M%S}"
    out = save(results, summaries, cfg, run_id)
    print(comparison_table(summaries).round(4).to_string())
    print(f"\nresultados em {out}")


if __name__ == "__main__":
    main()
