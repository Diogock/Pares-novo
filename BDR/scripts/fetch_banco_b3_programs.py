"""Baixa os programas de BDR não patrocinado em que o Banco B3 é a depositária.

NÃO é a lista completa: programas de outras depositárias (Itaú, Bradesco...)
não aparecem aqui. A lista completa (810 DRN) vem de ``fetch_b3_bdr_list.py``.
Este script existe porque cada programa do Banco B3 tem PDF com ativo-objeto e
paridade (ver ``enrich_from_programs.py``).

Fonte: página pública de programas da B3
https://finservices.b3.com.br/pt/bdr-nao-patrocinado/programas

A página é paginada (Liferay, ``delta`` itens por página e ``start`` = nº da
página). O script percorre todas as páginas até não aparecer ticker novo e
grava um CSV com: empresa, ticker, site, link do PDF do programa e a flag de
"somente investidor qualificado" (programas marcados com "*").

Uso:
    python BDR/scripts/fetch_banco_b3_programs.py --out BDR/data/programas_banco_b3.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import logging
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://finservices.b3.com.br"
URL = BASE + "/pt/bdr-nao-patrocinado/programas?delta={delta}&start={page}"
UA = "Mozilla/5.0 (compatible; bdr-list-fetcher)"

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
EMPRESA_RE = re.compile(r'table-bdr__result-one">\s*(.*?)\s*</td>', re.S)
TICKER_RE = re.compile(r'table-bdr__result-two">\s*(.*?)\s*</td>', re.S)
SITE_RE = re.compile(r'table-bdr__result-three-text"\s+href="([^"]*)"')
PDF_RE = re.compile(r'table-bdr__result-four-text"\s+href="([^"]*)"')
TOTAL_RE = re.compile(r"(\d[\d.]*)\s+resultados")
TAG_RE = re.compile(r"<[^>]+>")

log = logging.getLogger("fetch_bdr")


def _clean(s: str) -> str:
    return html.unescape(TAG_RE.sub("", s)).strip()


def fetch_page(page: int, delta: int, retries: int = 4) -> str:
    url = URL.format(delta=delta, page=page)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            wait = 2 ** (attempt + 1)
            log.warning("falha em %s (%s); nova tentativa em %ss", url, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"não consegui baixar {url}")


def parse(page_html: str) -> list[dict[str, str]]:
    out = []
    for m in ROW_RE.finditer(page_html):
        row = m.group(1)
        e, t = EMPRESA_RE.search(row), TICKER_RE.search(row)
        if not (e and t):
            continue
        empresa, ticker = _clean(e.group(1)), _clean(t.group(1))
        qualificado = "*" in empresa or "*" in ticker
        site, pdf = SITE_RE.search(row), PDF_RE.search(row)
        pdf_url = html.unescape(pdf.group(1)) if pdf else ""
        if pdf_url.startswith("/"):
            pdf_url = BASE + pdf_url.split("?")[0]
        out.append(
            {
                "ticker": ticker.replace("*", "").strip().upper(),
                "empresa": empresa.replace("*", "").strip(),
                "somente_qualificado": "1" if qualificado else "0",
                "site": html.unescape(site.group(1)) if site else "",
                "programa_pdf": pdf_url,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="BDR/data/programas_banco_b3.csv")
    ap.add_argument("--delta", type=int, default=200, help="itens por página")
    ap.add_argument("--max-pages", type=int, default=20)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    rows: dict[str, dict[str, str]] = {}
    total_site = None
    for page in range(1, args.max_pages + 1):
        h = fetch_page(page, args.delta)
        if total_site is None and (m := TOTAL_RE.search(h)):
            total_site = int(m.group(1).replace(".", ""))
        novos = [r for r in parse(h) if r["ticker"] not in rows]
        log.info("página %d: %d novos", page, len(novos))
        if not novos:
            break
        for r in novos:
            rows[r["ticker"]] = r
        time.sleep(1)

    data = sorted(rows.values(), key=lambda r: r["ticker"])
    for r in data:
        r["data_coleta"] = date.today().isoformat()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)
    log.info("%d BDRs gravados em %s (site informa %s resultados)", len(data), out, total_site)
    if total_site and len(data) < total_site:
        log.warning("faltam %d itens em relação ao total do site", total_site - len(data))


if __name__ == "__main__":
    main()
