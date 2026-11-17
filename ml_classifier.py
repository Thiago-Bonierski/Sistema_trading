"""
Classificador ML para filtro de sinais de trading.

Usa o modelo treinado para avaliar qualidade de sugestões
das engines de estratégia. Filtra trades de baixa qualidade
antes da execução.

Se modelo não estiver disponível, usa heurística baseada
em métricas de mercado.

O extrator de features é compartilhado com ml_training.py via
features.py, garantindo 100% de alinhamento entre treino e inferência
(sem data leakage).
"""
import math
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import logging

import pandas as pd
import config
from logging_config import setup_logging
from features import (
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    build_feature_row,
    N_FEATURES,
)

# Imports opcionais
try:
    import joblib

    JOBLIB_AVAILABLE = True
except ImportError:
    joblib = None
    JOBLIB_AVAILABLE = False
    logging.warning("joblib não disponível - ML classifier usará apenas heurística")

# Configurar logging
logger = setup_logging("ml_classifier", config.LOG_LEVEL)

# Mapeamentos de fallback (heurística) para encoding categórico
REGIME_MAP = {
    "TENDENCIA_ALTA": 1,
    "TENDENCIA_BAIXA": -1,
    "CONSOLIDACAO": 0,
    "TRANSICAO": 0,
    "ALTA_VOLATILIDADE": 0,
}

ENGINE_MAP = {
    "TrendFollowing": 1,
    "MeanReversion": 2,
    "BreakoutMomentum": 3,
    "ProtectFlat": 0,
}

ACTION_MAP = {
    "COMPRA": 1,
    "VENDA": -1,
    "NEUTRO": 0,
}


