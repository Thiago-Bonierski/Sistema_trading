"""
Gerenciamento de equity (capital) do sistema.

Classe unificada usada tanto em produção quanto em simulação.
"""
from typing import Optional
import logging

import config

logger = logging.getLogger(__name__)


class EquityManager:
    """
    Gerencia o capital (equity) do sistema de trading.
    
    Rastreia equity atual, pico histórico, drawdown e retorno total.
    Thread-safe quando usado corretamente (uma instância por estratégia).
    """
    
    def __init__(self, initial_capital: float = config.INITIAL_CAPITAL):
        """
        Inicializa o gerenciador de equity.
        
        Args:
            initial_capital: Capital inicial em valor absoluto
        """
        self.initial_capital = initial_capital
        self.current_equity = initial_capital
        self.peak_equity = initial_capital
        self.max_drawdown = 0.0
        
        # Rastreamento de histórico
        self.equity_history = [initial_capital]
        self.pnl_history = []
        
        logger.info(
            f"EquityManager inicializado com capital: "
            f"R$ {initial_capital:,.2f}"
        )
    
    def update_equity(self, pnl_amount: float) -> None:
        """
        Atualiza equity baseado em PnL de um trade.
        
        Args:
            pnl_amount: Valor absoluto de lucro/prejuízo do trade
        """
        # Atualizar equity
        self.current_equity += pnl_amount
        
        # Registrar no histórico
        self.equity_history.append(self.current_equity)
        self.pnl_history.append(pnl_amount)
        
        # Atualizar pico
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
            logger.debug(f"Novo pico de equity: R$ {self.peak_equity:,.2f}")
        
        # Calcular drawdown
        if self.peak_equity > 0:
            current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, current_drawdown)
            
            # Alertar se drawdown significativo
            if current_drawdown > 0.10:  # > 10%
                logger.warning(
                    f"Drawdown significativo: {current_drawdown:.1%} "
                    f"(max: {self.max_drawdown:.1%})"
                )
        
        logger.debug(
            f"Equity atualizado: R$ {self.current_equity:,.2f} "
            f"(PnL: {pnl_amount:+.2f})"
        )
    
    def get_max_equity_drawdown(self) -> float:
        """
        Retorna o drawdown máximo histórico.
        
        Returns:
            Drawdown máximo como porcentagem (0.0 a 1.0)
        """
        return self.max_drawdown
    
    def get_current_drawdown(self) -> float:
        """
        Retorna o drawdown atual.
        
        Returns:
            Drawdown atual como porcentagem (0.0 a 1.0)
        """
        if self.peak_equity > 0:
            return (self.peak_equity - self.current_equity) / self.peak_equity
        return 0.0
    
    def get_total_return(self) -> float:
        """
        Retorna o retorno total desde o início.
        
        Returns:
            Retorno como porcentagem (0.0 = 0%, 1.0 = 100%, etc)
        """
        if self.initial_capital > 0:
            return (self.current_equity - self.initial_capital) / self.initial_capital
        return 0.0
    
    def get_total_pnl(self) -> float:
        """
        Retorna PnL total absoluto.
        
        Returns:
            Valor absoluto de lucro/prejuízo
        """
        return self.current_equity - self.initial_capital
    
    def reset(self, new_capital: Optional[float] = None) -> None:
        """
        Reseta equity para novo capital (útil para simulações).
        
        Args:
            new_capital: Novo capital inicial (usa original se None)
        """
        capital = new_capital if new_capital is not None else self.initial_capital
        
        self.initial_capital = capital
        self.current_equity = capital
        self.peak_equity = capital
        self.max_drawdown = 0.0
        self.equity_history = [capital]
        self.pnl_history = []
        
        logger.info(f"Equity resetado para R$ {capital:,.2f}")
    
    def get_summary(self) -> dict:
        """
        Retorna resumo completo do estado do equity.
        
        Returns:
            Dicionário com métricas principais
        """
        return {
            "initial_capital": self.initial_capital,
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "total_return_pct": self.get_total_return() * 100,
            "total_pnl": self.get_total_pnl(),
            "current_drawdown_pct": self.get_current_drawdown() * 100,
            "max_drawdown_pct": self.max_drawdown * 100,
            "trade_count": len(self.pnl_history),
        }
    
    def __repr__(self) -> str:
        """Representação string do equity manager."""
        return (
            f"EquityManager(equity=R${self.current_equity:,.2f}, "
            f"return={self.get_total_return():.1%}, "
            f"dd={self.get_current_drawdown():.1%})"
        )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_currency(value: float) -> str:
    """
    Formata valor como moeda brasileira.
    
    Args:
        value: Valor a formatar
        
    Returns:
        String formatada (ex: "R$ 1.234,56")
    """
    return f"R$ {value:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')


def format_percentage(value: float, decimals: int = 2) -> str:
    """
    Formata valor como porcentagem.
    
    Args:
        value: Valor entre 0 e 1 (ou maior)
        decimals: Casas decimais
        
    Returns:
        String formatada (ex: "15.5%")
    """
    return f"{value * 100:.{decimals}f}%"
