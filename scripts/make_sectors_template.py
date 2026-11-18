"""Cria o Excel auxiliar de setores (configs/sectors.xlsx) a partir dos tickers do export.

Abas:
- setores:   ticker | setor | subsetor | segmento | emissor   (classificação B3; edite à mão)
- de_para:   ticker_antigo | ticker_novo | data_troca          (ticker antigo é descartado)
- exclusoes: ticker                                            (ignorados no modelo)

O emissor vem pré-preenchido pela raiz do ticker (PETR3/PETR4 → PETR); corrija onde precisar.
Se o arquivo já existir, as linhas existentes são mantidas e só os tickers novos são incluídos.

Uso:
    python scripts/make_sectors_template.py --prices data/raw/prices_adj.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pairs_ibra.data.loaders import issuer_root, read_bloomberg_wide
from pairs_ibra.data.synthetic import write_sectors_xlsx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", default="data/raw/prices_adj.txt")
    ap.add_argument("--out", default="configs/sectors.xlsx")
    ap.add_argument("--na", default="#N/A")
    args = ap.parse_args()
    tickers = list(read_bloomberg_wide(args.prices, na_values=[args.na]).columns)
    out = Path(args.out)
    de_para = exclusions = None
    if out.exists():
        book = pd.read_excel(out, sheet_name=None, dtype=str)
        cur = book.get("setores", pd.DataFrame(columns=["ticker"]))
        de_para = book.get("de_para")
        exclusions = list(book.get("exclusoes", pd.DataFrame({"ticker": []}))["ticker"].dropna())
    else:
        cur = pd.DataFrame(columns=["ticker", "setor", "subsetor", "segmento", "emissor"])
    new = [t for t in tickers if t not in set(cur["ticker"])]
    add = pd.DataFrame({"ticker": new, "setor": "", "subsetor": "", "segmento": "",
                        "emissor": [issuer_root(t) for t in new]})
    write_sectors_xlsx(pd.concat([cur, add], ignore_index=True), out, de_para, exclusions)
    print(f"{out}: {len(cur)} existentes + {len(new)} novos")


if __name__ == "__main__":
    main()
