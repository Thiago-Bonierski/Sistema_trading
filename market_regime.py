"""
Análise de regime de mercado.

Detecta o tipo de mercado (tendência, consolidação, alta volatilidade)
baseado em métricas técnicas de preço.
"""
from typing import Dict, Any
import logging

import pandas as pd

import config
from config import is_close

logger = logging.getLogger(__name__)

REGIMES = (
    "TENDENCIA_ALTA",
    "TENDENCIA_BAIXA",
    "CONSOLIDACAO",
    "TRANSICAO",
    "ALTA_VOLATILIDADE",
)


def analyze_regime(prices: pd.Series) -> Dict[str, Any]:
    """
    Analisa regime de mercado baseado em série histórica de preços.
    
    Identifica o tipo de mercado atual usando múltiplas métricas:
    - Slope: direção da tendência
    - Range: amplitude de variação
    - Volatilidade: instabilidade do mercado
    - Momentum: força do movimento
    - Persistência: consistência da direção
    
    Args:
        prices: Série pandas com preços históricos (mais recente primeiro)
        
    Returns:
        Dicionário com regime detectado e métricas calculadas:
        {
            'regime': str,  # TENDENCIA_ALTA, TENDENCIA_BAIXA, etc
            'slope': float,
            'range_rel': float,
            'volatility': float,
            'volatility_ratio': float,
            'momentum': float,
            'media_curta': float,
            'media_longa': float,
            'trend_up_persist': bool,
            'trend_down_persist': bool,
            'persistence_slopes': List[float]
        }
    """
    prices = prices.reset_index(drop=True)

    if len(prices) < config.MIN_HISTORY_FOR_REGIME:
        logger.debug(
            f"Dados insuficientes para análise: {len(prices)} < "
            f"{config.MIN_HISTORY_FOR_REGIME}"
        )
        return {
            "regime": "AGUARDANDO",
            "slope": 0.0,
            "range_rel": 0.0,
            "volatility": 0.0,
            "volatility_ratio": 0.0,
            "momentum": 0.0,
        }

    current = prices.iloc[0]
    recent = prices.iloc[:10]
    short_trend = prices.iloc[:15]
    previous_trend = prices.iloc[15:30]

    media_curta = recent.mean()
    media_longa_atual = short_trend.mean()
    media_longa_passada = previous_trend.mean()

    # Proteção contra divisão por zero
    if is_close(media_longa_passada, 0.0):
        slope = 0.0
    else:
        slope = (media_longa_atual - media_longa_passada) / media_longa_passada
    
    if is_close(current, 0.0):
        range_rel = 0.0
    else:
        range_rel = (recent.max() - recent.min()) / current

    returns = prices.pct_change().abs().dropna()
    
    # Proteção para séries muito curtas ou vazias
    if len(returns) >= 10:
        short_volatility = returns.rolling(10).std().iloc[9]
    else:
        short_volatility = 0.0
    
    if len(returns) >= 20:
        long_volatility = returns.rolling(20).std().iloc[19]
    else:
        long_volatility = 0.0
    
    volatility_ratio = short_volatility / long_volatility if long_volatility and not pd.isna(long_volatility) else 0.0

    # Proteção contra divisão por zero no momentum
    if is_close(prices.iloc[4], 0.0):
        momentum = 0.0
    else:
        momentum = (current - prices.iloc[4]) / prices.iloc[4]

    def slope_for_window(start: int) -> float:
        """
        Calcula slope de uma janela de tempo específica.
        
        Args:
            start: Índice inicial da janela
            
        Returns:
            Slope da janela
        """
        forward = prices.iloc[start:start + 10].mean()
        backward = prices.iloc[start + 10:start + 20].mean()
        if is_close(backward, 0.0):
            return 0.0
        return (forward - backward) / backward

    persistence_slopes = [slope_for_window(i) for i in (0, 5, 10)]
    trend_up_persist = all(
        window > config.SLOPE_THRESHOLD_MEDIUM for window in persistence_slopes
    )
    trend_down_persist = all(
        window < -config.SLOPE_THRESHOLD_MEDIUM for window in persistence_slopes
    )

    # Melhorar detecção de RANGE (CONSOLIDACAO)
    is_range = (
        range_rel < config.RANGE_THRESHOLD and
        abs(slope) < config.SLOPE_THRESHOLD_SMALL and
        not trend_up_persist and not trend_down_persist and
        volatility_ratio < config.VOLATILITY_RATIO_THRESHOLD
    )

    # Melhorar detecção de CHAOS (ALTA_VOLATILIDADE)
    is_chaos = (
        volatility_ratio > config.CHAOS_VOLATILITY_THRESHOLD and
        range_rel > config.CHAOS_RANGE_THRESHOLD and
        abs(momentum) < config.CHAOS_MOMENTUM_THRESHOLD
    )

    if is_range:
        regime = "CONSOLIDACAO"
    elif is_chaos:
        regime = "ALTA_VOLATILIDADE"
    elif trend_up_persist:
        regime = "TENDENCIA_ALTA"
    elif trend_down_persist:
        regime = "TENDENCIA_BAIXA"
    elif slope > config.SLOPE_THRESHOLD_LARGE:
        regime = "TENDENCIA_ALTA"
    elif slope < -config.SLOPE_THRESHOLD_LARGE:
        regime = "TENDENCIA_BAIXA"
    else:
        regime = "TRANSICAO"
    
    logger.debug(f"Regime detectado: {regime} (slope={slope:.4f}, vol_ratio={volatility_ratio:.2f})")

    return {
        "regime": regime,
        "slope": float(slope),
        "range_rel": float(range_rel),
        "volatility": float(short_volatility),
        "volatility_ratio": float(volatility_ratio),
        "momentum": float(momentum),
        "media_curta": float(media_curta),
        "media_longa": float(media_longa_atual),
        "trend_up_persist": bool(trend_up_persist),
        "trend_down_persist": bool(trend_down_persist),
        "persistence_slopes": [float(v) for v in persistence_slopes],
    }
