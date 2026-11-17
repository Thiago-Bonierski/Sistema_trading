"""
Testes da histerese de saída por risco de regime.

Regra:
- ALTA_VOLATILIDADE (caos) encerra imediatamente por regime_risk.
- TRANSICAO só encerra após REGIME_RISK_EXIT_TICKS avaliações consecutivas.
- Voltar à tendência antes do limite zera o contador e a posição continua
  viva até take-profit, stop-loss ou max_age.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from position_manager import PositionManager, Position


def _manager(monkeypatch, *, exit_ticks=3, max_age=None):
    monkeypatch.setattr(config, "REGIME_RISK_EXIT_TICKS", exit_ticks)
    manager = PositionManager(symbol="SIM")
    if max_age is not None:
        manager._max_age_override = max_age
    return manager


def _open(manager, price=100.0):
    result = manager.evaluate(
        symbol="SIM",
        signal="COMPRA",
        price=price,
        regime="TENDENCIA_ALTA",
        suggestion={
            "engine": "TrendFollowing",
            "confidence": 0.8,
            "details": "teste",
            "regime_metrics": {"slope": 0.01},
        },
        current_tick=0,
    )
    assert result["event"] == "ENTRY"
    return manager.get_position("SIM")


def _evaluate(manager, regime, price=100.0, signal="NEUTRO", tick=1):
    return manager.evaluate(
        symbol="SIM",
        signal=signal,
        price=price,
        regime=regime,
        suggestion={"engine": "TrendFollowing", "confidence": 0.8},
        current_tick=tick,
    )


class TestHistereseTransicao:
    def test_dois_ticks_de_transicao_nao_fecham(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        position = _open(manager)

        first = _evaluate(manager, "TRANSICAO")
        assert first["event"] == "HOLD"
        assert position.transition_ticks == 1

        second = _evaluate(manager, "TRANSICAO")
        assert second["event"] == "HOLD"
        assert position.transition_ticks == 2
        assert manager.get_position("SIM") is position

    def test_tres_ticks_consecutivos_fecham_por_regime_risk(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        _open(manager)

        assert _evaluate(manager, "TRANSICAO")["event"] == "HOLD"
        assert _evaluate(manager, "TRANSICAO")["event"] == "HOLD"

        final = _evaluate(manager, "TRANSICAO")
        assert final["event"] == "EXIT"
        assert final["action"] == "SAIR"
        assert final["result"]["reason"] == "regime_risk"
        assert manager.get_position("SIM") is None

    def test_retorno_a_tendencia_zera_o_contador(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        position = _open(manager)

        _evaluate(manager, "TRANSICAO")
        _evaluate(manager, "TRANSICAO")
        assert position.transition_ticks == 2

        back = _evaluate(manager, "TENDENCIA_ALTA")
        assert back["event"] == "HOLD"
        assert position.transition_ticks == 0

        # Recomeça a contagem: 2 ticks ainda não fecham.
        assert _evaluate(manager, "TRANSICAO")["event"] == "HOLD"
        assert _evaluate(manager, "TRANSICAO")["event"] == "HOLD"
        assert position.transition_ticks == 2

        # Terceiro consecutivo fecha.
        assert _evaluate(manager, "TRANSICAO")["event"] == "EXIT"


class TestAltaVolatilidade:
    def test_alta_volatilidade_fecha_imediatamente(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        _open(manager)

        result = _evaluate(manager, "ALTA_VOLATILIDADE")
        assert result["event"] == "EXIT"
        assert result["result"]["reason"] == "regime_risk"
        assert manager.get_position("SIM") is None

    def test_contador_de_transicao_e_zerado_no_caos(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=5)
        position = _open(manager)

        _evaluate(manager, "TRANSICAO")
        _evaluate(manager, "TRANSICAO")
        assert position.transition_ticks == 2

        # Caos fecha na hora e não deve reutilizar o contador depois.
        result = _evaluate(manager, "ALTA_VOLATILIDADE")
        assert result["event"] == "EXIT"
        assert result["result"]["reason"] == "regime_risk"


class TestPrioridades:
    def test_take_profit_vence_transicao_curta(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        _open(manager)

        _evaluate(manager, "TRANSICAO")  # contador = 1
        result = _evaluate(manager, "TRANSICAO", price=102.0)  # acima do TP
        assert result["event"] == "EXIT"
        assert result["result"]["reason"] == "take_profit"

    def test_stop_loss_vence_transicao_curta(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=3)
        _open(manager)

        _evaluate(manager, "TRANSICAO")
        result = _evaluate(manager, "TRANSICAO", price=98.0)  # abaixo do SL
        assert result["event"] == "EXIT"
        assert result["result"]["reason"] == "stop_loss"

    def test_transicao_curta_ainda_respeita_max_age(self, monkeypatch):
        manager = _manager(monkeypatch, exit_ticks=10, max_age=2)
        _open(manager)

        assert _evaluate(manager, "TRANSICAO")["event"] == "HOLD"
        result = _evaluate(manager, "TRANSICAO")
        assert result["event"] == "EXIT"
        assert result["result"]["reason"] == "max_age"


class TestPersistencia:
    def test_transition_ticks_sobrevive_ao_round_trip(self):
        position = Position(
            side="COMPRA",
            entry_price=100.0,
            stop_loss=99.2,
            take_profit=101.5,
            entry_tick=0,
            position_size=1000.0,
            transition_ticks=2,
        )

        restored = Position.from_dict(position.to_dict())
        assert restored.transition_ticks == 2
