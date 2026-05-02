"""
Rastreador de KPIs (Key Performance Indicators) do sistema.

Monitora e agrega métricas de performance:
- Total de trades e win rate
- PnL médio e total
- Performance por regime de mercado
- Performance por engine
- Performance por nível de agressividade

Usado para análise de performance e otimização de estratégias.
"""
from collections import defaultdict
from typing import Dict, Any, DefaultDict, Tuple
import logging

from logging_config import setup_logging

# Configurar logging
logger = setup_logging("kpis", "INFO")


class KPITracker:
    """
    Rastreador de KPIs do sistema de trading.
    
    Coleta e agrega métricas de:
    - Sinais gerados
    - Trades executados
    - Performance por regime
    - Performance por engine
    - Performance por nível de agressividade
    
    Attributes:
        signal_counts: Contagem de sinais por (regime, engine, action)
        signal_confidence: Soma de confidências por (regime, engine, action)
        trade_count: Total de trades executados
        win_count: Trades lucrativos
        loss_count: Trades com prejuízo
        total_pnl: PnL total acumulado
        total_duration: Duração total em ticks
        engine_counts: Contagem por engine
        regime_counts: Contagem por regime
    """
    
    def __init__(self):
        """Inicializa rastreador de KPIs com contadores zerados."""
        # Rastreamento de sinais
        self.signal_counts: DefaultDict[Tuple[str, str, str], int] = defaultdict(int)
        self.signal_confidence: DefaultDict[Tuple[str, str, str], float] = defaultdict(float)
        
        # Métricas gerais de trades
        self.trade_count: int = 0
        self.win_count: int = 0
        self.loss_count: int = 0
        self.total_pnl: float = 0.0
        self.total_duration: int = 0
        
        # Contagens agregadas
        self.engine_counts: DefaultDict[str, int] = defaultdict(int)
        self.regime_counts: DefaultDict[str, int] = defaultdict(int)
        
        # Métricas por agressividade
        self.aggressiveness_trades: DefaultDict[str, int] = defaultdict(int)
        self.aggressiveness_wins: DefaultDict[str, int] = defaultdict(int)
        self.aggressiveness_pnl: DefaultDict[str, float] = defaultdict(float)
        self.aggressiveness_duration: DefaultDict[str, int] = defaultdict(int)
        
        logger.debug("KPITracker inicializado")
    
    def record_signal(
        self,
        symbol: str,
        regime: str,
        engine: str,
        action: str,
        confidence: float,
        exhausted: bool = False
    ) -> None:
        """
        Registra sinal gerado por uma engine.
        
        Args:
            symbol: Símbolo da moeda
            regime: Regime de mercado
            engine: Engine que gerou o sinal
            action: Ação sugerida (COMPRA, VENDA, NEUTRO)
            confidence: Confiança do sinal (0.0 a 1.0)
            exhausted: Se símbolo está em exaustão
        """
        # Registrar contagem de sinais
        key = (regime, engine, action)
        self.signal_counts[key] += 1
        self.signal_confidence[key] += float(confidence)
        
        # Atualizar contagens agregadas
        self.regime_counts[regime] += 1
        self.engine_counts[engine] += 1
        
        logger.debug(
            f"Sinal registrado: {symbol} {action} via {engine} "
            f"(regime: {regime}, conf: {confidence:.2f})"
        )
    
    def record_trade_result(self, trade_result: Dict[str, Any]) -> None:
        """
        Registra resultado de trade executado.
        
        Args:
            trade_result: Dicionário com resultado do trade
        """
        if not trade_result:
            logger.warning("trade_result vazio, ignorando")
            return
        
        # Incrementar contador
        self.trade_count += 1
        
        # Extrair dados
        pnl = trade_result.get("pnl", 0.0)
        duration = trade_result.get("duration_ticks", 0)
        aggressiveness = trade_result.get("aggressiveness", "UNKNOWN")
        
        # Atualizar totais
        self.total_pnl += pnl
        self.total_duration += duration
        
        # Classificar como win/loss
        if pnl >= 0:
            self.win_count += 1
            is_win = True
        else:
            self.loss_count += 1
            is_win = False
        
        # Registrar por agressividade
        self.aggressiveness_trades[aggressiveness] += 1
        self.aggressiveness_pnl[aggressiveness] += pnl
        self.aggressiveness_duration[aggressiveness] += duration
        
        if is_win:
            self.aggressiveness_wins[aggressiveness] += 1
        
        logger.debug(
            f"Trade registrado: PnL={pnl:+.2f}, "
            f"Duration={duration}, "
            f"Agressiveness={aggressiveness}, "
            f"Win={is_win}"
        )
    
    def get_win_rate(self) -> float:
        """
        Calcula win rate geral.
        
        Returns:
            Win rate (0.0 a 1.0)
        """
        if self.trade_count == 0:
            return 0.0
        return self.win_count / self.trade_count
    
    def get_avg_pnl(self) -> float:
        """
        Calcula PnL médio por trade.
        
        Returns:
            PnL médio
        """
        if self.trade_count == 0:
            return 0.0
        return self.total_pnl / self.trade_count
    
    def get_avg_duration(self) -> float:
        """
        Calcula duração média em ticks.
        
        Returns:
            Duração média
        """
        if self.trade_count == 0:
            return 0.0
        return self.total_duration / self.trade_count
    
    def summary(self) -> Dict[str, Any]:
        """
        Retorna resumo completo de KPIs.
        
        Returns:
            Dicionário com todas as métricas:
            {
                'trade_count': int,
                'win_rate': float,
                'avg_pnl': float,
                'avg_duration': float,
                'total_pnl': float,
                'signals_by_regime': dict,
                'signals_by_engine': dict,
                'signal_counts': dict,
                'by_aggressiveness': dict
            }
        """
        # Métricas gerais
        win_rate = self.get_win_rate()
        avg_pnl = self.get_avg_pnl()
        avg_duration = self.get_avg_duration()
        
        # Calcular métricas por agressividade
        aggressiveness_summary = {}
        
        for level in ["NORMAL", "REDUCED", "PROTECT", "UNKNOWN"]:
            trades = self.aggressiveness_trades[level]
            
            if trades > 0:
                wins = self.aggressiveness_wins[level]
                pnl = self.aggressiveness_pnl[level]
                duration = self.aggressiveness_duration[level]
                
                aggressiveness_summary[level] = {
                    "trades": trades,
                    "win_rate": round(wins / trades, 4),
                    "avg_pnl": round(pnl / trades, 6),
                    "total_pnl": round(pnl, 6),
                    "avg_duration": round(duration / trades, 2)
                }
        
        # Formatar contagens de sinais
        signal_counts_formatted = {
            f"{regime}|{engine}|{action}": count
            for (regime, engine, action), count in self.signal_counts.items()
        }
        
        summary = {
            "trade_count": self.trade_count,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 6),
            "avg_duration": round(avg_duration, 2),
            "total_pnl": round(self.total_pnl, 6),
            "signals_by_regime": dict(self.regime_counts),
            "signals_by_engine": dict(self.engine_counts),
            "signal_counts": signal_counts_formatted,
            "by_aggressiveness": aggressiveness_summary,
        }
        
        logger.debug(f"Summary gerado: {self.trade_count} trades, win_rate={win_rate:.1%}")
        
        return summary
    
    def reset(self) -> None:
        """Reseta todos os contadores para zero."""
        self.__init__()
        logger.info("KPIs resetados")
    
    def __repr__(self) -> str:
        """Representação string do tracker."""
        return (
            f"KPITracker(trades={self.trade_count}, "
            f"win_rate={self.get_win_rate():.1%}, "
            f"pnl={self.total_pnl:+.2f})"
        )
