"""
Testes de persistência do estado vivo (fonte única de verdade).

Cobre:
- save_all_state / load_all_state (posições, equity, risco)
- Restauração automática no boot (restore_state)
- Snapshot thread-safe (get_state_snapshot)
"""
import sys
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import config
from database import (
    db_manager,
    init_database,
    save_all_state,
    load_all_state,
    save_positions,
    load_positions,
    save_system_state,
    load_system_state,
    save_risk_state,
    load_risk_state,
)
from equity import EquityManager
from risk_control import RiskController
from position_manager import PositionManager, Position
import monitor


class TestPersistenciaEstado:
    """Testes de persistência e restauração do estado vivo."""

    def setup_method(self):
        """Cria banco temporário isolado para cada teste."""
        self.tmp = tempfile.mktemp(suffix='.db')
        config.DB_PATH = Path(self.tmp)
        # Recria o db_manager com o novo caminho
        import database
        database.db_manager = database.DatabaseManager(config.DB_PATH)
        init_database()

    def teardown_method(self):
        import os
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_save_load_positions(self):
        """Deve salvar e carregar posições abertas."""
        posicoes = {
            "USD": Position.from_dict({
                "side": "COMPRA", "entry_price": 5.85, "stop_loss": 5.70,
                "take_profit": 6.14, "entry_tick": 10, "position_size": 10000.0,
                "age": 3, "regime": "TENDENCIA_ALTA", "engine": "TrendFollowing",
                "confidence": 0.82, "details": "teste",
            })
        }
        save_all_state(
            posicoes,
            {"initial_capital": 100000, "current_equity": 100000,
             "peak_equity": 100000, "max_drawdown": 0.0,
             "equity_history": [100000], "pnl_history": []},
            {"aggressiveness_level": "NORMAL", "global_trade_count": 0,
             "trade_count_by_regime": {}, "cooldown": {}, "blocked_trades": 0,
             "new_high_counter": 0, "last_reset_day": "2026-11-15",
             "last_equity_high": 0.0, "daily_start_equity": None,
             "kill_switch_activated": False, "kill_switch_until": None},
        )
        estado = load_all_state()
        assert "USD" in estado["positions"]
        assert estado["positions"]["USD"]["side"] == "COMPRA"
        assert estado["positions"]["USD"]["entry_price"] == 5.85

    def test_save_load_equity(self):
        """Deve salvar e carregar estado de equity."""
        save_all_state(
            {},
            {"initial_capital": 100000, "current_equity": 105000,
             "peak_equity": 110000, "max_drawdown": 0.10,
             "equity_history": [100000, 105000], "pnl_history": [5000]},
            {"aggressiveness_level": "REDUCED", "global_trade_count": 5,
             "trade_count_by_regime": {"TENDENCIA_ALTA": 3}, "cooldown": {},
             "blocked_trades": 2, "new_high_counter": 0,
             "last_reset_day": "2026-11-15", "last_equity_high": 110000.0,
             "daily_start_equity": 100000.0, "kill_switch_activated": False,
             "kill_switch_until": None},
        )
        estado = load_all_state()
        eq = estado["equity"]
        assert eq["current_equity"] == 105000
        assert eq["peak_equity"] == 110000
        assert eq["max_drawdown"] == 0.10

    def test_save_load_risco(self):
        """Deve salvar e carregar estado de risco."""
        save_all_state(
            {},
            {"initial_capital": 100000, "current_equity": 100000,
             "peak_equity": 100000, "max_drawdown": 0.0,
             "equity_history": [100000], "pnl_history": []},
            {"aggressiveness_level": "PROTECT", "global_trade_count": 8,
             "trade_count_by_regime": {}, "cooldown": {"BTC": 10},
             "blocked_trades": 3, "new_high_counter": 0,
             "last_reset_day": "2026-11-15", "last_equity_high": 0.0,
             "daily_start_equity": None, "kill_switch_activated": True,
             "kill_switch_until": "2026-11-15T22:00:00"},
        )
        estado = load_all_state()
        r = estado["risk"]
        assert r["aggressiveness_level"] == "PROTECT"
        assert r["global_trade_count"] == 8
        assert r["kill_switch_activated"] is True
        assert r["cooldown"] == {"BTC": 10}

    def test_restore_state_no_dados(self):
        """Deve retornar False quando não há estado persistido."""
        # Banco vazio
        resultado = monitor.restore_state()
        assert resultado is False

    def test_restore_state_com_dados(self):
        """Deve restaurar posições, equity e risco no boot."""
        # Salvar estado primeiro
        save_all_state(
            {"USD": Position.from_dict({
                "side": "VENDA", "entry_price": 100.0, "stop_loss": 102.0,
                "take_profit": 95.0, "entry_tick": 5, "position_size": 5000.0,
                "age": 2, "regime": "TENDENCIA_BAIXA", "engine": "MeanReversion",
                "confidence": 0.74, "details": "teste",
            })},
            {"initial_capital": 100000, "current_equity": 99000,
             "peak_equity": 100000, "max_drawdown": 0.01,
             "equity_history": [100000, 99000], "pnl_history": [-1000]},
            {"aggressiveness_level": "NORMAL", "global_trade_count": 1,
             "trade_count_by_regime": {}, "cooldown": {}, "blocked_trades": 0,
             "new_high_counter": 0, "last_reset_day": "2026-11-15",
             "last_equity_high": 100000.0, "daily_start_equity": 100000.0,
             "kill_switch_activated": False, "kill_switch_until": None},
        )

        # Limpar managers in-memory para simular boot
        monitor.position_manager.positions.clear()
        monitor.equity_manager.reset()
        monitor.risk_controller.global_trade_count = 0

        resultado = monitor.restore_state()
        assert resultado is True

        pos = monitor.position_manager.get_position("USD")
        assert pos is not None
        assert pos.side == "VENDA"
        assert pos.entry_price == 100.0
        assert monitor.equity_manager.current_equity == 99000
        assert monitor.risk_controller.aggressiveness_level == "NORMAL"

    def test_get_state_snapshot(self):
        """Deve retornar snapshot consistente sem expor objetos internos."""
        monitor.position_manager.positions.clear()
        monitor.equity_manager.reset()
        monitor.risk_controller.global_trade_count = 0

        monitor.position_manager.open_position(
            symbol="BTC", side="COMPRA", price=370000.0, regime="TENDENCIA_ALTA",
            engine="TrendFollowing", confidence=0.8, details="teste", entry_tick=1,
        )
        monitor.equity_manager.update_equity(2000.0)

        snap = monitor.get_state_snapshot()
        assert "BTC" in snap["positions"]
        assert snap["equity"]["current_equity"] == 102000.0
        assert snap["risk"]["aggressiveness_level"] == "NORMAL"

        # O snapshot deve ser uma cópia (não expor o dict interno)
        snap["positions"]["NOVO"] = {"fake": True}
        assert "NOVO" not in monitor.position_manager.positions
