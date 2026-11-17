"""Núcleo determinístico de decisão do Sistema_trading.

Expõe os contratos canônicos e o `DecisionPipeline` compartilhado por
`monitor.py` (produção) e `simular.py` (backtest/pesquisa).
"""

from core.contracts import (
    DecisionContext,
    DecisionResult,
    MarketEvent,
    OrderIntent,
)
from core.pipeline import DecisionPipeline, TrendConfirmationTracker

__all__ = [
    "DecisionContext",
    "DecisionResult",
    "MarketEvent",
    "OrderIntent",
    "DecisionPipeline",
    "TrendConfirmationTracker",
]
