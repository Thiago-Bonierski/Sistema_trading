"""
Testes de paridade do núcleo de decisão.

Provam que `monitor.py` e `simular.py` compartilham a mesma cadeia
determinística: dada a mesma sequência de `MarketEvent`, produzem os
mesmos `OrderIntent` e os mesmos motivos de bloqueio.

Cobrem:
- Abertura após confirmação de tendência
- Bloqueio por regime que não confirma a ação
- Bloqueio por ProtectFlat e por regimes voláteis/transição
- Bloqueio por exaustão
- Bloqueio por ML
- Bloqueio por risco
- Fechamento de posição
- Replay real de `run_simulation` contra um pipeline estilo monitor
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest

import config
from core.contracts import DecisionContext, MarketEvent, OrderIntent
from core.pipeline import DecisionPipeline, TrendConfirmationTracker
from equity import EquityManager
from position_manager import PositionManager
from risk_control import RiskController


# ============================================================================
# Dublês determinísticos
# ============================================================================

class ScriptedOrchestrator:
    """Orquestrador que devolve sugestões pré-definidas, uma por tick."""

    def __init__(self, suggestions):
        self.suggestions = list(suggestions)
        self.calls = 0

    def evaluate(self, price, regime, regime_metrics, prices):
        index = min(self.calls, len(self.suggestions) - 1)
        self.calls += 1
        return dict(self.suggestions[index])


class FixedOrchestrator:
    """Orquestrador sem estado: depende apenas do regime."""

    def evaluate(self, price, regime, regime_metrics, prices):
        if regime == "TENDENCIA_ALTA":
            return {
                "action": "COMPRA",
                "confidence": 0.9,
                "engine": "TrendFollowing",
                "details": "tendencia de alta",
            }
        return {
            "action": "NEUTRO",
            "confidence": 0.0,
            "engine": "ProtectFlat",
            "details": "sem sinal",
        }


class ScriptedClassifier:
    """Classificador ML determinístico (treinado) para testes de bloqueio."""

    def __init__(self, approve: bool = True, score: float = 0.9):
        self.approve = approve
        self.score = score

    def is_trained(self) -> bool:
        return True

    def filter_signal(self, suggestion, regime_metrics):
        filtered = dict(suggestion)
        filtered["ml_score"] = self.score
        if not self.approve and suggestion.get("action") != "NEUTRO":
            filtered["action"] = "NEUTRO"
            filtered["confidence"] = 0.0
            filtered["reason"] = f"Filtrado por ML (score={self.score:.4f})"
        return filtered


class UntrainedClassifier:
    """Classificador indisponível (sem modelo)."""

    def is_trained(self) -> bool:
        return False

    def filter_signal(self, suggestion, regime_metrics):  # pragma: no cover
        return dict(suggestion)


def _regime_metrics(regime: str) -> dict:
    return {
        "regime": regime,
        "slope": 0.01 if "ALTA" in regime else (-0.01 if "BAIXA" in regime else 0.0),
        "momentum": 0.002 if "ALTA" in regime else (-0.002 if "BAIXA" in regime else 0.0),
        "range_rel": 0.01,
        "volatility_ratio": 1.0,
    }


def _build_pipeline(
    position_symbol: str,
    suggestions,
    *,
    classifier=None,
    exhaustion=None,
):
    """Cria um pipeline isolado, com a mesma configuração de domínio."""
    equity = EquityManager(initial_capital=100_000.0)
    risk = RiskController()
    positions = PositionManager(equity, risk, symbol="SOL")
    positions._max_age_override = 100

    tracker = TrendConfirmationTracker(
        counts={position_symbol: 0},
        last_regime={position_symbol: None},
    )

    pipeline = DecisionPipeline(
        orchestrator=ScriptedOrchestrator(suggestions),
        position_manager=positions,
        risk_controller=risk,
        equity_manager=equity,
        classifier=classifier,
        analyze_regime=lambda prices, symbol: _regime_metrics("TENDENCIA_ALTA"),
        check_exhaustion=exhaustion or (lambda **kwargs: (False, "")),
        trend_tracker=tracker,
    )
    return pipeline


def _event(price: float, regime: str, tick: int) -> MarketEvent:
    return MarketEvent(
        symbol="SOL",
        price=price,
        timestamp=float(tick),
        sequence=tick,
        prices=pd.Series([price] * 35),
        regime=regime,
        regime_metrics=_regime_metrics(regime),
        source="test",
    )


def _run_sequence(pipeline, position_symbol, steps):
    """Executa uma sequência de (preço, regime) e extrai assinaturas."""
    signatures = []
    for tick, (price, regime) in enumerate(steps):
        result = pipeline.process(
            _event(price, regime, tick),
            DecisionContext(symbol="SOL", position_symbol=position_symbol, tick=tick),
        )
        signatures.append(
            (
                result.intent.value,
                result.action,
                result.blocked_by,
                result.block_reason,
                result.engine,
                round(result.confidence, 6),
                result.trend_confirmation_count,
            )
        )
    return signatures


# ============================================================================
# Paridade por sequência de MarketEvents
# ============================================================================

class TestPipelineParity:
    """Monitor-like e simulator-like devem decidir de forma idêntica."""

    def _assert_parity(self, monkeypatch, suggestions, steps, **pipeline_kwargs):
        monitor_pipe = _build_pipeline("SOL", suggestions, **pipeline_kwargs)
        simulator_pipe = _build_pipeline("SIM", suggestions, **pipeline_kwargs)

        monitor_results = _run_sequence(monitor_pipe, "SOL", steps)
        simulator_results = _run_sequence(simulator_pipe, "SIM", steps)

        assert monitor_results == simulator_results
        return monitor_results

    def test_abertura_identica_apos_confirmacao(self, monkeypatch):
        """A mesma sequência abre no mesmo tick em ambos os fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 2, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
        ]
        steps = [(100.0, "TENDENCIA_ALTA")] * 3

        results = self._assert_parity(monkeypatch, suggestions, steps)

        # 1º tick: bloqueado por confirmação; 2º: abre; 3º: mantém
        assert results[0][0] == OrderIntent.HOLD.value
        assert results[0][2] == "trend_confirmation"
        assert results[1][0] == OrderIntent.OPEN.value
        assert results[2][0] == OrderIntent.HOLD.value

    def test_bloqueio_regime_nao_confirma(self, monkeypatch):
        """COMPRA em TENDENCIA_BAIXA é bloqueada igualmente nos dois fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
        ]
        steps = [(100.0, "TENDENCIA_BAIXA")] * 3

        results = self._assert_parity(monkeypatch, suggestions, steps)

        assert all(r[0] == OrderIntent.HOLD.value for r in results)
        assert all(r[2] == "trend_confirmation" for r in results)
        assert all("não confirma" in r[3] for r in results)

    def test_bloqueio_protectflat(self, monkeypatch):
        """ProtectFlat não abre posição em nenhum dos fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "ProtectFlat", "details": "flat"},
        ]
        steps = [(100.0, "TENDENCIA_ALTA")] * 3

        results = self._assert_parity(monkeypatch, suggestions, steps)

        assert all(r[0] == OrderIntent.HOLD.value for r in results)
        assert all(r[2] == "protect_flat" for r in results)

    @pytest.mark.parametrize("regime", ["TRANSICAO", "ALTA_VOLATILIDADE"])
    def test_bloqueio_regimes_volateis(self, monkeypatch, regime):
        """Guarda de regimes voláteis bloqueia identicamente os dois fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "BreakoutMomentum", "details": "b"},
        ]
        steps = [(100.0, regime)] * 3

        monitor_pipe = _build_pipeline("SOL", suggestions)
        simulator_pipe = _build_pipeline("SIM", suggestions)

        # Isola a guarda de regime do filtro de confirmação (que, por ordem,
        # bloquearia antes). Isso exercita explicitamente a camada volátil.
        for pipe in (monitor_pipe, simulator_pipe):
            pipe.trend_tracker.apply_filter = (
                lambda symbol, regime, suggestion, has_position=False: (suggestion, None)
            )

        monitor_results = _run_sequence(monitor_pipe, "SOL", steps)
        simulator_results = _run_sequence(simulator_pipe, "SIM", steps)

        assert monitor_results == simulator_results
        assert all(r[0] == OrderIntent.HOLD.value for r in monitor_results)
        assert all(r[2] == "volatile_regime" for r in monitor_results)

    def test_ordem_dos_filtros_bloqueia_por_tendencia_antes_da_guarda(self, monkeypatch):
        """Em regime volátil, a confirmação de tendência é o primeiro bloqueio."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "BreakoutMomentum", "details": "b"},
        ]
        steps = [(100.0, "TRANSICAO")] * 2

        results = self._assert_parity(monkeypatch, suggestions, steps)
        assert all(r[0] == OrderIntent.HOLD.value for r in results)
        assert all(r[2] == "trend_confirmation" for r in results)


    def test_bloqueio_exaustao(self, monkeypatch):
        """Exaustão bloqueia a entrada no mesmo tick em ambos os fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
        ]
        steps = [(100.0, "TENDENCIA_ALTA")] * 3

        def always_exhausted(**kwargs):
            return True, "momentum_fraco"

        results = self._assert_parity(
            monkeypatch, suggestions, steps, exhaustion=always_exhausted
        )

        assert all(r[0] == OrderIntent.HOLD.value for r in results)
        assert all(r[2] == "exhaustion" for r in results)
        assert all("momentum_fraco" in r[3] for r in results)

    def test_bloqueio_ml(self, monkeypatch):
        """ML reprovando neutraliza o sinal do mesmo modo nos dois fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
        ]
        steps = [(100.0, "TENDENCIA_ALTA")] * 3

        results = self._assert_parity(
            monkeypatch,
            suggestions,
            steps,
            classifier=ScriptedClassifier(approve=False, score=0.1),
        )

        assert all(r[0] == OrderIntent.HOLD.value for r in results)
        assert all(r[2] == "ml" for r in results)
        assert all("Filtrado por ML" in r[3] for r in results)

    def test_bloqueio_risco(self, monkeypatch):
        """Bloqueio do RiskController gera a mesma intenção/motivo."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
        ]
        steps = [(100.0, "TENDENCIA_ALTA")] * 3

        monitor_pipe = _build_pipeline("SOL", suggestions)
        simulator_pipe = _build_pipeline("SIM", suggestions)
        monitor_pipe.risk_controller.global_limit = 0
        simulator_pipe.risk_controller.global_limit = 0

        monitor_results = _run_sequence(monitor_pipe, "SOL", steps)
        simulator_results = _run_sequence(simulator_pipe, "SIM", steps)

        assert monitor_results == simulator_results
        assert all(r[0] == OrderIntent.HOLD.value for r in monitor_results)
        assert all(r[2] == "risk_controller" for r in monitor_results)

    def test_fechamento_identico(self, monkeypatch):
        """Sinal oposto fecha a posição no mesmo tick em ambos os fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
            {"action": "VENDA", "confidence": 0.9, "engine": "TrendFollowing", "details": "b"},
            {"action": "NEUTRO", "confidence": 0.0, "engine": "ProtectFlat", "details": "c"},
        ]
        steps = [
            (100.0, "TENDENCIA_ALTA"),
            (101.0, "TENDENCIA_BAIXA"),
            (101.0, "TENDENCIA_BAIXA"),
        ]

        results = self._assert_parity(monkeypatch, suggestions, steps)

        assert results[0][0] == OrderIntent.OPEN.value
        assert results[1][0] == OrderIntent.CLOSE.value
        assert results[2][0] == OrderIntent.HOLD.value

    def test_reset_de_contadores_em_mudanca_de_regime(self, monkeypatch):
        """Troca de regime reseta contadores do regime anterior nos dois fluxos."""
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        suggestions = [
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "a"},
            {"action": "NEUTRO", "confidence": 0.0, "engine": "ProtectFlat", "details": "flat"},
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "b"},
        ]
        steps = [
            (100.0, "TENDENCIA_ALTA"),
            (100.0, "CONSOLIDACAO"),
            (100.0, "TENDENCIA_ALTA"),
        ]

        monitor_pipe = _build_pipeline("SOL", suggestions)
        simulator_pipe = _build_pipeline("SIM", suggestions)

        monitor_results = _run_sequence(monitor_pipe, "SOL", steps)
        simulator_results = _run_sequence(simulator_pipe, "SIM", steps)

        assert monitor_results == simulator_results
        # O contador de tendência reinicia ao sair e voltar para o regime
        assert monitor_results[2][6] == 1


