"""
Testes de simulação - Integração fim-a-fim.

Cobre:
- Modos RESEARCH e PAPER_TRADING com fontes de dados múltiplas
- Funil de decisões (sinais gerados vs. bloqueados)
- Performance por engine e por regime
- Reprodutibilidade com seed
- Integração com telemetry
"""

import config  # MUST be first - simular.py uses config at module level
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


def _import_all():
    """Importa todos os módulos necessários para os testes."""
    from simular import (
        run_simulation, SimulationMode, DataSource,
        SyntheticMarket, get_historical_prices,
        load_historical_data_from_db, download_and_cache_binance,
    )
    from simulation_telemetry import (
        SimulationTelemetry, TradeRecord, TickDecision, Regime, SignalSource,
        create_default_raw_signals, create_default_filter_details,
    )
    return dict(
        run_simulation=run_simulation,
        SimulationMode=SimulationMode,
        DataSource=DataSource,
        SyntheticMarket=SyntheticMarket,
        get_historical_prices=get_historical_prices,
        load_historical_data_from_db=load_historical_data_from_db,
        download_and_cache_binance=download_and_cache_binance,
        SimulationTelemetry=SimulationTelemetry,
        TradeRecord=TradeRecord,
        TickDecision=TickDecision,
        Regime=Regime,
        SignalSource=SignalSource,
        create_default_raw_signals=create_default_raw_signals,
        create_default_filter_details=create_default_filter_details,
    )


class TestSimulationModes:
    """Testes dos modos de simulação RESEARCH e PAPER_TRADING."""

    def test_pesquisa_mode_gera_trades(self):
        """Modo RESEARCH executa simulação completa sem erros."""
        m = _import_all()
        result = m["run_simulation"](
            m["SimulationMode"].RESEARCH, ticks=500, seed=42,
            data_source="synthetic"
        )
        # Verificar estrutura do resultado
        assert result is not None
        assert "trade_statistics" in result
        assert "final_equity" in result
        assert "max_drawdown" in result
        assert "total_return" in result
        assert "risk_level" in result
        # Verificar estatísticas válidas (pode ser 0 trades se filtros bloquearem)
        stats = result["trade_statistics"]
        assert isinstance(stats["total_trades"], int)
        assert stats["total_trades"] >= 0
        assert 0 <= stats["win_rate"] <= 1
        assert result["max_drawdown"] >= 0

    def test_paper_trading_mode_strict(self):
        """Modo PAPER_TRADING deve ser mais restritivo que RESEARCH."""
        m = _import_all()
        research = m["run_simulation"](
            m["SimulationMode"].RESEARCH, ticks=500, seed=42,
            data_source="synthetic"
        )
        paper = m["run_simulation"](
            m["SimulationMode"].PAPER_TRADING, ticks=500, seed=42,
            data_source="synthetic"
        )
        assert research["trade_statistics"]["total_trades"] >= paper["trade_statistics"]["total_trades"]

    def test_seed_reproducibility(self):
        """Mesmo seed deve produzir resultados idênticos."""
        m = _import_all()
        r1 = m["run_simulation"](
            m["SimulationMode"].PAPER_TRADING, ticks=200, seed=123,
            data_source="synthetic"
        )
        r2 = m["run_simulation"](
            m["SimulationMode"].PAPER_TRADING, ticks=200, seed=123,
            data_source="synthetic"
        )
        assert r1["final_equity"] == r2["final_equity"]
        assert r1["max_drawdown"] == r2["max_drawdown"]


class TestSimulationDataSources:
    def test_simulation_with_synthetic_source(self):
        """Simulação com fonte synthetic deve funcionar."""
        m = _import_all()
        result = m["run_simulation"](
            m["SimulationMode"].RESEARCH, ticks=200, seed=42,
            data_source="synthetic"
        )
        assert result is not None
        assert "trade_statistics" in result

    def test_simulation_with_db_source(self):
        """Simulação com fonte db deve funcionar se houver dados."""
        m = _import_all()
        result = m["run_simulation"](
            m["SimulationMode"].RESEARCH, ticks=100, seed=42,
            data_source="db", symbol="USD"
        )
        assert result is not None

    def test_data_source_enum(self):
        """DataSource enum deve ter valores corretos."""
        from simular import DataSource
        assert DataSource.SYNTHETIC.value == "synthetic"
        assert DataSource.DB.value == "db"
        assert DataSource.API.value == "api"


