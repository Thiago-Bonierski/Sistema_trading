"""
Resiliência da Binance Testnet e backup rápido.

Cobre os 3 estados exibidos na Sala de Controle (Online, Indisponível com
fallback PAPER, Desativada), a degradação em runtime e o endpoint /api/backup.
Tudo com exchange e filesystem falsos — nenhuma chamada de rede.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as app_module
import config
import monitor as monitor_module
from execution import (
    FallbackPaperAdapter,
    create_execution_adapter,
    # Alias para o pytest não coletar a função como teste (nome começa com "test").
    testnet_status_payload as describe_testnet,
)
from execution import binance_executor as executor


class OfflineExchange:
    """Exchange que falha ao carregar mercados, como acontece na queda da API."""

    def __init__(self, error=None):
        self.error = error or executor.NetworkError("timeout ao consultar testnet")
        self.sandbox = None

    def set_sandbox_mode(self, value):
        self.sandbox = value

    def load_markets(self):
        raise self.error

    def fetch_balance(self):
        return {"total": {"BRL": 100.0}}


class OfflineBalanceExchange(OfflineExchange):
    """Mercados OK, mas saldo indisponível (credenciais/API instável)."""

    def load_markets(self):
        return {"BTC/BRL": {}, "USDT/BRL": {}}

    def fetch_balance(self):
        raise executor.ExchangeError("API temporariamente indisponível")


class HealthyExchange(OfflineExchange):
    def load_markets(self):
        return {"BTC/BRL": {}, "USDT/BRL": {}}


def _use_exchange(monkeypatch, exchange):
    monkeypatch.setattr(executor.ccxt, "binance", lambda _params: exchange)


# ============================================================================
# 1) FALLBACK SEGuro NA INICIALIZAÇÃO
# ============================================================================

def test_testnet_offline_no_boot_vira_fallback_paper(monkeypatch):
    exchange = OfflineExchange()
    _use_exchange(monkeypatch, exchange)

    adapter = create_execution_adapter("TESTNET")

    assert isinstance(adapter, FallbackPaperAdapter)
    assert adapter.mode == "PAPER"
    assert adapter.requested_mode == "TESTNET"
    status = adapter.status()
    assert status["testnet_state"] == "unavailable"
    assert status["fallback"] is True
    assert "timeout" in status["fallback_reason"]
    # Nenhuma ordem real pode sair no fallback.
    assert adapter.execute_order("COMPRA", "BTC", 100.0, 60000.0)["paper"] is True


def test_timeout_generico_tambem_cai_no_fallback(monkeypatch):
    _use_exchange(monkeypatch, OfflineExchange(error=RuntimeError("connection reset")))

    adapter = create_execution_adapter("TESTNET")

    assert isinstance(adapter, FallbackPaperAdapter)
    assert "connection reset" in adapter.status()["fallback_reason"]


def test_falha_no_saldo_apos_mercados_tambem_cai_no_fallback(monkeypatch):
    _use_exchange(monkeypatch, OfflineBalanceExchange())

    adapter = create_execution_adapter("TESTNET")

    assert isinstance(adapter, FallbackPaperAdapter)
    assert "indisponível" in adapter.status()["fallback_reason"]


def test_paper_continua_sem_exchange(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("PAPER não pode instanciar ccxt")

    monkeypatch.setattr(executor.ccxt, "binance", explode)
    adapter = create_execution_adapter("PAPER")

    assert adapter.mode == "PAPER"
    assert adapter.status()["testnet_state"] == "disabled"
    assert describe_testnet(adapter)["state"] == "disabled"


# ============================================================================
# 2) ESTADOS DA TESTNET PARA O PAINEL
# ============================================================================

def test_testnet_status_payload_tem_tres_estados():
    online = SimpleNamespace(mode="TESTNET")
    offline = FallbackPaperAdapter("NetworkError: timeout", "TESTNET")
    disabled = SimpleNamespace(mode="PAPER")

    assert describe_testnet(online, {"connected": True}) == {
        "state": "online",
        "label": "Online",
        "online": True,
        "active": True,
        "fallback": False,
        "reason": None,
    }

    unavailable = describe_testnet(offline, offline.status())
    assert unavailable["state"] == "unavailable"
    assert unavailable["label"] == "Indisponível (operando em fallback PAPER)"
    assert unavailable["fallback"] is True
    assert unavailable["reason"]

    assert describe_testnet(disabled)["label"] == "Desativada"


# ============================================================================
# 3) DEGRADAÇÃO EM RUNTIME
# ============================================================================

def test_degradacao_em_runtime_so_em_falha_de_rede(monkeypatch):
    adapter = executor.BinanceCcxtAdapter(exchange=HealthyExchange())
    monkeypatch.setattr(monitor_module, "execution_adapter", adapter)

    changed = monitor_module.degrade_execution_to_paper(
        {"ok": False, "error_type": "NetworkError", "error": "timeout"},
        "teste de conexão",
    )

    assert changed is True
    current = monitor_module.get_execution_adapter()
    assert isinstance(current, FallbackPaperAdapter)
    assert current.status()["testnet_state"] == "unavailable"


def test_erro_de_negocio_nao_degrada_o_modo(monkeypatch):
    adapter = executor.BinanceCcxtAdapter(exchange=HealthyExchange())
    monkeypatch.setattr(monitor_module, "execution_adapter", adapter)

    changed = monitor_module.degrade_execution_to_paper(
        {"ok": False, "error_type": "InsufficientFunds", "error": "saldo insuficiente"},
        "execução de ordem",
    )

    assert changed is False
    assert monitor_module.get_execution_adapter() is adapter


# ============================================================================
# 4) API EXPÕE O ESTADO DA TESTNET
# ============================================================================

@pytest.fixture
def api_client(monkeypatch):
    fallback = FallbackPaperAdapter("NetworkError: timeout", "TESTNET")
    monkeypatch.setattr(app_module, "get_execution_adapter", lambda: fallback)
    monkeypatch.setattr(app_module, "set_execution_adapter", lambda new: new)
    monkeypatch.setattr(app_module.position_manager, "positions", {})
    monkeypatch.setattr(config, "EXECUTION_MODE", "PAPER")
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_api_status_mostra_testnet_indisponivel(api_client):
    body = api_client.get("/api/execution/status").get_json()

    assert body["mode"] == "PAPER"
    assert body["requested_mode"] == "TESTNET"
    assert body["testnet"]["state"] == "unavailable"
    assert body["testnet"]["label"] == "Indisponível (operando em fallback PAPER)"
    assert body["testnet"]["fallback"] is True


def test_api_troca_para_testnet_offline_responde_paper_com_aviso(api_client, monkeypatch):
    fallback = FallbackPaperAdapter("NetworkError: timeout", "TESTNET")
    monkeypatch.setattr(app_module, "create_execution_adapter", lambda _mode: fallback)
    monkeypatch.setattr(config, "EXECUTION_MODE", "PAPER")

    response = api_client.post("/api/execution/mode", json={"mode": "TESTNET"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["mode"] == "PAPER"
    assert body["requested_mode"] == "TESTNET"
    assert body["testnet"]["state"] == "unavailable"
    assert "fallback PAPER" in body["warning"]
    assert config.EXECUTION_MODE == "PAPER"


# ============================================================================
# 5) BACKUP RÁPIDO
# ============================================================================

def test_api_backup_copia_arquivos_e_reporta_ausentes(monkeypatch, tmp_path):
    (tmp_path / "historico.db").write_bytes(b"db")
    (tmp_path / "ml_model.joblib").write_bytes(b"model")
    monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    response = client.post("/api/backup")
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["copied"] == ["historico.db", "ml_model.joblib"]
    assert body["missing"] == ["runtime_config.json"]
    destination = tmp_path / "backups" / body["directory"]
    assert (destination / "historico.db").read_bytes() == b"db"
    assert (destination / "ml_model.joblib").read_bytes() == b"model"
