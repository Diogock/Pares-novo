"""Métodos de seleção de pares."""

from __future__ import annotations

from pairs_ibra.selection.base import PairSelector, PairSpec
from pairs_ibra.selection.cointegration import CointegrationSelector
from pairs_ibra.selection.distance import DistanceSelector


def get_selector(method: str) -> PairSelector:
    if method == "cointegration":
        return CointegrationSelector()
    if method == "distance":
        return DistanceSelector()
    raise ValueError(f"método de seleção não implementado: {method}")


__all__ = ["PairSpec", "PairSelector", "get_selector"]
