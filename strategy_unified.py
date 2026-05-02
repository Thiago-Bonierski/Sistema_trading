"""
Engines de estratégia de trading e Orquestrador.

Este arquivo unifica strategy_engines.py e strategy_orchestrator.py.

Engines de estratégia:
- TrendFollowing: Segue tendências de mercado
- MeanReversion: Retorno à média em consolidação
- BreakoutMomentum: Rompimentos com volume
- ProtectFlat: Modo defensivo em regimes arriscados

Orquestrador:
- Seleciona engines apropriadas por regime de mercado
- Executa múltiplas engines em paralelo
- Escolhe melhor sugestão baseada em confiança
- Fallback para modo proteção se necessário
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any
import logging

import pandas as pd

import config
from logging_config import setup_logging

# Configurar logging
logger = setup_logging("strategy_unified", config.LOG_LEVEL)


class BaseStrategyEngine(ABC):
    """
    Classe base abstrata para engines de estratégia.
    
    Todas as engines devem herdar desta classe e implementar
    o método suggest().
    
    Attributes:
        name: Nome da engine
    """
    
    def __init__(self, name: str):
        """
        Inicializa engine com nome.
        
        Args:
            name: Nome da estratégia
        """
        self.name = name
        logger.debug(f"Engine {name} inicializada")
    
    @abstractmethod
    def suggest(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Gera sugestão de trading baseada em análise.
        
        Args:
            prices: Série histórica de preços
            current_price: Preço atual
            regime_metrics: Métricas do regime de mercado
            
        Returns:
            Dicionário com:
            {
                'action': str,      # COMPRA, VENDA, NEUTRO
                'confidence': float, # 0.0 a 1.0
                'engine': str,      # Nome da engine
                'reason': str       # Justificativa
            }
        """
        raise NotImplementedError("Subclasses devem implementar suggest()")


