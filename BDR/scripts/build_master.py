"""Junta a lista oficial (API B3, 810 DRN) com os dados dos PDFs do Banco B3.

Entrada:
  BDR/data/bdr_nao_patrocinados.csv      (fetch_b3_bdr_list.py)
  BDR/data/programas_banco_b3_detalhe.csv (fetch_banco_b3_programs.py + enrich_from_programs.py)
Saída:
  BDR/data/bdr_master.csv  uma linha por código de negociação DRN, com ativo-objeto,
                           bolsa, país, setor e paridade quando o programa é do Banco B3.

Uso:
    python BDR/scripts/build_master.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


EXTRA = [
    "razao_social",
    "pais",
    "isin_lastro",
    "ticker_lastro",
    "lastro_via",
    "ticker_acao_origem",
    "tipo_lastro",
    "setor",
    "bolsa_lastro",
    "bdrs_por_acao",
    "custodiante",
    "programa_pdf",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lista", default="BDR/data/bdr_nao_patrocinados.csv")
    ap.add_argument("--programas", default="BDR/data/programas_banco_b3_detalhe.csv")
    ap.add_argument(
        "--manual",
        default="BDR/data/lastro_manual.csv",
        help="ativo-objeto preenchido à mão (programas Bradesco/Itaú, sem PDF)",
    )
    ap.add_argument("--out", default="BDR/data/bdr_master.csv")
    args = ap.parse_args()

    lista = read_csv(args.lista)
    progs = {p["ticker"]: p for p in read_csv(args.programas)}
    por_raiz: dict[str, list[dict[str, str]]] = {}
    for p in progs.values():
        por_raiz.setdefault(p["ticker"][:4], []).append(p)

    manual: dict[str, dict[str, str]] = {}
    if Path(args.manual).exists():
        manual = {m["ticker"]: m for m in read_csv(args.manual)}

    out = []
    for r in lista:
        tickers = [t for t in [r["ticker"], *r["outros_codigos"].split(";")] if t]
        origem = "api"
        if not tickers:  # API sem código: usa o(s) do programa do Banco B3 com a mesma raiz
            tickers = [p["ticker"] for p in por_raiz.get(r["raiz"], [])]
            origem = "programa_banco_b3"
        if not tickers:
            tickers, origem = [""], "sem_codigo"
        for t in tickers:
            p = progs.get(t, {})
            row = {
                "ticker": t,
                "origem_ticker": origem,
                **{
                    k: r[k]
                    for k in (
                        "raiz",
                        "empresa",
                        "depositaria",
                        "site",
                        "isin_bdr",
                        "data_listagem",
                        "code_cvm",
                    )
                },
            }
            row.update({k: p.get(k, "") for k in EXTRA})
            row["fonte_lastro"] = "programa_pdf" if p else ""
            if not p and t in manual:
                row["ticker_lastro"] = manual[t]["ticker_lastro"]
                row["bolsa_lastro"] = manual[t]["bolsa_lastro"]
                row["fonte_lastro"] = "manual"
            row["data_coleta"] = r["data_coleta"]
            out.append(row)

    out.sort(key=lambda x: x["ticker"] or x["raiz"])
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    com_lastro = sum(1 for x in out if x["ticker_lastro"])
    print(
        f"{len(out)} códigos ({len(lista)} emissores DRN) em {args.out}; {com_lastro} com ativo-objeto"
    )


if __name__ == "__main__":
    main()
