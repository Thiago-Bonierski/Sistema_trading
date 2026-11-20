"""
Camada de execução do sistema.

O `DecisionPipeline` continua puro: ele apenas decide OPEN/CLOSE/HOLD.
Esta pacote concentrado em `execution` traduz essas intenções em ordens,
trocando o adaptador ativo sem tocar na lógica de decisão.

- PAPER: simulação local, nenhuma ordem sai do processo.
- TESTNET: Binance Spot Testnet (sandbox) via ccxt.
- LIVE: Binance Spot real, exigindo trava dupla (ALLOW_LIVE_TRADING).
"""

from .binance_executor import (
    VALID_EXECUTION_MODES,
    BinanceCcxtAdapter,
    ExecutionAdapter,
    PaperExecutionAdapter,
)

__all__ = [
    "VALID_EXECUTION_MODES",
    "ExecutionAdapter",
    "ExecutionSecurityError",
    "PaperExecutionAdapter",
    "BinanceCcxtAdapter",
    "create_execution_adapter",
    "validate_execution_mode",
    "validate_mode_switch",
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
    """Fábrica do adaptador ativo. Nunca faz chamadas de rede no PAPER."""
    requested = validate_execution_mode(mode)
    if requested == "PAPER":
        return PaperExecutionAdapter()
    return BinanceCcxtAdapter(mode=requested)


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
