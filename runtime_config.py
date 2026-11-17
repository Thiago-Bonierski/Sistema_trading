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
    "PARAMETER_SPECS",
    "ParameterSpec",
    "RuntimeConfigManager",
    "runtime_config",
]
