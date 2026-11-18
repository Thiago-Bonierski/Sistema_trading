"""
Classificação da origem dos trades gravados em ``trade_history``.

Três categorias convivem na mesma tabela:

* ``USD``, ``BTC``, ``ETH``, ``SOL`` — trades reais do motor ao vivo;
* ``SIM_{symbol}`` — simulação com dados históricos reais (``api``/``db``).
  Entra no dataset de treino do ML como amostra histórica legítima;
* ``SIM_SYNTHETIC_{symbol}`` — simulação com preços inventados. É a única
  categoria que o ``MLTrainer`` ignora, para não contaminar o modelo.

Manter os prefixos aqui evita que API, simulador e trainer discordem sobre
o que é ou não amostra válida de treino.
"""
from typing import Optional

SIMULATED_PREFIX = "SIM_"
SYNTHETIC_PREFIX = "SIM_SYNTHETIC_"


def simulated_symbol(symbol: str, source: str) -> str:
    """Nome a gravar em ``trade_history`` para um trade simulado.

    Args:
        symbol: Símbolo simulado (``USD``, ``BTC``, ``SOL``...).
        source: Fonte da simulação (``synthetic``, ``db`` ou ``api``).
    """
    # Aceita tanto o valor textual quanto o enum DataSource usado no simulador.
    source_value = getattr(source, "value", source)
    prefix = (
        SYNTHETIC_PREFIX
        if str(source_value).strip().lower() == "synthetic"
        else SIMULATED_PREFIX
    )
    return f"{prefix}{symbol}"


def is_simulated(symbol: Optional[str]) -> bool:
    """True para qualquer trade de simulação, sintético ou histórico."""
    return bool(symbol) and str(symbol).startswith(SIMULATED_PREFIX)


def is_synthetic(symbol: Optional[str]) -> bool:
    """True apenas para simulações com preços inventados."""
    return bool(symbol) and str(symbol).startswith(SYNTHETIC_PREFIX)
