"""
Pipeline único e determinístico de decisão.

Toda a cadeia que transforma um `MarketEvent` em `DecisionResult` vive
aqui, sem IO direto:

    regime -> orquestrador -> confirmação de tendência
    -> guarda ProtectFlat/regimes voláteis -> exaustão -> ML -> risco/posição

`monitor.py` (produção) e `simular.py` (backtest/pesquisa) são drivers
finos: alimentam eventos, persistem/telemetram e reagem ao resultado.
O pipeline é a única fonte de verdade sobre a decisão.
"""

from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd

import config
from exhaustion_filter import check_exhaustion as default_check_exhaustion
from market_regime import analyze_regime as default_analyze_regime

from core.contracts import (
    DecisionContext,
    DecisionResult,
    MarketEvent,
    OrderIntent,
)

TREND_REGIMES = ("TENDENCIA_ALTA", "TENDENCIA_BAIXA")
VOLATILE_REGIMES = ("TRANSICAO", "ALTA_VOLATILIDADE")
DIRECTIONAL_ACTIONS = ("COMPRA", "VENDA")


class TrendConfirmationTracker:
    """
    Estado de confirmação de tendência.

    A classe pode operar sobre dicionários externos (compatibilidade com
    os globais históricos de `monitor.py`) ou sobre dicionários próprios.
    Isso preserva os testes e o contrato público do monitor sem duplicar
    a regra.
    """

    def __init__(
        self,
        counts: Optional[Dict[str, int]] = None,
        last_regime: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.counts: Dict[str, int] = counts if counts is not None else {}
        self.last_regime: Dict[str, Optional[str]] = (
            last_regime if last_regime is not None else {}
        )

    def update(self, symbol: str, regime: str) -> int:
        """Atualiza e retorna o contador de confirmações consecutivas."""
        if regime not in TREND_REGIMES:
            self.counts[symbol] = 0
            self.last_regime[symbol] = None
            return 0

        if self.last_regime.get(symbol) == regime:
            self.counts[symbol] = self.counts.get(symbol, 0) + 1
        else:
            self.last_regime[symbol] = regime
            self.counts[symbol] = 1

        return self.counts[symbol]

    def reset(self, symbol: str) -> None:
        """Zera o estado de confirmação de um símbolo."""
        self.counts[symbol] = 0
        self.last_regime[symbol] = None
    def apply_filter(
        self,
        symbol: str,
        regime: str,
        suggestion: Dict[str, Any],
        has_position: bool = False,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Bloqueia novas entradas direcionais sem confirmação suficiente.

        Não bloqueia NEUTRO/SAIR/HOLD nem quando já existe posição aberta
        (a posição precisa continuar sendo gerenciada).

        Returns:
            (sugestão possivelmente neutralizada, motivo do bloqueio)
        """
        action = suggestion.get("action", "NEUTRO")

        if action not in DIRECTIONAL_ACTIONS or has_position:
            return suggestion, None

        required_ticks = getattr(config, "TREND_CONFIRMATION_TICKS", 2)
        confirmation_count = self.counts.get(symbol, 0)
        expected_regime = (
            "TENDENCIA_ALTA" if action == "COMPRA" else "TENDENCIA_BAIXA"
        )

        if regime != expected_regime:
            filtered = suggestion.copy()
            filtered["action"] = "NEUTRO"
            filtered["confidence"] = 0.0
            filtered["details"] = (
                f"Sinal {action} bloqueado: regime {regime} "
                f"não confirma {expected_regime}"
            )
            filtered["engine"] = "TrendConfirmationFilter"
            return filtered, "regime não confirma ação"

        if confirmation_count < required_ticks:
            filtered = suggestion.copy()
            filtered["action"] = "NEUTRO"
            filtered["confidence"] = 0.0
            filtered["details"] = (
                f"Aguardando confirmação de tendência "
                f"({confirmation_count}/{required_ticks})"
            )
            filtered["engine"] = "TrendConfirmationFilter"
            return filtered, (
                f"confirmação insuficiente "
                f"({confirmation_count}/{required_ticks})"
            )

        return suggestion, None


class DecisionPipeline:
    """
    Núcleo único de decisão, compartilhado por produção e backtest.

    O pipeline não faz IO. Dependências de domínio são injetadas para
    permitir testes determinísticos e monkeypatches dos drivers.
    """

    def __init__(
        self,
        *,
        orchestrator: Any,
        position_manager: Any,
        risk_controller: Any,
        equity_manager: Any = None,
        classifier: Any = None,
        analyze_regime: Any = None,
        check_exhaustion: Any = None,
        trend_tracker: Optional[TrendConfirmationTracker] = None,
        update_drawdown: bool = True,
        reset_regime_counts: bool = True,
        apply_ml: bool = True,
        block_protect_flat: bool = True,
        block_volatile_regimes: bool = True,
    ):
        self.orchestrator = orchestrator
        self.position_manager = position_manager
        self.risk_controller = risk_controller
        self.equity_manager = equity_manager
        self.classifier = classifier
        self._analyze_regime = analyze_regime or default_analyze_regime
        self._check_exhaustion = check_exhaustion or default_check_exhaustion
        self.trend_tracker = trend_tracker or TrendConfirmationTracker()
        self.update_drawdown = update_drawdown
        self.reset_regime_counts = reset_regime_counts
        self.apply_ml = apply_ml
        self.block_protect_flat = block_protect_flat
        self.block_volatile_regimes = block_volatile_regimes
        self._last_regime: Dict[str, Optional[str]] = {}

    def reset_state(self, position_symbol: str) -> None:
        """
        Limpa o estado de decisão de uma chave de posição.

        Usado por drivers em descontinuidades de dados (DATA_GAP) para
        evitar que o pipeline misture contexto anterior e posterior.
        """
        self._last_regime.pop(position_symbol, None)
        self.trend_tracker.reset(position_symbol)

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def process(
        self,
        event: MarketEvent,
        context: Optional[DecisionContext] = None,
    ) -> DecisionResult:
        """
        Processa um evento de mercado e retorna a decisão completa.

        O pipeline mantém apenas o estado de decisão (confirmação de
        tendência e último regime por chave de posição). Todo o resto é
        derivado do evento + dependências injetadas.
        """
        context = context or DecisionContext(symbol=event.symbol)
        position_symbol = context.resolved_position_symbol()
        filter_details: Dict[str, Any] = {}
        blocked_by: Optional[str] = None
        block_reason: str = ""

        # 1) Regime (feed pode pré-computar; senão o pipeline calcula)
        prices_series = self._as_price_series(event.prices, event.price)
        regime, regime_metrics = self._resolve_regime(event, prices_series)

        # 2) Confirmação de tendência
        confirmation_count = self.trend_tracker.update(position_symbol, regime)
        has_position = (
            self.position_manager.get_position(position_symbol) is not None
        )

        # 3) Mudança de regime -> reset de contadores do regime anterior
        previous_regime = self._last_regime.get(position_symbol)
        regime_changed = (
            previous_regime is not None and previous_regime != regime
        )
        if regime_changed and self.reset_regime_counts:
            self.risk_controller.reset_regime_counts(previous_regime)
        self._last_regime[position_symbol] = regime

        # 4) Drawdown / agressividade
        if self.update_drawdown and self.equity_manager is not None:
            drawdown = context.equity_drawdown
            if drawdown is None:
                drawdown = self.equity_manager.get_current_drawdown()
            equity = context.equity
            if equity is None:
                equity = self.equity_manager.current_equity
            self.risk_controller.update_drawdown(drawdown, equity)

        # 5) Orquestrador de estratégias
        raw_signal = dict(
            self.orchestrator.evaluate(
                price=event.price,
                regime=regime,
                regime_metrics=regime_metrics,
                prices=prices_series,
            )
        )
        result_signal = dict(raw_signal)

        # 6) Confirmação de tendência (não bloqueia posição existente)
        result_signal, trend_reason = self.trend_tracker.apply_filter(
            symbol=position_symbol,
            regime=regime,
            suggestion=result_signal,
            has_position=has_position,
        )
        if trend_reason:
            blocked_by = "trend_confirmation"
            block_reason = trend_reason
            filter_details["trend_confirmation"] = {
                "blocked": True,
                "reason": trend_reason,
            }
        elif result_signal.get("action") in DIRECTIONAL_ACTIONS and has_position:
            filter_details["position_slot"] = {
                "blocked": True,
                "reason": "slot_ocupado",
            }

        # 7) Guarda ProtectFlat / regimes voláteis e de transição
        if result_signal.get("action") in DIRECTIONAL_ACTIONS:
            engine_name = result_signal.get("engine", "")
            is_protect = self.block_protect_flat and engine_name == "ProtectFlat"
            is_volatile = (
                self.block_volatile_regimes and regime in VOLATILE_REGIMES
            )
            if is_protect or is_volatile:
                result_signal["action"] = "NEUTRO"
                result_signal["confidence"] = 0.0
                result_signal["details"] = (
                    "Entrada bloqueada: ProtectFlat/regime volátil ou transição"
                )
                if not is_protect:
                    result_signal["engine"] = "TrendConfirmationFilter"
                blocked_by = "protect_flat" if is_protect else "volatile_regime"
                block_reason = (
                    "protectflat_ou_regime_volatil_transicao"
                )
                filter_details["trend_confirmation"] = {
                    "blocked": True,
                    "reason": block_reason,
                }

        # 8) Exaustão (apenas entradas; saídas de posição não são afetadas)
        if result_signal.get("action") in DIRECTIONAL_ACTIONS:
            exhausted, ex_reason = self._check_exhaustion(
                prices=prices_series,
                regime_metrics=regime_metrics,
                suggestion=result_signal,
                symbol=event.symbol,
            )
            if exhausted:
                result_signal["action"] = "NEUTRO"
                result_signal["confidence"] = 0.0
                result_signal["details"] = f"Exaustão: {ex_reason}"
                result_signal["engine"] = "ExhaustionFilter"
                result_signal["ml_score"] = None
                blocked_by = "exhaustion"
                block_reason = ex_reason
                filter_details["exhaustion"] = {
                    "blocked": True,
                    "reason": ex_reason,
                }

        # 9) Classificador ML (quando treinado)
        ml_score = result_signal.get("ml_score")
        if (
            self.apply_ml
            and self.classifier is not None
            and self.classifier.is_trained()
        ):
            action_before_ml = result_signal.get("action")
            result_signal = dict(
                self.classifier.filter_signal(result_signal, regime_metrics)
            )
            ml_score = result_signal.get("ml_score")
            if (
                action_before_ml in DIRECTIONAL_ACTIONS
                and result_signal.get("action") == "NEUTRO"
            ):
                blocked_by = "ml"
                block_reason = result_signal.get("reason") or "Filtrado por ML"
                filter_details["ml"] = {
                    "blocked": True,
                    "score": result_signal.get("ml_score", 0.0),
                    "threshold": config.ML_APPROVAL_THRESHOLD,
                }

        # 10) Risco e posição (autoridade única de entrada/saída)
        position_decision = self.position_manager.evaluate(
            symbol=position_symbol,
            signal=result_signal.get("action", "NEUTRO"),
            price=event.price,
            regime=regime,
            suggestion=result_signal,
            current_tick=context.tick,
        )
        position_action = position_decision.get("action", "NEUTRO")
        position_event = position_decision.get("event")
        risk_event: Optional[str] = None

        if position_action == "SAIR":
            trade_result = position_decision.get("result")
            if trade_result:
                if self.equity_manager is not None:
                    self.equity_manager.update_equity(trade_result["pnl"])
                self.risk_controller.close_position(position_symbol)
        elif position_action in DIRECTIONAL_ACTIONS:
            self.risk_controller.register_trade(
                position_symbol, regime, position_action
            )

        if position_event in ("RISK_BLOCK", "HIGH_VOLATILITY"):
            risk_event = position_event
            if blocked_by is None:
                blocked_by = (
                    "risk_controller"
                    if position_event == "RISK_BLOCK"
                    else "volatile_regime"
                )
                block_reason = (
                    "risco_bloqueado"
                    if position_event == "RISK_BLOCK"
                    else "regime_volatil"
                )
            if position_event == "RISK_BLOCK":
                filter_details["risk_controller"] = {
                    "blocked": True,
                    "reason": "risco_bloqueado",
                }

        # 11) Mapeamento para intenção canônica
        if position_action in DIRECTIONAL_ACTIONS:
            intent = OrderIntent.OPEN
        elif position_action == "SAIR":
            intent = OrderIntent.CLOSE
        else:
            intent = OrderIntent.HOLD

        held_position = position_decision.get("position")
        position_side = getattr(held_position, "side", None)

        return DecisionResult(
            intent=intent,
            action=position_action,
            symbol=event.symbol,
            position_symbol=position_symbol,
            price=event.price,
            regime=regime,
            regime_metrics=regime_metrics,
            engine=result_signal.get("engine", "N/A"),
            confidence=float(result_signal.get("confidence", 0.0) or 0.0),
            details=result_signal.get("details", ""),
            ml_score=ml_score,
            blocked_by=blocked_by,
            block_reason=block_reason,
            raw_signal=raw_signal,
            signal=result_signal,
            position_decision=position_decision,
            trade_result=position_decision.get("result"),
            position_side=position_side,
            trend_confirmation_count=confirmation_count,
            regime_changed=regime_changed,
            previous_regime=previous_regime,
            position_event=position_event,
            risk_event=risk_event,
            filter_details=filter_details,
            tick=context.tick,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _as_price_series(
        prices: Optional[Sequence[float]],
        fallback_price: float,
    ) -> Any:
        """Normaliza a janela de preços para pandas.Series."""
        if prices is None:
            return pd.Series([float(fallback_price)])
        if hasattr(prices, "iloc"):
            return prices
        values = list(prices)
        if not values:
            values = [float(fallback_price)]
        return pd.Series(values)

    def _resolve_regime(
        self,
        event: MarketEvent,
        prices_series: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Resolve regime e métricas.

        Feeds de replay/pesquisa podem pré-computar o regime (mantendo
        sua própria cadência de análise); feeds live deixam o pipeline
        calcular via `analyze_regime` injetado.
        """
        if event.regime is None:
            analysis = self._analyze_regime(
                prices_series, symbol=event.symbol
            )
            regime = analysis.get("regime", "AGUARDANDO")
            return regime, dict(analysis)

        metrics = dict(event.regime_metrics) if event.regime_metrics else {}
        metrics.setdefault("regime", event.regime)
        return event.regime, metrics
