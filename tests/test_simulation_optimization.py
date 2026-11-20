"""
Testes da otimização de volume/rentabilidade do backtest.

Cobre:
- virada de dia simulada no RiskController (1.440 candles = 1 dia);
- destravamento de `regime_limit` após a virada;
- expiração do kill-switch pelo relógio simulado;
- PAPER_TRADING usando MAX_POSITION_AGE_TICKS["REDUCED"] da config;
- engines com janela anterior e limiares adaptativos à volatilidade;
- paridade da configuração efetiva (runtime_config) com a simulação.
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

import config
import simular
from core.pipeline import TrendConfirmationTracker
from risk_control import RiskController
from strategy_unified import (
    BreakoutMomentumEngine,
    MeanReversionEngine,
    TrendFollowingEngine,
    _previous_window,
    _volatility_scale,
)
from simular import SimulationMode

BAND_WIDTH_ORIGINAL = config.MEAN_REVERSION_BAND_WIDTH


class TestRelogioSimulado:
    def test_virada_de_dia_reseta_contadores(self, monkeypatch):
        monkeypatch.setattr(config, "SIMULATION_TICKS_PER_DAY", 1440)
        risk = RiskController()
        risk.ticks_per_day = 1440
        risk.set_simulation_tick(0, current_equity=1000.0)
        risk.register_trade("SIM", "TENDENCIA_ALTA", "COMPRA")
        assert risk.global_trade_count == 1

        assert risk.set_simulation_tick(1439, current_equity=1000.0) is False
        assert risk.global_trade_count == 1

        assert risk.set_simulation_tick(1440, current_equity=1000.0) is True
        assert risk.global_trade_count == 0
        assert dict(risk.trade_count_by_regime) == {}
        assert risk.daily_start_equity == 1000.0

    def test_regime_limit_e_destravado_apos_virada(self, monkeypatch):
        monkeypatch.setattr(config, "SIMULATION_TICKS_PER_DAY", 1440)
        risk = RiskController()
        # Ancora o relógio simulado no tick 0: sem isto o dia inicial viria
        # de datetime.now() e o teste dependeria da data do sistema.
        risk.set_simulation_tick(0, current_equity=1000.0)
        for _ in range(3):
            risk.trade_count_by_regime["TENDENCIA_ALTA"] += 1

        assert risk.can_execute("SIM", "TENDENCIA_ALTA", "COMPRA") is False
        assert risk.blocked_trades_by_reason["regime_limit"] == 1

        risk.set_simulation_tick(1440, current_equity=1000.0)
        assert risk.can_execute("SIM", "TENDENCIA_ALTA", "COMPRA") is True

    def test_kill_switch_expira_no_tempo_simulado(self):
        risk = RiskController()
        risk.set_simulation_tick(0, current_equity=1000.0)
        risk.kill_switch_activated = True
        risk.kill_switch_until = risk._now() + timedelta(hours=2)

        assert risk.can_trade("COMPRA", 0.9, "TENDENCIA_ALTA") is False
        risk.set_simulation_tick(119, current_equity=1000.0)
        assert risk.can_trade("COMPRA", 0.9, "TENDENCIA_ALTA") is False

        risk.set_simulation_tick(120, current_equity=1000.0)
        assert risk.can_trade("COMPRA", 0.9, "TENDENCIA_ALTA") is True


class TestJanelaPaper:
    def test_config_reduced_e_30(self):
        assert config.MAX_POSITION_AGE_TICKS["REDUCED"] == 30

    def test_paper_usa_valor_da_config(self, monkeypatch):
        captured = {}
        original = simular.PositionManager

        def factory(*args, **kwargs):
            manager = original(*args, **kwargs)
            captured["manager"] = manager
            return manager

        monkeypatch.setattr(simular, "PositionManager", factory)
        monkeypatch.setattr(simular, "salvar_trade", lambda *a, **k: None)

        simular.run_simulation(
            SimulationMode.PAPER_TRADING,
            ticks=30,
            seed=42,
            data_source="synthetic",
            initial_capital=1000.0,
        )
        assert (
            captured["manager"]._max_age_override
            == config.MAX_POSITION_AGE_TICKS["REDUCED"]
        )


class TestEngines:
    @staticmethod
    def _prices(current, previous=100.0, n=10):
        return pd.Series([current] + [previous] * n)

    def test_breakout_usa_janela_anterior(self, monkeypatch):
        monkeypatch.setattr(config, "BREAKOUT_THRESHOLD", 0.001)
        monkeypatch.setattr(config, "BREAKOUT_MIN_RANGE", 0.001)
        engine = BreakoutMomentumEngine()
        metrics = {"regime": "TENDENCIA_ALTA", "range_rel": 0.003}

        result = engine.suggest(self._prices(102.0), 102.0, metrics)
        assert result["action"] == "COMPRA"

        inside = engine.suggest(self._prices(100.05), 100.05, metrics)
        assert inside["action"] == "NEUTRO"

    def test_mean_reversion_usa_janela_anterior(self, monkeypatch):
        monkeypatch.setattr(config, "MEAN_REVERSION_BAND_WIDTH", 0.001)
        engine = MeanReversionEngine()
        metrics = {"regime": "CONSOLIDACAO", "range_rel": 0.002}

        assert engine.suggest(self._prices(98.0), 98.0, metrics)["action"] == "COMPRA"
        assert engine.suggest(self._prices(102.0), 102.0, metrics)["action"] == "VENDA"

    def test_limiares_adaptativos_a_baixa_volatilidade(self, monkeypatch):
        monkeypatch.setattr(config, "MEAN_REVERSION_BAND_WIDTH", 0.01)
        engine = MeanReversionEngine()
        prices = self._prices(99.5)

        # USDT/BRL: range_rel pequeno reduz a banda e libera o sinal.
        low_vol = engine.suggest(
            prices, 99.5, {"regime": "CONSOLIDACAO", "range_rel": 0.0002}
        )
        assert low_vol["action"] == "COMPRA"

        # Ativo volátil mantém a banda cheia e não dispara.
        high_vol = engine.suggest(
            prices, 99.5, {"regime": "CONSOLIDACAO", "range_rel": 0.002}
        )
        assert high_vol["action"] == "NEUTRO"


class TestHelpersDasEngines:
    def test_previous_window_exclui_barra_atual(self):
        prices = pd.Series([999.0, 100.0, 101.0, 102.0])
        window = _previous_window(prices, 2)
        assert list(window) == [100.0, 101.0]
        assert 999.0 not in list(window)

    def test_volatility_scale_limita_e_so_reduz(self):
        assert _volatility_scale(0.002) == 1.0       # referência (SOL/BTC)
        assert _volatility_scale(0.004) == 1.0       # mais volátil: sem alteração
        assert _volatility_scale(0.0002) == 0.1      # piso para baixa volatilidade
        assert _volatility_scale(0) == 1.0           # sem dados: neutro
        assert _volatility_scale("invalido") == 1.0

    def test_volatility_scale_e_monotonico_na_faixa_util(self):
        escalas = [_volatility_scale(v) for v in (0.0002, 0.0004, 0.001, 0.002)]
        assert escalas == sorted(escalas)
        assert all(0.1 <= s <= 1.0 for s in escalas)


class TestCalibracaoTrendFollowing:
    def test_threshold_calibrado_e_usado_pela_engine(self):
        assert config.TREND_PRICE_THRESHOLD == 0.004
        assert TrendFollowingEngine().price_threshold == 0.004

    def test_filtra_ruido_mas_mantem_tendencia_real(self):
        engine = TrendFollowingEngine()
        metrics = {"regime": "TENDENCIA_ALTA", "momentum": 0.01}
        base = pd.Series([100.0] * 15)

        # 0,3% acima da média: ruído em 1m, não deve abrir posição.
        ruido = engine.suggest(
            pd.concat([pd.Series([100.3]), base]), 100.3, metrics
        )
        assert ruido["action"] == "NEUTRO"

        # 0,5% acima da média: tendência real, deve sinalizar COMPRA.
        tendencia = engine.suggest(
            pd.concat([pd.Series([100.5]), base]), 100.5, metrics
        )
        assert tendencia["action"] == "COMPRA"


class TestCalibracaoContraCustos:
    """Grid com 5.000 ticks reais e custos ativos fixou estes valores."""

    def test_banda_de_reversao_calibrada(self):
        assert config.MEAN_REVERSION_BAND_WIDTH == 0.0025
        assert MeanReversionEngine().band_width == 0.0025

    def test_range_minimo_de_breakout_calibrado(self):
        assert config.BREAKOUT_THRESHOLD == 0.0010
        assert config.BREAKOUT_MIN_RANGE == 0.0020
        assert BreakoutMomentumEngine().min_range == 0.0020

    def test_threshold_ml_mantido_para_nao_estrangular_volume(self):
        # 0,65 / 0,68 / 0,70 reduziram o lucro líquido no grid (menos trades,
        # sem ganho de assertividade).
        assert config.ML_APPROVAL_THRESHOLD == 0.58


class TestConfirmacaoConsolidacao:
    def test_consolidacao_conta_confirmacao_e_aceita_dois_lados(self, monkeypatch):
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 2)
        tracker = TrendConfirmationTracker()
        suggestion = {
            "action": "COMPRA", "confidence": 0.7,
            "engine": "MeanReversion",
        }

        assert tracker.update("SIM", "CONSOLIDACAO") == 1
        filtered, reason = tracker.apply_filter(
            "SIM", "CONSOLIDACAO", suggestion
        )
        assert reason is None
        assert filtered["action"] == "COMPRA"

        venda = dict(suggestion, action="VENDA")
        filtered, reason = tracker.apply_filter("SIM", "CONSOLIDACAO", venda)
        assert reason is None

    def test_regime_oposto_continua_bloqueado(self, monkeypatch):
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1)
        tracker = TrendConfirmationTracker()
        tracker.update("SIM", "TENDENCIA_BAIXA")
        _, reason = tracker.apply_filter(
            "SIM",
            "TENDENCIA_BAIXA",
            {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing"},
        )
        assert reason is not None
        assert "não confirma" in reason


class TestParidadeConfiguracao:
    def test_simular_importa_runtime_config(self):
        assert hasattr(simular, "runtime_config")

    def test_histerese_e_threshold_de_tendencia_expostos_no_painel(self):
        import runtime_config as rc_module

        keys = {spec.key for spec in rc_module.PARAMETER_SPECS}
        assert "REGIME_RISK_EXIT_TICKS" in keys
        assert "TREND_PRICE_THRESHOLD" in keys

    def test_override_efetivo_chega_as_engines(self, tmp_path):
        import runtime_config as rc_module

        manager = rc_module.RuntimeConfigManager(
            config_path=tmp_path / "runtime_config.json"
        )
        try:
            manager.update({"MEAN_REVERSION_BAND_WIDTH": 0.0007})
            assert config.MEAN_REVERSION_BAND_WIDTH == 0.0007
            assert MeanReversionEngine().band_width == 0.0007
        finally:
            manager.reset(["MEAN_REVERSION_BAND_WIDTH"])

        assert config.MEAN_REVERSION_BAND_WIDTH == BAND_WIDTH_ORIGINAL
