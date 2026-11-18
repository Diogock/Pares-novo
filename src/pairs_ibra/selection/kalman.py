"""Hedge dinâmico via filtro de Kalman (fase 5). Ainda não implementado."""

from __future__ import annotations


class KalmanSelector:
    method = "kalman"

    def select(self, *args: object, **kwargs: object) -> list[object]:
        raise NotImplementedError("selection.method=kalman é da fase 5")
