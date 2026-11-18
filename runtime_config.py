"""
Configuração dinâmica do motor de trading.

Este módulo é a única porta de entrada para calibrar o sistema em tempo
real. Ele mantém:

- Os valores padrão definidos em `config.py` (fonte original).
- Overrides explícitos persistidos em `runtime_config.json`.
- Validação de tipos, limites e consistência antes de aplicar.
- Aplicação atômica no módulo `config` e nos componentes vivos do motor.

O motor em Python não precisa ser reiniciado: parâmetros lidos em tempo de
chamada passam a valer imediatamente, e os componentes que copiam valores
no construtor (PositionManager, RiskController, MLClassifier, engines) são
sincronizados pelo listener `_sync_live_engine`.

A API Flask expõe este módulo via `GET/POST /api/config`.
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import config
from logging_config import setup_logging

logger = setup_logging("runtime_config", config.LOG_LEVEL)


# ============================================================================
# ESPECIFICAÇÃO DOS PARÂMETROS
# ============================================================================

CATEGORY_LABELS: Dict[str, str] = {
    "stops": "Stops / Alvos",
    "regime": "Regime de Mercado",
    "exhaustion": "Exaustão",
    "risk": "Risco",
    "ml": "Machine Learning",
}


@dataclass(frozen=True)
class ParameterSpec:
    """Metadados e regras de validação de um parâmetro calibrável."""

    key: str
    category: str
    kind: str  # "int" | "float" | "dict_int"
    label: str
    description: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None


PARAMETER_SPECS: Tuple[ParameterSpec, ...] = (
    # ---------------------------------------------------------------- stops
    ParameterSpec(
        "DEFAULT_STOP_LOSS_PCT", "stops", "float",
        "Stop-loss padrão",
        "Perda máxima por trade (fração do preço de entrada).",
        0.0005, 0.20, 0.0005,
    ),
    ParameterSpec(
        "DEFAULT_TAKE_PROFIT_PCT", "stops", "float",
        "Take-profit padrão",
        "Alvo de lucro por trade (fração do preço de entrada).",
        0.0005, 0.50, 0.0005,
    ),
    ParameterSpec(
        "BASE_POSITION_SIZE_PCT", "stops", "float",
        "Tamanho base da posição",
        "Fração do equity alocada por posição antes do ajuste por confiança.",
        0.001, 0.50, 0.001,
    ),
    ParameterSpec(
        "MIN_CONFIDENCE_FACTOR", "stops", "float",
        "Fator mínimo de confiança",
        "Piso do multiplicador de tamanho aplicado à confiança do sinal.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "MAX_CONFIDENCE_FACTOR", "stops", "float",
        "Fator máximo de confiança",
        "Teto do multiplicador de tamanho aplicado à confiança do sinal.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "MAX_POSITION_AGE_TICKS", "stops", "dict_int",
        "Idade máxima da posição",
        "Ticks máximos por nível de agressividade antes do fechamento.",
        1, 10000,
    ),
    # --------------------------------------------------------------- regime
    ParameterSpec(
        "REGIME_RISK_EXIT_TICKS", "regime", "int",
        "Histerese de saída por regime",
        "Ticks consecutivos em TRANSICAO antes de encerrar por regime_risk. "
        "ALTA_VOLATILIDADE encerra imediatamente.",
        1, 100, 1,
    ),
    ParameterSpec(
        "CRYPTO_VOL_MULTIPLIER", "regime", "float",
        "Multiplicador cripto",
        "Amplia thresholds e stops para ativos cripto mais voláteis.",
        1.0, 10.0, 0.1,
    ),
    ParameterSpec(
        "MIN_HISTORY_FOR_REGIME", "regime", "int",
        "Histórico mínimo do regime",
        "Pontos mínimos de preço para calcular o regime.",
        5, 1000, 1,
    ),
    ParameterSpec(
        "RANGE_THRESHOLD", "regime", "float",
        "Threshold de amplitude",
        "Amplitude relativa considerada baixa para consolidação.",
        0.000001, 0.50, 0.000001,
    ),
    ParameterSpec(
        "SLOPE_THRESHOLD_SMALL", "regime", "float",
        "Slope pequeno",
        "Inclinação mínima para movimentos curtos.",
        0.0000001, 0.50, 0.0000001,
    ),
    ParameterSpec(
        "SLOPE_THRESHOLD_MEDIUM", "regime", "float",
        "Slope médio",
        "Inclinação mínima para persistência de tendência.",
        0.0000001, 0.50, 0.0000001,
    ),
    ParameterSpec(
        "SLOPE_THRESHOLD_LARGE", "regime", "float",
        "Slope grande",
        "Inclinação mínima para tendência clara.",
        0.0000001, 0.50, 0.0000001,
    ),
    ParameterSpec(
        "VOLATILITY_RATIO_THRESHOLD", "regime", "float",
        "Razão de volatilidade",
        "Volatilidade curta/longa acima da qual o regime vira volátil.",
        0.1, 20.0, 0.1,
    ),
    ParameterSpec(
        "CHAOS_VOLATILITY_THRESHOLD", "regime", "float",
        "Volatilidade de caos",
        "Volatilidade extrema que caracteriza ALTA_VOLATILIDADE.",
        0.1, 20.0, 0.1,
    ),
    ParameterSpec(
        "CHAOS_RANGE_THRESHOLD", "regime", "float",
        "Amplitude de caos",
        "Amplitude alta que caracteriza ALTA_VOLATILIDADE.",
        0.000001, 0.50, 0.000001,
    ),
    ParameterSpec(
        "CHAOS_MOMENTUM_THRESHOLD", "regime", "float",
        "Momentum de caos",
        "Momentum fraco combinado com volatilidade alta.",
        0.000001, 0.50, 0.000001,
    ),
    ParameterSpec(
        "TREND_CONFIRMATION_TICKS", "regime", "int",
        "Confirmação de tendência",
        "Ticks consecutivos exigidos antes de permitir nova entrada.",
        1, 100, 1,
    ),
    ParameterSpec(
        "TREND_PRICE_THRESHOLD", "regime", "float",
        "Threshold de tendência",
        "Distância percentual da média que dispara o sinal de tendência.",
        0.000001, 0.50, 0.0001,
    ),
    ParameterSpec(
        "TREND_CONFIDENCE", "regime", "float",
        "Confiança da tendência",
        "Confiança atribuída aos sinais da engine TrendFollowing.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "MEAN_REVERSION_BAND_WIDTH", "regime", "float",
        "Largura da banda (reversão)",
        "Largura percentual da banda usada pela engine MeanReversion.",
        0.000001, 0.50, 0.0001,
    ),
    ParameterSpec(
        "MEAN_REVERSION_CONFIDENCE", "regime", "float",
        "Confiança da reversão",
        "Confiança atribuída aos sinais da engine MeanReversion.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "BREAKOUT_THRESHOLD", "regime", "float",
        "Threshold de rompimento",
        "Distância percentual do extremo que dispara rompimento.",
        0.000001, 0.50, 0.0001,
    ),
    ParameterSpec(
        "BREAKOUT_MIN_RANGE", "regime", "float",
        "Range mínimo de rompimento",
        "Amplitude mínima exigida para validar um rompimento.",
        0.000001, 0.50, 0.0001,
    ),
    ParameterSpec(
        "BREAKOUT_CONFIDENCE", "regime", "float",
        "Confiança do rompimento",
        "Confiança atribuída aos sinais da engine BreakoutMomentum.",
        0.0, 1.0, 0.01,
    ),
    # ----------------------------------------------------------- exhaustion
    ParameterSpec(
        "EXHAUSTION_MIN_HISTORY", "exhaustion", "int",
        "Histórico mínimo",
        "Pontos mínimos para avaliar exaustão.",
        2, 1000, 1,
    ),
    ParameterSpec(
        "EXHAUSTION_MOMENTUM_HIGH", "exhaustion", "float",
        "Momentum alto",
        "Momentum absoluto que dispara o critério de desaceleração.",
        0.0, 1.0, 0.001,
    ),
    ParameterSpec(
        "EXHAUSTION_DECELERATION_MIN", "exhaustion", "float",
        "Desaceleração mínima",
        "Queda de momentum que caracteriza exaustão.",
        0.0, 1.0, 0.001,
    ),
    ParameterSpec(
        "EXHAUSTION_WEAK_MOMENTUM", "exhaustion", "float",
        "Momentum fraco",
        "Momentum abaixo do qual um rompimento é suspeito.",
        0.0, 1.0, 0.001,
    ),
    ParameterSpec(
        "EXHAUSTION_RANGE_HIGH", "exhaustion", "float",
        "Amplitude alta",
        "Amplitude relativa que combinada com momentum fraco indica exaustão.",
        0.0, 1.0, 0.0005,
    ),
    ParameterSpec(
        "EXHAUSTION_VOLATILITY_RATIO_HIGH", "exhaustion", "float",
        "Volatilidade alta",
        "Razão de volatilidade para o critério de exaustão.",
        0.1, 20.0, 0.1,
    ),
    ParameterSpec(
        "EXHAUSTION_VOLATILITY_MOMENTUM_MAX", "exhaustion", "float",
        "Momentum sob volatilidade",
        "Momentum máximo aceitável quando a volatilidade está alta.",
        0.0, 1.0, 0.001,
    ),
    # ----------------------------------------------------------------- risk
    ParameterSpec(
        "GLOBAL_TRADE_LIMIT", "risk", "int",
        "Limite global de trades",
        "Máximo de trades por sessão/dia.",
        1, 10000, 1,
    ),
    ParameterSpec(
        "BASE_MAX_TRADES_BY_REGIME", "risk", "dict_int",
        "Trades máximos por regime",
        "Limite base de trades para cada regime de mercado.",
        0, 1000, 1,
    ),
    ParameterSpec(
        "MAX_OPEN_POSITIONS", "risk", "dict_int",
        "Posições abertas por nível",
        "Máximo de posições abertas em NORMAL/REDUCED/PROTECT.",
        0, 100, 1,
    ),
    ParameterSpec(
        "MAX_OPEN_POSITIONS_BY_SYMBOL", "risk", "dict_int",
        "Posições por símbolo",
        "Máximo de posições por símbolo em NORMAL/REDUCED/PROTECT.",
        0, 100, 1,
    ),
    ParameterSpec(
        "EQUITY_DRAWDOWN_LIMIT", "risk", "float",
        "Limite de drawdown",
        "Drawdown que reduz/bloqueia a operação.",
        0.01, 1.0, 0.01,
    ),
    ParameterSpec(
        "MIN_CONFIDENCE_FOR_REDUCED", "risk", "float",
        "Confiança mínima em REDUCED",
        "Confiança exigida para operar no modo REDUCED.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "DAILY_LOSS_LIMIT", "risk", "float",
        "Limite de perda diária",
        "Perda diária que aciona o kill-switch.",
        0.001, 1.0, 0.001,
    ),
    ParameterSpec(
        "KILL_SWITCH_HOURS", "risk", "int",
        "Horas de kill-switch",
        "Duração da pausa após o kill-switch.",
        0, 168, 1,
    ),
    ParameterSpec(
        "COOLDOWN_AFTER_STOP", "risk", "dict_int",
        "Cooldown após stop",
        "Ticks de cooldown após stop-loss por nível de risco.",
        0, 10000, 1,
    ),
    ParameterSpec(
        "MIN_NEW_HIGHS_FOR_REACTIVATION", "risk", "int",
        "Novos highs para reativar",
        "Novos highs necessários para voltar de REDUCED para NORMAL.",
        1, 100, 1,
    ),
    # ------------------------------------------------------------------- ml
    ParameterSpec(
        "ML_APPROVAL_THRESHOLD", "ml", "float",
        "Threshold de aprovação ML",
        "Score mínimo do classificador para aprovar um trade.",
        0.0, 1.0, 0.01,
    ),
    ParameterSpec(
        "MIN_TRADES_FOR_TRAINING", "ml", "int",
        "Trades mínimos para treino",
        "Histórico mínimo antes de permitir novo treinamento.",
        1, 1000000, 1,
    ),
    ParameterSpec(
        "TRAINING_INTERVAL_SECONDS", "ml", "int",
        "Intervalo de treinamento",
        "Segundos entre treinamentos automáticos.",
        60, 604800, 60,
    ),
)


# ============================================================================
# ORIENTAÇÃO DIDÁTICA DA CALIBRAGEM VISUAL
# ============================================================================
#
# Cada entrada responde a três perguntas que o painel exibe junto do campo:
# - impact_up:   o que muda quando o valor AUMENTA;
# - impact_down: o que muda quando o valor DIMINUI;
# - recommended: faixa considerada segura na calibração atual do motor;
# - tip:         contexto extra (armadilhas, interações, guardrails).
#
# Manter este conteúdo aqui (e não no frontend) garante que CLI, API e painel
# mostrem exatamente a mesma orientação, sem duplicação de texto.

PARAMETER_GUIDANCE: Dict[str, Dict[str, str]] = {
    # ---------------------------------------------------------------- stops
    "DEFAULT_STOP_LOSS_PCT": {
        "impact_up": (
            "Dá mais espaço ao preço antes de cortar a perda. Reduz saídas "
            "por ruído, mas aumenta o prejuízo máximo de cada trade."
        ),
        "impact_down": (
            "Corta perdas mais cedo e protege o capital, porém stop-outs em "
            "movimentos normais ficam mais frequentes."
        ),
        "recommended": "0,005 a 0,02 (0,5% a 2%)",
        "tip": (
            "Aplique junto de TAKE_PROFIT: stop muito apertado com alvo "
            "distante quebra a assimetria da estratégia."
        ),
    },
    "DEFAULT_TAKE_PROFIT_PCT": {
        "impact_up": (
            "Exige movimentos maiores para realizar lucro. Aumenta o ganho "
            "por acerto, mas reduz a taxa de acerto."
        ),
        "impact_down": (
            "Realiza lucro mais cedo e mais vezes, com ticket médio menor e "
            "maior exposição a custos de transação."
        ),
        "recommended": "0,005 a 0,03 (0,5% a 3%)",
        "tip": "Prefira alvo próximo do stop em regimes de consolidação.",
    },
    "BASE_POSITION_SIZE_PCT": {
        "impact_up": (
            "Aloca mais equity por posição. Amplifica lucros e prejuízos e "
            "consome mais rapidamente o limite de drawdown."
        ),
        "impact_down": (
            "Reduz exposição e volatilidade da curva de capital, mas dilui "
            "o impacto de bons sinais."
        ),
        "recommended": "0,02 a 0,10 (2% a 10% do equity)",
        "tip": "O tamanho final ainda é multiplicado pela confiança do sinal.",
    },
    "MIN_CONFIDENCE_FACTOR": {
        "impact_up": (
            "Sinais fracos deixam de ser reduzidos tanto: mais trades com "
            "tamanho relevante e maior risco."
        ),
        "impact_down": (
            "Sinais fracos operam com posição mínima. Filtra ruído, mas pode "
            "descartar reversões válidas."
        ),
        "recommended": "0,2 a 0,5",
        "tip": "Deve ficar sempre abaixo de MAX_CONFIDENCE_FACTOR.",
    },
    "MAX_CONFIDENCE_FACTOR": {
        "impact_up": (
            "Permite posições maiores quando a confiança é alta. Aumenta "
            "retorno potencial e risco de concentração."
        ),
        "impact_down": (
            "Limita o tamanho máximo mesmo em sinais perfeitos. Mais "
            "conservador e estável."
        ),
        "recommended": "1,0 a 2,0",
        "tip": "O limite de posições por regime continua se aplicando depois deste fator.",
    },
    "MAX_POSITION_AGE_TICKS": {
        "impact_up": (
            "Posições ficam abertas por mais ticks. Dá tempo ao alvo ser "
            "atingido, mas prende capital em sinais que já esfriaram."
        ),
        "impact_down": (
            "Fecha posições estagnadas mais rápido e libera slots, porém "
            "pode cortar movimentos que precisavam de mais tempo."
        ),
        "recommended": (
            "NORMAL 60–120 · REDUCED 20–40 · PROTECT 10–30 ticks"
        ),
        "tip": (
            "Em 1m, 30 ticks ≈ 30 minutos. O modo PAPER usa REDUCED e o "
            "RESEARCH usa NORMAL."
        ),
    },
    # --------------------------------------------------------------- regime
    "REGIME_RISK_EXIT_TICKS": {
        "impact_up": (
            "Tolera mais ticks consecutivos em TRANSICAO antes de fechar por "
            "risco de regime. Menos saídas precipitadas, mais exposição em "
            "momento de incerteza."
        ),
        "impact_down": (
            "Encerra antes em TRANSICAO e protege capital, mas aumenta o "
            "risco de fechar uma posição que se recuperaria."
        ),
        "recommended": "2 a 5 ticks (padrão: 3)",
        "tip": (
            "Histerese: ALTA_VOLATILIDADE SEMPRE encerra imediatamente; "
            "esta régua vale somente para TRANSICAO."
        ),
    },
    "CRYPTO_VOL_MULTIPLIER": {
        "impact_up": (
            "Exige movimentos maiores e usa stops mais largos em BTC, ETH e "
            "SOL. Filtra ruído, mas reduz o número de entradas."
        ),
        "impact_down": (
            "Aproxima cripto dos parâmetros de câmbio. Mais sinais, com "
            "risco de stop apertado diante da volatilidade real."
        ),
        "recommended": "1,0 a 2,0 (padrão mantém a calibração base)",
        "tip": (
            "Afeta apenas ativos cripto; USD e outros pares ignoram este "
            "multiplicador."
        ),
    },
    "MIN_HISTORY_FOR_REGIME": {
        "impact_up": (
            "Regime mais estável e menos suscetível a ruído, mas o motor "
            "leva mais tempo para começar a operar."
        ),
        "impact_down": (
            "Começa a decidir antes, porém com amostra curta o regime "
            "oscila mais e gera sinais falsos."
        ),
        "recommended": "15 a 30 pontos",
        "tip": "A simulação usa no máximo 100 pontos de histórico deslizante.",
    },
    "RANGE_THRESHOLD": {
        "impact_up": (
            "Mais janelas são classificadas como CONSOLIDAÇÃO, favorecendo "
            "MeanReversion."
        ),
        "impact_down": (
            "Menos consolidação detectada; o motor tende a TrendFollowing "
            "ou rompimento."
        ),
        "recommended": "0,001 a 0,005 (0,1% a 0,5%)",
        "tip": "Interage diretamente com MEAN_REVERSION_BAND_WIDTH.",
    },
    "SLOPE_THRESHOLD_SMALL": {
        "impact_up": "Inclinação mínima maior: movimentos fracos deixam de contar.",
        "impact_down": "Movimentos pequenos passam a contar como tendência inicial.",
        "recommended": "0,0001 a 0,0005",
        "tip": "É a porta de entrada da detectora de tendência.",
    },
    "SLOPE_THRESHOLD_MEDIUM": {
        "impact_up": "Persistência de tendência mais exigente: menos trocas de regime.",
        "impact_down": "Tendências fracas são confirmadas mais facilmente.",
        "recommended": "0,0005 a 0,002",
        "tip": "Use como regime intermediário entre SMALL e LARGE.",
    },
    "SLOPE_THRESHOLD_LARGE": {
        "impact_up": "Só tendências fortes são confirmadas: menos sinais e mais qualidade.",
        "impact_down": "Tendências moderadas também disparam sinal de entrada.",
        "recommended": "0,002 a 0,01",
        "tip": "Valor muito alto desativa na prática a engine TrendFollowing.",
    },
    "VOLATILITY_RATIO_THRESHOLD": {
        "impact_up": (
            "Só mudanças extremas de volatilidade viram ALTA_VOLATILIDADE."
        ),
        "impact_down": (
            "Pequenas altas de volatilidade bloqueiam entradas com mais "
            "facilidade."
        ),
        "recommended": "1,5 a 3,0",
        "tip": "Em ALTA_VOLATILIDADE o risco encerra posição imediatamente.",
    },
    "CHAOS_VOLATILITY_THRESHOLD": {
        "impact_up": "Caos exige volatilidade ainda maior: raro e tardio.",
        "impact_down": "Caos é detectado cedo, bloqueando mais entradas.",
        "recommended": "2,0 a 5,0",
        "tip": "Ative com cuidado: trava operações em dias de notícia.",
    },
    "CHAOS_RANGE_THRESHOLD": {
        "impact_up": "Só amplitudes muito grandes caracterizam caos.",
        "impact_down": "Amplitudes moderadas já bloqueiam o motor.",
        "recommended": "0,005 a 0,02 (0,5% a 2%)",
        "tip": "Funciona em conjunto com CHAOS_VOLATILITY_THRESHOLD.",
    },
    "CHAOS_MOMENTUM_THRESHOLD": {
        "impact_up": (
            "Exige momentum ainda mais fraco para declarar caos com vol alta."
        ),
        "impact_down": "Movimentos laterais com vol alta viram caos mais rápido.",
        "recommended": "0,0005 a 0,003",
        "tip": "Evite valores baixos em cripto, onde o ruído é natural.",
    },
    "TREND_CONFIRMATION_TICKS": {
        "impact_up": (
            "Exige mais ticks consecutivos em tendência antes de liberar "
            "entrada. Filtra falsos começos, mas perde o início do movimento."
        ),
        "impact_down": (
            "Entra mais cedo em tendências, com maior risco de reversão "
            "logo após a entrada."
        ),
        "recommended": "2 a 5 ticks",
        "tip": (
            "Este contador é por símbolo e é zerado quando o regime muda; "
            "posição já aberta não é bloqueada."
        ),
    },
    "TREND_PRICE_THRESHOLD": {
        "impact_up": (
            "Só movimentos mais fortes em relação à média disparam "
            "TrendFollowing. Menos trades e mais seletividade."
        ),
        "impact_down": (
            "Qualquer desvio pequeno gera sinal de tendência. Mais trades, "
            "porém mais ruído e custo de transação."
        ),
        "recommended": "0,003 a 0,006 (0,3% a 0,6%)",
        "tip": (
            "A calibração atual usa 0,004. O multiplicador cripto "
            "eleva o limite efetivo para BTC/ETH/SOL."
        ),
    },
    "TREND_CONFIDENCE": {
        "impact_up": (
            "Sinais de tendência recebem mais confiança: posição maior e "
            "score ML mais alto."
        ),
        "impact_down": "Sinais de tendência ficam menores e mais facilmente reprovados.",
        "recommended": "0,6 a 0,8",
        "tip": "Afeta o tamanho da posição por meio dos fatores de confiança.",
    },
    "MEAN_REVERSION_BAND_WIDTH": {
        "impact_up": (
            "Banda mais larga: mais preços entram na zona de reversão. "
            "Mais sinais, com maior risco de operar contra a tendência."
        ),
        "impact_down": (
            "Banda estreita: só desvios grandes geram reversão. Menos "
            "trades, porém mais precisos."
        ),
        "recommended": "0,0008 a 0,0015 (0,08% a 0,15%)",
        "tip": (
            "A calibração atual usa 0,0010. Ajuste junto de "
            "MEAN_REVERSION_CONFIDENCE e do stop."
        ),
    },
    "MEAN_REVERSION_CONFIDENCE": {
        "impact_up": "Reversões ganham peso no score ML e alocam mais capital.",
        "impact_down": "Reversões ficam conservadoras e podem ser filtradas.",
        "recommended": "0,5 a 0,7",
        "tip": "Engine mais sensível a RANGE_THRESHOLD.",
    },
    "BREAKOUT_THRESHOLD": {
        "impact_up": (
            "Rompimento precisa ultrapassar o extremo com folga maior. "
            "Menos falsos rompimentos, mas entrada mais tardia."
        ),
        "impact_down": (
            "Qualquer aproximação do extremo dispara rompimento. Entra "
            "cedo, com mais falsos sinais."
        ),
        "recommended": "0,0008 a 0,0015 (0,08% a 0,15%)",
        "tip": "A calibração atual usa 0,0010 com BREAKOUT_CONFIDENCE 0,68.",
    },
    "BREAKOUT_MIN_RANGE": {
        "impact_up": "Só ranges amplos podem romper: menos sinais, mais relevantes.",
        "impact_down": "Ranges estreitos também rompem: mais sinais e mais ruído.",
        "recommended": "0,001 a 0,003 (0,1% a 0,3%)",
        "tip": "Trabalha em conjunto com BREAKOUT_THRESHOLD.",
    },
    "BREAKOUT_CONFIDENCE": {
        "impact_up": "Rompimentos recebem mais confiança e tamanho maior.",
        "impact_down": "Rompimentos ficam menores e mais facilmente reprovados.",
        "recommended": "0,6 a 0,75",
        "tip": "Valor atual: 0,68. Equilibra frequência e qualidade.",
    },
    # ----------------------------------------------------------- exhaustion
    "EXHAUSTION_MIN_HISTORY": {
        "impact_up": "Avaliação mais estável, porém começa a filtrar mais tarde.",
        "impact_down": "Filtra antes, com amostra curta e mais falsos positivos.",
        "recommended": "5 a 20 pontos",
        "tip": "Abaixo de 2 o filtro é desativado.",
    },
    "EXHAUSTION_MOMENTUM_HIGH": {
        "impact_up": "Só momentum muito alto é considerado candidato a exaustão.",
        "impact_down": "Movimentos moderados também podem ser marcados como exaustos.",
        "recommended": "0,002 a 0,01",
        "tip": "É o gatilho da desaceleração: combine com DECELERATION_MIN.",
    },
    "EXHAUSTION_DECELERATION_MIN": {
        "impact_up": "Exige desaceleração maior: menos bloqueios de entrada.",
        "impact_down": "Qualquer perda de velocidade bloqueia a entrada.",
        "recommended": "0,001 a 0,005",
        "tip": "Valor alto deixa o filtro quase inativo em cripto.",
    },
    "EXHAUSTION_WEAK_MOMENTUM": {
        "impact_up": "Rompimentos com momentum fraco são aceitos com mais facilidade.",
        "impact_down": "Mais rompimentos suspeitos são bloqueados.",
        "recommended": "0,0005 a 0,003",
        "tip": "Critério específico da engine BreakoutMomentum.",
    },
    "EXHAUSTION_RANGE_HIGH": {
        "impact_up": "Só amplitudes grandes disparam exaustão por range.",
        "impact_down": "Amplitude moderada com momentum fraco já bloqueia.",
        "recommended": "0,002 a 0,01",
        "tip": "Trabalha em par com EXHAUSTION_WEAK_MOMENTUM.",
    },
    "EXHAUSTION_VOLATILITY_RATIO_HIGH": {
        "impact_up": "Só saltos extremos de volatilidade ativam o critério.",
        "impact_down": "Volatilidade um pouco acima da média já bloqueia entradas.",
        "recommended": "1,5 a 3,0",
        "tip": "Descontado automaticamente em TRANSICAO/ALTA_VOLATILIDADE.",
    },
    "EXHAUSTION_VOLATILITY_MOMENTUM_MAX": {
        "impact_up": "Permite mais momentum sob volatilidade alta antes de bloquear.",
        "impact_down": "Bloqueia antes movimentos em meio à volatilidade.",
        "recommended": "0,0005 a 0,003",
        "tip": "Use com cuidado: pode neutralizar boas entradas em rompimento.",
    },
    # ----------------------------------------------------------------- risk
    "GLOBAL_TRADE_LIMIT": {
        "impact_up": "Mais trades por sessão; maior exposição e custo acumulado.",
        "impact_down": "Encerra a sessão mais cedo e protege capital.",
        "recommended": "50 a 500 trades por sessão",
        "tip": "É um teto global, independente do limite por regime.",
    },
    "BASE_MAX_TRADES_BY_REGIME": {
        "impact_up": "Permite mais trades por regime antes do bloqueio de risco.",
        "impact_down": "Reduz a atividade e preserva capital em regimes específicos.",
        "recommended": (
            "TENDENCIA 20–60 · CONSOLIDACAO 10–30 · "
            "TRANSICAO 5–15 · ALTA_VOL 0–5"
        ),
        "tip": (
            "Contadores são zerados a cada mudança de regime na simulação. "
            "PROTECT usa limites reduzidos."
        ),
    },
    "MAX_OPEN_POSITIONS": {
        "impact_up": "Mais posições simultâneas: diversificação e mais exposição total.",
        "impact_down": "Menos exposição e gestão mais simples.",
        "recommended": "NORMAL 3–5 · REDUCED 1–2 · PROTECT 1",
        "tip": "O modo PAPER_TRADING usa REDUCED e, portanto, 1 posição.",
    },
    "MAX_OPEN_POSITIONS_BY_SYMBOL": {
        "impact_up": "Permite multiplicar a exposição no mesmo ativo.",
        "impact_down": "Evita concentração em um único símbolo.",
        "recommended": "NORMAL 1–2 · REDUCED 1 · PROTECT 1",
        "tip": "Conta por símbolo, somado ao limite global de posições.",
    },
    "EQUITY_DRAWDOWN_LIMIT": {
        "impact_up": "Tolera quedas maiores da curva antes de reduzir agressividade.",
        "impact_down": "Reduz/bloqueia operações mais cedo após perdas.",
        "recommended": "0,05 a 0,15 (5% a 15%)",
        "tip": "Na simulação o nível é fixo por modo; em produção acompanha o drawdown real.",
    },
    "MIN_CONFIDENCE_FOR_REDUCED": {
        "impact_up": "Mais sinais passam no modo REDUCED: maior atividade.",
        "impact_down": "Modo REDUCED fica mais seletivo e conservador.",
        "recommended": "0,6 a 0,75",
        "tip": "Aplicável após rebaixamento de agressividade por drawdown.",
    },
    "DAILY_LOSS_LIMIT": {
        "impact_up": "Perde mais antes do kill-switch: mais tempo operando.",
        "impact_down": "Kill-switch dispara cedo e preserva o capital.",
        "recommended": "0,02 a 0,05 (2% a 5% do capital)",
        "tip": "É o gatilho de perda diária; distinto do drawdown acumulado.",
    },
    "KILL_SWITCH_HOURS": {
        "impact_up": "Pausa mais longa depois do kill-switch: mais tempo fora do mercado.",
        "impact_down": "Volta a operar mais cedo, com risco de reentrar no mesmo cenário.",
        "recommended": "1 a 24 horas",
        "tip": "0 desativa a pausa automática.",
    },
    "COOLDOWN_AFTER_STOP": {
        "impact_up": "Demora mais para reentrar após stop-loss: evita revenge trading.",
        "impact_down": "Reentra rápido, com risco de sucessivos stop-outs.",
        "recommended": "NORMAL 5–20 · REDUCED 10–30 · PROTECT 30–60 ticks",
        "tip": "Contado em ticks do timeframe ativo (1m por padrão).",
    },
    "MIN_NEW_HIGHS_FOR_REACTIVATION": {
        "impact_up": "Exige mais confirmação de alta antes de voltar a NORMAL.",
        "impact_down": "Reativa a agressividade mais cedo.",
        "recommended": "2 a 5 novos highs",
        "tip": "Só atua após queda para REDUCED.",
    },
    # ------------------------------------------------------------------- ml
    "ML_APPROVAL_THRESHOLD": {
        "impact_up": (
            "Só sinais com score alto passam. Menos trades e maior qualidade "
            "média, com risco de perder bons sinais."
        ),
        "impact_down": (
            "Mais sinais aprovados. Aumenta frequência e exposição a falsos "
            "positivos."
        ),
        "recommended": "0,55 a 0,70 (atual: 0,58)",
        "tip": (
            "Em SHADOW MODE o score é calculado e registrado, mas NÃO "
            "bloqueia entradas. O filtro só atua com modelo validado e shadow desligado."
        ),
    },
    "MIN_TRADES_FOR_TRAINING": {
        "impact_up": (
            "Treino exige mais histórico: modelo mais robusto, porém "
            "atualizado com menos frequência."
        ),
        "impact_down": (
            "Retreino mais rápido, com risco de overfitting e instabilidade."
        ),
        "recommended": "mínimo 30 trades únicos; ideal 200+",
        "tip": (
            "GUARDRAIL: o retreino é recusado abaixo de 30 trades únicos e "
            "sem schema v2. Modelos reprovados ficam em quarentena."
        ),
    },
    "TRAINING_INTERVAL_SECONDS": {
        "impact_up": "Retreino mais espaçado: modelo estável, porém desatualizado.",
        "impact_down": "Retreino frequente: acompanha o mercado, mas custa mais e pode instabilizar.",
        "recommended": "86400 a 604800 s (1 a 7 dias)",
        "tip": "O intervalo mínimo é respeitado mesmo se houver novos trades.",
    },
}


class ConfigValidationError(ValueError):
    """Erro de validação de configuração (retornado como HTTP 400)."""


# ============================================================================
# GERENCIADOR
# ============================================================================

class RuntimeConfigManager:
    """
    Gerenciador thread-safe de configuração dinâmica.

    A configuração efetiva é sempre `default (config.py) + overrides (JSON)`.
    Nenhum override é aplicado sem validação completa, garantindo que uma
    requisição inválida não deixe o motor em estado parcialmente atualizado.
    """

    def __init__(
        self,
        config_path: Path = config.RUNTIME_CONFIG_PATH,
        *,
        config_module: Any = config,
        specs: Tuple[ParameterSpec, ...] = PARAMETER_SPECS,
    ):
        self.config_path = Path(config_path)
        self.config_module = config_module
        self._specs = {spec.key: spec for spec in specs}
        self._lock = threading.RLock()
        self._overrides: Dict[str, Any] = {}
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._updated_at: Optional[str] = None

        # Capturar os padrões originais ANTES de qualquer aplicação. Sem isso,
        # `_apply` sobrescreveria o próprio `config.py` e os "defaults"
        # passariam a apontar para o último override, quebrando o reset.
        self._defaults: Dict[str, Any] = {}
        for spec in self._specs.values():
            try:
                value = getattr(config_module, spec.key)
            except AttributeError as exc:
                raise ConfigValidationError(
                    f"Parâmetro ausente em config.py: {spec.key}"
                ) from exc
            self._defaults[spec.key] = _copy_value(value)

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """Retorna a configuração completa, agrupada por categoria."""
        with self._lock:
            return self._build_snapshot()

    def get_value(self, key: str) -> Any:
        """Retorna o valor efetivo de um parâmetro."""
        with self._lock:
            return self._effective_value(key)

    def _build_snapshot(self) -> Dict[str, Any]:
        categories: Dict[str, Dict[str, Any]] = {}
        values: Dict[str, Any] = {}
        defaults: Dict[str, Any] = {}
        overrides: Dict[str, Any] = {}

        for spec in self._specs.values():
            default = self._default_value(spec.key)
            value = self._overrides.get(spec.key, default)
            values[spec.key] = _jsonable(value)
            defaults[spec.key] = _jsonable(default)
            if spec.key in self._overrides:
                overrides[spec.key] = _jsonable(self._overrides[spec.key])

            category = categories.setdefault(
                spec.category,
                {
                    "key": spec.category,
                    "label": CATEGORY_LABELS.get(spec.category, spec.category),
                    "parameters": [],
                },
            )
            category["parameters"].append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "type": spec.kind,
                    "value": _jsonable(value),
                    "default": _jsonable(default),
                    "min": spec.minimum,
                    "max": spec.maximum,
                    "step": spec.step,
                    "description": spec.description,
                    "guidance": _jsonable(PARAMETER_GUIDANCE.get(spec.key, {})),
                    "overridden": spec.key in self._overrides,
                }
            )

        return {
            "categories": list(categories.values()),
            "values": values,
            "defaults": defaults,
            "overrides": overrides,
            "config_file": str(self.config_path),
            "updated_at": self._updated_at,
        }

    def _default_value(self, key: str) -> Any:
        try:
            value = self._defaults[key]
        except KeyError as exc:  # pragma: no cover - proteção de contrato
            raise ConfigValidationError(
                f"Parâmetro desconhecido: {key}"
            ) from exc
        return _copy_value(value)

    def _effective_value(self, key: str) -> Any:
        if key not in self._specs:
            raise ConfigValidationError(f"Parâmetro desconhecido: {key}")
        return self._overrides.get(key, self._default_value(key))

    # ------------------------------------------------------------------
    # Atualização
    # ------------------------------------------------------------------

    def update(self, updates: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Valida e aplica um conjunto de parâmetros.

        A operação é atômica: ou todos os valores são válidos e persistidos,
        ou nada é alterado.
        """
        if not isinstance(updates, Mapping):
            raise ConfigValidationError("Payload deve ser um objeto de parâmetros")

        with self._lock:
            validated = self._validate_updates(updates)
            candidate = dict(self._overrides)

            for key, value in validated.items():
                default = self._default_value(key)
                if value == default:
                    candidate.pop(key, None)
                else:
                    candidate[key] = value

            self._validate_consistency(candidate)

            if candidate == self._overrides:
                return self._build_snapshot()

            self._persist(candidate)
            self._apply(candidate)
            self._overrides = candidate
            self._updated_at = _utc_now()
            snapshot = self._build_snapshot()
            listeners = list(self._listeners)

        self._notify(listeners, snapshot)
        return snapshot

    def reset(
        self,
        keys: Optional[Mapping[str, Any] | List[str] | Tuple[str, ...]] = None,
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Restaura parâmetros para os padrões de `config.py`.

        Args:
            keys: lista de chaves a restaurar; None restaura todas.
            persist: se False, não grava o arquivo (usado em testes).
        """
        with self._lock:
            if keys is None:
                candidate: Dict[str, Any] = {}
            else:
                if isinstance(keys, Mapping):
                    key_list = list(keys.keys())
                else:
                    key_list = list(keys)
                unknown = [k for k in key_list if k not in self._specs]
                if unknown:
                    raise ConfigValidationError(
                        f"Parâmetros desconhecidos: {', '.join(unknown)}"
                    )
                candidate = dict(self._overrides)
                for key in key_list:
                    candidate.pop(key, None)

            self._validate_consistency(candidate)

            if candidate == self._overrides:
                return self._build_snapshot()

            if persist:
                self._persist(candidate)
            self._apply(candidate)
            self._overrides = candidate
            self._updated_at = _utc_now()
            snapshot = self._build_snapshot()
            listeners = list(self._listeners)

        self._notify(listeners, snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        """
        Carrega overrides do disco sem notificar listeners.

        Arquivos inválidos são ignorados por segurança (o motor sobe com os
        padrões de `config.py` e registra um warning).
        """
        with self._lock:
            if not self.config_path.exists():
                return self._build_snapshot()

            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(
                    "runtime_config.json inválido (%s) — usando padrões", exc
                )
                return self._build_snapshot()

            values = raw.get("values", raw) if isinstance(raw, Mapping) else None
            if not isinstance(values, Mapping):
                logger.warning(
                    "runtime_config.json sem objeto 'values' — usando padrões"
                )
                return self._build_snapshot()

            try:
                validated = self._validate_updates(values)
                # Valores idênticos ao padrão não precisam de override.
                validated = {
                    key: value
                    for key, value in validated.items()
                    if value != self._default_value(key)
                }
                self._validate_consistency(validated)
            except ConfigValidationError as exc:
                logger.warning(
                    "runtime_config.json rejeitado (%s) — usando padrões", exc
                )
                return self._build_snapshot()

            self._apply(validated)
            self._overrides = validated
            self._updated_at = (
                raw.get("updated_at") if isinstance(raw, Mapping) else None
            )
            logger.info(
                "Configuração dinâmica carregada: %d override(s) de %s",
                len(validated),
                self.config_path,
            )
            return self._build_snapshot()

    def _persist(self, overrides: Mapping[str, Any]) -> None:
        payload = {
            "updated_at": _utc_now(),
            "values": {key: _jsonable(value) for key, value in overrides.items()},
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(str(self.config_path) + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.config_path)

    def _apply(self, overrides: Mapping[str, Any]) -> None:
        for spec in self._specs.values():
            value = overrides.get(spec.key, self._default_value(spec.key))
            setattr(self.config_module, spec.key, _copy_value(value))

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def _validate_updates(self, updates: Mapping[str, Any]) -> Dict[str, Any]:
        unknown = [key for key in updates if key not in self._specs]
        if unknown:
            raise ConfigValidationError(
                f"Parâmetros desconhecidos: {', '.join(sorted(unknown))}"
            )

        validated: Dict[str, Any] = {}
        for key, value in updates.items():
            validated[key] = self._validate_value(self._specs[key], value)
        return validated

    def _validate_value(self, spec: ParameterSpec, value: Any) -> Any:
        if spec.kind == "int":
            return self._validate_int(spec, value)

        if spec.kind == "float":
            return self._validate_float(spec, value)

        if spec.kind == "dict_int":
            return self._validate_dict_int(spec, value)

        raise ConfigValidationError(  # pragma: no cover - contrato interno
            f"Tipo de parâmetro não suportado: {spec.kind}"
        )

    def _validate_int(self, spec: ParameterSpec, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError(
                f"{spec.key} deve ser inteiro (recebido: {value!r})"
            )
        self._check_bounds(spec, value)
        return int(value)

    def _validate_float(self, spec: ParameterSpec, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValidationError(
                f"{spec.key} deve ser numérico (recebido: {value!r})"
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ConfigValidationError(f"{spec.key} deve ser finito")
        self._check_bounds(spec, numeric)
        return numeric

    def _validate_dict_int(self, spec: ParameterSpec, value: Any) -> Dict[str, int]:
        if not isinstance(value, Mapping):
            raise ConfigValidationError(
                f"{spec.key} deve ser um objeto com valores inteiros"
            )

        current = self._effective_value(spec.key)
        if not isinstance(current, Mapping):
            current = self._default_value(spec.key)

        unknown = [key for key in value if key not in current]
        if unknown:
            raise ConfigValidationError(
                f"{spec.key} possui chaves inválidas: {', '.join(sorted(unknown))}"
            )

        merged = dict(current)
        for key, item in value.items():
            if isinstance(item, bool) or not isinstance(item, int):
                raise ConfigValidationError(
                    f"{spec.key}.{key} deve ser inteiro (recebido: {item!r})"
                )
            self._check_bounds(spec, item, label=f"{spec.key}.{key}")
            merged[key] = int(item)
        return merged

    @staticmethod
    def _check_bounds(
        spec: ParameterSpec,
        value: float,
        *,
        label: Optional[str] = None,
    ) -> None:
        name = label or spec.key
        if spec.minimum is not None and value < spec.minimum:
            raise ConfigValidationError(
                f"{name} abaixo do mínimo ({spec.minimum})"
            )
        if spec.maximum is not None and value > spec.maximum:
            raise ConfigValidationError(
                f"{name} acima do máximo ({spec.maximum})"
            )

    def _validate_consistency(self, overrides: Mapping[str, Any]) -> None:
        effective = {
            key: overrides.get(key, self._default_value(key))
            for key in self._specs
        }
        min_factor = effective.get("MIN_CONFIDENCE_FACTOR")
        max_factor = effective.get("MAX_CONFIDENCE_FACTOR")
        if (
            min_factor is not None
            and max_factor is not None
            and min_factor > max_factor
        ):
            raise ConfigValidationError(
                "MIN_CONFIDENCE_FACTOR não pode ser maior que "
                "MAX_CONFIDENCE_FACTOR"
            )

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def register_listener(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Registra callback chamado após cada atualização bem-sucedida."""
        with self._lock:
            self._listeners.append(callback)

    @staticmethod
    def _notify(
        listeners: List[Callable[[Dict[str, Any]], None]],
        snapshot: Dict[str, Any],
    ) -> None:
        for callback in listeners:
            try:
                callback(snapshot)
            except Exception:  # pragma: no cover - listener não deve derrubar API
                logger.exception("Falha ao executar listener de configuração")


# ============================================================================
# APLICAÇÃO AO VIVO NO MOTOR
# ============================================================================

def _sync_live_engine(snapshot: Dict[str, Any]) -> None:
    """
    Propaga a configuração para componentes que copiam valores no init.

    Parâmetros lidos em tempo de chamada (market_regime, exhaustion_filter,
    strategy thresholds usados diretamente) já refletem o módulo `config`
    mutado. Aqui sincronizamos os objetos vivos do monitor.
    """
    monitor = sys.modules.get("monitor")
    if monitor is None:
        return

    try:
        position_manager = getattr(monitor, "position_manager", None)
        if position_manager is not None:
            vol_mult = float(getattr(position_manager, "_vol_mult", 1.0) or 1.0)
            if hasattr(position_manager, "stop_loss_pct"):
                position_manager.stop_loss_pct = (
                    config.DEFAULT_STOP_LOSS_PCT * vol_mult
                )
            if hasattr(position_manager, "take_profit_pct"):
                position_manager.take_profit_pct = (
                    config.DEFAULT_TAKE_PROFIT_PCT * vol_mult
                )

        risk_controller = getattr(monitor, "risk_controller", None)
        if risk_controller is not None:
            risk_controller.global_limit = int(config.GLOBAL_TRADE_LIMIT)
            risk_controller.base_max_trades_by_regime = dict(
                config.BASE_MAX_TRADES_BY_REGIME
            )
            risk_controller.max_trades_by_regime = config.get_regime_limits(
                risk_controller.aggressiveness_level
            )
            risk_controller.max_open_positions = dict(
                config.MAX_OPEN_POSITIONS
            )
            risk_controller.max_open_positions_by_symbol = dict(
                config.MAX_OPEN_POSITIONS_BY_SYMBOL
            )
            risk_controller.equity_drawdown_limit = float(
                config.EQUITY_DRAWDOWN_LIMIT
            )
            risk_controller.min_confidence_for_reduced = float(
                config.MIN_CONFIDENCE_FOR_REDUCED
            )
            risk_controller.daily_loss_limit = float(config.DAILY_LOSS_LIMIT)
            risk_controller.kill_switch_hours = int(config.KILL_SWITCH_HOURS)
            risk_controller.min_new_highs_for_reactivation = int(
                config.MIN_NEW_HIGHS_FOR_REACTIVATION
            )

        classifier = getattr(monitor, "classifier", None)
        if classifier is not None:
            classifier.threshold = float(config.ML_APPROVAL_THRESHOLD)

        orchestrator = getattr(monitor, "orchestrator", None)
        engines = getattr(orchestrator, "engines", None)
        if isinstance(engines, dict):
            trend = engines.get("trend_following")
            if trend is not None:
                trend.price_threshold = float(config.TREND_PRICE_THRESHOLD)
                trend.confidence = float(config.TREND_CONFIDENCE)
            mean_reversion = engines.get("mean_reversion")
            if mean_reversion is not None:
                mean_reversion.band_width = float(
                    config.MEAN_REVERSION_BAND_WIDTH
                )
                mean_reversion.confidence = float(
                    config.MEAN_REVERSION_CONFIDENCE
                )
            breakout = engines.get("breakout")
            if breakout is not None:
                breakout.breakout_threshold = float(
                    config.BREAKOUT_THRESHOLD
                )
                breakout.min_range = float(config.BREAKOUT_MIN_RANGE)
                breakout.confidence = float(config.BREAKOUT_CONFIDENCE)

        logger.info(
            "Configuração aplicada em tempo real (%d parâmetro(s))",
            len(snapshot.get("values", {})),
        )
    except Exception:
        logger.exception("Falha ao sincronizar configuração com o motor vivo")


# ============================================================================
# HELPERS
# ============================================================================

def _copy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _jsonable(value: Any) -> Any:
    return _copy_value(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================================
# SINGLETON DO PROCESSO
# ============================================================================

runtime_config = RuntimeConfigManager()
runtime_config.load()
runtime_config.register_listener(_sync_live_engine)


__all__ = [
    "CATEGORY_LABELS",
    "ConfigValidationError",
    "PARAMETER_GUIDANCE",
    "PARAMETER_SPECS",
    "ParameterSpec",
    "RuntimeConfigManager",
    "runtime_config",
]
