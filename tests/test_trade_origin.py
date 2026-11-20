"""
Separação lógica da origem dos trades.

Garante que:
- simulações com dados reais (api/db) sejam gravadas como SIM_{symbol} e
  continuem alimentando o treino do ML;
- simulações sintéticas sejam gravadas como SIM_SYNTHETIC_{symbol} e
  ignoradas pelo MLTrainer;
- nenhum registro SIM_% apareça nos trades recentes/KPIs da Sala de Controle.
"""

import logging
import sqlite3
from contextlib import contextmanager

import pytest

import app as app_module
import config
import ml_training
import simular
from database import DatabaseManager
from trade_origin import (
    SIMULATED_PREFIX,
    SYNTHETIC_PREFIX,
    is_simulated,
    is_synthetic,
    simulated_symbol,
)


# ============================================================================
# HELPERS
# ============================================================================

class _FakeDB:
    """Expõe apenas a interface usada por MLTrainer.load_trade_history."""

    def __init__(self, path):
        self.path = path

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _make_training_db(path, symbols):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE trade_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "symbol TEXT NOT NULL, pnl REAL NOT NULL)"
    )
    for symbol in symbols:
        conn.execute(
            "INSERT INTO trade_history (symbol, pnl) VALUES (?, 1.0)",
            (symbol,),
        )
    conn.commit()
    conn.close()


def _insert_live_trade(db, symbol, pnl=10.0):
    db.execute(
        "INSERT INTO trade_history (symbol, side, entry_price, exit_price, "
        "entry_tick, exit_tick, entry_regime, exit_regime, pnl, duration_ticks) "
        "VALUES (?, 'COMPRA', 100, 101, 1, 5, 'CONSOLIDACAO', "
        "'CONSOLIDACAO', ?, 4)",
        (symbol, pnl),
    )


@pytest.fixture
def live_db(monkeypatch, tmp_path):
    """Banco isolado com trades reais, históricos e sintéticos."""
    db = DatabaseManager(tmp_path / "live.db")
    db.initialize_schema()

    _insert_live_trade(db, "BTC", 12.0)
    _insert_live_trade(db, "USD", 4.0)
    _insert_live_trade(db, simular.simulated_symbol("BTC", "api"), 7.0)
    _insert_live_trade(db, simular.simulated_symbol("SOL", "db"), -3.0)
    _insert_live_trade(db, simular.simulated_symbol("BTC", "synthetic"), 99.0)

    monkeypatch.setattr(app_module, "db_manager", db)
    app_module.app.config.update(TESTING=True)
    return db


# ============================================================================
# CLASSIFICAÇÃO DA ORIGEM
# ============================================================================

class TestClassificacaoOrigem:
    def test_prefixos_e_predicados(self):
        assert simulated_symbol("BTC", "api") == "SIM_BTC"
        assert simulated_symbol("SOL", "db") == "SIM_SOL"
        assert simulated_symbol("BTC", "synthetic") == "SIM_SYNTHETIC_BTC"

        assert is_simulated("BTC") is False
        assert is_simulated("SIM_BTC") is True
        assert is_simulated("SIM_SYNTHETIC_BTC") is True
        assert is_synthetic("SIM_BTC") is False
        assert is_synthetic("SIM_SYNTHETIC_BTC") is True

    def test_simulacao_sintetica_grava_prefixo_sintetico(self, monkeypatch):
        # O classificador da simulação lê config.ML_SHADOW_MODE na construção;
        # forçar shadow garante trades mesmo se o runtime_config local estiver
        # com ML_SHADOW_MODE=false (toggle feito pelo painel).
        monkeypatch.setattr(config, "ML_SHADOW_MODE", True, raising=False)
        captured = []
        monkeypatch.setattr(
            simular, "salvar_trade", lambda trade: captured.append(trade)
        )
        logging.disable(logging.CRITICAL)
        try:
            simular.run_simulation(
                simular.SimulationMode.RESEARCH,
                ticks=400,
                seed=42,
                data_source="synthetic",
                symbol="BTC",
            )
        finally:
            logging.disable(logging.NOTSET)

        assert captured
        assert all(
            trade["symbol"] == f"{SYNTHETIC_PREFIX}BTC" for trade in captured
        )

    def test_simulacao_com_dados_reais_grava_sim_symbol(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            simular, "salvar_trade", lambda trade: captured.append(trade)
        )
        logging.disable(logging.CRITICAL)
        try:
            # 3000 ticks usam o cache BTCBRL_1m_3000.csv (sem rede).
            simular.run_simulation(
                simular.SimulationMode.RESEARCH,
                ticks=3000,
                seed=42,
                data_source="api",
                symbol="BTC",
            )
        finally:
            logging.disable(logging.NOTSET)

        assert captured
        assert all(
            trade["symbol"] == f"{SIMULATED_PREFIX}BTC" for trade in captured
        )


# ============================================================================
# TREINAMENTO ML
# ============================================================================

class TestTreinoML:
    def test_sim_btc_entra_e_sim_sintetico_e_ignorado(self, monkeypatch, tmp_path):
        path = tmp_path / "training.db"
        symbols = [
            "BTC",
            "SIM_BTC",
            "SIM_SYNTHETIC_BTC",
            "SIM_SOL",
            "SIM_SYNTHETIC_SOL",
        ]
        _make_training_db(path, symbols)
        monkeypatch.setattr(ml_training, "db_manager", _FakeDB(path))

        df = ml_training.MLTrainer(db_path=path).load_trade_history()

        assert set(df["symbol"]) == {"BTC", "SIM_BTC", "SIM_SOL"}
        assert "SIM_BTC" in set(df["symbol"])
        assert not any(
            is_synthetic(symbol) for symbol in df["symbol"]
        )


# ============================================================================
# SALA DE CONTROLE
# ============================================================================

class TestSalaDeControle:
    def test_api_live_oculta_todos_os_sim(self, live_db):
        response = app_module.app.test_client().get("/api/live")

        assert response.status_code == 200
        body = response.get_json()
        symbols = [trade["symbol"] for trade in body["recent_trades"]]

        assert set(symbols) == {"BTC", "USD"}
        assert not any(is_simulated(symbol) for symbol in symbols)
        assert body["kpis"]["trade_count"] == 2
        assert body["kpis"]["win_rate"] == 1.0
        assert body["kpis"]["avg_pnl"] == pytest.approx(8.0)

    def test_api_status_separa_amostras_de_treino(self, live_db):
        response = app_module.app.test_client().get("/api/status")

        assert response.status_code == 200
        ml = response.get_json()["ml"]
        assert ml["trade_count"] == 4  # reais + simulações históricas
        assert ml["training_samples"] == {
            "live": 2,
            "simulated_historical": 2,
            "synthetic_ignored": 1,
        }
