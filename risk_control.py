"""
Controlador de risco do sistema de trading.

Gerencia limites de exposição, drawdown, kill-switch e agressividade.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, DefaultDict, Optional
import logging

import config
from logging_config import log_risk_event

logger = logging.getLogger(__name__)


class RiskController:
    """
    Controla todos os aspectos de risco do sistema.
    
    Responsabilidades:
    - Limites de trades por regime e globais
    - Gestão de drawdown e equity
    - Kill-switch automático por perdas diárias
    - Níveis de agressividade (NORMAL, REDUCED, PROTECT)
    - Cooldown após trades
    - Rastreamento de trades bloqueados
    
    Attributes:
        aggressiveness_level: Nível atual ("NORMAL", "REDUCED", "PROTECT")
        current_equity_drawdown: Drawdown atual (0.0 a 1.0)
        kill_switch_activated: Se kill-switch está ativo
        global_trade_count: Total de trades hoje
        blocked_trades: Total de trades bloqueados
    """
    
    def __init__(self):
        """Inicializa o controlador de risco com valores padrão."""
        
        # Cooldown por símbolo (ticks)
        self.cooldown: DefaultDict[str, int] = defaultdict(int)
        
        # Contadores de trades
        self.trade_count_by_regime: DefaultDict[str, int] = defaultdict(int)
        self.global_trade_count: int = 0
        self.global_limit: int = config.GLOBAL_TRADE_LIMIT
        
        # Limites de trades por regime
        self.base_max_trades_by_regime: Dict[str, int] = config.BASE_MAX_TRADES_BY_REGIME.copy()
        self.max_trades_by_regime: Dict[str, int] = self.base_max_trades_by_regime.copy()
        
        # Controle de posições abertas
        self.max_open_positions: Dict[str, int] = config.MAX_OPEN_POSITIONS.copy()
        self.max_open_positions_by_symbol: Dict[str, int] = config.MAX_OPEN_POSITIONS_BY_SYMBOL.copy()
        self.open_position_limit_mode: str = "global"  # global, symbol, hybrid
        self.current_open_positions: DefaultDict[str, int] = defaultdict(int)
        self.total_open_positions: int = 0
        
        # Equity Risk Rules
        self.equity_drawdown_limit: float = config.EQUITY_DRAWDOWN_LIMIT
        self.current_equity_drawdown: float = 0.0
        self.aggressiveness_level: str = "NORMAL"
        self.min_confidence_for_reduced: float = config.MIN_CONFIDENCE_FOR_REDUCED
        
        # Kill-switch
        self.daily_loss_limit: float = config.DAILY_LOSS_LIMIT
        self.daily_start_equity: Optional[float] = None
        self.daily_losses: float = 0.0
        self.kill_switch_activated: bool = False
        self.kill_switch_hours: int = config.KILL_SWITCH_HOURS
        self.kill_switch_until: Optional[datetime] = None
        
        # Métricas de trades bloqueados
        self.blocked_trades: int = 0
        self.blocked_trades_by_regime: DefaultDict[str, int] = defaultdict(int)
        self.blocked_trades_by_aggressiveness: DefaultDict[str, int] = defaultdict(int)
        self.blocked_trades_by_reason: DefaultDict[str, int] = defaultdict(int)
        
        # Regras de reativação
        self.new_high_counter: int = 0
        self.min_new_highs_for_reactivation: int = config.MIN_NEW_HIGHS_FOR_REACTIVATION
        self.last_reset_day: datetime.date = datetime.now().date()
        self.last_equity_high: float = 0.0
        
        logger.info(
            f"RiskController inicializado: "
            f"DD_limit={self.equity_drawdown_limit:.1%}, "
            f"daily_loss_limit={self.daily_loss_limit:.1%}"
        )
    
    def update_drawdown(
        self,
        equity_drawdown: float,
        current_equity: Optional[float] = None
    ) -> None:
        """
        Atualiza drawdown e ajusta nível de agressividade.
        
        Lógica de proteção:
        - DD >= 25% → PROTECT (para tudo)
        - DD >= 15% → REDUCED (apenas trades de alta confiança)
        - Novo high em REDUCED → conta para reativação
        - 3 novos highs → volta para NORMAL
        
        Args:
            equity_drawdown: Drawdown atual (0.0 a 1.0)
            current_equity: Equity atual (opcional)
        """
        old_level = self.aggressiveness_level
        self.current_equity_drawdown = equity_drawdown
        
        # Inicializar baseline do dia
        new_high = False
        if current_equity is not None:
            if self.daily_start_equity is None:
                self.daily_start_equity = current_equity
                logger.info(f"Equity inicial do dia: R$ {current_equity:,.2f}")
            
            # Detectar novo high
            if current_equity > self.last_equity_high:
                new_high = True
                logger.debug(
                    f"Novo equity high: R$ {current_equity:,.2f} "
                    f"(anterior: R$ {self.last_equity_high:,.2f})"
                )
            
            # Verificar kill-switch por perda diária
            self._check_daily_loss_killswitch(current_equity)
        
        # Reset de contadores se necessário
        if current_equity is not None:
            self._reset_trade_counts_if_needed(current_equity)
        
        # PRIORIDADE 1: Kill-switch ativo
        if self.kill_switch_activated:
            now = datetime.now()
            if self.kill_switch_until and now < self.kill_switch_until:
                self.aggressiveness_level = "PROTECT"
                self.max_trades_by_regime = self._derive_regime_limits("PROTECT")
                return
            else:
                # Kill-switch expirou
                self._deactivate_killswitch()
        
        # PRIORIDADE 2: Drawdown >= 25% → PROTECT
        if equity_drawdown >= 0.25:
            self.aggressiveness_level = "PROTECT"
            self.max_trades_by_regime = self._derive_regime_limits("PROTECT")
            self.new_high_counter = 0
            
            if old_level != "PROTECT":
                log_risk_event(
                    logger, "PROTECT_MODE_ACTIVATED",
                    {"drawdown": equity_drawdown, "reason": "DD >= 25%"}
                )
            return
        
        # PRIORIDADE 3: Drawdown >= 15% → REDUCED
        if equity_drawdown >= 0.15:
            if self.aggressiveness_level == "PROTECT":
                self.aggressiveness_level = "REDUCED"
                self.new_high_counter = 0
                log_risk_event(
                    logger, "MODE_DOWNGRADE",
                    {"from": "PROTECT", "to": "REDUCED", "drawdown": equity_drawdown}
                )
            elif self.aggressiveness_level == "NORMAL":
                self.aggressiveness_level = "REDUCED"
                log_risk_event(
                    logger, "REDUCED_MODE_ACTIVATED",
                    {"drawdown": equity_drawdown, "reason": "DD >= 15%"}
                )
            
            self.max_trades_by_regime = self._derive_regime_limits("REDUCED")
            return
        
        # PRIORIDADE 4: Saindo de PROTECT → REDUCED
        if self.aggressiveness_level == "PROTECT":
            self.aggressiveness_level = "REDUCED"
            self.max_trades_by_regime = self._derive_regime_limits("REDUCED")
            self.new_high_counter = 0
            log_risk_event(
                logger, "MODE_UPGRADE",
                {"from": "PROTECT", "to": "REDUCED", "drawdown": equity_drawdown}
            )
            return
        
        # PRIORIDADE 5: REDUCED → NORMAL (requer 3 novos highs)
        if self.aggressiveness_level == "REDUCED":
            if current_equity is not None and new_high:
                self.new_high_counter += 1
                logger.info(
                    f"Novo high em REDUCED: {self.new_high_counter}/"
                    f"{self.min_new_highs_for_reactivation}"
                )
            
            if self.new_high_counter >= self.min_new_highs_for_reactivation:
                self.aggressiveness_level = "NORMAL"
                self.max_trades_by_regime = self._derive_regime_limits("NORMAL")
                self.new_high_counter = 0
                log_risk_event(
                    logger, "NORMAL_MODE_REACTIVATED",
                    {"new_highs": self.min_new_highs_for_reactivation}
                )
    
    def _check_daily_loss_killswitch(self, current_equity: float) -> None:
        """
        Verifica se deve ativar kill-switch por perda diária.
        
        Args:
            current_equity: Equity atual
        """
        if self.daily_start_equity is None or config.is_close(self.daily_start_equity, 0.0):
            return
        
        now = datetime.now()
        
        # Calcular perda diária
        daily_loss_pct = (
            (self.daily_start_equity - current_equity) / self.daily_start_equity
        )
        
        # Ativar kill-switch se necessário
        if daily_loss_pct >= self.daily_loss_limit and not self.kill_switch_activated:
            self.kill_switch_activated = True
            self.kill_switch_until = now + timedelta(hours=self.kill_switch_hours)
            self.aggressiveness_level = "PROTECT"
            self.max_trades_by_regime = self._derive_regime_limits("PROTECT")
            
            log_risk_event(
                logger, "KILL_SWITCH_ACTIVATED",
                {
                    "daily_loss_pct": daily_loss_pct,
                    "limit": self.daily_loss_limit,
                    "until": self.kill_switch_until.isoformat(),
                    "hours": self.kill_switch_hours,
                }
            )
    
    def _deactivate_killswitch(self) -> None:
        """Desativa kill-switch após expiração."""
        logger.info("🟢 Kill-switch expirado, reativando trading")
        self.kill_switch_activated = False
        self.kill_switch_until = None
        # Reduzir contador global como recompensa
        self.global_trade_count = max(0, self.global_trade_count - 2)
    
    def reset_regime_counts(self, old_regime: str) -> None:
        """
        Reseta contadores quando regime muda.
        
        Evita bloqueio desnecessário quando mercado muda de regime.
        
        Args:
            old_regime: Regime anterior
        """
        if old_regime in self.trade_count_by_regime:
            old_count = self.trade_count_by_regime[old_regime]
            self.trade_count_by_regime[old_regime] = 0
            logger.info(f"🔄 Resetado contador de {old_regime}: {old_count} → 0")
    
    def _reset_trade_counts_if_needed(self, current_equity: float) -> None:
        """
        Reseta contadores de trade quando necessário.
        
        Reset diário: zera tudo no início de novo dia.
        Reset por novo high: reduz contadores parcialmente.
        
        Args:
            current_equity: Equity atual
        """
        today = datetime.now().date()
        
        # Reset diário
        if today != self.last_reset_day:
            logger.info(
                f"🔄 Reset diário de contadores "
                f"(trades: {self.global_trade_count}, "
                f"posições: {self.total_open_positions})"
            )
            
            self.global_trade_count = 0
            self.trade_count_by_regime = defaultdict(int)
            self.current_open_positions = defaultdict(int)
            self.total_open_positions = 0
            self.kill_switch_activated = False
            self.kill_switch_until = None
            self.daily_start_equity = current_equity
            self.last_reset_day = today
        
        # Novo equity high - reset parcial
        if current_equity > self.last_equity_high:
            old_count = self.global_trade_count
            self.global_trade_count = max(0, self.global_trade_count - 2)
            self.last_equity_high = current_equity
            
            if old_count != self.global_trade_count:
                logger.debug(
                    f"Contador global reduzido por novo high: "
                    f"{old_count} → {self.global_trade_count}"
                )
    
    def _derive_regime_limits(self, level: str) -> Dict[str, int]:
        """
        Deriva limites de trades por regime baseado no nível.
        
        Args:
            level: "NORMAL", "REDUCED", ou "PROTECT"
            
        Returns:
            Dicionário com limites por regime
        """
        return config.get_regime_limits(level)
    
    def can_trade(
        self,
        action: str = "COMPRA",
        confidence: float = 0.0,
        regime: str = ""
    ) -> bool:
        """
        Verifica se pode fazer trades baseado em agressividade.
        
        Args:
            action: Tipo de ação ("COMPRA", "VENDA", "NEUTRO", etc)
            confidence: Confiança do sinal (0.0 a 1.0)
            regime: Regime de mercado
            
        Returns:
            True se pode executar o trade
        """
        # Sempre permitir saídas e holds
        if action in ("NEUTRO", "SAIR") or action.startswith("HOLD"):
            return True
        
        # Bloquear se drawdown muito alto
        if self.current_equity_drawdown >= self.equity_drawdown_limit:
            logger.debug(
                f"Trade bloqueado: DD {self.current_equity_drawdown:.1%} >= "
                f"{self.equity_drawdown_limit:.1%}"
            )
            return False
        
        # Verificar kill-switch
        if self.kill_switch_activated:
            now = datetime.now()
            if self.kill_switch_until and now < self.kill_switch_until:
                remaining = (self.kill_switch_until - now).total_seconds() / 60
                logger.debug(
                    f"Trade bloqueado: kill-switch ativo "
                    f"({remaining:.0f} min restantes)"
                )
                return False
            
            # Kill-switch expirou
            self._deactivate_killswitch()
        
        # Modo PROTECT: bloquear todas as entradas
        if self.aggressiveness_level == "PROTECT":
            logger.debug("Trade bloqueado: modo PROTECT ativo")
            return False
        
        # Modo REDUCED: apenas trades de alta confiança em regimes estáveis
        if self.aggressiveness_level == "REDUCED":
            # Bloquear regimes voláteis
            if regime in ("TRANSICAO", "ALTA_VOLATILIDADE"):
                logger.debug(
                    f"Trade bloqueado: regime {regime} em modo REDUCED"
                )
                return False
            
            # Exigir alta confiança
            if confidence < self.min_confidence_for_reduced:
                logger.debug(
                    f"Trade bloqueado: confidence {confidence:.2f} < "
                    f"{self.min_confidence_for_reduced:.2f} em REDUCED"
                )
                return False
        
        return True
    
    def _record_blocked_trade(self, regime: str, reason: Optional[str] = None) -> None:
        """
        Registra trade bloqueado nas métricas.
        
        Args:
            regime: Regime de mercado
            reason: Razão do bloqueio (opcional)
        """
        self.blocked_trades += 1
        self.blocked_trades_by_regime[regime] += 1
        self.blocked_trades_by_aggressiveness[self.aggressiveness_level] += 1
        
        if reason:
            self.blocked_trades_by_reason[reason] += 1
            logger.debug(f"Trade bloqueado: {reason} (regime: {regime})")
    
    def register_trade(self, symbol: str, regime: str, action: str) -> None:
        """
        Registra trade executado e atualiza contadores.
        
        Args:
            symbol: Símbolo da moeda
            regime: Regime de mercado
            action: Tipo de ação
        """
        if action not in ("COMPRA", "VENDA"):
            return
        
        self.trade_count_by_regime[regime] += 1
        self.global_trade_count += 1
        self.current_open_positions[symbol] += 1
        self.total_open_positions += 1
        
        # Cooldown padrão
        cooldown_ticks = config.COOLDOWN_AFTER_STOP.get(
            self.aggressiveness_level, 5
        )
        self.cooldown[symbol] = cooldown_ticks
        
        logger.info(
            f"Trade registrado: {symbol} {action} "
            f"(global: {self.global_trade_count}/{self.global_limit}, "
            f"regime: {self.trade_count_by_regime[regime]}/"
            f"{self.max_trades_by_regime.get(regime, 0)})"
        )
    
    def close_position(self, symbol: str) -> None:
        """
        Registra fechamento de posição.
        
        Args:
            symbol: Símbolo da moeda
        """
        if self.current_open_positions[symbol] > 0:
            self.current_open_positions[symbol] -= 1
            self.total_open_positions = max(0, self.total_open_positions - 1)
            logger.debug(
                f"Posição fechada: {symbol} "
                f"(posições abertas: {self.total_open_positions})"
            )
    
    def tick(self) -> None:
        """Atualiza estado por tick (decrementa cooldowns)."""
        for symbol in list(self.cooldown.keys()):
            if self.cooldown[symbol] > 0:
                self.cooldown[symbol] -= 1
    
    def can_execute(
        self,
        symbol: str,
        regime: str,
        action: str,
        confidence: float = 0.0
    ) -> bool:
        """
        Verifica se pode executar trade específico.
        
        Combina todas as regras de risco:
        - Cooldown por símbolo
        - Limite global de trades
        - Limite de posições abertas
        - Limite por regime
        - Filtros de agressividade
        
        Args:
            symbol: Símbolo da moeda
            regime: Regime de mercado
            action: Tipo de ação
            confidence: Confiança do sinal
            
        Returns:
            True se pode executar
        """
        # Sempre permitir ações neutras
        if action == "NEUTRO":
            return True
        
        # FILTRO 1: Cooldown
        if self.cooldown[symbol] > 0:
            self._record_blocked_trade(regime, reason="cooldown")
            return False
        
        # FILTRO 2: Limite global
        if self.global_trade_count >= self.global_limit:
            self._record_blocked_trade(regime, reason="global_limit")
            return False
        
        # FILTRO 3: Limite de posições abertas
        max_global = self.max_open_positions.get(self.aggressiveness_level, 0)
        max_symbol = self.max_open_positions_by_symbol.get(
            self.aggressiveness_level, 0
        )
        symbol_count = self.current_open_positions[symbol]
        
        if self.open_position_limit_mode == "symbol":
            if symbol_count >= max_symbol:
                self._record_blocked_trade(
                    regime, reason="open_position_symbol_limit"
                )
                return False
        
        elif self.open_position_limit_mode == "hybrid":
            if symbol_count >= max_symbol or self.total_open_positions >= max_global:
                self._record_blocked_trade(
                    regime, reason="open_position_hybrid_limit"
                )
                return False
        
        else:  # global mode
            if self.total_open_positions >= max_global:
                self._record_blocked_trade(
                    regime, reason="open_position_limit"
                )
                return False
        
        # FILTRO 4: Limite por regime
        regime_limit = self.max_trades_by_regime.get(regime, 0)
        if self.trade_count_by_regime[regime] >= regime_limit:
            self._record_blocked_trade(regime, reason="regime_limit")
            return False
        
        # FILTRO 5: Filtros de agressividade e confiança
        can_trade = self.can_trade(
            action=action, confidence=confidence, regime=regime
        )
        
        if not can_trade:
            self._record_blocked_trade(regime, reason="risk_filter")
        
        return can_trade
    
    def get_risk_status(self) -> Dict[str, any]:
        """
        Retorna status completo de risco.
        
        Returns:
            Dicionário com todas as métricas de risco
        """
        return {
            "equity_drawdown": self.current_equity_drawdown,
            "aggressiveness_level": self.aggressiveness_level,
            "global_trades": self.global_trade_count,
            "global_limit": self.global_limit,
            "trades_by_regime": dict(self.trade_count_by_regime),
            "current_open_positions_by_symbol": dict(self.current_open_positions),
            "total_open_positions": self.total_open_positions,
            "kill_switch_active": self.kill_switch_activated,
            "kill_switch_until": (
                self.kill_switch_until.isoformat() 
                if self.kill_switch_until else None
            ),
            "blocked_trades": self.blocked_trades,
            "blocked_trades_by_regime": dict(self.blocked_trades_by_regime),
            "blocked_trades_by_aggressiveness": dict(
                self.blocked_trades_by_aggressiveness
            ),
            "blocked_trades_by_reason": dict(self.blocked_trades_by_reason),
            "can_trade": self.can_trade(),
            "new_high_counter": self.new_high_counter,
        }
