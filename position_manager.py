"""
Gerenciamento de posições abertas no sistema de trading.

Controla entradas, saídas, stop-loss, take-profit e idade das posições.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging
import threading

import config

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """
    Representa uma posição aberta no mercado.
    
    Attributes:
        side: Direção da posição ("COMPRA" ou "VENDA")
        entry_price: Preço de entrada
        stop_loss: Preço de stop-loss
        take_profit: Preço de take-profit
        entry_tick: Tick de entrada
        position_size: Tamanho da posição em valor absoluto
        age: Idade atual em ticks (incrementada a cada avaliação)
        regime: Regime de mercado na entrada
        engine: Engine que gerou o sinal
        confidence: Confiança do sinal (0.0 a 1.0)
        details: Detalhes adicionais do sinal
        entry_fee: Comissão paga na abertura (position_size * TRADING_FEE_PCT)
        
    Note:
        max_age_ticks é CALCULADO DINAMICAMENTE baseado no RiskController.
        Não é armazenado aqui para permitir que mudanças de nível de risco
        ajustem automaticamente a idade máxima das posições.
    """
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_tick: int
    position_size: float
    age: int = 0
    regime: str = ""
    engine: str = ""
    confidence: float = 0.0
    details: str = ""
    # Snapshot pré-trade persistido junto ao fechamento. Permite treinar ML
    # com as métricas de mercado realmente observadas na entrada.
    regime_metrics: Dict[str, Any] = field(default_factory=dict)
    ml_score: Optional[float] = None
    # Contador de histerese: avaliações consecutivas em TRANSICAO.
    # Zerado sempre que o regime volta a ser direcional/consolidação.
    transition_ticks: int = 0
    # Fee da perna de entrada, travada na abertura para não mudar se a
    # calibragem for alterada enquanto a posição está aberta.
    entry_fee: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializa a posição para persistência.
        
        Returns:
            Dict com todos os campos da posição
        """
        return {
            "side": self.side,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "entry_tick": self.entry_tick,
            "position_size": self.position_size,
            "age": self.age,
            "regime": self.regime,
            "engine": self.engine,
            "confidence": self.confidence,
            "details": self.details,
            "regime_metrics": dict(self.regime_metrics),
            "ml_score": self.ml_score,
            "transition_ticks": self.transition_ticks,
            "entry_fee": self.entry_fee,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        """
        Reconstrói uma posição a partir de um dict persistido.
        
        Args:
            data: Dict produzido por to_dict()
            
        Returns:
            Instância de Position
        """
        return cls(
            side=data["side"],
            entry_price=float(data["entry_price"]),
            stop_loss=float(data["stop_loss"]),
            take_profit=float(data["take_profit"]),
            entry_tick=int(data["entry_tick"]),
            position_size=float(data["position_size"]),
            age=int(data.get("age", 0)),
            regime=data.get("regime", ""),
            engine=data.get("engine", ""),
            confidence=float(data.get("confidence", 0.0)),
            details=data.get("details", ""),
            regime_metrics=dict(data.get("regime_metrics") or {}),
            ml_score=(
                float(data["ml_score"])
                if data.get("ml_score") is not None
                else None
            ),
            transition_ticks=int(data.get("transition_ticks", 0)),
            entry_fee=float(data.get("entry_fee", 0.0) or 0.0),
        )


class PositionManager:
    """
    Gerenciador de posições do sistema.
    
    Responsável por:
    - Abrir novas posições com stops e targets
    - Avaliar posições existentes
    - Fechar posições por stop, target, idade ou regime
    - Calcular tamanhos de posição baseados em equity e confidence
    """
    
    def __init__(self, equity_manager=None, risk_controller=None, symbol: str = "USD"):
        """
        Inicializa o gerenciador de posições.

        Args:
            equity_manager: Gerenciador de equity (para sizing)
            risk_controller: Controlador de risco (para limites)
            symbol: Símbolo da moeda (ex: "USD", "BTC", "ETH", "SOL").
                    Criptoativos aplicam multiplicador de volatilidade
                    para stop-loss e take-profit.
        """
        self.positions: Dict[str, Position] = {}
        self.equity_manager = equity_manager
        self.risk_controller = risk_controller
        self.symbol = symbol
        # Lock reentrante para operações atômicas de estado
        self._lock = threading.RLock()
        # Override opcional de max_age (usado por simulações)
        self._max_age_override: Optional[int] = None

        # Determinar multiplicador de volatilidade para criptoativos
        crypto_symbols = ("BTC", "ETH", "SOL", "BRL-BTC", "BRL-ETH", "BRL-SOL")
        is_crypto = any(s in symbol.upper() for s in crypto_symbols)
        self._vol_mult = config.CRYPTO_VOL_MULTIPLIER if is_crypto else 1.0

        # Parâmetros de risco (base fiduciária, com multiplicador para cripto)
        self.stop_loss_pct = config.DEFAULT_STOP_LOSS_PCT * self._vol_mult
        self.take_profit_pct = config.DEFAULT_TAKE_PROFIT_PCT * self._vol_mult

        # Custos de execução. Espelham `config` e são atualizados pelo
        # runtime_config em calibragem ao vivo (ver _sync_live_engine).
        self.trading_fee_pct = float(config.TRADING_FEE_PCT)
        self.slippage_pct = float(config.SLIPPAGE_PCT)
        self.volatile_slippage_multiplier = float(
            config.VOLATILE_SLIPPAGE_MULTIPLIER
        )

        logger.info(
            f"PositionManager inicializado: symbol={symbol}, "
            f"vol_mult={self._vol_mult}x, "
            f"SL={self.stop_loss_pct:.1%}, TP={self.take_profit_pct:.1%}"
        )
    
    @staticmethod
    def _is_volatile_regime(regime: str) -> bool:
        """Regimes em que o spread abre e a derrapagem é agravada."""
        return regime in ("TRANSICAO", "ALTA_VOLATILIDADE")

    def _slippage_for(self, regime: str) -> float:
        """
        Slippage efetivo de uma execução no regime informado.

        O multiplicador volátil incide sobre TRANSICAO e ALTA_VOLATILIDADE,
        tanto na abertura quanto no fechamento.
        """
        base = max(0.0, float(self.slippage_pct))
        if self._is_volatile_regime(regime):
            multiplier = max(0.0, float(self.volatile_slippage_multiplier))
            return base * multiplier
        return base

    def _execution_costs(
        self,
        position: Position,
        exit_price: float,
        exit_regime: str,
    ) -> Dict[str, float]:
        """
        Calcula preços efetivos, PnL bruto e custos de uma saída.

        O slippage é sempre desfavorável: compra-executa mais caro e venda
        executa mais barato. A comissão incide sobre o notional da posição
        em cada perna (entrada já travada em `position.entry_fee`).
        """
        entry_slippage = self._slippage_for(position.regime)
        exit_slippage = self._slippage_for(exit_regime)

        if position.side == "COMPRA":
            entry_effective = position.entry_price * (1.0 + entry_slippage)
            exit_effective = exit_price * (1.0 - exit_slippage)
            pnl_without_costs = (
                position.position_size
                * (exit_price - position.entry_price)
                / position.entry_price
            )
            gross_pnl = (
                position.position_size
                * (exit_effective - entry_effective)
                / entry_effective
            )
        else:
            entry_effective = position.entry_price * (1.0 - entry_slippage)
            exit_effective = exit_price * (1.0 + exit_slippage)
            pnl_without_costs = (
                position.position_size
                * (position.entry_price - exit_price)
                / position.entry_price
            )
            gross_pnl = (
                position.position_size
                * (entry_effective - exit_effective)
                / entry_effective
            )

        entry_fee = float(position.entry_fee)
        exit_fee = position.position_size * max(0.0, float(self.trading_fee_pct))
        total_fees = entry_fee + exit_fee

        return {
            "entry_price_effective": entry_effective,
            "exit_price_effective": exit_effective,
            "pnl_without_costs": pnl_without_costs,
            "gross_pnl": gross_pnl,
            "slippage_cost": pnl_without_costs - gross_pnl,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "total_fees": total_fees,
            "net_pnl": gross_pnl - total_fees,
        }

    def _get_max_age_for_level(self) -> int:
        """
        Retorna max_age baseado no nível de agressividade.
        
        Returns:
            Idade máxima em ticks
        """
        if not self.risk_controller:
            return self._max_age_override or config.MAX_POSITION_AGE_TICKS["NORMAL"]
        
        if self._max_age_override is not None:
            return self._max_age_override
        
        level = self.risk_controller.aggressiveness_level
        return config.MAX_POSITION_AGE_TICKS.get(level, 40)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Retorna posição aberta para um símbolo.
        
        Args:
            symbol: Símbolo da moeda
            
        Returns:
            Position se existir, None caso contrário
        """
        with self._lock:
            return self.positions.get(symbol)
    
    def _calculate_position_size(self, confidence: float) -> float:
        """
        Calcula tamanho da posição baseado em equity e confiança.
        
        Args:
            confidence: Confiança do sinal (0.0 a 1.0)
            
        Returns:
            Tamanho da posição em valor absoluto
        """
        if not self.equity_manager:
            return 10000.0  # Default
        
        base_size = (
            self.equity_manager.current_equity * 
            config.BASE_POSITION_SIZE_PCT
        )
        
        # Escalar pelo confidence (min 40%, max 100%)
        confidence_factor = max(
            config.MIN_CONFIDENCE_FACTOR,
            min(config.MAX_CONFIDENCE_FACTOR, confidence)
        )
        
        position_size = base_size * confidence_factor
        
        logger.debug(
            f"Tamanho calculado: R$ {position_size:,.2f} "
            f"(base: {base_size:,.2f}, conf: {confidence:.2f})"
        )
        
        return position_size
    
    def _build_position(
        self,
        symbol: str,
        side: str,
        price: float,
        regime: str,
        engine: str,
        confidence: float,
        details: str,
        entry_tick: int,
        regime_metrics: Optional[Dict[str, Any]] = None,
        ml_score: Optional[float] = None,
    ) -> Optional[Position]:
        """
        Constrói nova posição com stops e targets.
        
        Args:
            symbol: Símbolo da moeda
            side: "COMPRA" ou "VENDA"
            price: Preço de entrada
            regime: Regime de mercado
            engine: Engine que gerou o sinal
            confidence: Confiança do sinal
            details: Detalhes do sinal
            entry_tick: Tick de entrada
            
        Returns:
            Position construída ou None se inválida
        """
        if side not in ("COMPRA", "VENDA"):
            logger.warning(f"Side inválido: {side}")
            return None
        
        # Calcular stops e targets
        if side == "COMPRA":
            stop_loss = price * (1 - self.stop_loss_pct)
            take_profit = price * (1 + self.take_profit_pct)
        else:
            stop_loss = price * (1 + self.stop_loss_pct)
            take_profit = price * (1 - self.take_profit_pct)
        
        position_size = self._calculate_position_size(confidence)
        entry_fee = position_size * max(0.0, float(self.trading_fee_pct))
        
        position = Position(
            side=side,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_tick=entry_tick,
            position_size=position_size,
            regime=regime,
            engine=engine,
            confidence=confidence,
            details=details,
            regime_metrics=dict(regime_metrics or {}),
            ml_score=ml_score,
            entry_fee=entry_fee,
        )
        
        logger.info(
            f"Posição construída: {symbol} {side} @ {price:.2f} "
            f"(SL: {stop_loss:.2f}, TP: {take_profit:.2f}, "
            f"Size: R$ {position_size:,.2f}, Fee: R$ {entry_fee:,.2f})"
        )
        
        return position
    
    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        regime: str,
        engine: str,
        confidence: float,
        details: str,
        entry_tick: int,
        regime_metrics: Optional[Dict[str, Any]] = None,
        ml_score: Optional[float] = None,
    ) -> Optional[Position]:
        """
        Abre nova posição se já não houver uma aberta.
        
        Args:
            symbol: Símbolo da moeda
            side: "COMPRA" ou "VENDA"
            price: Preço de entrada
            regime: Regime de mercado
            engine: Engine que gerou sinal
            confidence: Confiança do sinal
            details: Detalhes do sinal
            entry_tick: Tick de entrada
            
        Returns:
            Position criada ou None se já existe ou inválida
        """
        if self.get_position(symbol) is not None:
            logger.debug(f"Posição já existe para {symbol}, ignorando abertura")
            return None
        
        position = self._build_position(
            symbol, side, price, regime, engine,
            confidence, details, entry_tick,
            regime_metrics=regime_metrics,
            ml_score=ml_score,
        )
        
        if position is not None:
            with self._lock:
                # Re-verifica sob o lock (double-checked locking)
                if self.get_position(symbol) is not None:
                    logger.debug(f"Posição já existe para {symbol}, ignorando abertura")
                    return None
                self.positions[symbol] = position
            logger.info(f"✅ Posição aberta: {symbol} {side}")
        
        return position
    
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_regime: str,
        reason: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fecha posição e calcula resultado.
        
        Args:
            symbol: Símbolo da moeda
            exit_price: Preço de saída
            exit_regime: Regime de mercado na saída
            reason: Razão do fechamento
            
        Returns:
            Dicionário com resultado do trade ou None
        """
        with self._lock:
            position = self.positions.pop(symbol, None)
        
        if position is None:
            logger.warning(f"Tentativa de fechar posição inexistente: {symbol}")
            return None
        
        # PnL com custos reais de execução: slippage desfavorável nas duas
        # pernas + comissão na entrada (travada) e na saída.
        costs = self._execution_costs(position, exit_price, exit_regime)
        pnl_amount = costs["net_pnl"]
        
        # Cooldown extra após stop-loss
        if self.risk_controller and "stop_loss" in reason.lower():
            level = self.risk_controller.aggressiveness_level
            extra_cooldown = config.COOLDOWN_AFTER_STOP.get(level, 10)
            self.risk_controller.cooldown[symbol] += extra_cooldown
            logger.info(
                f"Cooldown adicional de {extra_cooldown} ticks "
                f"após stop-loss em {symbol}"
            )
        
        trade_result = {
            "symbol": symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "entry_tick": position.entry_tick,
            "exit_tick": position.entry_tick + position.age,
            "entry_regime": position.regime,
            "exit_regime": exit_regime,
            "engine": position.engine,
            "confidence": position.confidence,
            "pnl": float(pnl_amount),
            # Detalhamento de custos (auditoria e relatórios)
            "gross_pnl": float(costs["gross_pnl"]),
            "fees": float(costs["total_fees"]),
            "entry_fee": float(costs["entry_fee"]),
            "exit_fee": float(costs["exit_fee"]),
            "total_fees": float(costs["total_fees"]),
            "slippage_cost": float(costs["slippage_cost"]),
            "pnl_without_costs": float(costs["pnl_without_costs"]),
            "entry_price_effective": float(costs["entry_price_effective"]),
            "exit_price_effective": float(costs["exit_price_effective"]),
            "position_size": position.position_size,
            "duration_ticks": position.age,
            "reason": reason,
            "aggressiveness": (
                self.risk_controller.aggressiveness_level 
                if self.risk_controller else "UNKNOWN"
            ),
            "slope": position.regime_metrics.get("slope"),
            "momentum": position.regime_metrics.get("momentum"),
            "range_rel": position.regime_metrics.get("range_rel"),
            "volatility_ratio": position.regime_metrics.get("volatility_ratio"),
            "ml_score": position.ml_score,
        }
        
        logger.info(
            f"🔴 Posição fechada: {symbol} {position.side} | "
            f"PnL: {pnl_amount:+.2f} | "
            f"Bruto: {costs['gross_pnl']:+.2f} | "
            f"Taxas: {costs['total_fees']:.2f} | "
            f"Slippage: {costs['slippage_cost']:.2f} | Razão: {reason}"
        )
        
        return trade_result
    
    def evaluate(
        self,
        symbol: str,
        signal: str,
        price: float,
        regime: str,
        suggestion: Dict[str, Any],
        current_tick: int = 0
    ) -> Dict[str, Any]:
        """
        Avalia se deve abrir, fechar ou manter posição.
        
        Args:
            symbol: Símbolo da moeda
            signal: Sinal atual ("COMPRA", "VENDA", "NEUTRO")
            price: Preço atual
            regime: Regime atual
            suggestion: Dict com sugestão da estratégia
            current_tick: Tick atual
            
        Returns:
            Dicionário com ação e detalhes:
            {
                'action': str,  # COMPRA, VENDA, SAIR, HOLD, NEUTRO
                'event': str,   # ENTRY, EXIT, HOLD, NO_POSITION, etc
                'position': Position,  # Se aplicável
                'result': dict  # Se foi saída
            }
        """
        position = self.get_position(symbol)
        
        # Sem posição aberta
        if position is None:
            # Verificar filtro de risco antes de abrir
            if self.risk_controller and not self.risk_controller.can_execute(
                symbol, regime, signal, suggestion.get("confidence", 0.0)
            ):
                return {"action": "NEUTRO", "event": "RISK_BLOCK"}
            
            # Não entrar em regimes voláteis
            if regime in ("TRANSICAO", "ALTA_VOLATILIDADE"):
                logger.debug(
                    f"Entrada bloqueada por regime volátil: {regime}"
                )
                return {"action": "NEUTRO", "event": "HIGH_VOLATILITY"}
            
            # Abrir nova posição
            if signal in ("COMPRA", "VENDA"):
                opened = self.open_position(
                    symbol=symbol,
                    side=signal,
                    price=price,
                    regime=regime,
                    engine=suggestion.get("engine", "N/A"),
                    confidence=suggestion.get("confidence", 0.0),
                    details=suggestion.get("details", ""),
                    entry_tick=current_tick,
                    regime_metrics=suggestion.get("regime_metrics"),
                    ml_score=suggestion.get("ml_score"),
                )
                return {"action": signal, "event": "ENTRY", "position": opened}
            
            return {"action": "NEUTRO", "event": "NO_POSITION"}
        
        # Posição existe - avaliar saída
        with self._lock:
            position.age += 1
        exit_reasons = []
        
        # PRIORIDADE 1: Stop-loss e Take-profit (sempre primeiro)
        if position.side == "COMPRA":
            if price <= position.stop_loss:
                exit_reasons.append("stop_loss")
            elif price >= position.take_profit:
                exit_reasons.append("take_profit")
        else:
            if price >= position.stop_loss:
                exit_reasons.append("stop_loss")
            elif price <= position.take_profit:
                exit_reasons.append("take_profit")
        
        # Se não teve stop/take, verificar outras razões
        if not exit_reasons:
            # PRIORIDADE 2: Regime de risco (com histerese em TRANSICAO)
            #
            # ALTA_VOLATILIDADE (caos extremo) encerra imediatamente por
            # segurança. TRANSICAO costuma ser ruído de 1 tick: só encerra
            # após REGIME_RISK_EXIT_TICKS avaliações consecutivas no regime.
            # Se o mercado voltar à tendência, o contador zera e a posição
            # segue respirando até take-profit, stop-loss ou max_age.
            if regime == "ALTA_VOLATILIDADE":
                position.transition_ticks = 0
                exit_reasons.append("regime_risk")
            elif regime == "TRANSICAO":
                position.transition_ticks += 1
                limit = max(
                    1, int(getattr(config, "REGIME_RISK_EXIT_TICKS", 3))
                )
                if position.transition_ticks >= limit:
                    exit_reasons.append("regime_risk")
            else:
                position.transition_ticks = 0

            if not exit_reasons:
                # PRIORIDADE 3: Idade máxima (calculada dinamicamente)
                max_age = self._get_max_age_for_level()
                if position.age >= max_age:
                    exit_reasons.append("max_age")

                # PRIORIDADE 4: Sinal oposto
                elif (position.side == "COMPRA" and signal == "VENDA") or \
                    (position.side == "VENDA" and signal == "COMPRA"):
                    exit_reasons.append("opposite_signal")
            
        # Executar saída se houver razão
        if exit_reasons:
            trade_result = self.close_position(
                symbol, price, regime, ",".join(exit_reasons)
            )
            return {"action": "SAIR", "event": "EXIT", "result": trade_result}
        
        # Manter posição
        return {"action": "HOLD", "event": "HOLD", "position": position}
    
    # ------------------------------------------------------------------
    # PERSISTÊNCIA (contrato de estado único)
    # ------------------------------------------------------------------
    
    def positions_to_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Serializa as posições abertas para persistência.
        
        Returns:
            Dict {symbol: position_dict}
        """
        with self._lock:
            return {
                symbol: position.to_dict()
                for symbol, position in self.positions.items()
            }
    
    def load_positions_dict(self, data: Dict[str, Dict[str, Any]]) -> None:
        """
        Restaura as posições abertas a partir de um dict persistido.
        
        Substitui completamente o conjunto atual de posições.
        
        Args:
            data: Dict {symbol: position_dict}
        """
        with self._lock:
            self.positions = {
                symbol: Position.from_dict(p)
                for symbol, p in data.items()
            }
            logger.info(f"PositionManager restaurado com {len(self.positions)} posição(ões)")
