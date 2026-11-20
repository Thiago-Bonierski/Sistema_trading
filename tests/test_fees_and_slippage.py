"""
Taxas de corretagem e slippage no motor e no simulador.

Cobre:
- direção do slippage na compra e na venda;
- multiplicador em TRANSICAO / ALTA_VOLATILIDADE;
- dedução exata das taxas no PnL e no EquityManager;
- custos zerados reproduzindo exatamente o PnL bruto histórico.
"""

import pandas as pd
import pytest

import config
import simular
from core.contracts import DecisionContext, MarketEvent, OrderIntent
from core.pipeline import DecisionPipeline, TrendConfirmationTracker
from equity import EquityManager
from position_manager import PositionManager
from risk_control import RiskController
from runtime_config import PARAMETER_GUIDANCE, PARAMETER_SPECS
from simular import SimulationMode

COST_KEYS = (
    "TRADING_FEE_PCT",
    "SLIPPAGE_PCT",
    "VOLATILE_SLIPPAGE_MULTIPLIER",
)


def _configure(monkeypatch, *, fee, slippage, multiplier=1.0):
    """Ajusta os custos ANTES de construir o PositionManager (que os espelha)."""
    monkeypatch.setattr(config, "TRADING_FEE_PCT", fee)
    monkeypatch.setattr(config, "SLIPPAGE_PCT", slippage)
    monkeypatch.setattr(config, "VOLATILE_SLIPPAGE_MULTIPLIER", multiplier)


def _manager(symbol="USD"):
    equity = EquityManager(initial_capital=100_000.0)
    risk = RiskController()
    manager = PositionManager(
        equity_manager=equity, risk_controller=risk, symbol=symbol
    )
    return manager, equity, risk


def _open(manager, side, *, price=100.0, regime="CONSOLIDACAO"):
    return manager.open_position(
        symbol="USD",
        side=side,
        price=price,
        regime=regime,
        engine="TrendFollowing",
        confidence=1.0,
        details="teste de custos",
        entry_tick=0,
    )


# ============================================================================
# (a) DIREÇÃO DO SLIPPAGE
# ============================================================================

class TestDirecaoSlippage:
    def test_compra_mais_cara_e_venda_mais_barata(self, monkeypatch):
        """Slippage é desfavorável nas duas pernas, sem taxa de corretagem."""
        _configure(monkeypatch, fee=0.0, slippage=0.01)
        manager, _, _ = _manager()

        _open(manager, "COMPRA")
        compra = manager.close_position("USD", 100.0, "CONSOLIDACAO", "test")
        assert compra["entry_price_effective"] == pytest.approx(101.0)
        assert compra["exit_price_effective"] == pytest.approx(99.0)
        assert compra["gross_pnl"] < 0
        assert compra["slippage_cost"] > 0
        assert compra["fees"] == pytest.approx(0.0)
        assert compra["pnl"] == pytest.approx(compra["gross_pnl"])

        _open(manager, "VENDA")
        venda = manager.close_position("USD", 100.0, "CONSOLIDACAO", "test")
        assert venda["entry_price_effective"] == pytest.approx(99.0)
        assert venda["exit_price_effective"] == pytest.approx(101.0)
        assert venda["gross_pnl"] < 0
        assert venda["slippage_cost"] > 0
        assert venda["pnl"] == pytest.approx(venda["gross_pnl"])


# ============================================================================
# (b) MULTIPLICADOR VOLÁTIL
# ============================================================================

