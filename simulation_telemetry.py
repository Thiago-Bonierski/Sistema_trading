"""
Simulation Telemetry - Rastreador de funil de decisões de trading.

Contabiliza tick a tick o destino de cada oportunidade:
- Total de ticks analisados por regime
- Sinais brutos gerados por cada engine
- Sinais barrados em cada camada e o motivo
- Trades executados com detalhes completos

O objetivo é tornar cada decisão do bot 100% transparente e auditável.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from collections import defaultdict
import pandas as pd

logger = logging.getLogger("simulation_telemetry")


# ============================================================================
# Enumerações para tipagem
# ============================================================================

class Regime(Enum):
    """Tipos de regime de mercado."""
    TENDENCIA_ALTA = "TENDENCIA_ALTA"
    TENDENCIA_BAIXA = "TENDENCIA_BAIXA"
    CONSOLIDACAO = "CONSOLIDACAO"
    TRANSICAO = "TRANSICAO"
    ALTA_VOLATILIDADE = "ALTA_VOLATILIDADE"
    AGUARDANDO = "AGUARDANDO"


class SignalSource(Enum):
    """Motor que gerou o sinal."""
    TREND_FOLLOWING = "TrendFollowing"
    MEAN_REVERSION = "MeanReversion"
    BREAKOUT_MOMENTUM = "BreakoutMomentum"
    PROTECT_FLAT = "ProtectFlat"
    ML_CLASSIFIER = "MLClassifier"
    EXHAUSTION_FILTER = "ExhaustionFilter"
    TREND_CONFIRMATION = "TrendConfirmationFilter"


class FilterResult(Enum):
    """Resultado do filtro em cada camada."""
    APPROVED = "approved"
    BLOCKED = "blocked"
    FILTERED = "filtered"


@dataclass
class TickDecision:
    """Registro de uma decisão em um tick específico."""
    tick: int
    price: float
    regime: Regime
    raw_signals: Dict[str, Any] = field(default_factory=dict)
    filtered_signals: Dict[str, Any] = field(default_factory=dict)
    final_action: str = "NEUTRO"
    final_engine: str = ""
    final_confidence: float = 0.0
    ml_score: Optional[float] = None
    filter_details: Dict[str, Any] = field(default_factory=dict)
    trade_executed: bool = False
    trade_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeRecord:
    """Registro completo de um trade executado."""
    entry_tick: int
    exit_tick: Optional[int]
    symbol: str
    regime_entry: Regime
    engine_entry: SignalSource
    confidence_entry: float
    ml_score_entry: Optional[float]
    entry_price: float
    exit_price: Optional[float]
    exit_reason: str  # STOP_LOSS, TAKE_PROFIT, MAX_AGE, REGIME_CHANGE, DATA_GAP
    pnl: float
    duration_ticks: int
    final_regime: Regime
    final_engine: SignalSource


# ============================================================================
# SimulationTelemetry - O Rastreador Principal
# ============================================================================

class SimulationTelemetry:
    """
    Rastreador de funil de decisões da simulação.
    
    Contabiliza, tick a tick, o destino de cada oportunidade de trading,
    permitindo auditores entenderem exatamente por que cada sinal foi
    aceito, modificado ou rejeitado.
    """
    
    def __init__(self, 
                 symbol: str = "USD",
                 enable_detailed_log: bool = True,
                 enable_funnel_stats: bool = True):
        self.symbol = symbol
        self.enable_detailed_log = enable_detailed_log
        self.enable_funnel_stats = enable_funnel_stats
        
        # Contadores de funil
        self.funnel_stats = {
            "total_ticks": 0,
            "ticks_by_regime": defaultdict(int),
            "raw_signals_by_engine": defaultdict(int),
            "signals_approved": 0,
            "signals_blocked_trend_confirmation": 0,
            "signals_blocked_exhaustion": 0,
            "signals_blocked_ml": 0,
            "signals_blocked_risk_controller": 0,
            "signals_blocked_position_slot": 0,
            "trades_executed": 0,
            "trades_by_regime": defaultdict(int),
            "trades_by_engine": defaultdict(int),
        }
        
        # Histórico detalhado de ticks
        self.tick_history: List[TickDecision] = []
        
        # Histórico de trades
        self.trade_history: List[TradeRecord] = []
        
        # Contador interno
        self._tick_counter = 0
    
    def reset(self) -> None:
        """Reseta todos os estatísticos para nova simulação."""
        self.funnel_stats = {
            "total_ticks": 0,
            "ticks_by_regime": defaultdict(int),
            "raw_signals_by_engine": defaultdict(int),
            "signals_approved": 0,
            "signals_blocked_trend_confirmation": 0,
            "signals_blocked_exhaustion": 0,
            "signals_blocked_ml": 0,
            "signals_blocked_risk_controller": 0,
            "signals_blocked_position_slot": 0,
            "trades_executed": 0,
            "trades_by_regime": defaultdict(int),
            "trades_by_engine": defaultdict(int),
        }
        self.tick_history = []
        self.trade_history = []
        self._tick_counter = 0
    
    def tick(self, 
             price: float, 
             regime: Regime,
             raw_signals: Dict[str, Any],
             filtered_signals: Dict[str, Any],
             final_action: str,
             final_engine: str,
             final_confidence: float,
             ml_score: Optional[float] = None,
             filter_details: Dict[str, Any] = None) -> None:
        """
        Registra uma decisão de um tick.
        
        Args:
            price: Preço do tick
            regime: Regime de mercado
            raw_signals: Sinais brutos antes dos filtros
            filtered_signals: Sinais após filtros parciais
            final_action: Ação final (COMPRA, VENDA, NEUTRO)
            final_engine: Engine que ficou responsável pela decisão
            final_confidence: Confiança final da decisão
            ml_score: Score do classificador ML (se aplicável)
            filter_details: Detalhes de quais filtros bloquearam/autorizaram
        """
        self._tick_counter += 1
        
        # Atualizar contadores de funil
        self.funnel_stats["total_ticks"] += 1
        self.funnel_stats["ticks_by_regime"][regime.value] += 1
        
        # Contar sinais brutos por engine
        for engine, signal_data in raw_signals.items():
            if isinstance(signal_data, dict) and "action" in signal_data:
                if signal_data["action"] in ("COMPRA", "VENDA"):
                    # engine é já uma string (chave do dicionário)
                    self.funnel_stats["raw_signals_by_engine"][engine] += 1
        
        # Contar sinais aprovados
        if final_action in ("COMPRA", "VENDA"):
            self.funnel_stats["signals_approved"] += 1

        # Contar sinais bloqueados por cada filtro
        fd = filter_details or {}
        if fd.get("trend_confirmation", {}).get("blocked"):
            self.funnel_stats["signals_blocked_trend_confirmation"] += 1
        if fd.get("exhaustion", {}).get("blocked"):
            self.funnel_stats["signals_blocked_exhaustion"] += 1
        if fd.get("ml", {}).get("blocked"):
            self.funnel_stats["signals_blocked_ml"] += 1
        if fd.get("risk_controller", {}).get("blocked"):
            self.funnel_stats["signals_blocked_risk_controller"] += 1
        if fd.get("position_slot", {}).get("blocked"):
            self.funnel_stats["signals_blocked_position_slot"] = (
                self.funnel_stats.get("signals_blocked_position_slot", 0) + 1
            )
        
        # Registrar decisão detalhada
        decision = TickDecision(
            tick=self._tick_counter,
            price=price,
            regime=regime,
            raw_signals=raw_signals,
            filtered_signals=filtered_signals,
            final_action=final_action,
            final_engine=final_engine,
            final_confidence=final_confidence,
            ml_score=ml_score,
            filter_details=filter_details or {},
        )
        self.tick_history.append(decision)
        
        # Log detalhado se habilitado
        if self.enable_detailed_log:
            self._log_tick_decision(decision)
    
    def _log_tick_decision(self, decision: TickDecision) -> None:
        """Loga uma decisão de tick no logger."""
        signal_summary = ""
        if decision.raw_signals:
            for engine, data in decision.raw_signals.items():
                if isinstance(data, dict) and "action" in data:
                    action = data["action"]
                    confidence = data.get("confidence", 0.0)
                    signal_summary += f" {engine}:{action}({confidence:.2f})"
        
        ml_info = f" | ML:{decision.ml_score:.2f}" if decision.ml_score is not None else ""
        
        logger.info(
            f"TICK {decision.tick} | PREÇO:{decision.price:,.0f} | "
            f"REGIME:{decision.regime.value} | "
            f"AÇÃO:{decision.final_action} | "
            f"ENGINE:{decision.final_engine} | "
            f"CONF:{decision.final_confidence:.2f}{ml_info} | "
            f"FILTROS:{decision.filter_details}"
        )
    
    def record_trade(self, trade: TradeRecord) -> None:
        """Registra um trade executado."""
        self.funnel_stats["trades_executed"] += 1
        self.funnel_stats["trades_by_regime"][trade.regime_entry.value] += 1
        self.funnel_stats["trades_by_engine"][trade.engine_entry.value] += 1
        self.trade_history.append(trade)
        
        if self.enable_detailed_log:
            logger.info(
                f"TRADE EXECUTADO | TICK:{trade.entry_tick} | "
                f"REGIME:{trade.regime_entry.value} | "
                f"ENGINE:{trade.engine_entry.value} | "
                f"ENTRADA:R$ {trade.entry_price:,.2f} | "
                f"SAÍDA:R$ {trade.exit_price or 0:,.2f} | "
                f"MOTIVO:{trade.exit_reason} | "
                f"PNL:R$ {trade.pnl:,.2f} | "
                f"DURACAO:{trade.duration_ticks} ticks"
            )
    
    def get_funnel_report(self) -> Dict[str, Any]:
        """Gera relatório resumido do funil de decisões."""
        total = self.funnel_stats["total_ticks"]
        approved = self.funnel_stats["signals_approved"]
        
        return {
            "symbol": self.symbol,
            "total_ticks": total,
            "total_signals_approved": approved,
            "approval_rate": round(approved / total * 100, 2) if total > 0 else 0.0,
            "trades_executed": self.funnel_stats["trades_executed"],
            "win_rate": self._calculate_overall_win_rate(),
            "regime_breakdown": dict(self.funnel_stats["ticks_by_regime"]),
            "engine_signal_breakdown": dict(self.funnel_stats["raw_signals_by_engine"]),
            "filter_stats": {
                "blocked_trend_confirmation": self.funnel_stats["signals_blocked_trend_confirmation"],
                "blocked_exhaustion": self.funnel_stats["signals_blocked_exhaustion"],
                "blocked_ml": self.funnel_stats["signals_blocked_ml"],
                "blocked_risk_controller": self.funnel_stats["signals_blocked_risk_controller"],
                "blocked_position_slot": self.funnel_stats.get("signals_blocked_position_slot", 0),
            },
            "trades_by_regime": dict(self.funnel_stats["trades_by_regime"]),
            "trades_by_engine": dict(self.funnel_stats["trades_by_engine"]),
        }
    
    def _calculate_overall_win_rate(self) -> float:
        """Calcula a taxa de vitória geral baseada no histórico de trades."""
        if not self.trade_history:
            return 0.0
        winning_trades = sum(1 for t in self.trade_history if t.pnl >= 0)
        return round(winning_trades / len(self.trade_history) * 100, 2)
    
    def export_to_dataframe(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Exporta os dados para DataFrames pandas para análise."""
        tick_df = pd.DataFrame([
            {
                "tick": d.tick,
                "price": d.price,
                "regime": d.regime.value,
                "final_action": d.final_action,
                "final_engine": d.final_engine,
                "final_confidence": d.final_confidence,
                "ml_score": d.ml_score,
            }
            for d in self.tick_history
        ])
        
        trade_df = pd.DataFrame([
            {
                "entry_tick": t.entry_tick,
                "exit_tick": t.exit_tick,
                "symbol": t.symbol,
                "regime_entry": t.regime_entry.value,
                "engine_entry": t.engine_entry.value,
                "confidence_entry": t.confidence_entry,
                "ml_score_entry": t.ml_score_entry,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price or 0.0,
                "exit_reason": t.exit_reason,
                "pnl": t.pnl,
                "duration_ticks": t.duration_ticks,
                "final_regime": t.final_regime.value,
                "final_engine": t.final_engine.value,
            }
            for t in self.trade_history
        ])
        
        return tick_df, trade_df


# ============================================================================
# Funções de utilidade para integração com o simulador
# ============================================================================

def create_default_raw_signals() -> Dict[str, Any]:
    """Cria dicionário vazio de sinais brutos para inicialização."""
    return {
        "TrendFollowing": {"action": "NEUTRO", "confidence": 0.0, "engine": "TrendFollowing"},
        "MeanReversion": {"action": "NEUTRO", "confidence": 0.0, "engine": "MeanReversion"},
        "BreakoutMomentum": {"action": "NEUTRO", "confidence": 0.0, "engine": "BreakoutMomentum"},
        "ProtectFlat": {"action": "NEUTRO", "confidence": 0.0, "engine": "ProtectFlat"},
    }


def create_default_filter_details() -> Dict[str, Any]:
    """Cria dicionário vazio de detalhes de filtros."""
    return {
        "trend_confirmation": {"blocked": False, "reason": ""},
        "exhaustion": {"blocked": False, "reason": ""},
        "ml": {"blocked": False, "score": 0.0, "threshold": 0.58},
        "risk_controller": {"blocked": False, "reason": ""},
    }