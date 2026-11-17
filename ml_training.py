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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

import numpy as np
import pandas as pd

import config
from database import db_manager, save_all_state
from features import (
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TRADE_FEATURE_COLUMNS,
    build_training_frame,
    deduplicate_trades,
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
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
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
        threshold: float = config.ML_APPROVAL_THRESHOLD,
    ):
        """
        Inicializa trainer.

        Args:
            db_path: Caminho do banco de dados
            model_path: Caminho para salvar modelo
            threshold: Threshold usado para medir a taxa de aprovação
        """
        self.db_path = db_path
        self.model_path = model_path
        self.threshold = threshold

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
        *,
        require_complete_features: bool = True,
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
        """
        Constrói features e target usando o contrato único (features.py).

        Args:
            df: DataFrame com histórico de trades
            require_complete_features: Exige que as features de mercado
                estejam persistidas (schema v2). O treino de produção nunca
                deve aceitar linhas com features zeradas por ausência.

        Returns:
            Tupla (X, y) com features e target, ou (None, None) se vazio
        """
        return build_training_frame(
            df,
            require_complete_features=require_complete_features,
            deduplicate=False,  # dedup é feito uma vez em train_model
            min_samples=config.MIN_TRADES_FOR_TRAINING,
        )

    @staticmethod
    def _unique_score_count(scores: np.ndarray, decimals: int = 6) -> int:
        """Conta scores distintos (proxy de modelo degenerado)."""
        rounded = np.round(np.asarray(scores, dtype=float), decimals)
        return int(np.unique(rounded).size)

    @staticmethod
    def _bootstrap_auc_ci(
        y_true: np.ndarray,
        y_score: np.ndarray,
        n_boot: int = config.ML_VALIDATION_BOOTSTRAP,
        seed: int = 42,
    ) -> Tuple[Optional[float], Optional[float]]:
        """IC95% bootstrap do AUC temporal."""
        y_true = np.asarray(y_true)
        y_score = np.asarray(y_score, dtype=float)
        if len(np.unique(y_true)) < 2 or len(y_true) < 2:
            return None, None

        rng = np.random.default_rng(seed)
        n = len(y_true)
        values: List[float] = []
        for _ in range(max(1, n_boot)):
            idx = rng.integers(0, n, size=n)
            yt = y_true[idx]
            if len(np.unique(yt)) < 2:
                continue
            values.append(float(roc_auc_score(yt, y_score[idx])))

        if not values:
            return None, None

        lo, hi = np.percentile(values, [2.5, 97.5])
        return float(lo), float(hi)

    @staticmethod
    def _ev_optimal_threshold(
        y_true: np.ndarray,
        y_score: np.ndarray,
        avg_win: float,
        avg_loss: float,
        min_approval: int = 5,
    ) -> Optional[float]:
        """
        Threshold que maximiza valor esperado no holdout.

        EV(t) = P(win | score >= t) * avg_win
                - (1 - P(win | score >= t)) * |avg_loss|
        """
        y_true = np.asarray(y_true)
        y_score = np.asarray(y_score, dtype=float)
        best_threshold: Optional[float] = None
        best_ev = float("-inf")

        for threshold in np.unique(np.round(y_score, 4)):
            mask = y_score >= threshold
            n = int(mask.sum())
            if n < min_approval:
                continue
            p_win = float(y_true[mask].mean())
            ev = p_win * float(avg_win) - (1.0 - p_win) * abs(float(avg_loss))
            if ev > best_ev:
                best_ev = ev
                best_threshold = float(threshold)

        return best_threshold

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

        original_rows = len(df)
        df = deduplicate_trades(df)

        if len(df) < config.MIN_TRADES_FOR_TRAINING:
            raise ValueError(
                f"Dados insuficientes: {len(df)} trades únicos < "
                f"{config.MIN_TRADES_FOR_TRAINING} mínimo"
            )

        # Construir features via contrato único (schema completo obrigatório)
        X, y = self.build_features(df)

        if X is None or y is None or len(X) < config.MIN_TRADES_FOR_TRAINING:
            raise ValueError(
                "Não foi possível montar features completas para "
                f"treinamento ({0 if X is None else len(X)} amostras)."
            )

        # Split temporal/estratificado
        X_train, X_test, y_train, y_test = self._temporal_stratified_split(
            X, y, test_size=0.2, random_state=42
        )

        logger.info(
            f"Dataset split: train={len(X_train)}, test={len(X_test)} "
            f"(linhas originais={original_rows}, únicas={len(df)})"
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

        # Modelo: RandomForest sem `class_weight='balanced'`.
        #
        # Balanced distorce a probabilidade prevista e torna o threshold um
        # alvo móvel. O score precisa permanecer interpretável como
        # P(win) para que o threshold por valor esperado faça sentido.
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=5,
            class_weight=None,
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

        # Avaliar no holdout temporal
        score = pipeline.score(X_test, y_test)
        proba_test = pipeline.predict_proba(X_test)[:, 1]
        proba_train = pipeline.predict_proba(X_train)[:, 1]
        y_test_arr = np.asarray(y_test)
        y_train_arr = np.asarray(y_train)

        auc_oos: Optional[float] = None
        if len(np.unique(y_test_arr)) >= 2:
            auc_oos = float(roc_auc_score(y_test_arr, proba_test))

        auc_ci_low, auc_ci_high = self._bootstrap_auc_ci(
            y_test_arr, proba_test
        )

        base_rate = float(y_test_arr.mean()) if len(y_test_arr) else 0.0
        brier_oos = float(brier_score_loss(y_test_arr, proba_test))
        brier_baseline = base_rate * (1.0 - base_rate)

        try:
            log_loss_oos: Optional[float] = float(
                log_loss(y_test_arr, proba_test, labels=[0, 1])
            )
        except ValueError:
            log_loss_oos = None

        unique_train_scores = self._unique_score_count(proba_train)
        unique_test_scores = self._unique_score_count(proba_test)
        approval_rate = float((proba_test >= self.threshold).mean())

        win_pnls = df.loc[df["pnl"] > 0, "pnl"]
        loss_pnls = df.loc[df["pnl"] <= 0, "pnl"]
        avg_win = float(win_pnls.mean()) if len(win_pnls) else 0.0
        avg_loss = abs(float(loss_pnls.mean())) if len(loss_pnls) else 0.0

        ev_threshold = self._ev_optimal_threshold(
            y_test_arr, proba_test, avg_win, avg_loss
        )

        rejection_reasons: List[str] = []
        if len(y_test_arr) < config.ML_MIN_VALIDATION_SAMPLES:
            rejection_reasons.append("insufficient_holdout")
        if auc_oos is None:
            rejection_reasons.append("undefined_auc")
        elif auc_oos < config.ML_MIN_AUC_OOS:
            rejection_reasons.append("auc_oos_below_min")
        if auc_ci_low is None or auc_ci_low < config.ML_MIN_AUC_CI_LOW:
            rejection_reasons.append("auc_ci_low_below_min")
        if brier_oos >= brier_baseline:
            rejection_reasons.append("brier_not_better_than_baseline")
        if unique_train_scores < config.ML_MIN_UNIQUE_SCORES:
            rejection_reasons.append("degenerate_scores")
        if approval_rate < config.ML_MIN_APPROVAL_RATE:
            rejection_reasons.append("threshold_unreachable")

        accepted = not rejection_reasons
        status = "accepted" if accepted else "rejected"

        metadata = {
            "status": status,
            "model_schema_version": config.ML_MODEL_SCHEMA_VERSION,
            "feature_schema_version": config.ML_FEATURE_SCHEMA_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "n_rows_original": int(original_rows),
            "n_rows_unique": int(len(df)),
            "n_samples_train": int(len(X_train)),
            "n_samples_test": int(len(X_test)),
            "n_features": int(X.shape[1]),
            "feature_columns": list(X.columns),
            "class_weight": None,
            "threshold": float(self.threshold),
            "base_rate_oos": base_rate,
            "auc_oos": auc_oos,
            "auc_ci_low": auc_ci_low,
            "auc_ci_high": auc_ci_high,
            "brier_oos": brier_oos,
            "brier_baseline": brier_baseline,
            "log_loss_oos": log_loss_oos,
            "unique_train_scores": unique_train_scores,
            "unique_test_scores": unique_test_scores,
            "approval_rate_at_threshold": approval_rate,
            "ev_recommended_threshold": ev_threshold,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "rejection_reasons": rejection_reasons,
        }

        logger.info(
            f"Holdout temporal: AUC={auc_oos}, IC95%="
            f"[{auc_ci_low}, {auc_ci_high}], Brier={brier_oos:.4f} "
            f"(base={brier_baseline:.4f}), "
            f"scores distintos={unique_train_scores}, "
            f"aprovação@{self.threshold:.2f}={approval_rate:.2%}"
        )

        # Persistir: aceito substitui o modelo ativo; rejeitado vai para
        # quarentena e NUNCA é carregado pelo pipeline.
        if accepted:
            target_path = self.model_path
        else:
            target_path = self.model_path.with_name(
                self.model_path.stem + config.ML_REJECTED_MODEL_SUFFIX
            )
            logger.warning(
                "ML_MODEL_REJECTED reasons=%s -> %s",
                ",".join(rejection_reasons),
                target_path,
            )

        payload = {"pipeline": pipeline, "metadata": metadata}

        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(target_path) + ".tmp"
        joblib.dump(payload, tmp_path)
        os.replace(tmp_path, str(target_path))

        logger.info(f"Modelo ({status}) salvo em {target_path}")

        result = {
            "model_path": str(target_path),
            "deployed": accepted,
            "status": status,
            "test_score": float(score),
            "samples_trained": len(X_train),
            "samples_tested": len(X_test),
            "n_features": int(X.shape[1]),
            "feature_columns": list(X.columns),
            "metrics": metadata,
        }

        return result