class TestMultiplicadorVolatil:
    def test_regimes_volateis_dobram_o_slippage(self, monkeypatch):
        _configure(monkeypatch, fee=0.0, slippage=0.01, multiplier=2.0)
        manager, _, _ = _manager()

        assert manager._slippage_for("CONSOLIDACAO") == pytest.approx(0.01)
        assert manager._slippage_for("TENDENCIA_ALTA") == pytest.approx(0.01)
        assert manager._slippage_for("TRANSICAO") == pytest.approx(0.02)
        assert manager._slippage_for("ALTA_VOLATILIDADE") == pytest.approx(0.02)

        # Regime de entrada e de saída voláteis: 2% em cada perna.
        _open(manager, "COMPRA", regime="ALTA_VOLATILIDADE")
        resultado = manager.close_position("USD", 100.0, "TRANSICAO", "test")
        assert resultado["entry_price_effective"] == pytest.approx(102.0)
        assert resultado["exit_price_effective"] == pytest.approx(98.0)

    def test_custo_volatil_supera_o_normal(self, monkeypatch):
        _configure(monkeypatch, fee=0.0, slippage=0.01, multiplier=2.0)
        volatil, _, _ = _manager()
        _open(volatil, "COMPRA")
        r_volatil = volatil.close_position("USD", 101.0, "TRANSICAO", "test")

        _configure(monkeypatch, fee=0.0, slippage=0.01, multiplier=1.0)
        normal, _, _ = _manager()
        _open(normal, "COMPRA")
        r_normal = normal.close_position("USD", 101.0, "TRANSICAO", "test")

        assert r_volatil["slippage_cost"] > r_normal["slippage_cost"]
        assert r_volatil["gross_pnl"] < r_normal["gross_pnl"]


# ============================================================================
# (c) DEDUÇÃO EXATA DAS TAXAS
# ============================================================================

class TestDeducaoDeTaxas:
    def test_entry_fee_persistida_e_pnl_liquido(self, monkeypatch):
        """Com slippage zero, o PnL cai exatamente 2x a comissão."""
        _configure(monkeypatch, fee=0.001, slippage=0.0)
        manager, equity, _ = _manager()

        position = _open(manager, "COMPRA")
        size = position.position_size
        fee_esperada = size * 0.001
        assert position.entry_fee == pytest.approx(fee_esperada)

        restored = type(position).from_dict(position.to_dict())
        assert restored.entry_fee == pytest.approx(fee_esperada)

        resultado = manager.close_position("USD", 110.0, "CONSOLIDACAO", "test")
        bruto_esperado = size * 0.10
        total_taxas = 2.0 * fee_esperada

        assert resultado["gross_pnl"] == pytest.approx(bruto_esperado)
        assert resultado["slippage_cost"] == pytest.approx(0.0)
        assert resultado["entry_fee"] == pytest.approx(fee_esperada)
        assert resultado["exit_fee"] == pytest.approx(fee_esperada)
        assert resultado["total_fees"] == pytest.approx(total_taxas)
        assert resultado["fees"] == pytest.approx(total_taxas)
        assert resultado["pnl"] == pytest.approx(bruto_esperado - total_taxas)

        equity.update_equity(resultado["pnl"])
        assert equity.current_equity == pytest.approx(
            100_000.0 + bruto_esperado - total_taxas
        )

    def test_pipeline_repassa_pnl_liquido_ao_equity(self, monkeypatch):
        """O único ponto que atualiza equity lê `trade_result['pnl']`."""
        _configure(monkeypatch, fee=0.001, slippage=0.0)
        monkeypatch.setattr(config, "TREND_CONFIRMATION_TICKS", 1, raising=False)

        equity = EquityManager(initial_capital=100_000.0)
        risk = RiskController()
        positions = PositionManager(equity, risk, symbol="SOL")
        positions._max_age_override = 100

        class Orchestrator:
            def __init__(self):
                self.calls = 0

            def evaluate(self, price, regime, regime_metrics, prices):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "action": "COMPRA",
                        "confidence": 0.9,
                        "engine": "TrendFollowing",
                        "details": "entrada",
                    }
                return {
                    "action": "VENDA",
                    "confidence": 0.9,
                    "engine": "TrendFollowing",
                    "details": "saida",
                }

        class TrainedClassifier:
            def is_trained(self):
                return False

            def filter_signal(self, suggestion, regime_metrics):
                return dict(suggestion)

        pipeline = DecisionPipeline(
            orchestrator=Orchestrator(),
            position_manager=positions,
            risk_controller=risk,
            equity_manager=equity,
            classifier=TrainedClassifier(),
            analyze_regime=lambda prices, symbol: {
                "regime": "TENDENCIA_ALTA",
                "slope": 0.01,
                "momentum": 0.002,
                "range_rel": 0.01,
                "volatility_ratio": 1.0,
            },
            check_exhaustion=lambda **kwargs: (False, ""),
            trend_tracker=TrendConfirmationTracker(
                counts={"SOL": 0}, last_regime={"SOL": None}
            ),
        )

        def event(price, tick):
            return MarketEvent(
                symbol="SOL",
                price=price,
                timestamp=float(tick),
                sequence=tick,
                prices=pd.Series([price] * 35),
                regime="TENDENCIA_ALTA",
                regime_metrics={"volatility_ratio": 1.0},
                source="test",
            )

        for tick, price in enumerate((100.0, 110.0)):
            decision = pipeline.process(
                event(price, tick),
                DecisionContext(symbol="SOL", position_symbol="SOL", tick=tick),
            )

        assert decision.intent == OrderIntent.CLOSE
        trade = decision.trade_result
        assert trade["pnl"] == pytest.approx(trade["gross_pnl"] - trade["fees"])
        assert trade["fees"] > 0
        assert equity.current_equity == pytest.approx(100_000.0 + trade["pnl"])


