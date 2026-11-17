"""
Contratos canônicos do núcleo de decisão.

Estes tipos definem a fronteira entre os drivers (`monitor.py`/`simular.py`)
e o `DecisionPipeline`. São estruturas puras (sem IO) e devem permanecer
estáveis: qualquer evolução do sistema (event bus, replay, execução real)
reutiliza os mesmos contratos.

Convenções:
- `symbol` é o símbolo de MERCADO (ex.: "SOL"), usado em regime, features
  e telemetria.
- `position_symbol` é a CHAVE lógica da posição/risco (ex.: "SIM" no
  simulador). Permite separar o ativo real do slot de portfólio.
- `action` preserva o vocabulário legado das engines
  ("COMPRA" | "VENDA" | "SAIR" | "HOLD" | "NEUTRO").
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Sequence


class OrderIntent(str, Enum):
    """Intenção de execução derivada da decisão."""

    HOLD = "HOLD"
    OPEN = "OPEN"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class MarketEvent:
    """
    Evento canônico de mercado consumido pelo pipeline.

    Attributes:
        symbol: Símbolo de mercado (ex.: "SOL").
        price: Preço corrente do evento.
        timestamp: Instante do evento (epoch) ou ordem lógica no replay.
        sequence: Ordem determinística do evento na sequência.
        prices: Janela de preços (mais recente primeiro). Pode ser
            pandas.Series ou sequência de floats.
        regime: Regime pré-computado pelo feed. Quando `None`, o
            pipeline calcula via `analyze_regime` injetado.
        regime_metrics: Métricas do regime (obrigatórias quando `regime`
            é informado e o feed não quer recalcular).
        source: Origem lógica do feed ("live", "db", "api", "synthetic").
    """

    symbol: str
    price: float
    timestamp: float = 0.0
    sequence: int = 0
    prices: Optional[Sequence[float]] = None
    regime: Optional[str] = None
    regime_metrics: Dict[str, Any] = field(default_factory=dict)
    source: str = "live"


@dataclass
class DecisionContext:
    """
    Contexto de execução de um evento, fornecido pelo driver.

    Não contém estado de decisão (esse vive no pipeline); apenas dados
    de ambiente e a chave de portfólio usada por posição/risco.
    """

    symbol: str
    position_symbol: Optional[str] = None
    tick: int = 0
    equity: Optional[float] = None
    equity_drawdown: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolved_position_symbol(self) -> str:
        """Retorna a chave de posição, usando `symbol` como fallback."""
        return self.position_symbol or self.symbol


@dataclass
class DecisionResult:
    """
    Resultado completo e auditável de uma decisão.

    Attributes:
        intent: Intenção de execução (HOLD/OPEN/CLOSE).
        action: Ação final no vocabulário legado.
        symbol: Símbolo de mercado.
        position_symbol: Chave lógica de posição/risco.
        price: Preço do evento.
        regime: Regime usado na decisão.
        regime_metrics: Métricas completas do regime.
        engine: Engine responsável pelo sinal final.
        confidence: Confiança do sinal final.
        details: Justificativa textual do sinal final.
        ml_score: Score do classificador ML, quando aplicável.
        blocked_by: Camada que bloqueou a entrada, se houve bloqueio.
        block_reason: Motivo textual do bloqueio.
        raw_signal: Sugestão bruta do orquestrador (antes dos filtros).
        signal: Sugestão final após a cadeia de filtros.
        position_decision: Decisão crua do `PositionManager`.
        trade_result: Resultado do trade, quando `intent == CLOSE`.
        position_side: Lado da posição mantida, quando `intent == HOLD`.
        trend_confirmation_count: Confirmações consecutivas no tick.
        regime_changed: Se o regime mudou em relação ao evento anterior.
        previous_regime: Regime anterior (mesma chave de posição).
        position_event: Evento do `PositionManager` (ENTRY/EXIT/HOLD/etc.).
        risk_event: Evento de risco (RISK_BLOCK/HIGH_VOLATILITY).
        filter_details: Detalhes por camada de filtro (telemetria).
        tick: Tick lógico informado pelo driver.
    """

    intent: OrderIntent
    action: str
    symbol: str
    position_symbol: str
    price: float = 0.0
    regime: str = "AGUARDANDO"
    regime_metrics: Dict[str, Any] = field(default_factory=dict)
    engine: str = "N/A"
    confidence: float = 0.0
    details: str = ""
    ml_score: Optional[float] = None
    blocked_by: Optional[str] = None
    block_reason: str = ""
    raw_signal: Dict[str, Any] = field(default_factory=dict)
    signal: Dict[str, Any] = field(default_factory=dict)
    position_decision: Dict[str, Any] = field(default_factory=dict)
    trade_result: Optional[Dict[str, Any]] = None
    position_side: Optional[str] = None
    trend_confirmation_count: int = 0
    regime_changed: bool = False
    previous_regime: Optional[str] = None
    position_event: Optional[str] = None
    risk_event: Optional[str] = None
    filter_details: Dict[str, Any] = field(default_factory=dict)
    tick: int = 0

    @property
    def is_blocked(self) -> bool:
        """True quando a entrada foi bloqueada por alguma camada."""
        return self.blocked_by is not None