class TestSyntheticMarket:
    def test_regime_coverage(self):
        """SyntheticMarket deve cobrir todos os tipos de regime ao longo do tempo."""
        m = _import_all()
        market = m["SyntheticMarket"](seed=42, n_ticks=2000)
        regimes = set()
        for _ in range(2000):
            _price, regime = market.generate_price()
            regimes.add(regime)
        assert len(regimes) >= 4

    def test_seed_reproducibility(self):
        """Mesmo seed deve produzir mesma sequência de regimes."""
        m = _import_all()
        market1 = m["SyntheticMarket"](seed=42, n_ticks=100)
        market2 = m["SyntheticMarket"](seed=42, n_ticks=100)
        regimes1 = [market1.generate_price()[1] for _ in range(100)]
        regimes2 = [market2.generate_price()[1] for _ in range(100)]
        assert regimes1 == regimes2

    def test_block_structure(self):
        """Regimes devem aparecer em blocos estruturados, não aleatórios."""
        m = _import_all()
        market = m["SyntheticMarket"](seed=42, n_ticks=200)
        regimes = [market.generate_price()[1] for _ in range(200)]
        alta_count = regimes.count("TENDENCIA_ALTA")
        assert alta_count >= 30


class TestTelemetryIntegration:
    def _get_telemetry(self):
        from simulation_telemetry import (
            SimulationTelemetry, TradeRecord, Regime, SignalSource,
            create_default_raw_signals, create_default_filter_details
        )
        return (
            SimulationTelemetry("USD", enable_detailed_log=False),
            TradeRecord,
            Regime,
            SignalSource,
            create_default_raw_signals,
            create_default_filter_details,
        )

    def test_funnel_report_structure(self):
        """Relatório de funil deve ter todas as chaves esperadas."""
        telemetry, TradeRecord, Regime, SignalSource, cdr, cfd = self._get_telemetry()
        for tick in range(10):
            telemetry.tick(
                price=100.0 + tick,
                regime=Regime.TENDENCIA_ALTA,
                raw_signals=cdr(),
                filtered_signals=cdr(),
                final_action="COMPRA" if tick < 5 else "NEUTRO",
                final_engine="TrendFollowing" if tick < 5 else "MeanReversion",
                final_confidence=0.8 if tick < 5 else 0.3,
                ml_score=0.7 if tick < 5 else None,
                filter_details=cfd(),
            )
        for _ in range(3):
            trade = TradeRecord(
                entry_tick=1, exit_tick=5, symbol="USD",
                regime_entry=Regime.TENDENCIA_ALTA, engine_entry=SignalSource.TREND_FOLLOWING,
                confidence_entry=0.8, ml_score_entry=0.7,
                entry_price=103.0, exit_price=107.0,
                exit_reason="TAKE_PROFIT", pnl=400.0, duration_ticks=4,
                final_regime=Regime.TENDENCIA_ALTA, final_engine=SignalSource.TREND_FOLLOWING,
            )
            telemetry.record_trade(trade)
        report = telemetry.get_funnel_report()
        assert "total_ticks" in report
        assert "total_signals_approved" in report
        assert "approval_rate" in report

    def test_dataframe_export(self):
        """Exportação para DataFrame deve funcionar corretamente."""
        telemetry, TradeRecord, Regime, SignalSource, cdr, cfd = self._get_telemetry()
        for tick in range(5):
            telemetry.tick(
                price=100.0 + tick,
                regime=Regime.CONSOLIDACAO,
                raw_signals=cdr(),
                filtered_signals=cdr(),
                final_action="NEUTRO",
                final_engine="ProtectFlat",
                final_confidence=0.3,
            )
        trade = TradeRecord(
            entry_tick=1, exit_tick=3, symbol="USD",
            regime_entry=Regime.CONSOLIDACAO, engine_entry=SignalSource.PROTECT_FLAT,
            confidence_entry=0.3, ml_score_entry=0.0,
            entry_price=100.0, exit_price=100.5,
            exit_reason="MAX_AGE", pnl=0.5, duration_ticks=2,
            final_regime=Regime.CONSOLIDACAO, final_engine=SignalSource.PROTECT_FLAT,
        )
        telemetry.record_trade(trade)
        tick_df, trade_df = telemetry.export_to_dataframe()
        assert len(tick_df) == 5
        assert len(trade_df) == 1
        assert "pnl" in trade_df.columns
        assert "exit_reason" in trade_df.columns
        assert "final_regime" in trade_df.columns
        assert "final_engine" in trade_df.columns