class TrendFollowingEngine(BaseStrategyEngine):
    """
    Engine de seguimento de tendência.
    
    Estratégia:
    - COMPRA em tendência de alta com momentum positivo
    - VENDA em tendência de baixa com momentum negativo
    - NEUTRO se condições não confirmadas
    
    Usa média móvel longa e momentum para confirmação.
    """
    
    def __init__(self):
        """Inicializa engine de trend following."""
        super().__init__("TrendFollowing")
        
        # Usar configurações centralizadas
        self.price_threshold = config.TREND_PRICE_THRESHOLD
        self.confidence = config.TREND_CONFIDENCE
    
    def suggest(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sugere ação baseada em tendência e momentum.
        
        Lógica:
        1. Calcula média móvel longa (15 períodos)
        2. Verifica regime de mercado
        3. Confirma com momentum e distância da média
        
        Args:
            prices: Série histórica de preços
            current_price: Preço atual
            regime_metrics: Métricas do regime
            
        Returns:
            Sugestão de trading
        """
        # Calcular média móvel longa
        media_longa = prices.iloc[:15].mean()
        momentum = regime_metrics.get("momentum", 0.0)
        regime = regime_metrics["regime"]
        
        # TENDÊNCIA DE ALTA
        if regime == "TENDENCIA_ALTA":
            # Preço acima da média + momentum positivo
            if current_price > media_longa * (1 + self.price_threshold) and momentum > 0:
                logger.debug(
                    f"TrendFollowing: COMPRA - "
                    f"price={current_price:.2f} > MA={media_longa:.2f}, "
                    f"momentum={momentum:.4f}"
                )
                return {
                    "action": "COMPRA",
                    "confidence": self.confidence,
                    "engine": self.name,
                    "reason": "Tendência alta com momentum positivo",
                }
        
        # TENDÊNCIA DE BAIXA
        elif regime == "TENDENCIA_BAIXA":
            # Preço abaixo da média + momentum negativo
            if current_price < media_longa * (1 - self.price_threshold) and momentum < 0:
                logger.debug(
                    f"TrendFollowing: VENDA - "
                    f"price={current_price:.2f} < MA={media_longa:.2f}, "
                    f"momentum={momentum:.4f}"
                )
                return {
                    "action": "VENDA",
                    "confidence": self.confidence,
                    "engine": self.name,
                    "reason": "Tendência baixa com momentum negativo",
                }
        
        # Sem condições claras
        return {
            "action": "NEUTRO",
            "confidence": 0.25,
            "engine": self.name,
            "reason": "Condições de tendência não confirmadas",
        }


class MeanReversionEngine(BaseStrategyEngine):
    """
    Engine de retorno à média.
    
    Estratégia:
    - COMPRA quando preço está muito abaixo da média (oversold)
    - VENDA quando preço está muito acima da média (overbought)
    - Funciona melhor em mercados de consolidação
    
    Usa bandas baseadas em média de curto prazo.
    """
    
    def __init__(self):
        """Inicializa engine de mean reversion."""
        super().__init__("MeanReversion")
        
        # Usar configurações centralizadas
        self.band_width = config.MEAN_REVERSION_BAND_WIDTH
        self.confidence = config.MEAN_REVERSION_CONFIDENCE
    
    def suggest(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sugere ação baseada em desvio da média.
        
        Lógica:
        1. Calcula média de curto prazo (10 períodos)
        2. Define bandas superior/inferior
        3. Compra em oversold, vende em overbought
        
        Args:
            prices: Série histórica de preços
            current_price: Preço atual
            regime_metrics: Métricas do regime
            
        Returns:
            Sugestão de trading
        """
        # Calcular média de curto prazo
        media_curta = prices.iloc[:10].mean()
        distancia = current_price - media_curta
        largura = media_curta * self.band_width
        
        # OVERSOLD - abaixo da banda inferior
        if distancia < -largura:
            logger.debug(
                f"MeanReversion: COMPRA - "
                f"price={current_price:.2f} << MA={media_curta:.2f}, "
                f"dist={distancia:.2f}"
            )
            return {
                "action": "COMPRA",
                "confidence": self.confidence,
                "engine": self.name,
                "reason": "Preço abaixo da média em consolidação",
            }
        
        # OVERBOUGHT - acima da banda superior
        if distancia > largura:
            logger.debug(
                f"MeanReversion: VENDA - "
                f"price={current_price:.2f} >> MA={media_curta:.2f}, "
                f"dist={distancia:.2f}"
            )
            return {
                "action": "VENDA",
                "confidence": self.confidence,
                "engine": self.name,
                "reason": "Preço acima da média em consolidação",
            }
        
        # Dentro das bandas - sem sinal
        return {
            "action": "NEUTRO",
            "confidence": 0.30,
            "engine": self.name,
            "reason": "Sem extremos de retorno à média",
        }


class BreakoutMomentumEngine(BaseStrategyEngine):
    """
    Engine de rompimento com momentum.
    
    Estratégia:
    - COMPRA em rompimento de máxima recente + volatilidade
    - VENDA em rompimento de mínima recente + volatilidade
    - Requer amplitude mínima para validar rompimento
    
    Funciona melhor em início de novas tendências.
    """
    
    def __init__(self):
        """Inicializa engine de breakout momentum."""
        super().__init__("BreakoutMomentum")
        
        # Usar configurações centralizadas
        self.breakout_threshold = config.BREAKOUT_THRESHOLD
        self.min_range = config.BREAKOUT_MIN_RANGE
        self.confidence = config.BREAKOUT_CONFIDENCE
    
    def suggest(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sugere ação baseada em rompimentos.
        
        Lógica:
        1. Identifica máxima/mínima recente (10 períodos)
        2. Verifica se há rompimento significativo
        3. Confirma com volatilidade (range_rel)
        
        Args:
            prices: Série histórica de preços
            current_price: Preço atual
            regime_metrics: Métricas do regime
            
        Returns:
            Sugestão de trading
        """
        # Calcular máxima e mínima recente
        recent = prices.iloc[:10]
        high = recent.max()
        low = recent.min()
        range_rel = regime_metrics.get("range_rel", 0.0)
        
        # ROMPIMENTO DE ALTA
        if current_price > high * (1 + self.breakout_threshold) and range_rel > self.min_range:
            logger.debug(
                f"BreakoutMomentum: COMPRA - "
                f"price={current_price:.2f} >> high={high:.2f}, "
                f"range={range_rel:.4f}"
            )
            return {
                "action": "COMPRA",
                "confidence": self.confidence,
                "engine": self.name,
                "reason": "Rompimento de alta em expansão de volatilidade",
            }
        
        # ROMPIMENTO DE BAIXA
        if current_price < low * (1 - self.breakout_threshold) and range_rel > self.min_range:
            logger.debug(
                f"BreakoutMomentum: VENDA - "
                f"price={current_price:.2f} << low={low:.2f}, "
                f"range={range_rel:.4f}"
            )
            return {
                "action": "VENDA",
                "confidence": self.confidence,
                "engine": self.name,
                "reason": "Rompimento de baixa em expansão de volatilidade",
            }
        
        # Sem rompimento válido
        return {
            "action": "NEUTRO",
            "confidence": 0.28,
            "engine": self.name,
            "reason": "Rompimento fraco ou ausência de momentum",
        }


class ProtectFlatEngine(BaseStrategyEngine):
    """
    Engine de proteção em regimes arriscados.
    
    Estratégia:
    - Sempre retorna NEUTRO
    - Usado em regimes de TRANSICAO ou ALTA_VOLATILIDADE
    - Foco em preservação de capital
    
    Esta engine é selecionada pelo orchestrator quando
    o mercado está muito instável.
    """
    
    def __init__(self):
        """Inicializa engine de proteção."""
        super().__init__("ProtectFlat")
    
    def suggest(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sempre retorna NEUTRO para proteção.
        
        Args:
            prices: Série histórica de preços (não usado)
            current_price: Preço atual (não usado)
            regime_metrics: Métricas do regime (não usado)
            
        Returns:
            Sempre NEUTRO com baixa confiança
        """
        logger.debug("ProtectFlat: NEUTRO - modo defensivo")
        
        return {
            "action": "NEUTRO",
            "confidence": 0.20,
            "engine": self.name,
            "reason": "Regime de risco ou transição, foco em sobrevivência",
        }


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def get_all_engines() -> Dict[str, BaseStrategyEngine]:
    """
    Retorna todas as engines disponíveis.
    
    Returns:
        Dicionário {nome: instância_da_engine}
    """
    engines = {
        "TrendFollowing": TrendFollowingEngine(),
        "MeanReversion": MeanReversionEngine(),
        "BreakoutMomentum": BreakoutMomentumEngine(),
        "ProtectFlat": ProtectFlatEngine(),
    }
    
    logger.debug(f"Engines carregadas: {list(engines.keys())}")
    return engines


def get_engine(name: str) -> BaseStrategyEngine:
    """
    Retorna engine específica por nome.
    
    Args:
        name: Nome da engine
        
    Returns:
        Instância da engine
        
    Raises:
        ValueError: Se engine não existir
    """
    engines = get_all_engines()
    
    if name not in engines:
        available = list(engines.keys())
        raise ValueError(
            f"Engine '{name}' não encontrada. "
            f"Disponíveis: {available}"
        )
    
    return engines[name]


# ============================================================================
# ORCHESTRATOR
# ============================================================================

class StrategyOrchestrator:
    """
    Orquestrador central de estratégias.
    
    Seleciona e executa engines apropriadas baseado no regime
    de mercado, e escolhe a melhor sugestão.
    
    Attributes:
        engines: Dicionário com todas as engines disponíveis
    """
    
    def __init__(self):
        """Inicializa orchestrator com todas as engines."""
        self.engines: Dict[str, BaseStrategyEngine] = {
            "trend_following": TrendFollowingEngine(),
            "mean_reversion": MeanReversionEngine(),
            "breakout": BreakoutMomentumEngine(),
            "protect": ProtectFlatEngine(),
        }
        
        logger.info(
            f"StrategyOrchestrator inicializado com {len(self.engines)} engines"
        )
    
    def candidate_engines(self, regime: str) -> List[BaseStrategyEngine]:
        """
        Seleciona engines candidatas baseado no regime de mercado.
        
        Lógica de seleção:
        - TENDENCIA_ALTA/BAIXA: TrendFollowing + Breakout
        - CONSOLIDACAO: MeanReversion + Protect
        - TRANSICAO: Breakout + TrendFollowing
        - ALTA_VOLATILIDADE: Breakout + Protect
        - Outros: Protect apenas
        
        Args:
            regime: Regime de mercado atual
            
        Returns:
            Lista de engines apropriadas para o regime
        """
        # TENDÊNCIA - usar engines de seguimento
        if regime in ("TENDENCIA_ALTA", "TENDENCIA_BAIXA"):
            candidates = [
                self.engines["trend_following"],
                self.engines["breakout"]
            ]
        
        # CONSOLIDAÇÃO - usar reversão à média
        elif regime == "CONSOLIDACAO":
            candidates = [
                self.engines["mean_reversion"],
                self.engines["protect"]
            ]
        
        # TRANSIÇÃO - tentar capturar início de tendência
        elif regime == "TRANSICAO":
            candidates = [
                self.engines["breakout"],
                self.engines["trend_following"]
            ]
        
        # ALTA VOLATILIDADE - cuidado especial
        elif regime == "ALTA_VOLATILIDADE":
            candidates = [
                self.engines["breakout"],
                self.engines["protect"]
            ]
        
        # Regime desconhecido - modo proteção
        else:
            logger.warning(f"Regime desconhecido: {regime}, usando apenas Protect")
            candidates = [self.engines["protect"]]
        
        logger.debug(
            f"Engines selecionadas para {regime}: "
            f"{[e.name for e in candidates]}"
        )
        
        return candidates
    
    def decide(
        self,
        prices: pd.Series,
        current_price: float,
        regime_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Decide melhor ação combinando sugestões de múltiplas engines.
        
        Processo:
        1. Seleciona engines candidatas pelo regime
        2. Coleta sugestões de cada engine
        3. Filtra sugestões não-neutras
        4. Escolhe sugestão com maior confiança
        5. Fallback para Protect se todas neutras
        
        Args:
            prices: Série histórica de preços
            current_price: Preço atual
            regime_metrics: Métricas do regime de mercado
            
        Returns:
            Melhor sugestão entre as engines candidatas
        """
        regime = regime_metrics["regime"]
        
        # Obter engines candidatas
        candidates = self.candidate_engines(regime)
        
        # Coletar sugestões de cada engine
        suggestions = []
        for engine in candidates:
            try:
                suggestion = engine.suggest(prices, current_price, regime_metrics)
                suggestions.append(suggestion)
                
                logger.debug(
                    f"{engine.name}: {suggestion['action']} "
                    f"(conf: {suggestion['confidence']:.2f})"
                )
                
            except Exception as e:
                logger.error(
                    f"Erro em {engine.name}: {e}",
                    exc_info=True
                )
                # Continuar com outras engines
                continue
        
        # Filtrar apenas sugestões não-neutras
        non_neutral = [s for s in suggestions if s["action"] != "NEUTRO"]
        
        # Se há sugestões ativas, escolher a de maior confiança
        if non_neutral:
            best = max(non_neutral, key=lambda s: s.get("confidence", 0.0))
            
            logger.info(
                f"Decisão: {best['action']} via {best['engine']} "
                f"(conf: {best['confidence']:.2f})"
            )
            
            return best
        
        # Fallback: todas neutras, usar Protect
        logger.debug("Todas as sugestões neutras, usando ProtectFlat")
        
        return self.engines["protect"].suggest(
            prices, current_price, regime_metrics
        )
    
    def evaluate(
        self,
        price: float,
        regime: str,
        regime_metrics: Dict[str, Any],
        prices: pd.Series = None
    ) -> Dict[str, Any]:
        """
        Interface simplificada para avaliação.
        
        Wrapper conveniente para decide() que padroniza output.
        
        Args:
            price: Preço atual
            regime: Regime de mercado
            regime_metrics: Métricas do regime
            prices: Série histórica (gerada se None)
            
        Returns:
            Dicionário com decisão padronizada:
            {
                'action': str,        # COMPRA, VENDA, NEUTRO
                'engine': str,      # Nome da engine
                'confidence':
 float, # 0.0 a 1.0
                'details': str      # Justificativa
            }
        """
        # Gerar série de preços se não fornecida ou insuficiente
        if prices is None or len(prices) < 20:
            prices = prices if prices is not None else pd.Series([price])
            if len(prices) < 20:
                prices = pd.concat([prices] * 20, ignore_index=True)
        
        # Obter decisão
        decision = self.decide(prices, price, regime_metrics)
        
        # Padronizar output (usando 'action' para consistência com engines)
        return {
            'action': decision['action'],
            'engine': decision['engine'],
            'confidence': decision['confidence'],
            'details': decision.get('reason', ''),
        }