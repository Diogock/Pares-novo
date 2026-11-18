"""Restrições da carteira de pares (CLAUDE.md, seção 5.2, etapa D).

Escolha gulosa por score: no máximo ``max_pairs_per_stock`` pares por ação e
no máximo ``ceil(max_sector_pct × n_pairs)`` pares por setor. Um par cross-setor
conta para os dois setores; ``SEM_SETOR`` não tem limite.
"""

from __future__ import annotations

import math
from collections import Counter

from pairs_ibra.config import PortfolioConfig
from pairs_ibra.selection.base import PairSpec


def apply_constraints(ranked: list[PairSpec], cfg: PortfolioConfig) -> list[PairSpec]:
    per_stock: Counter[str] = Counter()
    per_sector: Counter[str] = Counter()
    max_sector = max(1, math.ceil(cfg.max_sector_pct * cfg.n_pairs - 1e-9))
    chosen: list[PairSpec] = []
    seen: set[tuple[str, str]] = set()
    for s in ranked:
        if len(chosen) >= cfg.n_pairs:
            break
        if s.key in seen:
            continue
        if s.same_issuer and not cfg.include_same_issuer:
            continue
        if per_stock[s.leg_a] >= cfg.max_pairs_per_stock or per_stock[s.leg_b] >= cfg.max_pairs_per_stock:
            continue
        secs = {x for x in (s.sector_a, s.sector_b) if x and x != "SEM_SETOR"}
        if any(per_sector[x] >= max_sector for x in secs):
            continue
        chosen.append(s)
        seen.add(s.key)
        per_stock[s.leg_a] += 1
        per_stock[s.leg_b] += 1
        for x in secs:
            per_sector[x] += 1
    return chosen
