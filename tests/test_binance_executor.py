"""
Testes do adaptador Binance Spot via ccxt — 100% mockados, sem rede.

Cobre:
- set_sandbox_mode obrigatório na TESTNET;
- trava dupla do modo LIVE;
- conversão BRL -> quantidade com amount_to_precision e leitura de
  preço/taxa reais da resposta;
- tratamento gracioso de InsufficientFunds e NetworkError;
- bloqueio da troca de modo pela API com posição aberta.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as app_module
import config
from execution import (
    ExecutionSecurityError,
    create_execution_adapter,
)
from execution import binance_executor as executor


class FakeExchange:
    """Exchange em memória com a superfície mínima usada pelo adaptador."""

    def __init__(self):
        self.sandbox = None
        self.markets = {
            "BTC/BRL": {},
            "BTC/USDT": {},
            "SOL/BRL": {},
            "USDT/BRL": {},
            "ETH/USDT": {},
        }
        self.balance = {
            "total": {
                "BRL": 1000.0,
                "USDT": 50.0,
                "BTC": 0.1,
                "SOL": 2.0,
                "ETH": 0.0,
            }
        }
        self.tickers = {"USDT/BRL": {"last": 5.0}}
        self.order = None
        self.raise_on_order = None
        self.raise_on_balance = None
        self.calls = []

    def set_sandbox_mode(self, value):
        self.sandbox = value

    def load_markets(self):
        return self.markets

    def fetch_balance(self):
        if self.raise_on_balance:
            raise self.raise_on_balance
        return self.balance

    def fetch_ticker(self, symbol):
        return self.tickers[symbol]

    def amount_to_precision(self, symbol, amount):
        self.calls.append(("amount_to_precision", symbol, amount))
        return f"{amount:.6f}"

    def create_market_order(self, symbol, side, amount):
        self.calls.append(("create_market_order", symbol, side, amount))
        if self.raise_on_order:
            raise self.raise_on_order
        return self.order or {
            "id": "fake-order",
            "average": 60000.0,
            "fee": {"cost": 0.6, "currency": "BRL"},
            "cost": 600.0,
        }


# ============================================================================
# 1) SANDBOX OBRIGATÓRIO NA TESTNET
# ============================================================================

def test_testnet_obriga_sandbox_e_usa_chaves_da_testnet(monkeypatch):
    exchange = FakeExchange()
    created = {}

    def fake_binance(params):
        created["params"] = params
        return exchange

    monkeypatch.setattr(executor.ccxt, "binance", fake_binance)
    monkeypatch.setattr(config, "BINANCE_TESTNET_API_KEY", "test-key")
    monkeypatch.setattr(config, "BINANCE_TESTNET_API_SECRET", "test-secret")

    adapter = create_execution_adapter("TESTNET")

    assert adapter.mode == "TESTNET"
    assert exchange.sandbox is True
    assert created["params"]["apiKey"] == "test-key"
    assert created["params"]["secret"] == "test-secret"
    assert created["params"]["options"]["defaultType"] == "spot"


def test_paper_nao_cria_exchange(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("PAPER não pode instanciar ccxt")

    monkeypatch.setattr(executor.ccxt, "binance", explode)
    adapter = create_execution_adapter("PAPER")
    assert adapter.mode == "PAPER"
    assert adapter.execute_order("COMPRA", "BTC", 100.0, 60000.0)["paper"] is True


# ============================================================================
# 2) TRAVA DUPLA DO LIVE
# ============================================================================

def test_live_bloqueado_sem_allow_live_trading(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_LIVE_TRADING", False)

    with pytest.raises(ExecutionSecurityError):
        create_execution_adapter("LIVE")
    with pytest.raises(PermissionError):
        executor.BinanceCcxtAdapter(mode="LIVE", exchange=FakeExchange())


def test_live_permitido_com_trava_explicita(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_LIVE_TRADING", True)
    adapter = executor.BinanceCcxtAdapter(mode="LIVE", exchange=FakeExchange())
    assert adapter.mode == "LIVE"
    assert adapter.exchange.sandbox is None  # LIVE nunca ativa sandbox


# ============================================================================
# 3) CONVERSÃO BRL -> QUANTIDADE E DADOS REAIS DA ORDEM
# ============================================================================

def test_execute_order_converte_brl_e_extrai_preco_e_taxa_reais():
    exchange = FakeExchange()
    exchange.order = {
        "id": "ordem-42",
        "average": 61000.0,
        "fee": {"cost": 0.6, "currency": "BRL"},
        "cost": 610.0,
    }
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.execute_order("COMPRA", "BTC", 100.0, 60000.0)

    assert result["ok"] is True
    assert result["side"] == "buy"
    assert result["market"] == "BTC/BRL"
    assert result["average_price"] == pytest.approx(61000.0)
    assert result["fee"] == pytest.approx(0.6)
    assert result["fee_currency"] == "BRL"
    assert result["fee_estimated"] is False
    assert result["order_id"] == "ordem-42"

    # 100 / 60.000 = 0,001666... -> amount_to_precision arredonda para 6 casas
    precision_call = next(c for c in exchange.calls if c[0] == "amount_to_precision")
    assert precision_call[1] == "BTC/BRL"
    assert precision_call[2] == pytest.approx(100.0 / 60000.0)
    order_call = next(c for c in exchange.calls if c[0] == "create_market_order")
    assert order_call == ("create_market_order", "BTC/BRL", "buy", 0.001667)


def test_fallback_para_usdt_quando_par_brl_nao_existe():
    exchange = FakeExchange()
    exchange.markets = {"BTC/USDT": {}, "USDT/BRL": {}}
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.execute_order("VENDA", "BTC", 100.0, 60000.0)

    assert result["ok"] is True
    assert result["market"] == "BTC/USDT"
    assert result["side"] == "sell"
    # 100 BRL / 5 (USDT/BRL) / 60.000 = 0,000333... BTC
    order_call = next(c for c in exchange.calls if c[0] == "create_market_order")
    assert order_call == ("create_market_order", "BTC/USDT", "sell", 0.000333)


def test_fee_estimativa_quando_exchange_nao_devolve_taxa():
    exchange = FakeExchange()
    exchange.order = {"id": "sem-fee", "average": 100.0}
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.execute_order("COMPRA", "SOL", 100.0, 100.0)

    assert result["fee"] == pytest.approx(100.0 * config.TRADING_FEE_PCT)
    assert result["fee_estimated"] is True


def test_get_balances_e_status_retornam_saldos_da_testnet():
    exchange = FakeExchange()
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    balances = adapter.get_balances()

    assert balances["ok"] is True
    assert balances["connected"] is True
    assert balances["balances"]["BRL"] == pytest.approx(1000.0)
    assert balances["balances"]["BTC"] == pytest.approx(0.1)
    assert adapter.status()["balances"]["SOL"] == pytest.approx(2.0)


# ============================================================================
# 4) EXCEÇÕES ESPECÍFICAS DO CCXT
# ============================================================================

def test_insufficient_funds_e_tratado_sem_propagar():
    exchange = FakeExchange()
    exchange.raise_on_order = executor.InsufficientFunds("saldo insuficiente")
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.execute_order("COMPRA", "BTC", 100.0, 60000.0)

    assert result["ok"] is False
    assert result["error_type"] == "InsufficientFunds"
    assert "saldo insuficiente" in result["error"]


def test_network_error_no_fetch_balance_e_tratado():
    exchange = FakeExchange()
    exchange.raise_on_balance = executor.NetworkError("timeout")
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.get_balances()

    assert result["ok"] is False
    assert result["connected"] is False
    assert result["error_type"] == "NetworkError"
    assert result["balances"] == {}


def test_network_error_na_ordem_nao_trava_o_processo():
    exchange = FakeExchange()
    exchange.raise_on_order = executor.NetworkError("connection reset")
    adapter = executor.BinanceCcxtAdapter(exchange=exchange)

    result = adapter.execute_order("COMPRA", "BTC", 100.0, 60000.0)

    assert result["ok"] is False
    assert result["error_type"] == "NetworkError"


# ============================================================================
# 5) TROCA DE MODO VIA API
# ============================================================================

@pytest.fixture
def api_client(monkeypatch):
    adapter = SimpleNamespace(
        mode="PAPER",
        status=lambda: {"mode": "PAPER", "connected": True, "balances": {}},
    )
    captured = {}

    monkeypatch.setattr(app_module, "get_execution_adapter", lambda: adapter)
    monkeypatch.setattr(
        app_module,
        "set_execution_adapter",
        lambda new: captured.setdefault("adapter", new),
    )
    monkeypatch.setattr(config, "EXECUTION_MODE", "PAPER")
    monkeypatch.setattr(app_module.position_manager, "positions", {})
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), captured


def test_api_bloqueia_troca_de_modo_com_posicao_aberta(api_client, monkeypatch):
    client, captured = api_client
    monkeypatch.setattr(
        app_module.position_manager, "positions", {"BTC": SimpleNamespace()}
    )

    response = client.post("/api/execution/mode", json={"mode": "TESTNET"})

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert "posições abertas" in body["error"]
    assert "adapter" not in captured


def test_api_troca_para_testnet_sem_posicoes(api_client, monkeypatch):
    client, captured = api_client
    novo = SimpleNamespace(
        mode="TESTNET",
        status=lambda: {"mode": "TESTNET", "connected": True, "balances": {}},
    )
    monkeypatch.setattr(app_module, "create_execution_adapter", lambda mode: novo)

    response = client.post("/api/execution/mode", json={"mode": "TESTNET"})

    assert response.status_code == 200
    assert response.get_json()["mode"] == "TESTNET"
    assert captured["adapter"] is novo


def test_api_status_expoe_modo_e_saldos(api_client):
    client, _ = api_client
    response = client.get("/api/execution/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["mode"] == "PAPER"
    assert body["open_positions"] == 0
    assert body["connection"]["connected"] is True
