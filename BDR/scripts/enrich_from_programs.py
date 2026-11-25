"""Enriquece a lista de BDRs com os dados do Formulário de Identificação (Anexo I).

Para cada BDR baixa o PDF do programa (cache em ``BDR/data/pdfs/``, não
versionado), extrai o texto com ``pdftotext`` (poppler-utils) e lê os campos:
ativo-objeto, ISIN, bolsa de origem, país, setor, paridade BDR:ação, depositária
e custodiante.

ATENÇÃO: a paridade é a do PDF publicado. Após desdobramentos/grupamentos a B3
pode ter atualizado o programa ou não; confira contra o preço (BDR ≈ ação ×
câmbio / paridade) antes de usar em produção.

Uso:
    python BDR/scripts/enrich_from_programs.py \
        --inp BDR/data/programas_banco_b3.csv \
        --out BDR/data/programas_banco_b3_detalhe.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = "Mozilla/5.0 (compatible; bdr-list-fetcher)"
log = logging.getLogger("enrich_bdr")

# rótulo no PDF (pt) -> coluna de saída
FIELDS = {
    "Denominação Social": "razao_social",
    "País de Origem": "pais",
    "Código ISIN da Ação Representada": "isin_lastro",
    "Código da Ação Representada": "ticker_lastro",
    "Tipo da ação Representada": "tipo_lastro",
    "Setor de Atuação": "setor",
    "Bolsa de Valores da Ação Representada": "bolsa_lastro",
    "Código ISIN": "isin_bdr",
    "Relação BDR x Ação Lastro": "relacao",
}
COLS = list(FIELDS.values()) + [
    "lastro_via",
    "ticker_acao_origem",
    "bdrs_por_acao",
    "depositaria",
    "custodiante",
    "erro",
]


def download(url: str, dest: Path, retries: int = 4) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                dest.write_bytes(r.read())
            return
        except Exception as e:  # noqa: BLE001
            log.warning("falha %s: %s", dest.name, e)
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"download falhou: {url}")


def _section(text: str, start: str, end: str | None) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i) if end else -1
    return text[i : j if j > 0 else None]


def parse_form(text: str) -> dict[str, str]:
    """Lê o Anexo I. Dois layouts: lastro em ação direta ou lastro em ADR."""
    anexo = _section(text, "FORMULÁRIO DE IDENTIFICAÇÃO", "ANEXO II") or text
    sec1 = _section(anexo, "IDENTIFICAÇÃO DA COMPANHIA", "DESCRIÇÃO DOS")
    sec_adr = _section(anexo, "DESCRIÇÃO DOS ADR", "DESCRIÇÃO DOS BDR")
    sec_bdr = _section(anexo, "DESCRIÇÃO DOS BDR", "IDENTIFICAÇÃO DA INSTITUIÇÃO")
    sec3 = _section(
        anexo, "IDENTIFICAÇÃO DA INSTITUIÇÃO DEPOSITÁRIA", "IDENTIFICAÇÃO DO CUSTODIANTE"
    )
    sec4 = _section(anexo, "IDENTIFICAÇÃO DO CUSTODIANTE", "CONTRATO DE CUST")

    def grab(block: str, label: str) -> str:
        m = re.search(re.escape(label) + r"\s*:\s*([^\n]*)", block)
        return m.group(1).strip() if m else ""

    out: dict[str, str] = {}
    for label, col in FIELDS.items():
        block = sec_bdr if col in ("isin_bdr", "relacao") else sec1
        out[col] = grab(block, label)

    out["lastro_via"] = "adr" if sec_adr else "acao"
    out["ticker_acao_origem"] = out["ticker_lastro"]
    if sec_adr:  # o que se negocia nos EUA (e serve de lastro) é o ADR
        out["ticker_lastro"] = grab(sec_adr, "Código de Negociação") or out["ticker_lastro"]
        out["bolsa_lastro"] = grab(sec_adr, "Ambiente de Negociação") or out["bolsa_lastro"]
        out["isin_lastro"] = grab(sec_adr, "Código ISIN") or out["isin_lastro"]

    m = re.search(r"([\d.,]+)\s*:\s*([\d.,]+)", out["relacao"])
    if m:
        out["bdrs_por_acao"] = _ratio(m.group(1), m.group(2))
    else:  # texto corrido do descritivo: "Cada 1 ADR/Ação Representada dará lastro à emissão de N BDR(s)"
        m2 = re.search(
            r"Cada\s+([\d.,]+)\s+(?:ADR|A[çc][ãa]o)[^.]{0,80}?emiss[ãa]o\s+de\s+([\d.,]+)\s+BDR",
            text,
            re.S,
        )
        out["bdrs_por_acao"] = _ratio(m2.group(2), m2.group(1)) if m2 else ""
    out["depositaria"] = grab(sec3, "Denominação Social")
    out["custodiante"] = grab(sec4, "Denominação Social")
    return out


def _ratio(bdrs: str, acoes: str) -> str:
    def num(s: str) -> float:
        s = s.strip(".")
        return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)

    try:
        return f"{num(bdrs) / num(acoes):g}"
    except (ValueError, ZeroDivisionError):
        return ""


def process(row: dict[str, str], cache: Path) -> dict[str, str]:
    res = dict(row)
    try:
        if not row["programa_pdf"]:
            raise RuntimeError("sem PDF")
        pdf = cache / f"{row['ticker']}.pdf"
        download(row["programa_pdf"], pdf)
        text = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True
        ).stdout
        text = re.sub(r"[ \t]{2,}", " ", text)
        res.update(parse_form(text))
        res["erro"] = "" if res.get("ticker_lastro") else "campos não encontrados"
    except Exception as e:  # noqa: BLE001
        res["erro"] = str(e)[:200]
    for c in COLS:
        res.setdefault(c, "")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="BDR/data/programas_banco_b3.csv")
    ap.add_argument("--out", default="BDR/data/programas_banco_b3_detalhe.csv")
    ap.add_argument("--cache", default="BDR/data/pdfs")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    with open(args.inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with ThreadPoolExecutor(args.workers) as ex:
        out = list(ex.map(lambda r: process(r, cache), rows))
    fields = list(rows[0].keys()) + [c for c in COLS if c not in rows[0]]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    n_err = sum(1 for r in out if r["erro"])
    log.info("%d linhas gravadas em %s; %d com erro", len(out), args.out, n_err)


if __name__ == "__main__":
    main()
