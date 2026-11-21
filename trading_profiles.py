"""
Perfis de calibragem predefinidos para o painel de controle.

Um perfil é um ponto de partida coerente para a estratégia: ele ajusta um
conjunto pequeno de parâmetros que realmente mudam o comportamento do motor
(stops, tamanho da posição, limites de risco, filtro ML e confirmação de
regime). Parâmetros não listados — notadamente os custos de execução — são
preservados, para que a calibração de taxas/derrapagem do usuário não seja
atropelada.

Os valores ficam no backend (e não no JS) pelos mesmos motivos da
``PARAMETER_GUIDANCE``: CLI, API e painel passam a mostrar exatamente a mesma
orientação, e ``RuntimeConfigManager.validate()`` consegue rejeitar qualquer
perfil inválido antes de ele chegar ao navegador.

Contrato da API:
    GET /api/config/profiles -> {"ok": true, "profiles": [...], ...}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from runtime_config import runtime_config


@dataclass(frozen=True)
class TradingProfile:
    """Definição declarativa de um perfil de risco/retorno."""

    id: str
    name: str
    tagline: str
    description: str
    risk: str  # baixo | medio | alto
    icon: str  # nome do ícone Lucide usado pelo frontend
    tone: str  # emerald | sky | amber | violet | rose
    upside: str
    downside: str
    highlights: Tuple[str, ...]
    values: Mapping[str, Any]
    reset: bool = False  # True = restaura todos os padrões de config.py


# Parâmetros que NENHUM perfil altera: custos de execução são calibração de
# contabilidade, não de comportamento, e devem refletir a corretora real.
PROTECTED_KEYS: Tuple[str, ...] = (
    "TRADING_FEE_PCT",
    "SLIPPAGE_PCT",
    "VOLATILE_SLIPPAGE_MULTIPLIER",
)

TRADING_PROFILES: Tuple[TradingProfile, ...] = (
    TradingProfile(
        id="balanced",
        name="Equilibrado",
        tagline="Padrão de fábrica, sem overrides.",
        description=(
            "Volta aos valores calibrados em config.py: stop de 0,8%, "
            "alvo de 1,5%, 5% de equity por posição e filtro ML em modo "
            "observação. Bom ponto de partida após testar outros perfis."
        ),
        risk="medio",
        icon="Scale",
        tone="sky",
        upside="Remove personalizações acumuladas e retorna à linha de base validada.",
        downside="Abranda mão de perfis mais agressivos ou mais defensivos.",
        highlights=(),
        values={},
        reset=True,
    ),
    TradingProfile(
        id="aggressive",
        name="Máximo Lucro",
        tagline="Mais exposição, mais sinais, mais risco.",
        description=(
            "Amplia posições para 10% do equity, aceita sinais a partir de "
            "25% de confiança, abre até 4 posições e deixa o ML apenas "
            "observando. Busca capturar movimentos grandes com folga para "
            "os stops."
        ),
        risk="alto",
        icon="Flame",
        tone="rose",
        upside="Maior tamanho por acerto e muito mais oportunidades operadas.",
        downside="Uma sequência de stop-outs consome o capital e o limite diário rapidamente.",
        highlights=(
            "BASE_POSITION_SIZE_PCT",
            "MIN_CONFIDENCE_FACTOR",
            "EQUITY_DRAWDOWN_LIMIT",
            "ML_SHADOW_MODE",
        ),
        values={
            "DEFAULT_STOP_LOSS_PCT": 0.014,
            "DEFAULT_TAKE_PROFIT_PCT": 0.030,
            "BASE_POSITION_SIZE_PCT": 0.10,
            "MIN_CONFIDENCE_FACTOR": 0.25,
            "MAX_CONFIDENCE_FACTOR": 1.0,
            "MAX_POSITION_AGE_TICKS": {
                "NORMAL": 45,
                "REDUCED": 30,
                "PROTECT": 12,
            },
            "GLOBAL_TRADE_LIMIT": 60,
            "BASE_MAX_TRADES_BY_REGIME": {
                "TENDENCIA_ALTA": 8,
                "TENDENCIA_BAIXA": 8,
                "CONSOLIDACAO": 6,
                "TRANSICAO": 3,
                "ALTA_VOLATILIDADE": 2,
            },
            "MAX_OPEN_POSITIONS": {"NORMAL": 4, "REDUCED": 2, "PROTECT": 0},
            "MAX_OPEN_POSITIONS_BY_SYMBOL": {
                "NORMAL": 2,
                "REDUCED": 1,
                "PROTECT": 0,
            },
            "EQUITY_DRAWDOWN_LIMIT": 0.25,
            "MIN_CONFIDENCE_FOR_REDUCED": 0.35,
            "DAILY_LOSS_LIMIT": 0.05,
            "KILL_SWITCH_HOURS": 1,
            "COOLDOWN_AFTER_STOP": {"NORMAL": 2, "REDUCED": 5, "PROTECT": 10},
            "MIN_NEW_HIGHS_FOR_REACTIVATION": 2,
            "TREND_CONFIRMATION_TICKS": 2,
            "ML_SHADOW_MODE": True,
            "ML_APPROVAL_THRESHOLD": 0.45,
        },
    ),
    TradingProfile(
        id="capital_guard",
        name="Proteção de Capital",
        tagline="Sobrevive primeiro, lucra depois.",
        description=(
            "Reduz a posição para 2%, aperta o stop para 0,5%, exige 70% de "
            "confiança e liga o filtro ML com threshold 0,70. Drawdown de 6% "
            "e perda diária de 1% cortam a operação cedo."
        ),
        risk="baixo",
        icon="ShieldCheck",
        tone="emerald",
        upside="Curva de capital mais suave e preservação de capital em mercados hostis.",
        downside="Muitos sinais descartados e ganho por trade bem menor.",
        highlights=(
            "BASE_POSITION_SIZE_PCT",
            "EQUITY_DRAWDOWN_LIMIT",
            "MIN_CONFIDENCE_FACTOR",
            "ML_APPROVAL_THRESHOLD",
        ),
        values={
            "DEFAULT_STOP_LOSS_PCT": 0.005,
            "DEFAULT_TAKE_PROFIT_PCT": 0.008,
            "BASE_POSITION_SIZE_PCT": 0.02,
            "MIN_CONFIDENCE_FACTOR": 0.70,
            "MAX_CONFIDENCE_FACTOR": 0.85,
            "MAX_POSITION_AGE_TICKS": {
                "NORMAL": 20,
                "REDUCED": 12,
                "PROTECT": 6,
            },
            "GLOBAL_TRADE_LIMIT": 12,
            "BASE_MAX_TRADES_BY_REGIME": {
                "TENDENCIA_ALTA": 2,
                "TENDENCIA_BAIXA": 2,
                "CONSOLIDACAO": 1,
                "TRANSICAO": 0,
                "ALTA_VOLATILIDADE": 0,
            },
            "MAX_OPEN_POSITIONS": {"NORMAL": 1, "REDUCED": 1, "PROTECT": 0},
            "MAX_OPEN_POSITIONS_BY_SYMBOL": {
                "NORMAL": 1,
                "REDUCED": 1,
                "PROTECT": 0,
            },
            "EQUITY_DRAWDOWN_LIMIT": 0.06,
            "MIN_CONFIDENCE_FOR_REDUCED": 0.80,
            "DAILY_LOSS_LIMIT": 0.01,
            "KILL_SWITCH_HOURS": 6,
            "COOLDOWN_AFTER_STOP": {"NORMAL": 12, "REDUCED": 20, "PROTECT": 40},
            "MIN_NEW_HIGHS_FOR_REACTIVATION": 5,
            "TREND_CONFIRMATION_TICKS": 5,
            "ML_SHADOW_MODE": False,
            "ML_APPROVAL_THRESHOLD": 0.70,
        },
    ),
    TradingProfile(
        id="scalping",
        name="Scalping",
        tagline="Muitos trades curtos, alvos mínimos.",
        description=(
            "Stop de 0,3% e alvo de 0,4% com posições de até 10 ticks. O "
            "volume sobe para compensar o ticket médio pequeno — e os custos "
            "de execução viram uma fatia relevante de cada resultado."
        ),
        risk="medio",
        icon="Zap",
        tone="amber",
        upside="Alta rotação: realiza lucro várias vezes ao dia e limita o tempo exposto.",
        downside="Alvo de 0,4% é sensível a taxas e derrapagem; ruído gera mais stop-outs.",
        highlights=(
            "DEFAULT_TAKE_PROFIT_PCT",
            "MAX_POSITION_AGE_TICKS",
            "GLOBAL_TRADE_LIMIT",
            "BASE_POSITION_SIZE_PCT",
        ),
        values={
            "DEFAULT_STOP_LOSS_PCT": 0.003,
            "DEFAULT_TAKE_PROFIT_PCT": 0.004,
            "BASE_POSITION_SIZE_PCT": 0.04,
            "MIN_CONFIDENCE_FACTOR": 0.45,
            "MAX_CONFIDENCE_FACTOR": 0.90,
            "MAX_POSITION_AGE_TICKS": {
                "NORMAL": 10,
                "REDUCED": 8,
                "PROTECT": 4,
            },
            "GLOBAL_TRADE_LIMIT": 70,
            "BASE_MAX_TRADES_BY_REGIME": {
                "TENDENCIA_ALTA": 10,
                "TENDENCIA_BAIXA": 10,
                "CONSOLIDACAO": 8,
                "TRANSICAO": 4,
                "ALTA_VOLATILIDADE": 2,
            },
            "MAX_OPEN_POSITIONS": {"NORMAL": 3, "REDUCED": 1, "PROTECT": 0},
            "MAX_OPEN_POSITIONS_BY_SYMBOL": {
                "NORMAL": 1,
                "REDUCED": 1,
                "PROTECT": 0,
            },
            "EQUITY_DRAWDOWN_LIMIT": 0.10,
            "MIN_CONFIDENCE_FOR_REDUCED": 0.55,
            "DAILY_LOSS_LIMIT": 0.025,
            "KILL_SWITCH_HOURS": 2,
            "COOLDOWN_AFTER_STOP": {"NORMAL": 3, "REDUCED": 6, "PROTECT": 12},
            "MIN_NEW_HIGHS_FOR_REACTIVATION": 3,
            "TREND_CONFIRMATION_TICKS": 2,
            "ML_SHADOW_MODE": True,
            "ML_APPROVAL_THRESHOLD": 0.50,
        },
    ),
    TradingProfile(
        id="swing",
        name="Swing / Tendência",
        tagline="Poucos trades, movimentos longos.",
        description=(
            "Alvo de 5% com stop de 2% e posições que podem durar até 90 "
            "ticks. Só opera tendências confirmadas, ignora consolidação e "
            "usa o filtro ML para evitar entradas fracas."
        ),
        risk="medio",
        icon="TrendingUp",
        tone="violet",
        upside="Ticket médio maior e menos tempo pagando custos de transação.",
        downside="Fica fora de mercados laterais e exige paciência para ver o alvo.",
        highlights=(
            "DEFAULT_TAKE_PROFIT_PCT",
            "MAX_POSITION_AGE_TICKS",
            "BASE_MAX_TRADES_BY_REGIME",
            "ML_APPROVAL_THRESHOLD",
        ),
        values={
            "DEFAULT_STOP_LOSS_PCT": 0.020,
            "DEFAULT_TAKE_PROFIT_PCT": 0.050,
            "BASE_POSITION_SIZE_PCT": 0.06,
            "MIN_CONFIDENCE_FACTOR": 0.55,
            "MAX_CONFIDENCE_FACTOR": 1.0,
            "MAX_POSITION_AGE_TICKS": {
                "NORMAL": 90,
                "REDUCED": 60,
                "PROTECT": 15,
            },
            "GLOBAL_TRADE_LIMIT": 15,
            "BASE_MAX_TRADES_BY_REGIME": {
                "TENDENCIA_ALTA": 4,
                "TENDENCIA_BAIXA": 4,
                "CONSOLIDACAO": 0,
                "TRANSICAO": 1,
                "ALTA_VOLATILIDADE": 0,
            },
            "MAX_OPEN_POSITIONS": {"NORMAL": 2, "REDUCED": 1, "PROTECT": 0},
            "MAX_OPEN_POSITIONS_BY_SYMBOL": {
                "NORMAL": 1,
                "REDUCED": 1,
                "PROTECT": 0,
            },
            "EQUITY_DRAWDOWN_LIMIT": 0.12,
            "MIN_CONFIDENCE_FOR_REDUCED": 0.65,
            "DAILY_LOSS_LIMIT": 0.02,
            "KILL_SWITCH_HOURS": 3,
            "COOLDOWN_AFTER_STOP": {"NORMAL": 8, "REDUCED": 15, "PROTECT": 30},
            "MIN_NEW_HIGHS_FOR_REACTIVATION": 4,
            "TREND_CONFIRMATION_TICKS": 4,
            "ML_SHADOW_MODE": False,
            "ML_APPROVAL_THRESHOLD": 0.62,
        },
    ),
)


def validate_profiles(manager=None) -> None:
    """
    Garante que todos os perfis são aplicáveis pelo RuntimeConfigManager.

    Levanta ``ConfigValidationError`` se algum perfil tiver chave desconhecida,
    valor fora dos limites, inconsistência MIN/MAX ou tentativa de alterar
    custos de execução.
    """
    manager = manager or runtime_config
    seen = set()

    for profile in TRADING_PROFILES:
        if profile.id in seen:
            raise ValueError(f"Perfil duplicado: {profile.id}")
        seen.add(profile.id)

        if profile.risk not in {"baixo", "medio", "alto"}:
            raise ValueError(f"Risco inválido no perfil {profile.id}")

        blocked = PROTECTED_KEYS & profile.values.keys()
        if blocked:
            raise ValueError(
                f"Perfil {profile.id} não pode alterar custos: "
                f"{', '.join(sorted(blocked))}"
            )

        for key in profile.highlights:
            if key not in profile.values:
                raise ValueError(
                    f"Destaque {key} não existe nos valores do perfil {profile.id}"
                )

        if not profile.reset and not profile.values:
            raise ValueError(f"Perfil {profile.id} não altera nenhum parâmetro")

        # Valida tipos, limites e consistência contra os padrões de config.py,
        # sem depender dos overrides que o usuário tenha no momento.
        manager.validate(profile.values, use_defaults=True)


def _serialize_profile(profile: TradingProfile) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "tagline": profile.tagline,
        "description": profile.description,
        "risk": profile.risk,
        "icon": profile.icon,
        "tone": profile.tone,
        "upside": profile.upside,
        "downside": profile.downside,
        "highlights": list(profile.highlights),
        "reset": profile.reset,
        "values": dict(profile.values),
        "parameter_count": len(profile.values),
    }


def profiles_payload() -> Dict[str, Any]:
    """Payload do endpoint, já validado e pronto para JSON estrito."""
    validate_profiles()
    return {
        "profiles": [_serialize_profile(profile) for profile in TRADING_PROFILES],
        "preserves_other_parameters": True,
        "note": (
            "Cada perfil ajusta apenas seus parâmetros listados; demais "
            "personalizações são preservadas. O perfil Equilibrado restaura "
            "todos os padrões. Aplique com Salvar e Aplicar."
        ),
    }
