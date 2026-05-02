"""
Classificador ML para filtro de sinais de trading.

Usa modelo treinado para avaliar qualidade de sugestões
das engines de estratégia. Filtra trades de baixa qualidade
antes da execução.

Se modelo não estiver disponível, usa heurística baseada
em métricas de mercado.
"""
import math
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import logging

import config
from logging_config import setup_logging

# Imports opcionais
try:
    import joblib
except ImportError:
    joblib = None
    logging.warning("joblib não disponível - ML classifier usará apenas heurística")

# Configurar logging
logger = setup_logging("ml_classifier", config.LOG_LEVEL)

# Mapeamentos para encoding
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
        threshold: Threshold mínimo para aprovar trade (0.0 a 1.0)
        model_path: Caminho do modelo treinado
        model: Modelo scikit-learn carregado (ou None)
    """
    
    def __init__(
        self,
        threshold: float = config.ML_APPROVAL_THRESHOLD,
        model_path: Path = config.ML_MODEL_PATH
    ):
        """
        Inicializa classificador ML.
        
        Args:
            threshold: Score mínimo para aprovar trade (0.0 a 1.0)
            model_path: Caminho do arquivo do modelo
        """
        self.threshold = threshold
        self.model_path = model_path
        self.model = self._load_model()
        
        logger.info(
            f"MLClassifier inicializado: threshold={threshold:.2f}, "
            f"model={'loaded' if self.model else 'not available'}"
        )
    
    def _load_model(self) -> Optional[Any]:
        """
        Carrega modelo ML do disco.
        
        Returns:
            Modelo carregado ou None se não disponível
        """
        if joblib is None:
            logger.debug("joblib não disponível, modelo não será carregado")
            return None
        
        if not self.model_path.exists():
            logger.debug(f"Modelo não encontrado em {self.model_path}")
            return None
        
        try:
            model = joblib.load(str(self.model_path))
            logger.info(f"Modelo ML carregado de {self.model_path}")
            return model
            
        except Exception as e:
            logger.error(f"Erro ao carregar modelo: {e}", exc_info=True)
            return None
    
    def is_trained(self) -> bool:
        """
        Verifica se modelo ML está disponível.
        
        Returns:
            True se modelo carregado
        """
        return self.model is not None
    
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
    
    def _build_features(self, suggestion: Dict[str, Any]) -> List[float]:
        """
        Constrói vetor de features para o modelo.
        
        Features:
        0. confidence
        1. slope
        2. momentum
        3. range_rel
        4. volatility_ratio
        5. regime (encoded)
        6. engine (encoded)
        7. action (encoded: 1=COMPRA, -1=VENDA, 0=NEUTRO)
        
        Args:
            suggestion: Dicionário com sugestão da engine
            
        Returns:
            Lista com 8 features
        """
        regime_metrics = suggestion.get("regime_metrics", {})
        engine = suggestion.get("engine", "N/A")
        action = suggestion.get("action", "NEUTRO")
        
        features = [
            suggestion.get("confidence", 0.0),
            regime_metrics.get("slope", 0.0),
            regime_metrics.get("momentum", 0.0),
            regime_metrics.get("range_rel", 0.0),
            regime_metrics.get("volatility_ratio", 0.0),
            REGIME_MAP.get(regime_metrics.get("regime", ""), 0),
            ENGINE_MAP.get(engine, 0),
            1 if action == "COMPRA" else -1 if action == "VENDA" else 0,
        ]
        
        return features
    
    def score_trade(self, suggestion: Dict[str, Any]) -> float:
        """
        Calcula score de qualidade do trade.
        
        Usa modelo ML se disponível, caso contrário usa heurística.
        
        Args:
            suggestion: Dicionário com sugestão da engine
            
        Returns:
            Score entre 0.0 e 1.0 (probabilidade de sucesso)
        """
        # NEUTRO sempre retorna score 0
        if suggestion["action"] == "NEUTRO":
            return 0.0
        
        # TENTATIVA 1: Usar modelo ML se disponível
        if self.model is not None:
            try:
                features = self._build_features(suggestion)
                probability = self.model.predict_proba([features])[0][1]
                score = float(probability)
                
                logger.debug(
                    f"ML score: {score:.4f} para {suggestion['action']} "
                    f"via {suggestion.get('engine', 'N/A')}"
                )
                
                return score
                
            except Exception as e:
                logger.warning(
                    f"Erro ao usar modelo ML, usando heurística: {e}"
                )
                # Continuar para heurística
        
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
            f"Heuristic score: {score:.4f} para {suggestion['action']} "
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
            regime_metrics: Métricas do regime
            
        Returns:
            Sugestão modificada com ml_score
        """
        # Adicionar métricas à sugestão para scoring
        suggestion_with_metrics = {
            **suggestion,
            "regime_metrics": regime_metrics
        }
        
        # Calcular score
        approved, score = self.approve_trade(suggestion_with_metrics)
        
        # Modificar sugestão
        filtered = suggestion.copy()
        filtered["ml_score"] = score
        
        # Se reprovado, converter para NEUTRO
        if not approved and suggestion["action"] != "NEUTRO":
            logger.info(
                f"ML FILTRO: {suggestion['action']} → NEUTRO "
                f"(score {score:.4f} < {self.threshold:.4f})"
            )
            
            filtered["action"] = "NEUTRO"
            filtered["confidence"] = 0.0
            filtered["reason"] = f"Filtrado por ML (score={score:.4f})"
        
        return filtered
