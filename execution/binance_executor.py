"""
Adaptadores de execução: Paper (local) e Binance Spot via ccxt.

Contrato único para o motor:

    adapter.get_balances() -> dict
    adapter.execute_order(side, symbol, amount_brl, current_price) -> dict
    adapter.test_connection() -> dict
    adapter.status() -> dict

Nenhum adaptador altera o `DecisionPipeline`: as ordens são efeitos colaterais
disparados pelo driver `monitor.py` depois que a decisão foi tomada.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import config
from logging_config import setup_logging

logger = setup_logging("execution", config.LOG_LEVEL)

try:  # pragma: no cover - ccxt é dependência declarada no requirements.txt
    import ccxt
    from ccxt import BaseError, ExchangeError, InsufficientFunds, NetworkError
except ImportError:  # pragma: no cover - mantém importável sem a dependência
    ccxt = None

    class BaseError(Exception):
        pass

    class ExchangeError(BaseError):
        pass

    class InsufficientFunds(ExchangeError):
        pass

    class NetworkError(BaseError):
        pass


VALID_EXECUTION_MODES = ("PAPER", "TESTNET", "LIVE")

# Par preferido em BRL e alternativa em USDT na Spot Testnet.
# USD é o ativo interno USDT/BRL: não existe fallback USDT/USDT, então o
# adaptador reporta "par indisponível" se o BRL não existir na conta.
_PRIMARY_MARKETS = {
    "BTC": "BTC/BRL",
    "SOL": "SOL/BRL",
    "ETH": "ETH/BRL",
    "USD": "USDT/BRL",
}
_BALANCE_CURRENCIES = ("BRL", "USDT", "BTC", "SOL", "ETH")


def market_candidates(symbol: str) -> List[str]:
    """Lista pares candidatos, com fallback automático para USDT."""
    primary = _PRIMARY_MARKETS.get(str(symbol).strip().upper())
    if not primary:
        return []

    candidates = [primary]
    base = primary.split("/")[0]
    fallback = f"{base}/USDT"
    # USDT/BRL -> USDT/USDT não é um mercado válido.
    if fallback != primary and fallback.split("/")[1] != base:
        candidates.append(fallback)
    return candidates


def normalize_side(side: str) -> Optional[str]:
    """Converte COMPRA/VENDA (interno) em buy/sell (ccxt)."""
    value = str(side or "").strip().upper()
    if value in ("COMPRA", "BUY", "B"):
        return "buy"
    if value in ("VENDA", "SELL", "S"):
        return "sell"
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if value is None:
            continue
        number = _as_float(value, default=float("nan"))
        if number == number and number > 0:
            return number
    return None


def _extract_fee(order: Dict[str, Any], amount_brl: float) -> Tuple[float, str, bool]:
    """Extrai (custo, moeda, estimado) da resposta da exchange."""
    fee = order.get("fee")
    if isinstance(fee, dict):
        cost = _as_float(fee.get("cost"), 0.0)
        currency = str(fee.get("currency") or "")
        if cost > 0:
            return cost, currency, False

    fees = order.get("fees")
    if isinstance(fees, list) and fees:
        costs = [
            _as_float(item.get("cost"), 0.0)
            for item in fees
            if isinstance(item, dict)
        ]
        if any(cost > 0 for cost in costs):
            currencies = {
                str(item.get("currency") or "")
                for item in fees
                if isinstance(item, dict)
            }
            return sum(costs), "/".join(sorted(c for c in currencies if c)), False

    # A resposta pode não trazer `fee`: usa a taxa configurada como estimativa
    # explícita, sem fingir que veio da exchange.
    return _as_float(amount_brl, 0.0) * config.TRADING_FEE_PCT, "BRL", True


def _timed(call, *args, **kwargs):
    started = time.perf_counter()
    result = call(*args, **kwargs)
    latency = round((time.perf_counter() - started) * 1000, 2)
    return result, latency


class ExecutionAdapter(ABC):
    """Interface comum a todas as formas de execução."""

    mode = "BASE"

    @abstractmethod
    def get_balances(self) -> Dict[str, Any]:
        """Saldos atuais, normalizados por moeda."""

    @abstractmethod
    def execute_order(
        self, side: str, symbol: str, amount_brl: float, current_price: float
    ) -> Dict[str, Any]:
        """Executa uma ordem a mercado e devolve o preenchimento real."""

    def test_connection(self) -> Dict[str, Any]:
        return {"ok": True, "mode": self.mode, "simulated": True}

    def status(self) -> Dict[str, Any]:
        return {"mode": self.mode, "connected": True, "exchange": "local"}


class PaperExecutionAdapter(ExecutionAdapter):
    """
    Execução simulada local: nunca cria ordem na exchange.

    Mantém o comportamento histórico do motor. O retorno usa o mesmo formato
    do adaptador real para que o driver e a API não precisem de `if mode`.
    """

    mode = "PAPER"

    def __init__(self, equity_manager=None):
        self.equity_manager = equity_manager
        self.orders: List[Dict[str, Any]] = []

    def get_balances(self) -> Dict[str, Any]:
        equity = 0.0
        if self.equity_manager is not None:
            equity = _as_float(
                getattr(self.equity_manager, "current_equity", 0.0), 0.0
            ) or _as_float(
                getattr(self.equity_manager, "initial_capital", 0.0), 0.0
            )
        balances = {currency: 0.0 for currency in _BALANCE_CURRENCIES}
        balances["BRL"] = round(equity, 2)
        return {
            "ok": True,
            "mode": self.mode,
            "connected": True,
            "simulated": True,
            "latency_ms": 0.0,
            "balances": balances,
        }

    def execute_order(
        self, side: str, symbol: str, amount_brl: float, current_price: float
    ) -> Dict[str, Any]:
        side_ccxt = normalize_side(side)
        notional = max(0.0, _as_float(amount_brl))
        price = _as_float(current_price)
        result = {
            "ok": True,
            "paper": True,
            "mode": self.mode,
            "symbol": str(symbol).strip().upper(),
            "market": "LOCAL",
            "side": side_ccxt or str(side).upper(),
            "requested_amount_brl": round(notional, 2),
            "amount": round(notional / price, 8) if price > 0 else 0.0,
            "average_price": price,
            "fee": round(notional * config.TRADING_FEE_PCT, 4),
            "fee_currency": "BRL",
            "fee_estimated": True,
            "cost": round(notional, 4),
            "order_id": None,
        }
        self.orders.append(result)
        logger.info(
            "📝 PAPER ordem simulada: %s %s R$ %.2f @ %.4f",
            result["side"], result["symbol"], notional, price,
        )
        return result

    def test_connection(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "mode": self.mode,
            "exchange": "local",
            "sandbox": False,
            "simulated": True,
            "latency_ms": 0.0,
            "balances": self.get_balances()["balances"],
            "pairs": [],
        }

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "exchange": "local",
            "sandbox": False,
            "connected": True,
            "simulated": True,
            "latency_ms": 0.0,
            "last_error": None,
            "balances": self.get_balances()["balances"],
            "available_pairs": [],
        }


class BinanceCcxtAdapter(ExecutionAdapter):
    """Binance Spot (Testnet sandbox ou LIVE com trava dupla) via ccxt."""

    mode = "TESTNET"

    def __init__(self, mode: str = "TESTNET", exchange=None, markets=None):
        requested = str(mode or "TESTNET").strip().upper()
        if requested not in ("TESTNET", "LIVE"):
            raise ValueError(
                f"BinanceCcxtAdapter aceita apenas TESTNET/LIVE, recebeu {requested!r}"
            )
        if requested == "LIVE" and not config.ALLOW_LIVE_TRADING:
            raise PermissionError(
                "LIVE bloqueado: ALLOW_LIVE_TRADING deve ser True no .env"
            )
        if exchange is None and ccxt is None:
            raise RuntimeError(
                "ccxt não está instalado. Execute: pip install -r requirements.txt"
            )

        self.mode = requested
        self.exchange = exchange if exchange is not None else self._build_exchange()
        self._markets = markets
        self._balances: Dict[str, float] = {}
        self._latency_ms: Optional[float] = None
        self._last_error: Optional[str] = None

    # ---------------------------------------------------------------- setup
    def _credentials(self) -> Tuple[str, str]:
        if self.mode == "TESTNET":
            return config.BINANCE_TESTNET_API_KEY, config.BINANCE_TESTNET_API_SECRET
        return config.BINANCE_API_KEY, config.BINANCE_API_SECRET

    def _build_exchange(self):
        api_key, secret = self._credentials()
        exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
                "timeout": 15000,
                "options": {"defaultType": "spot"},
            }
        )
        if self.mode == "TESTNET":
            # Exigência de segurança: a Testnet só é usada em sandbox.
            exchange.set_sandbox_mode(True)
        logger.info(
            "🔗 Binance adaptador pronto: mode=%s sandbox=%s",
            self.mode, self.mode == "TESTNET",
        )
        return exchange

    # -------------------------------------------------------------- helpers
    def _load_markets(self) -> Dict[str, Any]:
        if self._markets is None:
            self._markets = self.exchange.load_markets() or {}
        return self._markets

    def _resolve_market(self, symbol: str) -> Optional[str]:
        try:
            markets = self._load_markets()
        except BaseError as exc:
            logger.error("Falha ao carregar mercados da Binance: %s", exc)
            self._last_error = str(exc)
            return None
        for candidate in market_candidates(symbol):
            if candidate in markets:
                return candidate
        return None

    def available_pairs(self) -> List[str]:
        try:
            markets = self._load_markets()
        except BaseError as exc:
            logger.error("Falha ao listar pares da Binance: %s", exc)
            self._last_error = str(exc)
            return []
        return [
            candidate
            for symbol in _PRIMARY_MARKETS
            for candidate in market_candidates(symbol)
            if candidate in markets
        ]

    def _brl_per_quote(self, quote: str) -> float:
        if quote == "BRL":
            return 1.0
        if quote != "USDT":
            raise ExchangeError(f"Quote {quote} não suportado na conversão de BRL")
        ticker = self.exchange.fetch_ticker("USDT/BRL") or {}
        rate = _first_number(ticker.get("last"), ticker.get("close"))
        if rate is None:
            raise ExchangeError("Sem cotação USDT/BRL para converter o valor em BRL")
        return rate

    def brl_to_amount(
        self, symbol: str, current_price: float, amount_brl: float
    ) -> float:
        """Converte notional em BRL para quantidade do ativo no par resolvido."""
        market = self._resolve_market(symbol)
        if not market:
            raise ExchangeError(
                f"Par indisponível para {symbol} (candidatos: {market_candidates(symbol)})"
            )
        quote = market.split("/")[1]
        price = _as_float(current_price)
        if price <= 0:
            raise ExchangeError(f"Preço inválido para {symbol}: {current_price}")
        rate = self._brl_per_quote(quote)
        return max(0.0, _as_float(amount_brl) / (price * rate))

    def _failure(self, error_type: str, exc: Exception, symbol: str) -> Dict[str, Any]:
        self._last_error = f"{error_type}: {exc}"
        logger.error("❌ Ordem Binance falhou (%s, %s): %s", error_type, symbol, exc)
        return {
            "ok": False,
            "paper": False,
            "mode": self.mode,
            "symbol": str(symbol).strip().upper(),
            "error_type": error_type,
            "error": str(exc),
        }

    # -------------------------------------------------------------- adapter
    def get_balances(self) -> Dict[str, Any]:
        try:
            raw, latency = _timed(self.exchange.fetch_balance)
            self._latency_ms = latency
            self._last_error = None
            totals = raw.get("total") or raw
            balances = {
                currency: round(_as_float(totals.get(currency)), 6)
                for currency in _BALANCE_CURRENCIES
            }
            self._balances = balances
            return {
                "ok": True,
                "mode": self.mode,
                "connected": True,
                "sandbox": self.mode == "TESTNET",
                "latency_ms": latency,
                "balances": balances,
            }
        except (NetworkError, ExchangeError) as exc:
            error_type = "NetworkError" if isinstance(exc, NetworkError) else "ExchangeError"
            self._last_error = f"{error_type}: {exc}"
            logger.error("❌ Falha ao consultar saldo Binance (%s): %s", error_type, exc)
            return {
                "ok": False,
                "mode": self.mode,
                "connected": False,
                "error_type": error_type,
                "error": str(exc),
                "balances": self._balances,
            }

    def execute_order(
        self, side: str, symbol: str, amount_brl: float, current_price: float
    ) -> Dict[str, Any]:
        side_ccxt = normalize_side(side)
        if side_ccxt is None:
            return {
                "ok": False,
                "mode": self.mode,
                "symbol": str(symbol).strip().upper(),
                "error_type": "InvalidSide",
                "error": f"Lado inválido: {side!r} (use COMPRA ou VENDA)",
            }

        try:
            market = self._resolve_market(symbol)
            if not market:
                raise ExchangeError(
                    f"Par indisponível para {symbol} "
                    f"(candidatos: {market_candidates(symbol)})"
                )

            amount = self.brl_to_amount(symbol, current_price, amount_brl)
            precise = _as_float(
                self.exchange.amount_to_precision(market, amount)
            )
            if precise <= 0:
                raise ExchangeError(
                    f"Quantidade abaixo do lote mínimo de {market}: {amount}"
                )

            order = self.exchange.create_market_order(market, side_ccxt, precise) or {}
            average = _first_number(
                order.get("average"), order.get("price")
            )
            if average is None:
                cost = _as_float(order.get("cost"))
                if cost > 0:
                    average = abs(cost) / precise
            fee, fee_currency, estimated = _extract_fee(order, _as_float(amount_brl))

            self._last_error = None
            logger.info(
                "✅ Ordem Binance: %s %s %s @ %.8f | fee %.6f %s | id=%s",
                side_ccxt, precise, market, average or 0.0, fee,
                fee_currency or "?", order.get("id"),
            )
            return {
                "ok": True,
                "paper": False,
                "mode": self.mode,
                "sandbox": self.mode == "TESTNET",
                "symbol": str(symbol).strip().upper(),
                "market": market,
                "side": side_ccxt,
                "requested_amount_brl": round(_as_float(amount_brl), 2),
                "amount": precise,
                "average_price": average,
                "fee": fee,
                "fee_currency": fee_currency,
                "fee_estimated": estimated,
                "cost": _as_float(order.get("cost"), _as_float(amount_brl)),
                "order_id": order.get("id"),
                "raw": order,
            }
        except InsufficientFunds as exc:
            return self._failure("InsufficientFunds", exc, symbol)
        except NetworkError as exc:
            return self._failure("NetworkError", exc, symbol)
        except ExchangeError as exc:
            return self._failure("ExchangeError", exc, symbol)
        except BaseError as exc:
            return self._failure("BaseError", exc, symbol)
        except Exception as exc:  # nunca derruba o motor por causa da exchange
            return self._failure(type(exc).__name__, exc, symbol)

    def test_connection(self) -> Dict[str, Any]:
        try:
            markets, latency = _timed(self._load_markets)
            self._latency_ms = latency
            balances = self.get_balances()
            result = {
                "ok": bool(balances.get("ok")),
                "mode": self.mode,
                "exchange": "binance",
                "sandbox": self.mode == "TESTNET",
                "latency_ms": latency,
                "balances": balances.get("balances", {}),
                "pairs": [
                    candidate
                    for symbol in _PRIMARY_MARKETS
                    for candidate in market_candidates(symbol)
                    if candidate in (markets or {})
                ],
            }
            if not result["ok"]:
                result["error"] = balances.get("error")
                result["error_type"] = balances.get("error_type")
            return result
        except (NetworkError, ExchangeError) as exc:
            error_type = "NetworkError" if isinstance(exc, NetworkError) else "ExchangeError"
            self._last_error = f"{error_type}: {exc}"
            logger.error("❌ Teste de conexão falhou (%s): %s", error_type, exc)
            return {
                "ok": False,
                "mode": self.mode,
                "exchange": "binance",
                "sandbox": self.mode == "TESTNET",
                "error_type": error_type,
                "error": str(exc),
                "balances": self._balances,
                "pairs": [],
            }

    def status(self) -> Dict[str, Any]:
        """Status sem chamada de rede: usa o último saldo consultado."""
        return {
            "mode": self.mode,
            "exchange": "binance",
            "sandbox": self.mode == "TESTNET",
            "connected": bool(self._balances),
            "latency_ms": self._latency_ms,
            "last_error": self._last_error,
            "balances": dict(self._balances),
            # Só lista pares se os mercados já estiverem em cache: status()
            # precisa ser barato o suficiente para o polling do painel.
            "available_pairs": (
                self.available_pairs() if self._markets is not None else []
            ),
        }