# ============================================================================
# (d) CUSTOS ZERADOS = COMPORTAMENTO BRUTO
# ============================================================================

class TestCustoZero:
    @pytest.mark.parametrize(
        "side,entrada,saida",
        [("COMPRA", 100.0, 110.0), ("VENDA", 100.0, 90.0)],
    )
    def test_zero_reproduz_pnl_bruto(self, monkeypatch, side, entrada, saida):
        _configure(monkeypatch, fee=0.0, slippage=0.0)
        manager, _, _ = _manager()

        position = _open(manager, side, price=entrada)
        size = position.position_size
        bruto_esperado = size * abs(saida - entrada) / entrada

        resultado = manager.close_position("USD", saida, "CONSOLIDACAO", "test")

        assert resultado["entry_price_effective"] == pytest.approx(entrada)
        assert resultado["exit_price_effective"] == pytest.approx(saida)
        assert resultado["gross_pnl"] == pytest.approx(bruto_esperado)
        assert resultado["slippage_cost"] == pytest.approx(0.0)
        assert resultado["fees"] == pytest.approx(0.0)
        assert resultado["pnl"] == pytest.approx(bruto_esperado)


# ============================================================================
# (e) EXPOSIÇÃO EM CALIBRAGEM E RELATÓRIO
# ============================================================================

class TestExposicaoDosCustos:
    def test_parametros_expostos_na_calibragem(self):
        specs = {spec.key: spec for spec in PARAMETER_SPECS}
        for key in COST_KEYS:
            assert key in specs
            assert specs[key].category == "costs"
            assert key in PARAMETER_GUIDANCE
            guidance = PARAMETER_GUIDANCE[key]
            assert guidance["impact_up"]
            assert guidance["impact_down"]
            assert guidance["recommended"]

    def test_relatorio_de_simulacao_expoe_composicao_dos_custos(self, monkeypatch):
        _configure(monkeypatch, fee=0.001, slippage=0.0002, multiplier=2.0)
        monkeypatch.setattr(simular, "salvar_trade", lambda *args, **kwargs: None)

        resultado = simular.run_simulation(
            SimulationMode.RESEARCH,
            ticks=500,
            seed=42,
            data_source="synthetic",
        )

        for key in ("gross_pnl", "total_fees", "slippage_cost", "net_pnl"):
            assert key in resultado
        assert resultado["net_pnl"] == pytest.approx(resultado["total_pnl"])
        assert resultado["final_equity"] == pytest.approx(
            resultado["initial_capital"] + resultado["net_pnl"]
        )
        assert resultado["total_fees"] >= 0.0
        assert resultado["slippage_cost"] >= 0.0

        for trade in resultado["trades"]:
            assert "gross_pnl" in trade
            assert "fees" in trade
            assert trade["pnl"] == pytest.approx(
                trade["gross_pnl"] - trade["fees"]
            )
