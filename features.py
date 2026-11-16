"""
Contrato único de extração de features para ML.

Este módulo é a ÚNICA fonte de definição de features, usada tanto pelo
treinamento (ml_training.py) quanto pela inferência (ml_classifier.py).
Garante que as dimensões, nomes, ordem e transformações sejam 100%
idênticas entre os dois lados, eliminando o desalinhamento estrutural
encontrado na auditoria forense.

Features (TODAS pré-trade, sem data leakage):
  0. confidence        (float)   confiança da engine (0.0-1.0)
  1. slope             (float)   inclinação da tendência recente
  2. momentum          (float)   momentum de preço (pré-trade)
  3. range_rel         (float)   amplitude relativa recente
  4. volatility_ratio  (float)   razão vol curta / vol longa
  5. regime            (cat)     regime de mercado (ex: TENDENCIA_ALTA)
  6. engine            (cat)     engine que gerou o sinal
  7. action            (cat)     ação sugerida (COMPRA / VENDA / NEUTRO)

Target (treino): pnl_positive (1 se lucro > 0, 0 caso contrário)

Não usamos duration_ticks nem side_signal: ambos só são conhecidos APÓS o
trade ser fechado e gerariam data leakage (look-ahead bias).
"""
from typing import Dict, Any, List, Tuple, Optional
import logging

import pandas as pd
import numpy as np

from logging_config import setup_logging

logger = setup_logging("features", "INFO")

# ---------------------------------------------------------------------------
# Definição rígida do contrato de features
# ---------------------------------------------------------------------------

NUMERIC_FEATURES: List[str] = [
    "confidence",
    "slope",
    "momentum",
    "range_rel",
    "volatility_ratio",
]

CATEGORICAL_FEATURES: List[str] = [
    "regime",
    "engine",
    "action",
]

FEATURE_COLUMNS: List[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES
N_FEATURES: int = len(FEATURE_COLUMNS)

# Mapeamentos de ação para normalizar strings em código numérico (fallback)
ACTION_MAP: Dict[str, int] = {
    "COMPRA": 1,
    "VENDA": -1,
    "NEUTRO": 0,
}


def build_feature_vector(
    suggestion: Dict[str, Any],
    regime_metrics: Dict[str, Any],
) -> List[float]:
    """
    Extrai o vetor de features (8 colunas) a partir de uma sugestão e métricas.

    Todas as features são pré-trade. Não há data leakage.

    Args:
        suggestion: dict com 'confidence', 'engine', 'action' e opcionalmente
                    'regime_metrics'.
        regime_metrics: dict com 'regime', 'slope', 'momentum', 'range_rel',
                        'volatility_ratio'.

    Returns:
        Lista com N_FEATURES valores na ordem de FEATURE_COLUMNS.
    """
    rm = regime_metrics or {}

    vector: List[float] = [
        float(suggestion.get("confidence", 0.0)),
        float(rm.get("slope", 0.0)),
        float(rm.get("momentum", 0.0)),
        float(rm.get("range_rel", 0.0)),
        float(rm.get("volatility_ratio", 0.0)),
        float(0.0),  # placeholder regime (categórico, preenchido abaixo como str)
        float(0.0),  # placeholder engine (categórico)
        float(0.0),  # placeholder action (categórico)
    ]
    # Os campos categóricos são mantidos como strings no DataFrame de treino.
    # Aqui retornamos floats para compatibilidade com pipelines legados; o
    # DataFrame de treino reconstrói as strings a partir dos campos originais.
    return vector


def build_feature_row(
    suggestion: Dict[str, Any],
    regime_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Retorna uma linha (dict) com todas as features na ordem do contrato.

    Útil para montar DataFrames de treino e inferência com tipos corretos
    (numéricas como float, categóricas como str).

    Args:
        suggestion: dict com 'confidence', 'engine', 'action'.
        regime_metrics: dict com 'regime', 'slope', 'momentum', 'range_rel',
                        'volatility_ratio'.

    Returns:
        Dict com chaves exatamente iguais a FEATURE_COLUMNS.
    """
    rm = regime_metrics or {}
    action = suggestion.get("action", "NEUTRO")

    return {
        "confidence": float(suggestion.get("confidence", 0.0)),
        "slope": float(rm.get("slope", 0.0)),
        "momentum": float(rm.get("momentum", 0.0)),
        "range_rel": float(rm.get("range_rel", 0.0)),
        "volatility_ratio": float(rm.get("volatility_ratio", 0.0)),
        "regime": str(rm.get("regime", "DESCONHECIDO")),
        "engine": str(suggestion.get("engine", "UNKNOWN")),
        "action": str(action),
    }


def build_training_frame(
    df: pd.DataFrame,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
    """
    Constrói X (features) e y (target) a partir do histórico de trades.

    Este é o contrato ÚNICO de treino: mesma ordem e nomes de colunas que
    build_feature_row, sem duration_ticks nem side_signal.

    Colunas esperadas em df:
        confidence, entry_regime, engine, pnl, regime, action (ou side),
        slope, momentum, range_rel, volatility_ratio (opcionais, preenchidos
        com 0.0 se ausentes).

    Returns:
        (X, y) ou (None, None) se dados insuficientes.
    """
    if df is None or df.empty:
        logger.warning("DataFrame vazio, não há dados para features")
        return None, None

    df = df.copy()

    # Normalizar 'side' para 'action' se necessário
    if "action" not in df.columns and "side" in df.columns:
        df["action"] = df["side"].map({"COMPRA": "COMPRA", "VENDA": "VENDA"}).fillna("NEUTRO")

    # Validar colunas mínimas
    required = ["confidence", "entry_regime", "engine", "pnl", "action"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.error(f"Colunas faltando no DataFrame: {missing}")
        return None, None

    # Preencher features numéricas opcionais
    for col, default in (
        ("slope", 0.0),
        ("momentum", 0.0),
        ("range_rel", 0.0),
        ("volatility_ratio", 0.0),
    ):
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    # Preencher categóricas
    df["entry_regime"] = df["entry_regime"].fillna("DESCONHECIDO").astype(str)
    df["engine"] = df["engine"].fillna("UNKNOWN").astype(str)
    df["action"] = df["action"].fillna("NEUTRO").astype(str)
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.5)

    # Renomear entry_regime -> regime para alinhar com o contrato de inferência
    df = df.rename(columns={"entry_regime": "regime"})

    # Garantir ordem exata das colunas
    X = df[FEATURE_COLUMNS].copy()
    # Categóricas como str para o OneHotEncoder
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype(str)
    for col in NUMERIC_FEATURES:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)

    y = (df["pnl"] > 0).astype(int)

    logger.debug(
        f"Frame de treino construído: {len(X)} amostras, "
        f"{len(NUMERIC_FEATURES)} numéricas + {len(CATEGORICAL_FEATURES)} categóricas"
    )
    return X, y
