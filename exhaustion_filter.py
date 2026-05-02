"""
Filtro de exaustão de movimento.

Detecta quando um movimento de preço está perdendo força,
mesmo que ainda haja sinal de trading ativo.

Critérios de exaustão:
- Momentum alto mas desacelerando
- Rompimento com momentum fraco
- Alta volatilidade sem momentum consistente

Previne entradas em movimentos que estão chegando ao fim.
"""
from typing import Tuple, Dict, Any, Optional
import logging

import pandas as pd

import config
from logging_config import setup_logging

# Configurar logging
logger = setup_logging("exhaustion_filter", "INFO")

# Estado de exaustão por símbolo (cache simples)
_exhaustion_state: Dict[str, bool] = {}


def is_exhausted(symbol: str, regime: str) -> bool:
    """
    Interface simplificada para uso no monitor.
    
    Retorna estado de exaustão baseado em cache.
    Use check_exhaustion() para análise completa.
    
    Args:
        symbol: Símbolo da moeda
        regime: Regime de mercado
        
    Returns:
        True se símbolo está em exaustão
    """
    # Regimes de alto risco sempre retornam False
    # (já são tratados pelo risk_control)
    if regime in ("TRANSICAO", "ALTA_VOLATILIDADE"):
        return False
    
    # Retornar estado cacheado
    return _exhaustion_state.get(symbol, False)


def check_exhaustion(
    prices: pd.Series,
    regime_metrics: Dict[str, Any],
    suggestion: Dict[str, Any],
    symbol: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Verifica se movimento está em exaustão.
    
    Análise detalhada de:
    - Desaceleração de momentum
    - Força de rompimentos
    - Consistência de volatilidade
    
    Args:
        prices: Série histórica de preços
        regime_metrics: Métricas do regime de mercado
        suggestion: Sugestão da engine
        symbol: Símbolo (opcional, para cache)
        
    Returns:
        Tupla (is_exhausted, reason)
    """
    # Apenas verificar sinais ativos
    if suggestion["action"] not in ("COMPRA", "VENDA"):
        _update_cache(symbol, False)
        return False, ""
    
    # Dados insuficientes
    if len(prices) < 12:
        _update_cache(symbol, False)
        return False, ""
    
    # Calcular momentum atual e anterior
    current_momentum = regime_metrics.get("momentum", 0.0)
    
    try:
        previous_momentum = (
            (prices.iloc[5] - prices.iloc[9]) / prices.iloc[9]
        )
    except (IndexError, ZeroDivisionError):
        _update_cache(symbol, False)
        return False, ""
    
    # Calcular desaceleração
    deceleration = abs(previous_momentum) - abs(current_momentum)
    
    # CRITÉRIO 1: Momentum alto mas desacelerando
    if abs(current_momentum) > 0.025 and deceleration > 0.006:
        reason = "Momentum alto mas desacelerando"
        logger.info(
            f"Exaustão detectada ({symbol}): {reason} "
            f"(momentum={current_momentum:.4f}, decel={deceleration:.4f})"
        )
        _update_cache(symbol, True)
        return True, reason
    
    # CRITÉRIO 2: Rompimento com momentum fraco
    range_rel = regime_metrics.get("range_rel", 0.0)
    if abs(current_momentum) < 0.008 and range_rel > 0.0045:
        reason = "Rompimento potencial mas momentum fraco"
        logger.info(
            f"Exaustão detectada ({symbol}): {reason} "
            f"(momentum={current_momentum:.4f}, range={range_rel:.4f})"
        )
        _update_cache(symbol, True)
        return True, reason
    
    # CRITÉRIO 3: Alta volatilidade sem momentum consistente
    volatility_ratio = regime_metrics.get("volatility_ratio", 0.0)
    if volatility_ratio > 2.5 and abs(current_momentum) < 0.012:
        reason = "Volatilidade alta sem momentum confiável"
        logger.info(
            f"Exaustão detectada ({symbol}): {reason} "
            f"(vol_ratio={volatility_ratio:.2f}, momentum={current_momentum:.4f})"
        )
        _update_cache(symbol, True)
        return True, reason
    
    # Sem exaustão detectada
    _update_cache(symbol, False)
    return False, ""


def _update_cache(symbol: Optional[str], exhausted: bool) -> None:
    """
    Atualiza cache de estado de exaustão.
    
    Args:
        symbol: Símbolo da moeda (pode ser None)
        exhausted: Estado de exaustão
    """
    if symbol:
        _exhaustion_state[symbol] = exhausted


def reset_exhaustion_state(symbol: Optional[str] = None) -> None:
    """
    Reseta estado de exaustão.
    
    Args:
        symbol: Símbolo específico ou None para resetar todos
    """
    global _exhaustion_state
    
    if symbol:
        _exhaustion_state.pop(symbol, None)
        logger.debug(f"Estado de exaustão resetado para {symbol}")
    else:
        _exhaustion_state.clear()
        logger.debug("Estado de exaustão resetado para todos os símbolos")


def get_exhaustion_state() -> Dict[str, bool]:
    """
    Retorna estado de exaustão de todos os símbolos.
    
    Returns:
        Dicionário {symbol: is_exhausted}
    """
    return _exhaustion_state.copy()
