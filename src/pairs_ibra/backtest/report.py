"""Relatório HTML estático de uma rodada (gráficos matplotlib embutidos + tabelas)."""

from __future__ import annotations

import base64
import html
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from pairs_ibra.backtest.engine import BacktestResult  # noqa: E402
from pairs_ibra.backtest.metrics import drawdown, summary  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES_1 = "#2a78d6"   # estratégia
SERIES_2 = "#eb6834"   # CDI

PCT_KEYS = {"return_total", "return_ann", "cdi_ann", "excess_ann", "vol_ann", "max_drawdown",
            "hit_rate", "avg_return_trade", "cost_pct_gross"}


def _style(ax: Any, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=11, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TEXT_2, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _png(fig: Any) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=144, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _charts(res: BacktestResult) -> list[tuple[str, str]]:
    nav = res.nav
    out = []
    base = nav["nav"].iloc[0]
    strat = nav["nav"] / base
    cdi = (1 + nav["cdi_daily"]).cumprod()
    cdi = cdi / cdi.iloc[0]

    fig, ax = plt.subplots(figsize=(9, 3.4), facecolor=SURFACE)
    _style(ax, "NAV (base 1) vs CDI")
    ax.plot(strat.index, strat, color=SERIES_1, linewidth=2, label="Estratégia")
    ax.plot(cdi.index, cdi, color=SERIES_2, linewidth=2, label="CDI")
    for s, name in ((strat, "Estratégia"), (cdi, "CDI")):
        ax.annotate(f"{name} {s.iloc[-1]:.2f}", (s.index[-1], s.iloc[-1]), xytext=(4, 0),
                    textcoords="offset points", color=TEXT, fontsize=8, va="center")
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT, loc="upper left")
    out.append(("NAV vs CDI", _png(fig)))

    dd = drawdown(nav["nav"]) * 100
    fig, ax = plt.subplots(figsize=(9, 2.4), facecolor=SURFACE)
    _style(ax, "Drawdown (%)")
    ax.fill_between(dd.index, dd, 0, color=SERIES_1, alpha=0.35, linewidth=0)
    ax.plot(dd.index, dd, color=SERIES_1, linewidth=1.2)
    out.append(("Drawdown", _png(fig)))

    expo = nav["gross"] / nav["nav"] * 100
    fig, ax = plt.subplots(figsize=(9, 2.4), facecolor=SURFACE)
    _style(ax, "Exposição bruta (% do NAV)")
    ax.plot(expo.index, expo, color=SERIES_1, linewidth=1.5)
    ax.set_ylim(bottom=0)
    out.append(("Exposição", _png(fig)))

    if not res.trades.empty:
        reasons = res.trades["exit_reason"].value_counts(normalize=True).sort_values() * 100
        fig, ax = plt.subplots(figsize=(9, 0.4 * len(reasons) + 0.8), facecolor=SURFACE)
        _style(ax, "Motivo de saída (% dos trades)")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
        ax.barh(reasons.index, reasons.to_numpy(), color=SERIES_1, height=0.6)
        for i, v in enumerate(reasons.to_numpy()):
            ax.text(float(v) + 0.5, i, f"{v:.0f}%", va="center", color=TEXT, fontsize=8)
        out.append(("Saídas", _png(fig)))
    return out


def _fmt(k: str, v: Any) -> str:
    if isinstance(v, float):
        if k in PCT_KEYS or k.startswith("exit_"):
            return f"{v:.2%}"
        if v.is_integer() and abs(v) < 1e5:
            return f"{v:,.0f}"
        return f"{v:,.2f}"
    return html.escape(str(v))


def _dict_table(d: dict[str, Any]) -> str:
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{_fmt(k, v)}</td></tr>" for k, v in d.items())
    return f"<table>{rows}</table>"


def _frame_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "<p>—</p>"
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = ""
    for idx, r in df.iterrows():
        cells = "".join(f"<td>{_fmt(str(c), v)}</td>" for c, v in r.items())
        body += f"<tr><th>{html.escape(str(idx))}</th>{cells}</tr>"
    return f"<table><tr><th></th>{head}</tr>{body}</table>"


def render_html(res: BacktestResult, run_id: str) -> str:
    s = summary(res)
    charts = "".join(f'<figure><img alt="{html.escape(t)}" src="data:image/png;base64,{b}"/></figure>'
                     for t, b in _charts(res))
    general = {**s["performance"], "turnover_ann": s["turnover_ann"],
               "avg_gross_exposure": s["avg_gross_exposure"], "avg_positions": s["avg_positions"]}
    sections = [
        ("Desempenho (período inteiro)", _dict_table(general)),
        ("Calibração vs OOS", _frame_table(s["calibration_oos"])),
        ("Subperíodos", _frame_table(s["subperiods"])),
        ("Trades", _dict_table(s["trades"])),
        ("Mesmo emissor (ON/PN) vs demais", _frame_table(s.get("by_issuer", pd.DataFrame()))),
        ("Intra-setor vs cross-setor", _frame_table(s.get("by_sector_type", pd.DataFrame()))),
        ("Por setor (perna A)", _frame_table(s.get("by_sector", pd.DataFrame()))),
        ("Por motivo de saída", _frame_table(s.get("by_exit", pd.DataFrame()))),
    ]
    body = "".join(f"<h2>{t}</h2>{c}" for t, c in sections)
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Backtest {html.escape(run_id)}</title>
<style>
body {{ font-family: system-ui, sans-serif; background: {SURFACE}; color: {TEXT};
       max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.05rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; font-size: .82rem; margin: .5rem 0; }}
th, td {{ padding: .25rem .6rem; border-bottom: 1px solid {GRID}; text-align: right; }}
th {{ text-align: left; color: {TEXT_2}; font-weight: 500; }}
figure {{ margin: 1rem 0; }} img {{ max-width: 100%; }}
.meta {{ color: {TEXT_2}; font-size: .85rem; }}
</style></head><body>
<h1>Backtest pairs IBRA — {html.escape(run_id)}</h1>
<p class="meta">Método: {res.config.selection.method} · execução: {res.config.signal.execution} ·
{res.nav.index.min().date()} a {res.nav.index.max().date()} · Sharpe em excesso de CDI, sobre o capital.</p>
{charts}{body}
</body></html>"""
