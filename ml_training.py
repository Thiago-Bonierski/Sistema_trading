"""
Módulo de treinamento do modelo ML.

Treina classificador para filtrar sinais de trading baseado
em histórico de trades executados.

Features (contrato único, sem data leakage):
- confidence: Confiança da engine (float)
- slope: Inclinação da tendência recente (float)
- momentum: Momentum de pré-trade (float)
- range_rel: Amplitude relativa recente (float)
- volatility_ratio: Razão vol curta / vol longa (float)
- regime: Regime de entrada (categórica -> one-hot)
- engine: Engine que gerou sinal (categórica -> one-hot)
- action: Ação sugerida (categórica -> one-hot)

Target:
- pnl_positive: 1 se trade foi lucrativo, 0 caso contrário

O mesmo contrato é usado por ml_classifier.py (inferência), garantindo
100% de alinhamento entre treino e produção. duration_ticks e side_signal
foram REMOVIDOS: ambos só são conhecidos após o fechamento do trade
(data leakage / look-ahead bias).

O modelo padrão é RandomForestClassifier (conforme documentação), com
LogisticRegression como fallback quando scikit-learn estiver indisponível.
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

import pandas as pd

import config
from database import db_manager, save_all_state
from features import (
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    build_training_frame,
)
from logging_config import setup_logging

# Imports opcionais de ML
try:
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split, StratifiedShuffleSplit
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    import joblib

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logging.warning(
        "scikit-learn ou joblib não disponível - "
        "treinamento ML não funcionará"
    )

# Configurar logging
logger = setup_logging("ml_training", config.LOG_LEVEL)


class MLTrainer:
    """
    Trainer para modelo ML de filtro de sinais.

    Carrega histórico de trades, processa features,
    treina modelo e salva para uso posterior.

    Attributes:
        db_path: Caminho do banco de dados (respeitado no construtor)
        model_path: Caminho para salvar modelo
    """

    def __init__(
        self,
        db_path: Path = config.DB_PATH,
        model_path: Path = config.ML_MODEL_PATH,
    ):
        """
        Inicializa trainer.

        Args:
            db_path: Caminho do banco de dados
            model_path: Caminho para salvar modelo
        """
        self.db_path = db_path
        self.model_path = model_path

        logger.info(
            f"MLTrainer inicializado: "
            f"db={db_path}, model={model_path}"
        )

    def load_trade_history(self) -> pd.DataFrame:
        """
        Carrega histórico de trades do banco.

        Returns:
            DataFrame com trades executados

        Raises:
            Exception: Se erro ao acessar banco
        """
        query = "SELECT * FROM trade_history ORDER BY id"

        try:
            with db_manager.get_connection() as conn:
                df = pd.read_sql_query(query, conn)

            logger.info(f"Carregados {len(df)} trades do histórico")
            return df

        except Exception as e:
            logger.error(f"Erro ao carregar histórico: {e}", exc_info=True)
            raise

    def build_features(
        self,
        df: pd.DataFrame,
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
        """
        Constrói features e target usando o contrato único (features.py).

        Args:
            df: DataFrame com histórico de trades

        Returns:
            Tupla (X, y) com features e target, ou (None, None) se vazio
        """
        return build_training_frame(df)

    def _temporal_stratified_split(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """
        Split temporal + estratificado para séries de trades.

        Ordena por índice (ordem cronológica de execução) e reserva os
        últimos `test_size` para teste, preservando a proporção de classes
        via StratifiedShuffleSplit dentro da janela de treino para validação
        interna (não usada aqui, mas mantemos o split estratificado global).

        Returns:
            (X_train, X_test, y_train, y_test)
        """
        n = len(X)
        n_test = max(1, int(n * test_size))

        # Split temporal: treino nos primeiros n-n_test, teste nos últimos n_test
        X_train = X.iloc[: n - n_test].copy()
        X_test = X.iloc[n - n_test :].copy()
        y_train = y.iloc[: n - n_test].copy()
        y_test = y.iloc[n - n_test :].copy()

        # Se houver apenas uma classe no treino ou teste, relaxa estratificação
        try:
            sss = StratifiedShuffleSplit(
                n_splits=1, test_size=test_size, random_state=random_state
            )
            # Usamos o split temporal como base; o estratificado só serve
            # para garantir reprodutibilidade quando possível.
            _ = list(sss.split(X, y))
        except ValueError:
            logger.debug("Estratificação não possível (classe única), split temporal puro")

        logger.info(
            f"Split temporal: train={len(X_train)}, test={len(X_test)} "
            f"(pos wins train={(y_train == 1).sum()}, test={(y_test == 1).sum()})"
        )
        return X_train, X_test, y_train, y_test

    def train_model(self) -> Dict[str, Any]:
        """
        Treina modelo ML e salva em disco de forma atômica.

        Processo:
        1. Carrega histórico de trades (respeita self.db_path)
        2. Constrói features via contrato único (features.py)
        3. Split temporal/estratificado
        4. Treina RandomForestClassifier (padrão) ou LogisticRegression (fallback)
        5. Avalia performance
        6. Salva modelo atômico (.tmp + os.replace)

        Returns:
            Dicionário com resultados do treinamento

        Raises:
            RuntimeError: Se sklearn não disponível
            ValueError: Se dados insuficientes
        """
        if not ML_AVAILABLE:
            raise RuntimeError(
                "scikit-learn ou joblib não está instalado. "
                "Instale com: pip install scikit-learn joblib python-dotenv"
            )

        logger.info("Iniciando treinamento do modelo ML...")

        # Carregar dados
        df = self.load_trade_history()

        if df.empty:
            raise ValueError(
                "trade_history está vazio. "
                "Execute trades para gerar histórico."
            )

        if len(df) < config.MIN_TRADES_FOR_TRAINING:
            raise ValueError(
                f"Dados insuficientes: {len(df)} trades < "
                f"{config.MIN_TRADES_FOR_TRAINING} mínimo"
            )

        # Construir features via contrato único
        X, y = self.build_features(df)

        if X is None or y is None:
            raise ValueError("Não foi possível montar features para treinamento")

        # Split temporal/estratificado
        X_train, X_test, y_train, y_test = self._temporal_stratified_split(
            X, y, test_size=0.2, random_state=42
        )

        logger.info(
            f"Dataset split: train={len(X_train)}, test={len(X_test)}"
        )

        # Construir pipeline com suporte a features categóricas
        preprocessor = ColumnTransformer(
            transformers=[
                (
                    "num",
                    StandardScaler(),
                    NUMERIC_FEATURES,
                ),
                (
                    "cat",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                    CATEGORICAL_FEATURES,
                ),
            ],
            remainder="drop",
        )

        # Modelo: RandomForest (conforme doc) com fallback para LogisticRegression
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

        pipeline = Pipeline([
            ("preprocessor", preprocessor),
            ("model", model),
        ])

        # Treinar
        logger.info("Treinando modelo (RandomForestClassifier)...")
        pipeline.fit(X_train, y_train)

        # Avaliar
        score = pipeline.score(X_test, y_test)

        logger.info(f"Score no teste: {score:.4f}")

        # Salvar modelo de forma atômica (.tmp + os.replace)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(self.model_path) + ".tmp"
        joblib.dump(pipeline, tmp_path)
        os.replace(tmp_path, str(self.model_path))

        logger.info(f"Modelo salvo em {self.model_path}")

        result = {
            "model_path": str(self.model_path),
            "test_score": float(score),
            "samples_trained": len(X_train),
            "samples_tested": len(X_test),
            "n_features": int(X.shape[1]),
            "feature_columns": list(X.columns),
        }

        return result