# ============================================================================
# Paridade de replay real (run_simulation) contra pipeline estilo monitor
# ============================================================================

class _FakeMarket:
    """Feed sintético determinístico de preços em alta."""

    def __init__(self, seed=None, n_ticks=10000):
        self.price = 100.0
        self.regime = "TENDENCIA_ALTA"

    def generate_price(self):
        self.price *= 1.005
        return self.price, self.regime


class _RecordingPipeline(DecisionPipeline):
    """Pipeline que registra eventos/contextos/resultados para replay."""

    records = []

    def process(self, event, context=None):
        result = super().process(event, context)
        self.records.append((event, context, result))
        return result


def test_replay_real_do_simulador_tem_paridade_com_monitor(monkeypatch):
    """
    O caminho real de `simular.run_simulation` produz as mesmas decisões
    que um pipeline configurado como o de `monitor.py`, para os mesmos
    eventos de mercado.
    """
    import simular

    monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 2, raising=False)
    monkeypatch.setattr(simular, "SyntheticMarket", _FakeMarket)
    monkeypatch.setattr(simular, "StrategyOrchestrator", FixedOrchestrator)
    monkeypatch.setattr(simular, "MLClassifier", lambda *a, **kw: UntrainedClassifier())
    monkeypatch.setattr(simular, "analyze_regime", lambda prices, symbol=None: _regime_metrics("TENDENCIA_ALTA"))
    monkeypatch.setattr(simular, "salvar_trade", lambda payload: None)

    _RecordingPipeline.records = []
    monkeypatch.setattr(simular, "DecisionPipeline", _RecordingPipeline)

    result = simular.run_simulation(
        mode=simular.SimulationMode.RESEARCH,
        ticks=120,
        seed=7,
        data_source="synthetic",
        symbol="SOL",
    )

    captured = list(_RecordingPipeline.records)
    assert captured, "O simulador não registrou nenhum evento"
    assert any(r.intent == OrderIntent.OPEN for _, _, r in captured)
    assert any(r.intent == OrderIntent.CLOSE for _, _, r in captured)
    assert result["trade_statistics"]["total_trades"] >= 1

    # Replay dos mesmos eventos em um pipeline configurado como produção
    equity = EquityManager(initial_capital=100_000.0)
    risk = RiskController()
    positions = PositionManager(equity, risk, symbol="SOL")
    positions._max_age_override = 100
    tracker = TrendConfirmationTracker(
        counts={"MON": 0}, last_regime={"MON": None}
    )
    monitor_like = DecisionPipeline(
        orchestrator=FixedOrchestrator(),
        position_manager=positions,
        risk_controller=risk,
        equity_manager=equity,
        classifier=UntrainedClassifier(),
        analyze_regime=simular.analyze_regime,
        check_exhaustion=simular.check_exhaustion,
        trend_tracker=tracker,
        update_drawdown=False,
        reset_regime_counts=False,
    )

    for event, context, sim_result in captured:
        replay = monitor_like.process(
            event,
            DecisionContext(
                symbol=event.symbol,
                position_symbol="MON",
                tick=context.tick,
            ),
        )
        # O driver de produção/simulação decrementa cooldowns a cada tick.
        risk.tick()

        assert replay.intent == sim_result.intent
        assert replay.action == sim_result.action
        assert replay.blocked_by == sim_result.blocked_by
        assert replay.block_reason == sim_result.block_reason
        assert replay.engine == sim_result.engine
        assert replay.trend_confirmation_count == sim_result.trend_confirmation_count
        if sim_result.trade_result is not None:
            assert replay.trade_result is not None
            assert replay.trade_result["pnl"] == pytest.approx(
                sim_result.trade_result["pnl"]
            )
