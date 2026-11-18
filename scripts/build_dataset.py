"""Lê os exports Bloomberg de data/raw/, valida e grava parquet em data/processed/.

Uso:
    python scripts/build_dataset.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pairs_ibra.config import load_config
from pairs_ibra.data.loaders import build_dataset, save_dataset
from pairs_ibra.data.validation import quality_report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/base.yaml")
    ap.add_argument("--base-dir", default=".")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    ds, warnings = build_dataset(cfg, args.base_dir)
    out = Path(args.base_dir) / cfg.data.processed_dir
    save_dataset(ds, out)
    rep = quality_report(ds, cfg.data.max_abs_daily_return, warnings)
    (out / "quality_report.md").write_text(rep.to_markdown(), encoding="utf-8")
    logging.info("dataset: %d pregões × %d ativos (%s a %s)", *ds.close_adj.shape,
                 ds.dates[0].date(), ds.dates[-1].date())
    logging.info("relatório de qualidade: %s (%s)", out / "quality_report.md",
                 "OK" if rep.ok else "ERRO CRÍTICO")
    for c in rep.critical:
        logging.error(c)
    for w in rep.warnings:
        logging.warning(w)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
