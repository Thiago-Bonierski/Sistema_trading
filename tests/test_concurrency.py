"""
Testes de concorrência e thread-safety.

Cobre:
- state_lock protege position_manager/equity_manager/risk_controller
- get_state_snapshot retorna cópia consistente (sem RuntimeError)
- Posições abertas/fechadas sob lock não corrompem o snapshot
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from database import init_database
from equity import EquityManager
from risk_control import RiskController
from position_manager import PositionManager
import monitor


class TestConcorrencia:
    """Testes de thread-safety do estado vivo."""

    def setup_method(self):
        init_database()
        monitor.position_manager.positions.clear()
        monitor.equity_manager.reset()
        monitor.risk_controller.global_trade_count = 0

    def test_snapshot_nao_quebra_durante_mutacao(self):
        """O snapshot deve ser consistente mesmo enquanto o monitor muta o estado."""
        erros = []
        stop = threading.Event()

        def escritor():
            """Thread que abre e fecha posições rapidamente."""
            i = 0
            while not stop.is_set():
                try:
                    monitor.position_manager.open_position(
                        symbol="USD", side="COMPRA", price=5.85,
                        regime="TENDENCIA_ALTA", engine="TrendFollowing",
                        confidence=0.8, details="concorrencia", entry_tick=i,
                    )
                    time.sleep(0.001)
                    monitor.position_manager.close_position(
                        "USD", 5.90, "TENDENCIA_ALTA", "teste_concorrencia"
                    )
                    monitor.equity_manager.update_equity(10.0)
                    i += 1
                except Exception as e:
                    erros.append(("escritor", str(e)))
                    break

        def leitor():
            """Thread que lê snapshots continuamente."""
            while not stop.is_set():
                try:
                    snap = monitor.get_state_snapshot()
                    # Validar estrutura do snapshot
                    assert "positions" in snap
                    assert "equity" in snap
                    assert "risk" in snap
                    # Não deve levantar RuntimeError por dicionário mutado
                    _ = list(snap["positions"].keys())
                except Exception as e:
                    erros.append(("leitor", str(e)))
                    break

        t1 = threading.Thread(target=escritor)
        t2 = threading.Thread(target=leitor)
        t1.start()
        t2.start()

        time.sleep(0.5)
        stop.set()
        t1.join()
        t2.join()

        assert not erros, f"Erros de concorrência: {erros}"

    def test_equity_thread_safe(self):
        """EquityManager deve ser thread-safe (RLock interno)."""
        em = EquityManager(initial_capital=100000.0)
        erros = []
        stop = threading.Event()

        def worker():
            while not stop.is_set():
                try:
                    em.update_equity(1.0)
                    _ = em.get_current_drawdown()
                    _ = em.get_total_return()
                except Exception as e:
                    erros.append(str(e))
                    break

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join()

        assert not erros, f"Erros no equity: {erros}"
        assert em.current_equity > 100000.0

    def test_position_manager_double_checked_lock(self):
        """Não deve abrir posição duplicada sob concorrência."""
        pm = PositionManager(monitor.equity_manager, monitor.risk_controller)
        erros = []
        stop = threading.Event()

        def worker():
            while not stop.is_set():
                try:
                    p = pm.open_position(
                        symbol="BTC", side="COMPRA", price=370000.0,
                        regime="TENDENCIA_ALTA", engine="TrendFollowing",
                        confidence=0.8, details="lock", entry_tick=1,
                    )
                    if p is not None:
                        pm.close_position("BTC", 371000.0, "TENDENCIA_ALTA", "ok")
                except Exception as e:
                    erros.append(str(e))
                    break

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join()

        assert not erros, f"Erros no position manager: {erros}"
        # Ao final não deve ficar posição aberta
        assert pm.get_position("BTC") is None
