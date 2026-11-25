"""Baixa a lista oficial de BDRs listados na B3 (API pública de empresas listadas).

Fonte: https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/
  - ``GetCompaniesBDR``: todos os emissores de BDR, com ``typeBDR``:
      DRN = BDR não patrocinado de ações, DRE = BDR de ETF,
      DR1/DR2/DR3 = BDR patrocinado nível I/II/III.
  - ``GetDetail``: código de negociação, ISINs, depositária e site.

Gera:
  BDR/data/bdr_todos.csv              todos os emissores de BDR (todos os tipos)
  BDR/data/bdr_nao_patrocinados.csv   só DRN (a lista dos ~810)

Uso:
    python BDR/scripts/fetch_b3_bdr_list.py            # completo (com detalhe)
    python BDR/scripts/fetch_b3_bdr_list.py --no-detail  # só a listagem, rápido
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

API = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
UA = "Mozilla/5.0 (compatible; bdr-list-fetcher)"
TIPOS = {
    "DRN": "nao_patrocinado",
    "DRE": "etf",
    "DR1": "patrocinado_n1",
    "DR2": "patrocinado_n2",
    "DR3": "patrocinado_n3",
}
log = logging.getLogger("fetch_bdr")


def call(endpoint: str, payload: dict[str, Any], retries: int = 4) -> Any:
    q = base64.b64encode(json.dumps(payload).encode()).decode()
    url = API + endpoint + "/" + q
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            wait = 2 ** (attempt + 1)
            log.warning("%s falhou (%s); nova tentativa em %ss", endpoint, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"falha em {endpoint} {payload}")


def list_all(page_size: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        d = call(
            "GetCompaniesBDR", {"language": "pt-br", "pageNumber": page, "pageSize": page_size}
        )
        out += d["results"]
        if page >= d["page"]["totalPages"]:
            return out
        page += 1


def detail(code_cvm: str) -> dict[str, Any]:
    try:
        d = call("GetDetail", {"codeCVM": code_cvm, "language": "pt-br"})
        return d if isinstance(d, dict) else {}
    except RuntimeError as e:
        log.error("%s", e)
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outdir", default="BDR/data")
    ap.add_argument("--no-detail", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    base = list_all()
    log.info("%d emissores de BDR na listagem", len(base))
    dets: list[dict[str, Any]] = [{}] * len(base)
    if not args.no_detail:
        with ThreadPoolExecutor(args.workers) as ex:
            dets = list(ex.map(lambda r: detail(r["codeCVM"]), base))

    hoje = date.today().isoformat()
    rows = []
    for r, d in zip(base, dets, strict=True):
        codes = d.get("otherCodes") or []
        rows.append(
            {
                "ticker": d.get("code") or "",
                "outros_codigos": ";".join(
                    c["code"] for c in codes if c.get("code") != d.get("code")
                ),
                "isin_bdr": ";".join(c.get("isin", "") for c in codes),
                "raiz": r["issuingCompany"],
                "empresa": r["companyName"].strip(),
                "nome_pregao": r["tradingName"].strip(),
                "tipo_bdr": r["typeBDR"],
                "tipo_desc": TIPOS.get(r["typeBDR"], r["typeBDR"]),
                "depositaria": (
                    d.get("institutionPreferred") or d.get("institutionCommon") or ""
                ).strip(),
                "site": d.get("website") or "",
                "categoria_b3": r.get("describleCategoryBVMF") or "",
                "mercado": r.get("market", ""),
                "data_listagem": r.get("dateListing", ""),
                "code_cvm": r["codeCVM"],
                "status": r["status"],
                "data_coleta": hoje,
            }
        )
    rows.sort(key=lambda x: (x["tipo_bdr"], x["ticker"] or x["raiz"]))

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    def write(path: Path, data: list[dict[str, str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(data)
        log.info("%d linhas em %s", len(data), path)

    write(out / "bdr_todos.csv", rows)
    write(out / "bdr_nao_patrocinados.csv", [r for r in rows if r["tipo_bdr"] == "DRN"])
    sem = sum(1 for r in rows if not r["ticker"]) if not args.no_detail else 0
    if sem:
        log.warning("%d emissores sem código de negociação no detalhe", sem)


if __name__ == "__main__":
    main()
