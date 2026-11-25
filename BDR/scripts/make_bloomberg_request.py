"""Gera as listas de tickers para o export Bloomberg dos modelos BDR (MODELOS.md §3).

Saída em BDR/data/bloomberg_request/:
  etfs.csv          BDR de ETF setorial -> ETF nos EUA (universo amplo/completo) + IVV
  acoes.csv         BDR de ação -> ativo-objeto (sem REITs marcados no programa)
  tickers_us.txt    um ticker Bloomberg por linha (ETFs + IVV + ações), para colar no BDP/BDH
  tickers_dy.txt    só ações (EQY_DVD_YLD_12M e GICS)

Uso:
    python BDR/scripts/make_bloomberg_request.py
"""

from __future__ import annotations

import csv
from pathlib import Path

# BDR do ETF -> (ETF nos EUA, universo)
ETFS = {
    "BIVB39": ("IVV", "hedge"),
    "BIYW39": ("IYW", "amplo"),
    "BIYF39": ("IYF", "amplo"),
    "BIYE39": ("IYE", "amplo"),
    "BIYJ39": ("IYJ", "amplo"),
    "BIYK39": ("IYK", "amplo"),
    "BIYC39": ("IYC", "amplo"),
    "BIYM39": ("IYM", "amplo"),
    "BUTL39": ("IDU", "amplo"),
    "BIYZ39": ("IYZ", "amplo"),
    "BUSR39": ("USRT", "amplo"),
    "BIXJ39": ("IXJ", "amplo"),
    "BBMR39": ("BBRE", "completo"),
    "BIHE39": ("IHE", "completo"),
    "BIHI39": ("IHI", "completo"),
    "BIHF39": ("IHF", "completo"),
    "BIYP39": ("IYT", "completo"),
    "BAER39": ("ITA", "completo"),
    "BIAK39": ("IAK", "completo"),
    "BIEO39": ("IEO", "completo"),
    "BITB39": ("ITB", "completo"),
    "BSOX39": ("SOXX", "completo"),
    "BIAT39": ("IAT", "completo"),
    "BIBB39": ("IBB", "completo"),
}
US_EXCHANGES = {"US", "NYSE", "NASDAQ", "NASDAQ GM", "NASDAQ GS", "NASDAQ CM", "CBOE", "NYSE ARCA"}


def main() -> None:
    base = Path("BDR/data")
    out = base / "bloomberg_request"
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "etfs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bdr", "etf_us", "etf_bbg", "universo"])
        for bdr, (etf, uni) in ETFS.items():
            w.writerow([bdr, etf, f"{etf} US Equity", uni])

    with open(base / "bdr_master.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    acoes, fora = [], []
    for r in rows:
        if not (r["ticker"] and r["ticker_lastro"]):
            continue
        if r["tipo_lastro"].upper() == "REIT":
            fora.append((r["ticker"], "REIT (programa)"))
            continue
        if r["bolsa_lastro"].upper() not in US_EXCHANGES:
            fora.append((r["ticker"], f"lastro fora dos EUA: {r['bolsa_lastro']}"))
            continue
        acoes.append(r)

    with open(out / "acoes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bdr", "lastro", "lastro_bbg", "lastro_via", "empresa"])
        seen = set()
        for r in acoes:
            bbg = f"{r['ticker_lastro'].replace('.', '/')} US Equity"
            w.writerow([r["ticker"], r["ticker_lastro"], bbg, r["lastro_via"], r["empresa"]])
            seen.add(bbg)

    etf_bbg = [f"{e} US Equity" for e, _ in ETFS.values()]
    acoes_bbg = sorted(seen)
    (out / "tickers_us.txt").write_text("\n".join(etf_bbg + acoes_bbg) + "\n", encoding="utf-8")
    (out / "tickers_dy.txt").write_text("\n".join(acoes_bbg) + "\n", encoding="utf-8")
    with open(out / "excluidos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bdr", "motivo"])
        w.writerows(fora)
    print(f"{len(ETFS)} ETFs, {len(acoes_bbg)} ações-objeto, {len(fora)} excluídos -> {out}")


if __name__ == "__main__":
    main()
