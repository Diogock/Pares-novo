"""Resumo da lista de BDRs + arquivo de tickers para export Bloomberg.

Gera:
  BDR/data/resumo.md            contagens por bolsa, país, setor e tipo de lastro
  BDR/data/bloomberg_tickers.csv  BDR (XXXX34 BZ Equity) e lastro (AAPL US Equity)

Uso:
    python BDR/scripts/summarize.py
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

# sufixo Bloomberg por bolsa de origem (o que não estiver aqui fica em branco)
BBG_SUFFIX = {
    "US": "US",
    "NYSE": "US",
    "NASDAQ": "US",
    "NYSE ARCA": "US",
    "NYSE AMERICAN": "US",
    "NYSE MKT": "US",
    "CBOE": "US",
    "BATS": "US",
    "NASDAQ GM": "US",
    "NASDAQ GS": "US",
    "NASDAQ CM": "US",
    "LONDON STOCK EXCHANGE": "LN",
}


def top(counter: Counter[str], n: int = 15) -> str:
    lines = ["| item | qtd |", "|---|---:|"]
    lines += [f"| {k or '(vazio)'} | {v} |" for k, v in counter.most_common(n)]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="BDR/data/bdr_master.csv")
    ap.add_argument("--outdir", default="BDR/data")
    args = ap.parse_args()
    with open(args.inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = Path(args.outdir)

    def norm(s: str) -> str:
        return s.strip().upper()

    md = [
        "# Resumo da lista de BDRs não patrocinados (B3)",
        "",
        f"Total de códigos de negociação: **{len(rows)}** (coleta {rows[0].get('data_coleta', '')}).",
        f"Emissores DRN: **{len({r['code_cvm'] for r in rows})}**.",
        f"Com ativo-objeto identificado: {sum(bool(r['ticker_lastro']) for r in rows)}; "
        f"com paridade: {sum(bool(r['bdrs_por_acao']) for r in rows)}.",
        "",
        "## Depositária",
        top(Counter(r["depositaria"].strip() for r in rows)),
        "",
        "## Bolsa do lastro",
        top(Counter(norm(r["bolsa_lastro"]) for r in rows)),
        "",
        "## País de origem",
        top(Counter(r["pais"].strip() for r in rows)),
        "",
        "## Setor (como declarado no programa)",
        top(Counter(r["setor"].strip() for r in rows), 25),
        "",
        "## Tipo do lastro",
        top(Counter(r["tipo_lastro"].strip() for r in rows)),
        "",
        "## Custodiante",
        top(Counter(r["custodiante"].strip() for r in rows)),
        "",
    ]
    (out / "resumo.md").write_text("\n".join(md), encoding="utf-8")

    with open(out / "bloomberg_tickers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bdr", "bdr_bbg", "lastro_bbg", "bdrs_por_acao"])
        for r in rows:
            suf = BBG_SUFFIX.get(norm(r["bolsa_lastro"]), "")
            lastro = (
                f"{r['ticker_lastro'].replace('.', '/')} {suf} Equity"
                if suf and r["ticker_lastro"]
                else ""
            )
            if r["ticker"]:
                w.writerow([r["ticker"], f"{r['ticker']} BZ Equity", lastro, r["bdrs_por_acao"]])
    print(f"ok: {out / 'resumo.md'}, {out / 'bloomberg_tickers.csv'}")


if __name__ == "__main__":
    main()
