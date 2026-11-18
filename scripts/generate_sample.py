"""Gera dados sintéticos no formato Bloomberg (para testes e para validar o pipeline).

Uso:
    python scripts/generate_sample.py --out data/sample            # amostra pequena (versionada)
    python scripts/generate_sample.py --out data/raw --tickers 300 --end 2026-11-13   # tamanho real
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pairs_ibra.data import synthetic


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--tickers", type=int, default=40)
    ap.add_argument("--pairs", type=int, default=8)
    ap.add_argument("--start", default="2008-01-02")
    ap.add_argument("--end", default="2011-12-30")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    d = synthetic.generate(n_tickers=args.tickers, start=args.start, end=args.end,
                           n_planted=args.pairs, seed=args.seed)
    out = Path(args.out)
    synthetic.write_all(d, out, out / "sectors.xlsx")
    (out / "planted_pairs.csv").write_text(
        "leg_a,leg_b,gamma,half_life\n"
        + "".join(f"{p.leg_a},{p.leg_b},{p.gamma:.4f},{p.half_life:.2f}\n" for p in d.planted))
    print(f"dados sintéticos em {out}: {len(d.close_adj.columns)} tickers, {len(d.planted)} pares plantados")


if __name__ == "__main__":
    main()