class TestSimulationRegressions:
    """Regressões de paridade/atribuição do simulador."""

    def _base_regime_metrics(self, regime="TENDENCIA_ALTA"):
        return {
            "regime": regime,
            "slope": 0.01 if "ALTA" in regime else (-0.01 if "BAIXA" in regime else 0.0),
            "momentum": 0.002 if "ALTA" in regime else (-0.002 if "BAIXA" in regime else 0.0),
            "range_rel": 0.01,
            "volatility_ratio": 1.0,
        }

    def test_analyze_regime_called_with_symbol(self, monkeypatch):
        """run_simulation deve propagar o símbolo real para analyze_regime."""
        import simular
        from simular import run_simulation, SimulationMode

        monkeypatch.setattr(config, "MIN_HISTORY_FOR_REGIME", 5, raising=False)
        called = []

        def fake_analyze(prices, symbol=None):
            called.append(symbol)
            return self._base_regime_metrics("TENDENCIA_ALTA")

        monkeypatch.setattr(simular, "analyze_regime", fake_analyze)

        result = run_simulation(
            mode=SimulationMode.RESEARCH,
            ticks=20,
            seed=1,
            data_source="synthetic",
            symbol="SOL",
        )
        assert result is not None
        assert called, "analyze_regime não foi chamado"
        assert all(s == "SOL" for s in called)

    def test_blocks_protectflat_entry(self, monkeypatch):
        """ProtectFlat nunca deve abrir ordens, mesmo com ação direcional."""
        import simular
        from simular import run_simulation, SimulationMode

        class FakeOrchestrator:
            def evaluate(self, price, regime, regime_metrics, prices):
                return {
                    "action": "COMPRA",
                    "confidence": 0.9,
                    "engine": "ProtectFlat",
                    "details": "fake protectflat",
                }

        monkeypatch.setattr(simular, "StrategyOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(
            simular, "analyze_regime",
            lambda prices, symbol=None: self._base_regime_metrics("TENDENCIA_ALTA"),
        )

        result = run_simulation(
            mode=SimulationMode.RESEARCH,
            ticks=30,
            seed=2,
            data_source="synthetic",
            symbol="SOL",
        )
        assert result["trade_statistics"]["total_trades"] == 0
        funnel = result.get("_funnel_report", {})
        # Deve ter sido barrado por confirmação/guarda explícito (não executado)
        assert funnel.get("trades_executed", 0) == 0

    def test_blocks_transition_volatile_entry(self, monkeypatch):
        """Regimes TRANSICAO/ALTA_VOLATILIDADE não devem abrir ordens."""
        import simular
        from simular import run_simulation, SimulationMode

        monkeypatch.setattr(config, "MIN_HISTORY_FOR_REGIME", 5, raising=False)

        class FakeSyntheticMarket:
            def __init__(self, seed=42, n_ticks=10000):
                self.price = 100.0

            def generate_price(self):
                self.price *= 1.001
                return self.price, "TRANSICAO"

        class FakeOrchestrator:
            def evaluate(self, price, regime, regime_metrics, prices):
                return {
                    "action": "COMPRA",
                    "confidence": 0.9,
                    "engine": "TrendFollowing",
                    "details": "fake trend",
                }

        monkeypatch.setattr(simular, "SyntheticMarket", FakeSyntheticMarket)
        monkeypatch.setattr(simular, "StrategyOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(
            simular, "analyze_regime",
            lambda prices, symbol=None: self._base_regime_metrics("TRANSICAO"),
        )

        result = run_simulation(
            mode=SimulationMode.RESEARCH,
            ticks=30,
            seed=3,
            data_source="synthetic",
            symbol="SOL",
        )
        assert result["trade_statistics"]["total_trades"] == 0
        assert result.get("_funnel_report", {}).get("trades_executed", 0) == 0

    def test_trend_confirmation_count_in_simulator(self, monkeypatch):
        """Simulador deve respeitar TREND_CONFIRMATION_TICKS consecutivos."""
        import simular
        from simular import run_simulation, SimulationMode

        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 3, raising=False)
        monkeypatch.setattr(config, "MIN_HISTORY_FOR_REGIME", 5, raising=False)
        # Estes testes verificam a confirmação de tendência, não o filtro ML.
        # Um runtime_config.json local pode ter desligado o shadow mode.
        monkeypatch.setattr(config, "ML_SHADOW_MODE", True, raising=False)

        class FakeSyntheticMarket:
            def __init__(self, seed=42, n_ticks=10000):
                self.price = 100.0

            def generate_price(self):
                self.price *= 1.001
                return self.price, "TENDENCIA_ALTA"

        class FakeOrchestrator:
            def evaluate(self, price, regime, regime_metrics, prices):
                return {
                    "action": "COMPRA",
                    "confidence": 0.9,
                    "engine": "TrendFollowing",
                    "details": "fake trend",
                }

        actionable_ticks = []
        original_eval = simular.PositionManager.evaluate

        def counting_eval(self, symbol, signal, price, regime, suggestion, current_tick):
            # Conta tentativas de abertura aprovadas pelo filtro de confirmação (sinal ainda COMPRA)
            if self.get_position(symbol) is None and suggestion.get("action") in ("COMPRA", "VENDA"):
                actionable_ticks.append(current_tick)
            return original_eval(self, symbol, signal, price, regime, suggestion, current_tick)

        monkeypatch.setattr(simular, "SyntheticMarket", FakeSyntheticMarket)
        monkeypatch.setattr(simular, "StrategyOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(simular.PositionManager, "evaluate", counting_eval)
        monkeypatch.setattr(
            simular, "analyze_regime",
            lambda prices, symbol=None: self._base_regime_metrics("TENDENCIA_ALTA"),
        )

        result = run_simulation(
            mode=SimulationMode.RESEARCH,
            ticks=20,
            seed=4,
            data_source="synthetic",
            symbol="SOL",
        )
        # Com 3 ticks de confirmação, a primeira tentativa de abertura só pode ocorrer no 3º tick consecutivo
        assert actionable_ticks, "Nenhuma tentativa de abertura aprovada encontrada"
        assert min(actionable_ticks) >= 2
        assert result["_funnel_report"]["total_ticks"] == 20

    def test_trade_attribution_uses_entry_metadata(self, monkeypatch):
        """Fechamento deve atribuir trade à engine/regime de entrada e manter final_* do tick de saída."""
        import simular
        from simular import run_simulation, SimulationMode

        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)
        # O teste é sobre atribuição de metadados na saída, não sobre o filtro
        # ML; não deve depender do shadow mode salvo no runtime_config local.
        monkeypatch.setattr(config, "ML_SHADOW_MODE", True, raising=False)

        class FlippingOrchestrator:
            def __init__(self):
                self.i = 0

            def evaluate(self, price, regime, regime_metrics, prices):
                self.i += 1
                if self.i <= 5:
                    return {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing", "details": "open"}
                return {"action": "NEUTRO", "confidence": 0.0, "engine": "ProtectFlat", "details": "flat"}

        regimes = iter(["TENDENCIA_ALTA"] * 5 + ["TRANSICAO"] * 20)

        def fake_analyze(prices, symbol=None):
            r = next(regimes, "TRANSICAO")
            return self._base_regime_metrics(r)

        def fake_eval(self, symbol, signal, price, regime, suggestion, current_tick):
            pos = self.get_position(symbol)
            if pos is None and suggestion.get("action") in ("COMPRA", "VENDA"):
                # Força abertura com metadados de entrada conhecidos
                self.positions[symbol] = simular.PositionManager.__mro__[0]  # placeholder, replaced below
                from position_manager import Position
                self.positions[symbol] = Position(
                    side=suggestion["action"],
                    entry_price=price,
                    stop_loss=price * 0.9,
                    take_profit=price * 1.1,
                    entry_tick=current_tick,
                    position_size=1000.0,
                    regime=regime,
                    engine=suggestion.get("engine", "TrendFollowing"),
                    confidence=suggestion.get("confidence", 0.9),
                    details="forced",
                )
                return {"action": suggestion["action"], "event": "POSITION_OPENED", "result": None}
            if pos is not None and current_tick >= (pos.entry_tick + 2):
                # Fecha no tick atual (regime/engine atuais vêm do contexto da simulação)
                trade_result = self.close_position(symbol, price, regime, "forced_exit")
                return {"action": "SAIR", "event": "POSITION_CLOSED", "result": trade_result}
            return {"action": "MANTER" if pos else "NEUTRO", "event": None, "result": None}

        monkeypatch.setattr(simular, "StrategyOrchestrator", FlippingOrchestrator)
        monkeypatch.setattr(simular, "analyze_regime", fake_analyze)
        monkeypatch.setattr(simular.PositionManager, "evaluate", fake_eval)

        # Evitar ruído de persistência em DB durante teste
        monkeypatch.setattr(simular, "salvar_trade", lambda payload: None)

        result = run_simulation(
            mode=SimulationMode.RESEARCH,
            ticks=20,
            seed=5,
            data_source="synthetic",
            symbol="SOL",
        )
        assert result["trade_statistics"]["total_trades"] >= 1

        # Telemetry report é agregado, mas engine_stats/regime_stats devem refletir origem (entrada)
        # com a nossa atribuição corrigida: entrada TrendFollowing/TENDENCIA_ALTA.
        eng_stats = result.get("engine_stats", {})
        reg_stats = result.get("regime_stats", {})
        assert eng_stats.get("TrendFollowing", {}).get("trades", 0) >= 1
        assert reg_stats.get("TENDENCIA_ALTA", {}).get("trades", 0) >= 1
        # Não deve atribuir o trade de entrada ao ProtectFlat do tick de saída
        assert eng_stats.get("ProtectFlat", {}).get("trades", 0) == 0
        # Report não persiste trade_history detalhado, mas valida agregação de entrada correta.