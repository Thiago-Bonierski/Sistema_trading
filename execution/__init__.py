"""
Camada de execução do sistema.

O `DecisionPipeline` continua puro: ele apenas decide OPEN/CLOSE/HOLD.
Esta pacote concentrado em `execution` traduz essas intenções em ordens,
trocando o adaptador ativo sem tocar na lógica de decisão.

- PAPER: simulação local, nenhuma ordem sai do processo.
- TESTNET: Binance Spot Testnet (sandbox) via ccxt.
- LIVE: Binance Spot real, exigindo trava dupla (ALLOW_LIVE_TRADING).

Resiliência: se a TESTNET estiver fora do ar (timeout, erro de rede ou falha
ao carregar mercados), a fábrica devolve um `FallbackPaperAdapter` em vez de
quebrar a inicialização. O estado é exposto ao painel em
`GET /api/execution/status` → `testnet`.
"""

import logging
from typing import Any, Dict, Optional

from .binance_executor import (
    VALID_EXECUTION_MODES,
    BinanceCcxtAdapter,
    ExecutionAdapter,
    FallbackPaperAdapter,
    PaperExecutionAdapter,
    is_network_failure,
)

logger = logging.getLogger("execution")

__all__ = [
    "VALID_EXECUTION_MODES",
    "ExecutionAdapter",
    "ExecutionSecurityError",
    "FallbackPaperAdapter",
    "PaperExecutionAdapter",
    "BinanceCcxtAdapter",
    "create_execution_adapter",
    "validate_execution_mode",
    "validate_mode_switch",
    "testnet_status_payload",
    "is_network_failure",
]


class ExecutionSecurityError(PermissionError):
    """Lançada quando uma troca de modo viola a trava de segurança."""


def validate_execution_mode(mode=None) -> str:
    """Normaliza e valida o modo, aplicando a trava dupla do LIVE."""
    import config

    requested = str(mode or config.EXECUTION_MODE).strip().upper()
    if requested not in VALID_EXECUTION_MODES:
        raise ValueError(
            f"EXECUTION_MODE inválido: {requested!r}. "
            f"Use um de {', '.join(VALID_EXECUTION_MODES)}."
        )
    if requested == "LIVE" and not config.ALLOW_LIVE_TRADING:
        raise ExecutionSecurityError(
            "Modo LIVE bloqueado: defina ALLOW_LIVE_TRADING=True no .env "
            "e reinicie o serviço."
        )
    return requested


def create_execution_adapter(mode=None) -> ExecutionAdapter:
    """
    Fábrica do adaptador ativo. Nunca faz chamadas de rede no PAPER.

    Para TESTNET/LIVE, valida a conexão e os mercados antes de devolver o
    adaptador. Qualquer falha vira fallback PAPER com motivo registrado —
    o boot do motor e do painel nunca dependem da Binance estar no ar.
    """
    requested = validate_execution_mode(mode)
    if requested == "PAPER":
        return PaperExecutionAdapter()

    try:
        adapter = BinanceCcxtAdapter(mode=requested)
        probe = adapter.test_connection()
    except Exception as exc:  # rede, ccxt ausente, credenciais, qualquer coisa
        reason = f"{type(exc).__name__}: {exc}"
        logger.error(
            "⚠️ %s indisponível na inicialização (%s). "
            "Operando em fallback PAPER.", requested, reason,
        )
        return FallbackPaperAdapter(reason, requested_mode=requested)

    if not probe.get("ok"):
        kind = probe.get("error_type") or "ExchangeError"
        detail = probe.get("error") or "falha ao verificar mercados/saldos"
        reason = f"{kind}: {detail}"
        logger.warning(
            "⚠️ %s indisponível na verificação inicial (%s). "
            "Operando em fallback PAPER.", requested, reason,
        )
        return FallbackPaperAdapter(reason, requested_mode=requested)

    logger.info("✅ %s verificada e disponível.", requested)
    return adapter


TESTNET_LABELS = {
    "online": "Online",
    "unavailable": "Indisponível (operando em fallback PAPER)",
    "disabled": "Desativada",
}


def testnet_status_payload(
    adapter: ExecutionAdapter, status: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Resume o estado da Testnet para o painel (3 estados apenas)."""
    info = status if isinstance(status, dict) else {}
    if getattr(adapter, "mode", "PAPER") == "TESTNET" and not info.get("fallback"):
        state = "online"
    elif str(info.get("testnet_state") or "") == "unavailable" or info.get("fallback"):
        state = "unavailable"
    else:
        state = "disabled"

    return {
        "state": state,
        "label": TESTNET_LABELS[state],
        "online": state == "online",
        "active": state == "online",
        "fallback": state == "unavailable",
        "reason": info.get("fallback_reason") if state == "unavailable" else None,
    }


def validate_mode_switch(current, requested, open_positions, allow_live=None) -> tuple:
    """
    Valida uma troca de modo sem efeito colateral.

    Returns:
        (permitido: bool, motivo: str | None)
    """
    import config

    atual = str(current).strip().upper()
    try:
        novo = str(requested).strip().upper()
    except Exception:
        return False, "Modo inválido."

    if novo not in VALID_EXECUTION_MODES:
        return False, (
            f"Modo inválido: {requested!r}. "
            f"Use PAPER ou TESTNET (LIVE exige trava dupla no .env)."
        )
    if novo == atual:
        return True, None
    if open_positions:
        return False, (
            "Feche as posições abertas antes de trocar o modo de execução."
        )
    if novo == "LIVE":
        permitido = (
            config.ALLOW_LIVE_TRADING if allow_live is None else bool(allow_live)
        )
        if not permitido:
            return False, (
                "Modo LIVE bloqueado: defina ALLOW_LIVE_TRADING=True no .env."
            )
    return True, None