class MLClassifier:
    """
    Classificador ML para filtro de sinais.

    Avalia probabilidade de sucesso de um trade baseado em:
    - Confiança da engine
    - Métricas de regime (slope, momentum, volatilidade)
    - Tipo de regime
    - Engine que gerou o sinal
    - Direção do trade

    Se modelo ML não disponível, usa heurística.

    Attributes:
        threshold: Score mínimo para aprovar trade (0.0 a 1.0)
        model_path: Caminho do modelo treinado
        model: Modelo scikit-learn carregado (ou None)
        _last_mtime: Último timestamp de modificação do arquivo do modelo
    """

    def __init__(
        self,
        threshold: float = config.ML_APPROVAL_THRESHOLD,
        model_path: Path = config.ML_MODEL_PATH,
        shadow_mode: Optional[bool] = None,
    ):
        """
        Inicializa classificador ML.

        Args:
            threshold: Score mínimo para aprovar trade (0.0 a 1.0)
            model_path: Caminho do arquivo do modelo
            shadow_mode: Se True, calcula o score mas nunca bloqueia a
                entrada. None usa `config.ML_SHADOW_MODE`.
        """
        self.threshold = threshold
        self.model_path = model_path
        self.model = None
        self.metadata: Dict[str, Any] = {}
        self.disabled_reason: Optional[str] = None
        self.shadow_mode = (
            config.ML_SHADOW_MODE if shadow_mode is None else shadow_mode
        )
        self._last_mtime: Optional[float] = None
        self._lock = threading.RLock()
        self._load_model()

        logger.info(
            f"MLClassifier inicializado: threshold={threshold:.2f}, "
            f"model={'loaded' if self.model else 'not available'}, "
            f"usable={self.is_usable()}, shadow={self.shadow_mode}, "
            f"reason={self.disabled_reason or '-'}"
        )

    def _load_model(self) -> Optional[Any]:
        """
        Carrega modelo ML do disco.

        Returns:
            Modelo carregado ou None se não disponível
        """
        with self._lock:
            if not JOBLIB_AVAILABLE:
                logger.debug("joblib não disponível, modelo não será carregado")
                return None

            if not self.model_path.exists():
                logger.debug(f"Modelo não encontrado em {self.model_path}")
                self.model = None
                self.metadata = {}
                self.disabled_reason = None
                self._last_mtime = None
                return None

            try:
                current_mtime = self.model_path.stat().st_mtime
                if self._last_mtime is not None and current_mtime == self._last_mtime:
                    # Já carregado, nenhuma mudança
                    return self.model

                payload = joblib.load(str(self.model_path))

                # Formato v2: {"pipeline": ..., "metadata": {...}}.
                # Artefatos antigos (pipeline puro) são aceitos para
                # inferência, mas ficam inelegíveis para aplicar o filtro.
                if isinstance(payload, dict) and "pipeline" in payload:
                    model = payload["pipeline"]
                    metadata = dict(payload.get("metadata") or {})
                else:
                    model = payload
                    metadata = {}

                if not hasattr(model, "predict_proba"):
                    logger.error(
                        "Artefato ML inválido: pipeline sem predict_proba"
                    )
                    self.model = None
                    self.metadata = metadata
                    self.disabled_reason = "invalid_model_artifact"
                    self._last_mtime = None
                    return None

                n_features = getattr(model, "n_features_in_", N_FEATURES)
                if int(n_features) != N_FEATURES:
                    logger.error(
                        f"Modelo ML incompatível: {n_features} features "
                        f"(contrato atual={N_FEATURES})"
                    )
                    self.model = None
                    self.metadata = metadata
                    self.disabled_reason = "feature_dimension_mismatch"
                    self._last_mtime = None
                    return None

                self.model = model
                self.metadata = metadata
                self._last_mtime = current_mtime
                self._evaluate_guardrails()
                logger.info(f"Modelo ML carregado de {self.model_path}")
                return model

            except Exception as e:
                logger.error(f"Erro ao carregar modelo: {e}", exc_info=True)
                self.model = None
                self.metadata = {}
                self.disabled_reason = None
                self._last_mtime = None
                return None

    def _evaluate_guardrails(self) -> None:
        """
        Decide se o artefato carregado pode efetivamente filtrar entradas.

        Um modelo só é aplicável quando o treino comprova edge temporal
        out-of-sample. Modelos legados (sem metadados), degenerados (poucos
        scores distintos) ou com threshold inatingível ficam em shadow mode.
        """
        reasons: List[str] = []
        metadata = self.metadata or {}

        if self.model is None:
            self.disabled_reason = None
            return

        if not metadata:
            reasons.append("legacy_model_without_validation")
        else:
            if metadata.get("status") not in (None, "accepted"):
                reasons.append("model_rejected_by_training")

            auc = metadata.get("auc_oos")
            if auc is None:
                reasons.append("missing_auc_oos")
            elif float(auc) < config.ML_MIN_AUC_OOS:
                reasons.append("auc_oos_below_min")

            ci_low = metadata.get("auc_ci_low")
            if ci_low is None:
                reasons.append("missing_auc_ci_low")
            elif float(ci_low) < config.ML_MIN_AUC_CI_LOW:
                reasons.append("auc_ci_low_below_min")

            unique_scores = metadata.get("unique_train_scores")
            if (
                unique_scores is not None
                and int(unique_scores) < config.ML_MIN_UNIQUE_SCORES
            ):
                reasons.append("degenerate_scores")

            approval_rate = metadata.get("approval_rate_at_threshold")
            if (
                approval_rate is not None
                and float(approval_rate) < config.ML_MIN_APPROVAL_RATE
            ):
                reasons.append("threshold_unreachable")

            schema = metadata.get("feature_schema_version")
            if (
                schema is not None
                and int(schema) != config.ML_FEATURE_SCHEMA_VERSION
            ):
                reasons.append("feature_schema_mismatch")

        self.disabled_reason = ",".join(reasons) or None
        if self.disabled_reason:
            logger.warning(
                "ML_DISABLED_DEGENERATE model=%s reasons=%s shadow=%s",
                self.model_path,
                self.disabled_reason,
                self.shadow_mode,
            )

    def reload_model(self) -> bool:
        """
        Força recarregamento do modelo do disco (chamado após treino).

        Returns:
            True se um modelo válido foi carregado
        """
        with self._lock:
            self._last_mtime = None  # forçar releitura
            self._load_model()
            return self.model is not None

    def _maybe_reload(self) -> None:
        """
        Verifica se o arquivo do modelo mudou desde a última carga e
        recarrega automaticamente se necessário.
        """
        try:
            if not self.model_path.exists():
                with self._lock:
                    if self.model is not None:
                        self.model = None
                        self.metadata = {}
                        self.disabled_reason = None
                        self._last_mtime = None
                        logger.info("Modelo removido do disco, inferência via heurística")
                return
            current_mtime = self.model_path.stat().st_mtime
            with self._lock:
                needs_reload = self._last_mtime is None or current_mtime != self._last_mtime
            if needs_reload:
                self._load_model()
        except Exception as e:
            logger.debug(f"Erro ao verificar mtime do modelo: {e}")

    def is_trained(self) -> bool:
        """
        Verifica se modelo ML está disponível (validação estrutural).

        Returns:
            True se modelo carregado
        """
        self._maybe_reload()
        with self._lock:
            return self.model is not None

    def is_usable(self) -> bool:
        """
        Verifica se o modelo pode efetivamente filtrar entradas.

        Diferente de `is_trained()`, exige que o artefato tenha passado nos
        guardrails de validação (AUC OOS, scores distintos, threshold
        atingível). Um modelo treinado mas não validado é observado em
        shadow mode, sem bloquear trades.
        """
        self._maybe_reload()
        with self._lock:
            return self.model is not None and self.disabled_reason is None

    def ml_status(self) -> Dict[str, Any]:
        """Retorna o estado do filtro ML para telemetria/API."""
        self._maybe_reload()
        with self._lock:
            return {
                "trained": self.model is not None,
                "usable": self.model is not None and self.disabled_reason is None,
                "shadow_mode": self.shadow_mode,
                "disabled_reason": self.disabled_reason,
                "threshold": self.threshold,
                "model_path": str(self.model_path),
                "metadata": dict(self.metadata),
            }

    @staticmethod
    def _sigmoid(x: float) -> float:
        """
        Função sigmoid para normalização.

        Args:
            x: Valor a normalizar

        Returns:
            Valor entre 0 e 1
        """
        try:
            return 1 / (1 + math.exp(-x))
        except OverflowError:
            # x muito grande ou muito pequeno
            return 0.0 if x < 0 else 1.0

    def _build_features(self, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        """
        Constrói vetor de features usando o contrato único (features.py).

        Args:
            suggestion: Dicionário com sugestão da engine

        Returns:
            Dict com as colunas de FEATURE_COLUMNS
        """
        regime_metrics = suggestion.get("regime_metrics", {})
        return build_feature_row(suggestion, regime_metrics)

    def score_trade(self, suggestion: Dict[str, Any]) -> float:
        """
        Calcula score de qualidade do trade.

        Usa modelo ML se disponível, caso contrário usa heurística.

        Args:
            suggestion: Dicionário com sugestão da engine

        Returns:
            Score entre 0.0 e 1.0 (probabilidade de sucesso)

        Raises:
            RuntimeError: Se o modelo estiver carregado mas falhar na
                          predição (não silencia o erro).
        """
        # NEUTRO sempre retorna score 0
        if suggestion.get("action") == "NEUTRO":
            return 0.0

        # Verificar se há novo modelo no disco antes de predizer
        self._maybe_reload()

        # TENTATIVA 1: Usar modelo ML se disponível
        with self._lock:
            model = self.model
        if model is not None:
            try:
                features_dict = self._build_features(suggestion)
                X = pd.DataFrame([features_dict], columns=FEATURE_COLUMNS)
                # Categóricas como str para o OneHotEncoder
                for col in CATEGORICAL_FEATURES:
                    X[col] = X[col].astype(str)
                for col in NUMERIC_FEATURES:
                    X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)

                probability = model.predict_proba(X)[0][1]
                score = float(probability)

                logger.debug(
                    f"ML score: {score:.4f} para {suggestion.get('action')} "
                    f"via {suggestion.get('engine', 'N/A')}"
                )

                return score

            except Exception as e:
                # Erro real de predição: não silenciar, logar como erro
                logger.error(
                    f"Falha na predição do modelo ML: {e}", exc_info=True
                )
                raise RuntimeError(f"ML prediction failed: {e}") from e

        # TENTATIVA 2: Heurística baseada em métricas
        regime_metrics = suggestion.get("regime_metrics", {})
        confidence = suggestion.get("confidence", 0.0)
        slope = regime_metrics.get("slope", 0.0)
        momentum = regime_metrics.get("momentum", 0.0)
        range_rel = regime_metrics.get("range_rel", 0.0)

        # Combinar métricas em score
        base_score = confidence * 5
        base_score += slope * 40
        base_score += abs(momentum) * 15
        base_score -= range_rel * 20

        score = float(self._sigmoid(base_score))

        logger.debug(
            f"Heuristic score: {score:.4f} para {suggestion.get('action')} "
            f"via {suggestion.get('engine', 'N/A')}"
        )

        return score

    def approve_trade(self, suggestion: Dict[str, Any]) -> Tuple[bool, float]:
        """
        Avalia se deve aprovar um trade.

        Args:
            suggestion: Dicionário com sugestão da engine

        Returns:
            Tupla (aprovado, score)
        """
        score = self.score_trade(suggestion)
        approved = score >= self.threshold

        logger.debug(
            f"Trade {'APROVADO' if approved else 'REJEITADO'}: "
            f"score={score:.4f} (threshold={self.threshold:.4f})"
        )

        return approved, score

    def filter_signal(
        self,
        suggestion: Dict[str, Any],
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Filtra sinal adicionando score ML.

        Adiciona campo 'ml_score' à sugestão e pode alterar
        action para NEUTRO se reprovado.

        Args:
            suggestion: Sugestão da engine
            regime_metrics: Métricas do regime de mercado

        Returns:
            Sugestão modificada com ml_score
        """
        # Adicionar métricas à sugestão para scoring
        suggestion_with_metrics = {
            **suggestion,
            "regime_metrics": regime_metrics,
        }

        # Calcular score (pode levantar RuntimeError se o modelo estiver quebrado)
        try:
            approved, score = self.approve_trade(suggestion_with_metrics)
        except RuntimeError:
            # Se o modelo estiver carregado mas quebrado, cai para heurística
            # sem silenciar o erro de base
            logger.warning(
                "Modelo ML indisponível ou quebrado, usando heurística de fallback"
            )
            # Recalcular apenas a heurística diretamente
            score = self._heuristic_score(suggestion_with_metrics)
            approved = score >= self.threshold

        # Modificar sugestão
        filtered = suggestion.copy()
        filtered["ml_score"] = score

        # Shadow mode: observa o score, mas nunca neutraliza a entrada.
        if self.shadow_mode or not self.is_usable():
            filtered["ml_shadow"] = True
            if self.disabled_reason:
                filtered["ml_disabled_reason"] = self.disabled_reason
            logger.debug(
                "ML shadow: score=%.4f action=%s reason=%s",
                score,
                suggestion.get("action"),
                self.disabled_reason or "shadow_mode",
            )
            return filtered

        # Se reprovado, converter para NEUTRO
        if not approved and suggestion.get("action") != "NEUTRO":
            logger.info(
                f"ML FILTRO: {suggestion.get('action')} → NEUTRO "
                f"(score {score:.4f} < {self.threshold:.4f})"
            )

            filtered["action"] = "NEUTRO"
            filtered["confidence"] = 0.0
            filtered["reason"] = f"Filtrado por ML (score={score:.4f})"

        return filtered

    def _heuristic_score(self, suggestion: Dict[str, Any]) -> float:
        """
        Heurística pura (sem modelo ML) usada como fallback.

        Args:
            suggestion: Dicionário com sugestão da engine (com regime_metrics)

        Returns:
            Score entre 0.0 e 1.0
        """
        regime_metrics = suggestion.get("regime_metrics", {})
        confidence = suggestion.get("confidence", 0.0)
        slope = regime_metrics.get("slope", 0.0)
        momentum = regime_metrics.get("momentum", 0.0)
        range_rel = regime_metrics.get("range_rel", 0.0)

        base_score = confidence * 5
        base_score += slope * 40
        base_score += abs(momentum) * 15
        base_score -= range_rel * 20

        return float(self._sigmoid(base_score))
